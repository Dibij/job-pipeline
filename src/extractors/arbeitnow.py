"""Arbeitnow job board API extractor."""
import logging
from typing import Any, Dict, List, Optional
import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class ArbeitnowExtractor(BaseExtractor):
    """Extractor for Arbeitnow public job board API (https://www.arbeitnow.com/api/job-board-api)."""

    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    def __init__(self, delay_seconds: float = 1.0):
        super().__init__(source_name="arbeitnow", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Use the unique slug or URL as the external ID."""
        slug = item.get("slug")
        if slug:
            return str(slug).strip()
        url = item.get("url")
        if url:
            return str(url).strip()
        return ""

    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch listings from Arbeitnow up to max_pages."""
        collected: List[Dict[str, Any]] = []
        next_url: Optional[str] = self.BASE_URL
        pages_fetched = 0

        while next_url and pages_fetched < max_pages:
            pages_fetched += 1
            logger.info("[%s] Fetching page %d: %s", self.source_name, pages_fetched, next_url)
            try:
                response = self.session.get(
                    next_url,
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.HTTPError as exc:
                if response.status_code == 429:
                    logger.warning("[%s] Rate limited (HTTP 429). Stopping fetch.", self.source_name)
                else:
                    logger.error("[%s] HTTP error fetching %s: %s", self.source_name, next_url, exc)
                break
            except requests.exceptions.RequestException as exc:
                logger.error("[%s] Network error fetching %s: %s", self.source_name, next_url, exc)
                break
            except ValueError as exc:
                logger.error("[%s] Failed to parse JSON response: %s", self.source_name, exc)
                break

            items = data.get("data", [])
            logger.info("[%s] Received %d items from page %d", self.source_name, len(items), pages_fetched)
            collected.extend(items)

            # Determine next page URL
            links = data.get("links", {})
            next_url = links.get("next")

            if next_url and pages_fetched < max_pages:
                self.polite_sleep()

        logger.info("[%s] Total fetched items across %d page(s): %d", self.source_name, pages_fetched, len(collected))
        return collected
