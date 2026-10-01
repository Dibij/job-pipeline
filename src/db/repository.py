"""Repository handling PostgreSQL operations for normalized jobs."""
import logging
from typing import Any, Dict, List, Optional
from psycopg.types.json import Jsonb

from src.db.connection import get_connection
from src.models.job import NormalizedJob

logger = logging.getLogger(__name__)


class JobRepository:
    """Data access layer for normalized jobs and match scoring."""

    def upsert_job(self, job: NormalizedJob) -> Optional[str]:
        """Upsert a single NormalizedJob into PostgreSQL using fingerprint deduplication."""
        sql = """
            INSERT INTO jobs (
                source, external_id, title, company_name, company_url,
                location_raw, is_remote, remote_restriction, job_type,
                experience_level, description_text, description_html,
                apply_url, salary_min, salary_max, salary_currency,
                tags, posted_at, expires_at, fingerprint_hash
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (fingerprint_hash) DO UPDATE SET
                title = EXCLUDED.title,
                company_name = EXCLUDED.company_name,
                company_url = COALESCE(EXCLUDED.company_url, jobs.company_url),
                location_raw = COALESCE(EXCLUDED.location_raw, jobs.location_raw),
                is_remote = EXCLUDED.is_remote,
                remote_restriction = COALESCE(EXCLUDED.remote_restriction, jobs.remote_restriction),
                job_type = COALESCE(EXCLUDED.job_type, jobs.job_type),
                description_text = EXCLUDED.description_text,
                description_html = COALESCE(EXCLUDED.description_html, jobs.description_html),
                apply_url = EXCLUDED.apply_url,
                salary_min = COALESCE(EXCLUDED.salary_min, jobs.salary_min),
                salary_max = COALESCE(EXCLUDED.salary_max, jobs.salary_max),
                salary_currency = COALESCE(EXCLUDED.salary_currency, jobs.salary_currency),
                tags = EXCLUDED.tags,
                posted_at = COALESCE(EXCLUDED.posted_at, jobs.posted_at),
                updated_at = NOW()
            RETURNING id;
        """
        params = (
            job.source,
            job.external_id,
            job.title,
            job.company_name,
            job.company_url,
            job.location_raw,
            job.is_remote,
            job.remote_restriction,
            job.job_type,
            job.experience_level,
            job.description_text,
            job.description_html,
            job.apply_url,
            job.salary_min,
            job.salary_max,
            job.salary_currency,
            job.tags,
            job.posted_at,
            job.expires_at,
            job.fingerprint_hash,
        )

        with get_connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                job_id = str(row["id"]) if row else None
            conn.commit()
            return job_id

    def upsert_jobs(self, jobs: List[NormalizedJob]) -> Dict[str, int]:
        """Batch upsert normalized jobs into PostgreSQL."""
        if not jobs:
            return {"total": 0, "upserted": 0}

        upserted = 0
        for job in jobs:
            try:
                res = self.upsert_job(job)
                if res:
                    upserted += 1
            except Exception as exc:
                logger.error("Failed to upsert job '%s' (%s): %s", job.title, job.external_id, exc)

        return {"total": len(jobs), "upserted": upserted}

    def get_unprocessed_raw(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Fetch raw listings that haven't been normalized yet."""
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, source, external_id, payload 
                    FROM raw_job_listings 
                    WHERE processed = FALSE 
                    ORDER BY id ASC 
                    LIMIT %s;
                    """,
                    (limit,),
                )
                return cur.fetchall()

    def mark_raw_processed(self, ids: List[int]):
        """Mark raw listing IDs as processed."""
        if not ids:
            return
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE raw_job_listings SET processed = TRUE WHERE id = ANY(%s);",
                    (ids,),
                )
