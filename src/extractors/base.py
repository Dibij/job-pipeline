"""Abstract base class for all job data extractors."""
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import requests
from psycopg.types.json import Jsonb

from src import config
from src.db.connection import get_connection

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Base class for pulling job listings and staging them in PostgreSQL."""

    def __init__(self, source_name: str, delay_seconds: float = 1.0):
        self.source_name = source_name
        self.delay_seconds = delay_seconds
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.DEFAULT_USER_AGENT,
            "Accept": "application/json",
        })

    @abstractmethod
    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        """Fetch raw listings from the source."""
        pass

    @abstractmethod
    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Extract a unique external ID from an individual raw listing item."""
        pass

    def stage_raw(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Stage raw listings into raw_job_listings table with conflict resolution."""
        if not items:
            logger.info("[%s] No items provided to stage.", self.source_name)
            return {"total": 0, "inserted": 0, "skipped": 0}

        inserted = 0
        with get_connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                for item in items:
                    ext_id = str(self.extract_external_id(item)).strip()
                    if not ext_id:
                        logger.warning("[%s] Skipping item without external ID: %s", self.source_name, item)
                        continue

                    payload_json = Jsonb(item)
                    cur.execute(
                        """
                        INSERT INTO raw_job_listings (source, external_id, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (source, external_id) DO NOTHING
                        RETURNING id;
                        """,
                        (self.source_name, ext_id, payload_json),
                    )
                    if cur.fetchone() is not None:
                        inserted += 1

            conn.commit()

        total = len(items)
        skipped = total - inserted
        logger.info(
            "[%s] Staged %d item(s) (Inserted: %d, Skipped/Duplicate: %d)",
            self.source_name,
            total,
            inserted,
            skipped,
        )
        return {"total": total, "inserted": inserted, "skipped": skipped}

    def polite_sleep(self):
        """Sleep for polite rate limiting between network calls."""
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
