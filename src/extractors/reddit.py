"""Reddit extractor for r/forhire, r/hiring and similar opportunity subreddits.

Reddit blocks unauthenticated JSON access (HTTP 403), so this extractor needs an
OAuth "script" app. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in the
environment. Without credentials the extractor logs a warning and returns an
empty list rather than failing the pipeline.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from src import config
from src.extractors.base import BaseExtractor
from src.models.job import NormalizedJob
from src.opportunities.compensation import detect_compensation

logger = logging.getLogger(__name__)

SUBREDDITS = ["forhire", "hiring", "slavelabour", "beermoney", "paidforwriting"]
OAUTH_BASE_URL = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
MAX_POSTS_PER_SUBREDDIT = 25

SKIP_PHRASES = (
    "meta discussion",
    "announcement",
    "sticky",
    "moderator",
    "weekly thread",
)

JOB_PHRASES = (
    "hiring",
    "freelance",
    "contract",
    "looking for",
    "need developer",
    "need programmer",
    "looking to hire",
    "budget",
    "compensation",
    "bounty",
    "reward",
    "prize",
    "bug bounty",
)

FREELANCE_KEYWORDS = ("freelance", "contract", "consult", "gig", "per project")
BOUNTY_KEYWORDS = ("bounty", "reward", "prize", "bug bounty")

TAG_KEYWORDS = (
    "python", "django", "flask", "react", "javascript", "typescript",
    "node", "golang", "ruby", "php", "rust", "llm", "rag", "devops",
)

BUDGET_PATTERNS = (
    re.compile(r"budget[:\-\s]*\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"rate[:\-\s]*\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(?:/|per\s*)?(?:hr|hour)", re.IGNORECASE),
    re.compile(r"\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)", re.IGNORECASE),
)


class RedditExtractor(BaseExtractor):
    """Extractor for Reddit job and freelance postings."""

    def __init__(
        self,
        delay_seconds: float = 5.0,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        super().__init__(source_name="reddit", delay_seconds=delay_seconds)
        self.client_id = client_id or os.getenv("REDDIT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("REDDIT_CLIENT_SECRET")
        self._access_token: Optional[str] = None
        self.session.headers.update({"User-Agent": config.DEFAULT_USER_AGENT})
        if self.client_id and self.client_secret:
            self._authenticate()

    # ------------------------------------------------------------------ auth
    def _authenticate(self) -> bool:
        """Fetch an OAuth bearer token using client-credentials grant."""
        if not (self.client_id and self.client_secret):
            logger.warning(
                "[%s] REDDIT_CLIENT_ID/SECRET not set; Reddit extraction disabled",
                self.source_name,
            )
            return False
        try:
            resp = requests.post(
                TOKEN_URL,
                auth=requests.auth.HTTPBasicAuth(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": config.DEFAULT_USER_AGENT},
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            self._access_token = resp.json().get("access_token")
        except requests.exceptions.RequestException as exc:
            logger.warning("[%s] Reddit OAuth failed: %s", self.source_name, exc)
            return False
        if self._access_token:
            self.session.headers.update(
                {"Authorization": f"bearer {self._access_token}"}
            )
            logger.info("[%s] Authenticated with Reddit OAuth", self.source_name)
            return True
        return False

    # ------------------------------------------------------------- extraction
    def extract_external_id(self, item: Dict[str, Any]) -> str:
        return str(item.get("id", "")).strip()

    @staticmethod
    def _parse_date(created_utc: float) -> datetime:
        return datetime.fromtimestamp(created_utc, tz=timezone.utc)

    @staticmethod
    def _is_job_post(title: str, selftext: str) -> bool:
        title_lower = title.lower()
        text_lower = (selftext or "").lower()
        if any(phrase in title_lower for phrase in SKIP_PHRASES):
            return False
        if "[for hire]" in title_lower or "[hiring]" in title_lower:
            return True
        return any(
            phrase in title_lower or phrase in text_lower
            for phrase in JOB_PHRASES
        )

    @staticmethod
    def _determine_opportunity_type(title: str, selftext: str) -> str:
        combined = f"{title} {selftext or ''}".lower()
        if any(kw in combined for kw in BOUNTY_KEYWORDS):
            return "bounty"
        if any(kw in combined for kw in FREELANCE_KEYWORDS):
            return "freelance"
        return "job"

    @staticmethod
    def _extract_budget(selftext: str) -> Optional[tuple]:
        text = selftext or ""
        for pattern in BUDGET_PATTERNS:
            match = pattern.search(text)
            if match:
                amount = float(match.group(1).replace(",", ""))
                return amount, "USD"
        return None

    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch candidate posts from each subreddit's /new listing."""
        if not self._access_token and not self._authenticate():
            return []

        all_posts: List[Dict[str, Any]] = []
        for subreddit in SUBREDDITS:
            url = f"{OAUTH_BASE_URL}/r/{subreddit}/new"
            params = {"limit": MAX_POSTS_PER_SUBREDDIT, "raw_json": 1}
            try:
                resp = self.session.get(
                    url, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS
                )
                resp.raise_for_status()
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "[%s] Failed to fetch r/%s: %s", self.source_name, subreddit, exc
                )
                continue
            try:
                children = resp.json().get("data", {}).get("children", [])
            except ValueError as exc:
                logger.warning(
                    "[%s] Bad JSON from r/%s: %s", self.source_name, subreddit, exc
                )
                continue

            for child in children:
                post = child.get("data", {})
                if not self._is_job_post(
                    post.get("title", ""), post.get("selftext", "")
                ):
                    continue
                post["subreddit"] = subreddit
                all_posts.append(post)
            self.polite_sleep()

        logger.info(
            "[%s] Found %d candidate post(s)", self.source_name, len(all_posts)
        )
        return all_posts

    # ----------------------------------------------------------- normalising
    def _to_jobs(self, items: List[Dict[str, Any]]) -> List[NormalizedJob]:
        jobs: List[NormalizedJob] = []
        for item in items:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            selftext = item.get("selftext") or ""
            subreddit = item.get("subreddit", "")
            link = item.get("url") or item.get("permalink") or ""
            if link and not link.startswith("http"):
                link = f"https://www.reddit.com{link}"

            created = item.get("created_utc") or 0
            posted_at = (
                self._parse_date(created) if created else datetime.now(timezone.utc)
            )

            comp = detect_compensation(selftext, kind="freelance")
            budget = self._extract_budget(selftext)
            budget_min = budget_max = None
            budget_currency = None
            if budget:
                budget_min = budget_max = budget[0]
                budget_currency = budget[1]
            elif comp.compensation_type != "unknown":
                budget_min = comp.budget_min
                budget_max = comp.budget_max
                budget_currency = comp.budget_currency

            tags = ["reddit", subreddit]
            title_lower = title.lower()
            tags.extend(kw for kw in TAG_KEYWORDS if kw in title_lower)

            title_upper = title.upper()
            if any(k in title_upper for k in ("JUNIOR", "ENTRY", "BEGINNER")):
                experience_level = "junior"
            elif any(k in title_upper for k in ("SENIOR", "STAFF", "PRINCIPAL")):
                experience_level = "senior"
            elif any(k in title_upper for k in ("MID-LEVEL", "MID_LEVEL")):
                experience_level = "mid"
            else:
                experience_level = "unspecified"

            job = NormalizedJob(
                source="reddit",
                external_id=self.extract_external_id(item),
                title=title,
                company_name="",
                company_url=None,
                location_raw="remote",
                is_remote=True,
                remote_restriction="unspecified",
                accessibility="UNKNOWN",
                reachable_from_nepal="unknown",
                reachable_reason="no_location_restriction_stated",
                detected_language="english",
                is_unpaid=comp.compensation_type == "unpaid",
                nepal_accessible=False,
                job_type=None,
                experience_level=experience_level,
                description_text=selftext,
                description_html=None,
                apply_url=link,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                tags=tags,
                posted_at=posted_at,
                expires_at=None,
                fingerprint_hash=None,
                opportunity_type=self._determine_opportunity_type(title, selftext),
                compensation_type=comp.compensation_type,
                budget_min=budget_min,
                budget_max=budget_max,
                budget_currency=budget_currency,
                deadline=None,
                payment_verification_status=comp.payment_verification_status,
                scam_risk_score=0.0,
                risk_flags=[],
                risk_explanation=None,
                status="open",
                source_url=link,
                last_seen_at=datetime.now(timezone.utc),
            )
            job.fingerprint_hash = job.compute_fingerprint()
            jobs.append(job)
        return jobs

    def stage_raw(self, max_pages: int = 1) -> Dict[str, int]:
        """Fetch, normalise and stage Reddit postings."""
        raw = self.fetch_raw(max_pages=max_pages)
        if not raw:
            return {"total": 0, "inserted": 0, "skipped": 0}
        jobs = self._to_jobs(raw)
        res = self.stage_normalized_jobs(jobs)
        skipped = len(raw) - len(jobs)
        res["total"] = len(raw)
        res["skipped"] = res.get("skipped", 0) + skipped
        return res
