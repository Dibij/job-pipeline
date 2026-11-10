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
                location_raw, is_remote, remote_restriction, accessibility,
                reachable_from_nepal, reachable_reason, job_type,
                experience_level, description_text, description_html,
                apply_url, salary_min, salary_max, salary_currency,
                tags, posted_at, expires_at, fingerprint_hash,
                detected_language, is_unpaid, nepal_accessible, exclude_reason,
                opportunity_type, compensation_type, budget_min, budget_max, budget_currency,
                deadline, payment_verification_status, scam_risk_score, risk_flags,
                risk_explanation, status, source_url, last_seen_at,
                outreach_draft, technical_angle, clarification_questions,
                bounty_verdict, reject_reasons, funding_evidence,
                bounty_confidence, reject_evidence
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (fingerprint_hash) DO UPDATE SET
                title = EXCLUDED.title,
                company_name = EXCLUDED.company_name,
                company_url = COALESCE(EXCLUDED.company_url, jobs.company_url),
                location_raw = COALESCE(EXCLUDED.location_raw, jobs.location_raw),
                is_remote = EXCLUDED.is_remote,
                remote_restriction = COALESCE(EXCLUDED.remote_restriction, jobs.remote_restriction),
                accessibility = EXCLUDED.accessibility,
                reachable_from_nepal = EXCLUDED.reachable_from_nepal,
                reachable_reason = EXCLUDED.reachable_reason,
                job_type = COALESCE(EXCLUDED.job_type, jobs.job_type),
                experience_level = EXCLUDED.experience_level,
                detected_language = EXCLUDED.detected_language,
                is_unpaid = EXCLUDED.is_unpaid,
                nepal_accessible = EXCLUDED.nepal_accessible,
                exclude_reason = COALESCE(EXCLUDED.exclude_reason, jobs.exclude_reason),
                description_text = EXCLUDED.description_text,
                description_html = COALESCE(EXCLUDED.description_html, jobs.description_html),
                apply_url = EXCLUDED.apply_url,
                salary_min = COALESCE(EXCLUDED.salary_min, jobs.salary_min),
                salary_max = COALESCE(EXCLUDED.salary_max, jobs.salary_max),
                salary_currency = COALESCE(EXCLUDED.salary_currency, jobs.salary_currency),
                tags = EXCLUDED.tags,
                posted_at = COALESCE(EXCLUDED.posted_at, jobs.posted_at),
                updated_at = NOW(),
                opportunity_type = EXCLUDED.opportunity_type,
                compensation_type = COALESCE(EXCLUDED.compensation_type, jobs.compensation_type),
                budget_min = COALESCE(EXCLUDED.budget_min, jobs.budget_min),
                budget_max = COALESCE(EXCLUDED.budget_max, jobs.budget_max),
                budget_currency = COALESCE(EXCLUDED.budget_currency, jobs.budget_currency),
                deadline = COALESCE(EXCLUDED.deadline, jobs.deadline),
                payment_verification_status = COALESCE(EXCLUDED.payment_verification_status, jobs.payment_verification_status),
                scam_risk_score = EXCLUDED.scam_risk_score,
                risk_flags = EXCLUDED.risk_flags,
                risk_explanation = COALESCE(EXCLUDED.risk_explanation, jobs.risk_explanation),
                status = COALESCE(EXCLUDED.status, jobs.status),
                source_url = COALESCE(EXCLUDED.source_url, jobs.source_url),
                outreach_draft = COALESCE(EXCLUDED.outreach_draft, jobs.outreach_draft),
                technical_angle = COALESCE(EXCLUDED.technical_angle, jobs.technical_angle),
                clarification_questions = COALESCE(EXCLUDED.clarification_questions, jobs.clarification_questions),
                last_seen_at = NOW(),
                bounty_verdict = COALESCE(EXCLUDED.bounty_verdict, jobs.bounty_verdict),
                reject_reasons = COALESCE(EXCLUDED.reject_reasons, jobs.reject_reasons),
                funding_evidence = COALESCE(EXCLUDED.funding_evidence, jobs.funding_evidence),
                bounty_confidence = COALESCE(EXCLUDED.bounty_confidence, jobs.bounty_confidence),
                reject_evidence = COALESCE(EXCLUDED.reject_evidence, jobs.reject_evidence)
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
            job.accessibility,
            job.reachable_from_nepal,
            job.reachable_reason,
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
            job.detected_language,
            job.is_unpaid,
            job.nepal_accessible,
            job.exclude_reason,
            job.opportunity_type,
            job.compensation_type,
            job.budget_min,
            job.budget_max,
            job.budget_currency,
            job.deadline,
            job.payment_verification_status,
            job.scam_risk_score,
            job.risk_flags,
            job.risk_explanation,
            job.status,
            job.source_url,
            job.last_seen_at,
            job.outreach_draft,
            job.technical_angle,
            job.clarification_questions,
            job.bounty_verdict,
            job.reject_reasons,
            Jsonb(job.funding_evidence) if job.funding_evidence is not None else None,
            job.bounty_confidence,
            job.reject_evidence,
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

    def record_source_run(
        self,
        run_id: str,
        source: str,
        started_at: Any,
        fetched: int,
        inserted: int,
        skipped: int,
        error: Optional[str] = None,
    ) -> None:
        """Record an extraction run outcome into source_runs table."""
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO source_runs (run_id, source, started_at, fetched, inserted, skipped, error)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (run_id, source, started_at, fetched, inserted, skipped, error),
                )
