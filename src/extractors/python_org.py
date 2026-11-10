"""Python.org Jobs RSS feed extractor.

Official Python Software Foundation jobs feed:
https://www.python.org/jobs/feed/rss/

This extracts job/listing data from the RSS feed and normalizes it into
NormalizedJob records. Both traditional employment and contract/freelance
Python-related opportunities are captured.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from decimal import Decimal
from xml.etree import ElementTree

import requests

from src import config
from src.extractors.base import BaseExtractor
from src.models.job import NormalizedJob

logger = logging.getLogger(__name__)

# Python.org official jobs RSS feed
RSS_URL = "https://www.python.org/jobs/feed/rss/"

# Date format in the RSS feed
RSS_DATE_FORMAT = "%a, %d %b %Y %H:%M:%S %z"

# How many days back from current date to consider a listing fresh
FRESHNESS_DAYS = 30


class PythonOrgExtractor(BaseExtractor):
    """Extractor for Python.org Jobs RSS feed."""

    def __init__(self, delay_seconds: float = 5.0):
        super().__init__(source_name="python_org", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Use the guid (permalink) as the external ID."""
        guid = item.get("guid") or item.get("link") or ""
        return str(guid).strip()

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse RSS date format."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, RSS_DATE_FORMAT).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None

    def _build_job_from_item(self, item: Dict[str, Any]) -> Optional[NormalizedJob]:
        """Build a NormalizedJob from an RSS item."""
        title = item.get("title") or ""
        if not title.strip():
            return None

        # Skip items that are clearly not jobs (e.g., announcements, events)
        skip_phrases = ["announcement", "release", "call for", "rfp", "proposal"]
        title_lower = title.lower()
        if any(phrase in title_lower for phrase in skip_phrases):
            logger.debug("Skipping non-job RSS item: %s", title[:80])
            return None

        description = item.get("description") or ""
        link = item.get("link") or ""
        guid = item.get("guid") or ""
        pub_date_str = item.get("pubDate") or ""

        posted_at = self._parse_date(pub_date_str)
        if posted_at is None:
            posted_at = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)

        # Estimate compensation from description if present
        from src.opportunities.compensation import detect_compensation
        comp = detect_compensation(description, kind="freelance")

        # Determine opportunity type based on title and description
        opportunity_type = "job"
        title_upper = title.upper()
        if any(kw in title_upper for kw in ["CONTRACT", "FREELANCE", "CONSULT"]):
            opportunity_type = "freelance"
        elif any(kw in title_upper for kw in ["BONUS", "REWARD", "BOUNTY"]):
            opportunity_type = "bounty"

        # Extract budget if present
        budget_min: Optional[float] = None
        budget_max: Optional[float] = None
        budget_currency: Optional[str] = None
        if comp.compensation_type != "unknown":
            budget_min = comp.budget_min
            budget_max = comp.budget_max
            budget_currency = comp.budget_currency

        # Determine if remote
        is_remote = False
        location_raw = (item.get("category") or "").strip()
        if "remote" in (location_raw or "").lower():
            is_remote = True

        # Build tags from RSS categories and title
        tags: List[str] = []
        if item.get("category"):
            cat = str(item["category"])
            if isinstance(cat, str):
                tags = [c.strip() for c in cat.split(",") if c.strip()]
            elif isinstance(cat, list):
                tags = [str(c).strip() for c in cat if str(c).strip()]
        if "python" not in [t.lower() for t in tags] and "python" in title_lower:
            tags.append("python")

        # Estimate experience level from title
        experience_level = "unspecified"
        if any(kw in title_upper for kw in ["JUNIOR", "ENTRY", "BEGINNER"]):
            experience_level = "junior"
        elif any(kw in title_upper for kw in ["SENIOR", "STAFF", "PRINCIPAL"]):
            experience_level = "senior"
        elif any(kw in title_upper for kw in ["MID-LEVEL", "MID_LEVEL"]):
            experience_level = "mid"

        # Determine remote restriction
        remote_restriction = "unspecified"
        if is_remote:
            remote_restriction = "unspecified"

        # Build the NormalizedJob
        job = NormalizedJob(
            source="python_org",
            external_id=self.extract_external_id(item),
            title=title,
            company_name="",  # Often not available in RSS; may be in description
            company_url=None,
            location_raw=location_raw or None,
            is_remote=is_remote,
            remote_restriction=remote_restriction,
            accessibility="UNKNOWN",
            reachable_from_nepal="unknown",
            reachable_reason="no_location_restriction_stated",
            detected_language="english",
            is_unpaid=comp.compensation_type == "unpaid",
            nepal_accessible=False,
            job_type=None,
            experience_level=experience_level,
            description_text=description,
            description_html=None,
            apply_url=link,
            salary_min=None,  # Not applicable for Python.org feed
            salary_max=None,
            salary_currency=None,
            tags=tags,
            posted_at=posted_at,
            expires_at=None,
            fingerprint_hash=None,  # Will be computed by model_post_init
            opportunity_type=opportunity_type,
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

        # Compute fingerprint
        job.fingerprint_hash = job.compute_fingerprint()

        return job

    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch listings from Python.org RSS feed."""
        logger.info("[%s] Fetching Python.org Jobs RSS feed", self.source_name)

        try:
            resp = self.session.get(
                RSS_URL,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Failed to fetch Python.org RSS: %s", self.source_name, exc)
            return []

        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError as exc:
            logger.error("[%s] Failed to parse Python.org RSS XML: %s", self.source_name, exc)
            return []

        # RSS items are <item> elements
        items = root.findall(".//item")
        logger.info("[%s] Found %d items in Python.org RSS feed", self.source_name, len(items))

        raw_items: List[Dict[str, Any]] = []
        for item in items:
            # Convert XML element to dict
            d: Dict[str, Any] = {}
            for child in item:
                if child.text:
                    d[child.tag] = child.text.strip()
                else:
                    d[child.tag] = ""

            # Also handle namespace-free attrs if any
            raw_items.append(d)

        return raw_items

    def stage_raw(self, max_pages: int = 1) -> Dict[str, int]:
        """Fetch and stage Python.org job listings."""
        raw_items = self.fetch_raw(max_pages=max_pages)
        return self.stage_raw_items(raw_items)

    def stage_raw_items(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Transform and stage raw RSS items into normalized jobs."""
        normalized = []
        skipped = 0

        for item in items:
            job = self._build_job_from_item(item)
            if job is None:
                skipped += 1
                continue
            normalized.append(job)

        res = self.stage_normalized_jobs(normalized)
        res["total"] = len(items)
        res["skipped"] = res.get("skipped", 0) + skipped
        return res
