"""GitHub issue discovery: two sources, two lanes.

SEARCH  - property-based queries from config/github_issues.yml, run on schedule.
WATCHLIST - repos that passed the health check, polled directly (ETag-cached).

Only the official GitHub REST API is used (https://api.github.com). No HTML
scraping. Authenticated search is ~30 req/min; we back off on 403/429, honour
Retry-After and X-RateLimit-Reset, and cache ETags/Last-Modified per URL.

Every issue is scored by src.opportunities.bounty_verdict.LaneVerdictEngine and
stored under payload["_bounty_verdict"]. Nothing is auto-accepted, auto-messaged
or auto-contacted.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from src import config
from src.extractors.base import BaseExtractor
from src.opportunities.bounty_config import load_github_config
from src.opportunities.bounty_verdict import (
    BountyVerdictEngine,
    Verdict,
    material_state_hash,
)
from src.opportunities.repo_health import RepoHealthChecker

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.github.com/search/issues"
REPO_ISSUES_URL = "https://api.github.com/repos/{repo}/issues"

DEFAULT_SEARCH_QUERIES = [
    'is:issue is:open archived:false no:assignee label:"good first issue"',
    'is:issue is:open archived:false no:assignee label:"help wanted"',
]


class GitHubIssuesExtractor(BaseExtractor):
    """Discover open issues across the SEARCH and WATCHLIST sources."""

    def __init__(
        self,
        delay_seconds: float = 6.0,
        token: Optional[str] = None,
        per_query: int = 50,
        config_path: Optional[str] = None,
        run_verdict: bool = True,
        use_search: bool = True,
        use_watchlist: bool = True,
        secondary_backoff_seconds: float = 60.0,
        max_watchlist_repos: Optional[int] = None,
        max_repo_meta_fetches: Optional[int] = None,
    ):
        super().__init__(source_name="github", delay_seconds=delay_seconds)
        self.token = token if token is not None else config.GITHUB_TOKEN
        self.per_query = per_query
        self.cfg = load_github_config(config_path) if config_path else load_github_config()
        self.run_verdict = run_verdict
        self.secondary_backoff_seconds = secondary_backoff_seconds
        self.use_search = use_search
        self.use_watchlist = use_watchlist
        self._verdict_engine = BountyVerdictEngine(self.cfg) if run_verdict else None
        self.max_watchlist_repos = (
            max_watchlist_repos
            if max_watchlist_repos is not None
            else self.cfg.thresholds.max_watchlist_repos
        )
        self.max_repo_meta_fetches = (
            max_repo_meta_fetches
            if max_repo_meta_fetches is not None
            else self.cfg.thresholds.max_repo_meta_fetches
        )
        self._repo_meta_fetches = 0
        self._health = RepoHealthChecker(
            token=self.token,
            config=self.cfg,
            quota_reserve=self.cfg.thresholds.api_quota_reserve,
        )
        self._etag_cache: Dict[str, Tuple[str, Optional[str]]] = {}
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["X-GitHub-Api-Version"] = "2022-11-28"

    # ------------------------------------------------------------------ utils
    def extract_external_id(self, item: Dict[str, Any]) -> str:
        return str(item.get("id") or item.get("html_url") or "").strip()

    @staticmethod
    def repo_from_url(repo_url: str) -> str:
        parts = (repo_url or "").rstrip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return ""

    def _conditional_get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[requests.Response]:
        """GET with ETag/If-Modified-Since and rate-limit backoff.

        Returns None on 304 (cached), network error, or unrecoverable rate limit.
        """
        headers: Dict[str, str] = {}
        key = url + repr(sorted((params or {}).items()))
        cached = self._etag_cache.get(key)
        if cached:
            etag, mtime = cached
            if etag:
                headers["If-None-Match"] = etag
            if mtime:
                headers["If-Modified-Since"] = mtime
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=config.REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logger.warning("[github] request failed %s: %s", url, exc)
            return None

        if resp.status_code == 304:
            return None
        if resp.status_code in (403, 429):
            self._handle_rate_limit(resp)
            return None
        if resp.status_code != 200:
            logger.warning("[github] HTTP %s for %s", resp.status_code, url)
            return None
        if resp.headers.get("ETag"):
            self._etag_cache[key] = (resp.headers["ETag"], resp.headers.get("Last-Modified"))
        return resp

    def _handle_rate_limit(self, resp: requests.Response) -> None:
        """Back off on primary OR secondary rate limits.

        Primary limits exhaust the quota (X-RateLimit-Remaining: 0) and give
        X-RateLimit-Reset. Secondary limits can fire while remaining is high and
        often omit Retry-After; GitHub asks for at least a one-minute pause then.
        """
        retry_after = resp.headers.get("Retry-After")
        reset = resp.headers.get("X-RateLimit-Reset")
        remaining = resp.headers.get("X-RateLimit-Remaining")
        try:
            remaining_n = int(remaining) if remaining is not None else None
        except ValueError:
            remaining_n = None

        wait = 0.0
        if retry_after:
            try:
                wait = float(retry_after)
            except ValueError:
                wait = 0.0
        elif reset and (remaining_n == 0):
            try:
                wait = max(0.0, float(reset) - time.time())
            except ValueError:
                wait = 0.0
        else:
            # Secondary limit (or unknown): GitHub recommends >= 60s.
            wait = self.secondary_backoff_seconds

        wait = min(wait, 120.0)
        logger.warning(
            "[github] rate limited (remaining=%s); sleeping %.0fs", remaining, wait
        )
        if wait > 0:
            time.sleep(wait)

    # --------------------------------------------------------------- discovery
    def _search_source(self, max_pages: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        queries = self.cfg.search_queries or []
        if not queries:
            for i, q in enumerate(DEFAULT_SEARCH_QUERIES):
                from src.opportunities.bounty_config import SearchQuery

                queries.append(SearchQuery(source=f"default_{i}", q=q))

        for sq in queries:
            q = sq.q or ""
            if sq.updated_within_days:
                since = (datetime.now(timezone.utc) - timedelta(days=sq.updated_within_days)).date().isoformat()
                if "updated:" not in q:
                    q = f"{q} updated:>={since}"
            if sq.language and "language:" not in q and len(sq.language) == 1:
                q = f"{q} language:{sq.language[0]}"
            if "archived:" not in q:
                q = f"{q} archived:false"

            page = 1
            while page <= max_pages:
                params = {"q": q.strip(), "per_page": sq.per_page or self.per_query, "page": page}
                resp = self._conditional_get(SEARCH_URL, params)
                if resp is None:
                    break
                items = (resp.json() or {}).get("items") or []
                if not items:
                    break
                for it in items:
                    it["_gh_source"] = sq.source
                    out.append(it)
                if len(items) < (sq.per_page or self.per_query):
                    break
                page += 1
                self.polite_sleep()
        return out

    def _watchlist_source(self, max_pages: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        repos = self._load_watchlist()
        if not repos:
            repos = list(self.cfg.watchlist_seeds or [])
            for r in repos:
                self._add_to_watchlist(r, source="seed")

        if self.max_watchlist_repos:
            repos = repos[: self.max_watchlist_repos]

        for repo in repos:
            health = self._health.assess(repo)
            if not health.checked:
                # Transient failure: skip quietly, never call it unhealthy.
                logger.info(
                    "[github] watchlist skip %s (unverified: %s)", repo, health.reasons
                )
                continue
            if not health.healthy:
                logger.info(
                    "[github] watchlist skip %s (%d/%d criteria passed, missing: %s)",
                    repo, health.passed, health.total, health.reasons,
                )
                continue
            url = REPO_ISSUES_URL.format(repo=repo)
            page = 1
            while page <= max_pages:
                resp = self._conditional_get(url, {"state": "open", "per_page": self.per_query, "page": page})
                if resp is None:
                    break
                items = resp.json() or []
                if not items:
                    break
                for it in items:
                    if it.get("pull_request"):
                        continue
                    it["_gh_source"] = "watchlist"
                    it["_gh_repo"] = repo
                    out.append(it)
                if len(items) < self.per_query:
                    break
                page += 1
                self.polite_sleep()
            self._touch_watchlist(repo)
        return out

    # ------------------------------------------------------------- watchlist db
    def _load_watchlist(self) -> List[str]:
        from src.db.connection import get_connection

        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT repo FROM watchlist WHERE active = TRUE;")
                    return [r["repo"] for r in cur.fetchall()]
        except Exception as exc:
            logger.debug("[github] watchlist read failed: %s", exc)
            return []

    def _add_to_watchlist(self, repo: str, source: str = "search") -> None:
        from src.db.connection import get_connection

        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO watchlist (repo, source) VALUES (%s, %s)
                        ON CONFLICT (repo) DO NOTHING;
                        """,
                        (repo, source),
                    )
        except Exception as exc:
            logger.debug("[github] watchlist insert failed for %s: %s", repo, exc)

    def _touch_watchlist(self, repo: str) -> None:
        from src.db.connection import get_connection

        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE watchlist SET last_polled_at = NOW(), consecutive_failures = 0 WHERE repo = %s;",
                        (repo,),
                    )
        except Exception as exc:
            logger.debug("[github] watchlist touch failed for %s: %s", repo, exc)

    # ------------------------------------------------------------------ verdict
    def _run_verdict(
        self,
        issue: Dict[str, Any],
        repo_meta: Optional[Dict[str, Any]] = None,
        similar_titles_count: int = 0,
        author_recent_issues: int = 0,
        template_group_size: int = 0,
    ) -> Dict[str, Any]:
        if not self._verdict_engine:
            return {}
        try:
            result = self._verdict_engine.evaluate(
                issue=issue,
                repo_meta=repo_meta,
                similar_titles_count=similar_titles_count,
                author_recent_issues=author_recent_issues,
                template_group_size=template_group_size,
            )
            return BountyVerdictEngine.verdict_to_db_fields(result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[github] verdict failed for issue %s: %s", issue.get("id"), exc)
            return {
                "bounty_verdict": Verdict.UNCERTAIN,
                "reject_reasons": [],
                "funding_evidence": None,
                "bounty_confidence": 0,
                "reject_evidence": "verdict error: " + str(exc),
                "score": 0,
                "score_breakdown": {},
                "why": "",
                "notes": "",
            }

    @staticmethod
    def normalize_title(title: str) -> str:
        """Normalize a title for clone/template grouping.

        Lowercase, strip repeated bracket/area prefixes, numbers and hex-like ids.
        """
        t = (title or "").lower()
        # Strip leading tag prefixes such as "[BX]", "feat(devx):", "[CSS 2024]".
        t = re.sub(r"^\s*(?:\[[^\]]*\]|\([^)]*\)|[a-z]+(?:\([^)]*\))?:)\s*", "", t)
        t = re.sub(r"0x[0-9a-f]+", " ", t)
        t = re.sub(r"\b[0-9a-f]{8,}\b", " ", t)
        t = re.sub(r"\d+", " ", t)
        t = re.sub(r"[^a-z\s]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _batch_signals(
        self, items: List[Dict[str, Any]]
    ) -> tuple:
        """Count normalized-title spread across repos and per-author volume."""
        from collections import Counter, defaultdict

        title_repos: Dict[str, set] = defaultdict(set)
        title_counts: Counter = Counter()
        author_counts: Counter = Counter()
        template_groups: Counter = Counter()

        for it in items:
            repo = it.get("_gh_repo") or ""
            norm = self.normalize_title(it.get("title") or "")
            author = ((it.get("user") or {}).get("login") or "").lower()
            if norm:
                title_repos[norm].add(repo)
                title_counts[norm] += 1
            if author:
                author_counts[author] += 1
                # Near-identical template: same author, same leading 3 words.
                prefix = " ".join(norm.split()[:3])
                if prefix:
                    template_groups[(author, prefix)] += 1

        cross_repo = {n: len(r) for n, r in title_repos.items()}
        return title_counts, cross_repo, author_counts, template_groups

    def _enrich_and_verdict(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Attach repo metadata, compute batch signals, run verdict."""
        seen_repos: Dict[str, Optional[Dict[str, Any]]] = {}
        (
            title_counts,
            cross_repo,
            author_counts,
            template_groups,
        ) = self._batch_signals(items)
        kept: List[Dict[str, Any]] = []
        for it in items:
            repo = it.get("_gh_repo") or self.repo_from_url(it.get("repository_url") or "")
            it["_gh_repo"] = repo
            if repo not in seen_repos:
                seen_repos[repo] = self._fetch_repo_meta(repo)
            repo_meta = seen_repos[repo]
            if self.run_verdict:
                norm = self.normalize_title(it.get("title") or "")
                author = ((it.get("user") or {}).get("login") or "").lower()
                similar = max(cross_repo.get(norm, 1), title_counts.get(norm, 1)) - 1
                prefix = " ".join(norm.split()[:3])
                template_group = template_groups.get((author, prefix), 1)
                verdict_fields = self._run_verdict(
                    it,
                    repo_meta,
                    similar_titles_count=similar,
                    author_recent_issues=max(0, author_counts.get(author, 1) - 1),
                    template_group_size=template_group,
                )
                it["_bounty_verdict"] = verdict_fields
                if verdict_fields.get("bounty_verdict") == Verdict.REJECT:
                    self._record_rejected(it, verdict_fields)
                elif verdict_fields.get("bounty_verdict") == Verdict.UNCERTAIN:
                    # Route to triage, never drop.
                    it["_triage"] = True
            kept.append(it)
        return kept

    def _record_rejected(self, issue: Dict[str, Any], verdict_fields: Dict[str, Any]) -> None:
        """Persist a rejection to the ledger. Never deletes rows."""
        repo = issue.get("_gh_repo") or ""
        number = issue.get("number")
        if not repo or number is None:
            return
        try:
            from src.db.repository import JobRepository

            state_hash = material_state_hash(issue)
            JobRepository().upsert_rejected_issue(
                repo=repo,
                issue_number=int(number),
                title=issue.get("title") or "",
                source_url=issue.get("html_url") or "",
                verdict=verdict_fields.get("bounty_verdict") or Verdict.REJECT,
                reject_reasons=verdict_fields.get("reject_reasons") or [],
                reject_evidence=verdict_fields.get("reject_evidence") or "",
                state_hash=state_hash,
                funding_evidence=verdict_fields.get("funding_evidence"),
                score=verdict_fields.get("score"),
                score_breakdown=verdict_fields.get("score_breakdown"),
                why=verdict_fields.get("why"),
                notes=verdict_fields.get("notes"),
            )
        except Exception as exc:  # pragma: no cover - DB optional in tests
            logger.debug("[github] could not record rejection %s#%s: %s", repo, number, exc)

    def _fetch_repo_meta(self, repo: str) -> Optional[Dict[str, Any]]:
        if not repo:
            return None
        if self._repo_meta_fetches >= self.max_repo_meta_fetches:
            return None
        self._repo_meta_fetches += 1
        resp = self._conditional_get(f"https://api.github.com/repos/{repo}")
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    # -------------------------------------------------------------------- fetch
    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        raw: List[Dict[str, Any]] = []
        if self.use_search:
            raw.extend(self._search_source(max_pages))
        if self.use_watchlist:
            raw.extend(self._watchlist_source(max_pages))

        # Dedupe by repo + issue number (never by title).
        seen: set = set()
        unique: List[Dict[str, Any]] = []
        for it in raw:
            repo = it.get("_gh_repo") or self.repo_from_url(it.get("repository_url") or "")
            num = it.get("number")
            key = f"{repo}#{num}" if repo and num is not None else self.extract_external_id(it)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(it)

        collected = self._enrich_and_verdict(unique)

        # NOTE: accepted repos are NOT auto-added to the watchlist. The watchlist
        # grows from the configured seed list only, so one search run can never
        # trigger hundreds of health checks and exhaust the API quota.

        logger.info("[github] collected %d unique issues.", len(collected))
        return collected
