"""Working Nomads public exposed-jobs API extractor."""
import logging
from typing import Any, Dict, List

import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class WorkingNomadsExtractor(BaseExtractor):
    """Extractor for the public Working Nomads exposed-jobs JSON endpoint.

    The endpoint is a single unpaginated JSON array of current listings.
    robots.txt is fully permissive; keep a polite delay between runs.
    """

    BASE_URL = "https://www.workingnomads.com/api/exposed_jobs/"

    def __init__(self, delay_seconds: float = 2.0):
        super().__init__(source_name="workingnomads", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        return str(item.get("url") or "").strip()

    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        logger.info("[%s] Fetching %s", self.source_name, self.BASE_URL)
        try:
            response = self.session.get(
                self.BASE_URL,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as exc:
            if response.status_code == 429:
                logger.warning("[%s] Rate limited (HTTP 429).", self.source_name)
            else:
                logger.error("[%s] HTTP error: %s", self.source_name, exc)
            return []
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Network error: %s", self.source_name, exc)
            return []
        except ValueError as exc:
            logger.error("[%s] Failed to parse JSON: %s", self.source_name, exc)
            return []

        jobs = data if isinstance(data, list) else data.get("jobs", [])
        logger.info("[%s] Retrieved %d jobs", self.source_name, len(jobs))
        return jobs
