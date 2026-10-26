"""Jobicy public JSON API extractor."""
import logging
from typing import Any, Dict, List

import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)

# Jobicy: ?geo=worldwide returns HTTP 400 (verified live 2026-10-18).
# Client-side pre-filter: only stage jobs with no geo restriction or an
# explicit worldwide/global geo.  Single-country strings are skipped to
# reduce REGION_LOCKED rejections downstream (~98% of fetched jobs).
_WORLDWIDE_GEOS = frozenset({"", "worldwide", "anywhere", "global", "remote"})


def _jobicy_geo_is_accessible(job: Dict[str, Any]) -> bool:
    """Return True if the job has no single-country geo restriction."""
    geo_raw = (job.get("jobGeo") or "").lower().strip()
    parts = [p.strip() for p in geo_raw.split(",") if p.strip()]
    if not parts:
        return True  # blank = worldwide
    return all(p in _WORLDWIDE_GEOS for p in parts)


class JobicyExtractor(BaseExtractor):
    """Extractor for Jobicy public API (https://jobicy.com/api/v2/remote-jobs).

    Jobicy API Guidelines:
    - Free public JSON API, no authentication.
    - Paginated via count parameter (max 50 per request).
    - ?geo=worldwide is NOT supported on the free API (HTTP 400, verified 2026-10-18).
    - Client-side geo filter applied: only worldwide/blank geos are staged.
    - Rate limit: Fair use, polite delay between requests.
    """

    API_URL = "https://jobicy.com/api/v2/remote-jobs"

    def __init__(self, delay_seconds: float = 2.0):
        super().__init__(source_name="jobicy", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Extract unique external ID using id or jobSlug."""
        item_id = item.get("id")
        if item_id is not None:
            return str(item_id).strip()
        slug = item.get("jobSlug")
        if slug:
            return str(slug).strip()
        return ""

    def fetch_raw(self, count: int = 100, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch remote job listings from Jobicy API.

        Only returns jobs with worldwide or unspecified geo restrictions.
        Single-country jobs are discarded before staging.
        Note: The free Jobicy API does not support offset/page pagination parameters (HTTP 400).
        Count parameter accepts up to 100 listings.

        Args:
            count: Number of jobs to fetch (max 100).
            max_pages: Maintained for interface compatibility (always 1 for Jobicy free API).
        """
        collected: List[Dict[str, Any]] = []

        params: Dict[str, Any] = {"count": count}
        logger.info(
            "[%s] Fetching jobs (count=%d)",
            self.source_name,
            count,
        )
        try:
            response = self.session.get(
                self.API_URL,
                params=params,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as exc:
            if response.status_code == 429:
                logger.warning("[%s] Rate limited (HTTP 429). Stopping.", self.source_name)
            else:
                logger.error("[%s] HTTP error: %s", self.source_name, exc)
            return collected
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Network error: %s", self.source_name, exc)
            return collected
        except ValueError as exc:
            logger.error("[%s] JSON parse error: %s", self.source_name, exc)
            return collected

        jobs = data.get("jobs", [])
        if not jobs:
            logger.info("[%s] No jobs returned.", self.source_name)
            return collected

        before = len(jobs)
        jobs = [j for j in jobs if _jobicy_geo_is_accessible(j)]
        skipped_geo = before - len(jobs)
        if skipped_geo:
            logger.info(
                "[%s] Geo pre-filter: dropped %d/%d single-country jobs.",
                self.source_name, skipped_geo, before,
            )

        collected.extend(jobs)
        logger.info("[%s] Retrieved %d accessible jobs total", self.source_name, len(collected))
        return collected
