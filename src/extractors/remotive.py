"""Remotive remote job board API extractor."""
import logging
from typing import Any, Dict, List, Optional
import requests

from src import config
from src.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class RemotiveExtractor(BaseExtractor):
    """Extractor for Remotive public jobs API (https://remotive.com/api/remote-jobs).
    
    Remotive API Guidelines:
    - Rate limit: Do not exceed 2 requests per minute.
    - Attribution: Job listings must preserve and link to the original Remotive URL.
    """

    BASE_URL = "https://remotive.com/api/remote-jobs"

    def __init__(self, delay_seconds: float = 30.0):
        # Default 30s delay between calls to strictly comply with max 2 req/min limit
        super().__init__(source_name="remotive", delay_seconds=delay_seconds)

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Extract unique external ID from job item using 'id' or 'url'."""
        item_id = item.get("id")
        if item_id is not None:
            return str(item_id).strip()
        url = item.get("url")
        if url:
            return str(url).strip()
        return ""

    def fetch_raw(
        self,
        category: Optional[str] = "software-dev",
        search: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch remote job listings from Remotive API.
        
        Args:
            category: Job category filter (e.g. 'software-dev', 'data', 'qa').
            search: Optional keyword search string.
            limit: Maximum number of jobs to retrieve.
        """
        params: Dict[str, Any] = {}
        if category:
            params["category"] = category
        if search:
            params["search"] = search
        if limit:
            params["limit"] = limit

        logger.info("[%s] Fetching jobs from %s with params %s", self.source_name, self.BASE_URL, params)
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
                logger.warning("[%s] Rate limited (HTTP 429): Exceeded 2 requests/min.", self.source_name)
            else:
                logger.error("[%s] HTTP error fetching jobs: %s", self.source_name, exc)
            return []
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Network error contacting Remotive: %s", self.source_name, exc)
            return []
        except ValueError as exc:
            logger.error("[%s] Failed to parse JSON response: %s", self.source_name, exc)
            return []

        jobs = data.get("jobs", [])
        logger.info("[%s] Successfully retrieved %d jobs", self.source_name, len(jobs))
        return jobs
