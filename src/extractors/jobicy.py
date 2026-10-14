"""Jobicy public JSON API extractor."""
import logging
from typing import Any, Dict, List
import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class JobicyExtractor(BaseExtractor):
    """Extractor for Jobicy public API (https://jobicy.com/api/v2/remote-jobs).

    Jobicy API Guidelines:
    - Free public JSON API, no authentication.
    - Paginated via count parameter (max 50 per request).
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

    def fetch_raw(self, count: int = 50, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch remote job listings from Jobicy API.

        Args:
            count: Number of jobs per page (max 50).
            max_pages: Maximum number of pages to retrieve.
        """
        collected: List[Dict[str, Any]] = []

        for page in range(max_pages):
            params: Dict[str, Any] = {"count": count}
            logger.info(
                "[%s] Fetching page %d (count=%d)",
                self.source_name,
                page + 1,
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
                break
            except requests.exceptions.RequestException as exc:
                logger.error("[%s] Network error: %s", self.source_name, exc)
                break
            except ValueError as exc:
                logger.error("[%s] JSON parse error: %s", self.source_name, exc)
                break

            jobs = data.get("jobs", [])
            if not jobs:
                logger.info("[%s] No more jobs returned.", self.source_name)
                break

            collected.extend(jobs)

            if page < max_pages - 1:
                self.polite_sleep()

        logger.info("[%s] Retrieved %d jobs total", self.source_name, len(collected))
        return collected
