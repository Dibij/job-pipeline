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
                bounty_confidence, reject_evidence,
                score, score_breakdown, why, notes, lane,
                issue_state, issue_state_reason, issue_closed_at,
                author_login, author_association, assignee_logins,
                issue_created_at, labels_with_actor,
                parent_issue_url, sub_issue_urls,
                fetched_at, verified_at, verification_status
            ) VALUES (                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s)
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
                reject_evidence = COALESCE(EXCLUDED.reject_evidence, jobs.reject_evidence),
                score = COALESCE(EXCLUDED.score, jobs.score),
                score_breakdown = COALESCE(EXCLUDED.score_breakdown, jobs.score_breakdown),
                why = COALESCE(EXCLUDED.why, jobs.why),
                notes = COALESCE(EXCLUDED.notes, jobs.notes),
                lane = COALESCE(EXCLUDED.lane, jobs.lane),
                issue_state = EXCLUDED.issue_state,
                issue_state_reason = EXCLUDED.issue_state_reason,
                issue_closed_at = EXCLUDED.issue_closed_at,
                author_login = COALESCE(EXCLUDED.author_login, jobs.author_login),
                author_association = COALESCE(EXCLUDED.author_association, jobs.author_association),
                assignee_logins = EXCLUDED.assignee_logins,
                issue_created_at = COALESCE(EXCLUDED.issue_created_at, jobs.issue_created_at),
                labels_with_actor = COALESCE(EXCLUDED.labels_with_actor, jobs.labels_with_actor),
                parent_issue_url = COALESCE(EXCLUDED.parent_issue_url, jobs.parent_issue_url),
                sub_issue_urls = COALESCE(EXCLUDED.sub_issue_urls, jobs.sub_issue_urls),
                fetched_at = COALESCE(EXCLUDED.fetched_at, jobs.fetched_at),
                verified_at = EXCLUDED.verified_at,
                verification_status = EXCLUDED.verification_status
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
            job.score,
            Jsonb(job.score_breakdown) if job.score_breakdown is not None else None,
            job.why,
            job.notes,
            job.lane,
            job.issue_state,
            job.issue_state_reason,
            job.issue_closed_at,
            job.author_login,
            job.author_association,
            job.assignee_logins or [],
            job.issue_created_at,
            Jsonb(job.labels_with_actor) if job.labels_with_actor is not None else None,
            job.parent_issue_url,
            Jsonb(job.sub_issue_urls) if job.sub_issue_urls is not None else None,
            job.fetched_at,
            job.verified_at,
            job.verification_status,
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


    # ------------------------------------------------------------------
    # Rejected-issue ledger: nothing is deleted, and we never re-surface an
    # unchanged rejection. Dedupe key is (repo, issue_number).
    # ------------------------------------------------------------------
    def upsert_rejected_issue(
        self,
        repo: str,
        issue_number: int,
        title: str,
        source_url: str,
        verdict: str,
        reject_reasons: List[str],
        reject_evidence: str,
        state_hash: str,
        funding_evidence: Optional[Dict[str, Any]] = None,
        score: Optional[int] = None,
        score_breakdown: Optional[Dict[str, Any]] = None,
        why: Optional[str] = None,
        notes: Optional[str] = None,
        reject_reason: Optional[str] = None,
        verified_at: Optional[Any] = None,
        fetched_at: Optional[Any] = None,
        verification_status: str = "VERIFIED",
    ) -> Dict[str, Any]:
        """Record a rejected issue; report whether it should be shown again.

        Re-surfaces only when last_state_hash changed (e.g. a linked PR was
        closed without merging, an assignee was removed, or a funding label
        appeared). Returns a dict with inserted/resurfaced/changed booleans.
        """
        with get_connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_state_hash FROM rejected_issues WHERE repo=%s AND issue_number=%s;",
                    (repo, issue_number),
                )
                row = cur.fetchone()
                previous_hash = row["last_state_hash"] if row else None

                cur.execute(
                    """
                    INSERT INTO rejected_issues (
                        repo, issue_number, title, verdict, reject_reasons,
                        reject_evidence, funding_evidence, score, score_breakdown,
                        why, notes, last_state_hash, source_url,
                        reject_reason, verified_at, fetched_at, verification_status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (repo, issue_number) DO UPDATE SET
                        title = EXCLUDED.title,
                        verdict = EXCLUDED.verdict,
                        reject_reasons = EXCLUDED.reject_reasons,
                        reject_evidence = EXCLUDED.reject_evidence,
                        funding_evidence = EXCLUDED.funding_evidence,
                        score = EXCLUDED.score,
                        score_breakdown = EXCLUDED.score_breakdown,
                        why = EXCLUDED.why,
                        notes = EXCLUDED.notes,
                        last_state_hash = EXCLUDED.last_state_hash,
                        source_url = EXCLUDED.source_url,
                        reject_reason = EXCLUDED.reject_reason,
                        verified_at = EXCLUDED.verified_at,
                        fetched_at = EXCLUDED.fetched_at,
                        verification_status = EXCLUDED.verification_status,
                        last_seen_at = NOW()
                    """
                    ,
                    (
                        repo, issue_number, title, verdict, list(reject_reasons or []),
                        reject_evidence,
                        Jsonb(funding_evidence) if funding_evidence is not None else None,
                        score,
                        Jsonb(score_breakdown) if score_breakdown is not None else None,
                        why, notes, state_hash, source_url,
                        reject_reason, verified_at, fetched_at, verification_status,
                    ),
                )
            conn.commit()

        changed = previous_hash != state_hash
        return {
            "inserted": previous_hash is None,
            "resurfaced": previous_hash is not None and changed,
            "changed": changed,
        }

    def get_rejected_state_hash(self, repo: str, issue_number: int) -> Optional[str]:
        """Return the last stored state hash for a rejected issue, if any."""
        with get_connection(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_state_hash FROM rejected_issues WHERE repo=%s AND issue_number=%s;",
                    (repo, issue_number),
                )
                row = cur.fetchone()
                return row["last_state_hash"] if row else None