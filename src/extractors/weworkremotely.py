"""We Work Remotely job board RSS feed extractor."""
import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, List
import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class WWRExtractor(BaseExtractor):
    """Extractor for We Work Remotely RSS feed (https://weworkremotely.com/remote-jobs.rss).

    WWR Guidelines:
    - Public RSS feed, no authentication required.
    - Single feed with all listings (no pagination needed).
    - Polite delay between requests as a courtesy.
    """

    FEED_URL = "https://weworkremotely.com/remote-jobs.rss"

    def __init__(self, delay_seconds: float = 2.0):
        super().__init__(source_name="weworkremotely", delay_seconds=delay_seconds)
        # RSS returns XML, not JSON
        self.session.headers.update({"Accept": "application/rss+xml, application/xml, text/xml"})

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Extract unique external ID from parsed RSS item using guid or link."""
        guid = item.get("guid")
        if guid:
            return str(guid).strip()
        link = item.get("link")
        if link:
            return str(link).strip()
        return ""

    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch all job listings from the WWR RSS feed.

        Args:
            max_pages: Ignored (single feed), kept for BaseExtractor interface.
        """
        logger.info("[%s] Fetching RSS feed from %s", self.source_name, self.FEED_URL)
        try:
            response = self.session.get(
                self.FEED_URL,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            if response.status_code == 429:
                logger.warning("[%s] Rate limited (HTTP 429).", self.source_name)
            else:
                logger.error("[%s] HTTP error fetching RSS: %s", self.source_name, exc)
            return []
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Network error fetching RSS: %s", self.source_name, exc)
            return []

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            logger.error("[%s] Failed to parse RSS XML: %s", self.source_name, exc)
            return []

        items = root.findall(".//item")
        collected: List[Dict[str, Any]] = []

        for item_el in items:
            parsed: Dict[str, Any] = {}
            for child in item_el:
                # Store text content by tag name
                parsed[child.tag] = child.text
            collected.append(parsed)

        logger.info("[%s] Retrieved %d items from RSS feed", self.source_name, len(collected))
        return collected
