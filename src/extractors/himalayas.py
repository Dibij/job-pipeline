"""Himalayas remote job board API extractor."""
import logging
from typing import Any, Dict, List, Optional
import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class HimalayasExtractor(BaseExtractor):
    """Extractor for Himalayas public jobs API (https://himalayas.app/jobs/api).
    
    Himalayas API Guidelines:
    - Free public API endpoint.
    - Paginated via limit and offset parameters.
    - Rate limit: Fair use, polite delay between requests.
    """

    BASE_URL = "https://himalayas.app/jobs/api"

    def __init__(self, delay_seconds: float = 2.0):
        super().__init__(source_name="himalayas", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Extract unique external ID using guid or applicationLink."""
        guid = item.get("guid")
        if guid:
            return str(guid).strip()
        link = item.get("applicationLink")
        if link:
            return str(link).strip()
        return ""

    def fetch_raw(
        self,
        limit: int = 50,
        max_pages: int = 1,
    ) -> List[Dict[str, Any]]:
        """Fetch remote job listings from Himalayas API.
        
        Args:
            limit: Number of jobs per page (max recommended: 50).
            max_pages: Maximum number of pages to retrieve.
        """
        collected: List[Dict[str, Any]] = []
        offset = 0

        for page in range(max_pages):
            params = {
                "limit": limit,
                "offset": offset,
            }
            logger.info(
                "[%s] Fetching page %d (offset %d, limit %d)",
                self.source_name,
                page + 1,
                offset,
                limit,
            )
            try:
                response = self.session.get(
                    self.BASE_URL,
                    params=params,
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.HTTPError as exc:
                if response.status_code == 429:
                    logger.warning("[%s] Rate limited (HTTP 429). Stopping fetch.", self.source_name)
                else:
                    logger.error("[%s] HTTP error fetching jobs: %s", self.source_name, exc)
                break
            except requests.exceptions.RequestException as exc:
                logger.error("[%s] Network error contacting Himalayas: %s", self.source_name, exc)
                break
            except ValueError as exc:
                logger.error("[%s] Failed to parse JSON response: %s", self.source_name, exc)
                break

            jobs = data.get("jobs", [])
            if not jobs:
                logger.info("[%s] No more jobs returned at offset %d.", self.source_name, offset)
                break

            collected.extend(jobs)
            offset += len(jobs)

            if page < max_pages - 1:
                self.polite_sleep()

        logger.info(
            "[%s] Successfully retrieved %d jobs across %d page(s)",
            self.source_name,
            len(collected),
            max_pages,
        )
        return collected
