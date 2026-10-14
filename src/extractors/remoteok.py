"""Remote OK public JSON API extractor."""
import logging
from typing import Any, Dict, List
import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class RemoteOKExtractor(BaseExtractor):
    """Extractor for Remote OK public API (https://remoteok.com/api).

    Remote OK API Guidelines:
    - Free public JSON API endpoint.
    - Returns a flat list: first element is a legal/metadata notice, remaining are jobs.
    - Rate limit: Fair use. Polite delay between requests.
    """

    API_URL = "https://remoteok.com/api"

    def __init__(self, delay_seconds: float = 2.0):
        super().__init__(source_name="remoteok", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Extract unique external ID using id or slug."""
        item_id = item.get("id")
        if item_id is not None:
            return str(item_id).strip()
        slug = item.get("slug")
        if slug:
            return str(slug).strip()
        return ""

    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch all job listings from Remote OK API.

        Args:
            max_pages: Ignored (single endpoint), kept for BaseExtractor interface.
        """
        logger.info("[%s] Fetching jobs from %s", self.source_name, self.API_URL)
        try:
            response = self.session.get(
                self.API_URL,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as exc:
            if response.status_code == 429:
                logger.warning("[%s] Rate limited (HTTP 429).", self.source_name)
            else:
                logger.error("[%s] HTTP error fetching jobs: %s", self.source_name, exc)
            return []
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Network error contacting Remote OK: %s", self.source_name, exc)
            return []
        except ValueError as exc:
            logger.error("[%s] Failed to parse JSON response: %s", self.source_name, exc)
            return []

        if not isinstance(data, list):
            logger.error("[%s] Unexpected response type: %s", self.source_name, type(data))
            return []

        # First element is a legal/metadata notice, skip it
        jobs = [item for item in data if "position" in item or "id" in item and "legal" not in item]
        logger.info("[%s] Retrieved %d jobs", self.source_name, len(jobs))
        return jobs
