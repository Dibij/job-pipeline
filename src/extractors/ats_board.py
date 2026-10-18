"""ATS company board extractor (Greenhouse / Lever / Ashby).

Supports fetching job listings from public ATS job board APIs.
Source names are namespaced as 'ats:{slug}' (e.g. 'ats:supabase').

Polite delay: 1.5 s between requests. Boards are configured in
config/ats_boards.json and loaded by the pipeline at startup.

API endpoints (no auth required):
  Greenhouse : https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
  Lever      : https://api.lever.co/v0/postings/{slug}?mode=json
  Ashby      : https://api.ashbyhq.com/posting-api/job-board/{slug}
"""
import logging
import time
from typing import Any, Dict, List

import requests

from src import config
from src.db.connection import get_connection
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


class ATSBoardExtractor:
    """Fetch job listings from a single ATS company board and stage them in PostgreSQL.

    Args:
        board_slug:   Board identifier used in the API URL (e.g. 'supabase').
        platform:     One of 'greenhouse', 'lever', 'ashby'.
        company_name: Human-readable company name (stored in the payload).
        delay_seconds: Politeness sleep between any network retries.
    """

    PLATFORM_URLS = {
        "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
        "lever":      "https://api.lever.co/v0/postings/{slug}?mode=json",
        "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    }

    def __init__(
        self,
        board_slug: str,
        platform: str,
        company_name: str,
        delay_seconds: float = 1.5,
    ) -> None:
        if platform not in self.PLATFORM_URLS:
            raise ValueError(
                f"Unknown ATS platform '{platform}'. "
                f"Valid options: {list(self.PLATFORM_URLS)}"
            )
        self.board_slug = board_slug
        self.platform = platform
        self.company_name = company_name
        self.delay_seconds = delay_seconds
        self.source_name = f"ats:{board_slug}"
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": config.DEFAULT_USER_AGENT,
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_raw(self) -> List[Dict[str, Any]]:
        """Fetch raw job listings from the ATS board API.

        Returns a list of raw job dicts. Each dict is source-specific
        but always contains a '_ats_meta' key added by this extractor:
          {
            '_ats_meta': {
              'platform': 'ashby',
              'board_slug': 'supabase',
              'company_name': 'Supabase',
            },
            ... original API fields ...
          }
        """
        url = self.PLATFORM_URLS[self.platform].format(slug=self.board_slug)
        logger.info("[%s] Fetching from %s", self.source_name, url)
        try:
            resp = self._session.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            if resp.status_code == 429:
                logger.warning("[%s] Rate limited (HTTP 429).", self.source_name)
            else:
                logger.error("[%s] HTTP error: %s", self.source_name, exc)
            return []
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Network error: %s", self.source_name, exc)
            return []

        try:
            raw = resp.json()
        except ValueError as exc:
            logger.error("[%s] JSON parse error: %s", self.source_name, exc)
            return []

        items = self._extract_items(raw)
        meta = {
            "platform": self.platform,
            "board_slug": self.board_slug,
            "company_name": self.company_name,
        }
        for item in items:
            item["_ats_meta"] = meta

        logger.info("[%s] Retrieved %d raw listings", self.source_name, len(items))
        return items

    def stage_raw(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Upsert raw listings into raw_job_listings. Skips duplicates silently."""
        if not items:
            logger.info("[%s] No items to stage.", self.source_name)
            return {"total": 0, "inserted": 0, "skipped": 0}

        inserted = 0
        with get_connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                for item in items:
                    ext_id = self._extract_external_id(item)
                    if not ext_id:
                        logger.warning(
                            "[%s] Skipping item without extractable ID: %s",
                            self.source_name, str(item)[:120],
                        )
                        continue
                    cur.execute(
                        """
                        INSERT INTO raw_job_listings (source, external_id, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (source, external_id) DO NOTHING
                        RETURNING id;
                        """,
                        (self.source_name, ext_id, Jsonb(item)),
                    )
                    if cur.fetchone() is not None:
                        inserted += 1
            conn.commit()

        total = len(items)
        skipped = total - inserted
        logger.info(
            "[%s] Staged %d item(s)  (Inserted: %d, Skipped/Dup: %d)",
            self.source_name, total, inserted, skipped,
        )
        return {"total": total, "inserted": inserted, "skipped": skipped}

    def run(self) -> Dict[str, int]:
        """Convenience: fetch + stage in one call."""
        items = self.fetch_raw()
        if self.delay_seconds > 0 and items:
            time.sleep(self.delay_seconds)
        return self.stage_raw(items)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_items(self, raw: Any) -> List[Dict[str, Any]]:
        """Unwrap platform-specific envelope and return a flat list of job dicts."""
        if self.platform == "greenhouse":
            # {"jobs": [...], "meta": {...}}
            if isinstance(raw, dict):
                return [j for j in raw.get("jobs", []) if isinstance(j, dict)]
            return []

        elif self.platform == "lever":
            # Plain list of posting objects
            if isinstance(raw, list):
                return [j for j in raw if isinstance(j, dict)]
            return []

        elif self.platform == "ashby":
            # {"jobs": [...], "jobBoard": {...}}
            if isinstance(raw, dict):
                return [j for j in raw.get("jobs", []) if isinstance(j, dict)]
            return []

        return []

    def _extract_external_id(self, item: Dict[str, Any]) -> str:
        """Return a stable, unique external ID for the given raw item."""
        if self.platform == "greenhouse":
            return str(item.get("id", "")).strip()

        elif self.platform == "lever":
            return str(item.get("id", "")).strip()

        elif self.platform == "ashby":
            # Ashby uses 'id' (UUID string)
            return str(item.get("id", "")).strip()

        return ""
