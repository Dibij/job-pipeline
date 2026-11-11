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
from src.models.job import NormalizedJob

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
                        ON CONFLICT (source, external_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            fetched_at = NOW(),
                            processed = FALSE
                        RETURNING (xmax = 0) AS inserted;
                        """,
                        (self.source_name, ext_id, payload_json),
                    )
                    row = cur.fetchone()
                    if row is not None and row.get("inserted"):
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

    def stage_normalized_jobs(self, jobs: List[NormalizedJob]) -> Dict[str, int]:
        """Stage already-normalized jobs into raw_job_listings.

        Used by extractors that build NormalizedJob objects directly (python_org,
        reddit) because their source payloads are not in a shape the shared
        transformers can consume. The full job dump is stored as the payload and
        re-hydrated later by transform_pre_normalized.
        """
        if not jobs:
            logger.info("[%s] No normalized jobs to stage.", self.source_name)
            return {"total": 0, "inserted": 0, "skipped": 0}

        from datetime import datetime
        from decimal import Decimal

        inserted = 0
        invalid = 0
        with get_connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                for job in jobs:
                    payload = job.model_dump(mode="json")
                    for key, value in list(payload.items()):
                        if isinstance(value, (datetime, Decimal)):
                            payload[key] = str(value)
                        elif isinstance(value, str) and key.startswith("budget_"):
                            try:
                                payload[key] = float(value)
                            except (TypeError, ValueError):
                                pass
                    ext_id = str(job.external_id).strip()
                    if not ext_id:
                        invalid += 1
                        continue
                    cur.execute(
                        """
                        INSERT INTO raw_job_listings (source, external_id, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (source, external_id) DO NOTHING
                        RETURNING id;
                        """,
                        (self.source_name, ext_id, Jsonb(payload)),
                    )
                    if cur.fetchone() is not None:
                        inserted += 1
            conn.commit()

        total = len(jobs)
        skipped = total - inserted
        logger.info(
            "[%s] Staged %d normalized job(s) (Inserted: %d, Skipped/Duplicate: %d)",
            self.source_name, total, inserted, skipped,
        )
        return {"total": total, "inserted": inserted, "skipped": skipped}

    def polite_sleep(self):
        """Sleep for polite rate limiting between network calls."""
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
