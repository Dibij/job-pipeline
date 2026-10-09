"""Batch scoring service matching database jobs against candidate profile."""
import logging
from typing import Any, Dict, List
from psycopg.types.json import Jsonb

from src.db.connection import get_connection
from src.matching.hard_filter import apply_batch as hard_filter_batch, FilterReason
from src.matching.scorer import MatchScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def score_all_jobs() -> Dict[str, Any]:
    """Hard-filter then score every stored job. Writes results to job_matches.

    Pipeline:
      1. HardFilter — disqualify region-locked, German-only, unpaid, on-site-abroad jobs.
      2. MatchScorer — score only the jobs that passed hard filter.
      3. Upsert ALL jobs into job_matches (failed ones get score=0, reason_code set).
    """
    scorer = MatchScorer()

    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, description_text, location_raw, remote_restriction,
                       is_remote, experience_level, detected_language, is_unpaid,
                       nepal_accessible, tags
                FROM jobs;
            """)
            jobs = cur.fetchall()

    if not jobs:
        logger.info("No jobs found in database to score.")
        return {"total": 0, "passed_filter": 0, "scored": 0}

    logger.info("Running HardFilter on %d jobs...", len(jobs))
    filter_result = hard_filter_batch(jobs)
    passed_jobs = filter_result["passed"]
    failed_jobs = filter_result["failed"]  # list of (job, FilterResult)
    reason_counts = filter_result["reason_counts"]
    pass_rate = filter_result["pass_rate"]

    logger.info(
        "HardFilter: %d passed (%.0f%%), %d disqualified. Reason breakdown: %s",
        len(passed_jobs), pass_rate * 100, len(failed_jobs), reason_counts,
    )

    match_rows = []
    high_match_count = 0

    # Score jobs that passed the hard filter
    logger.info("Scoring %d jobs with MatchScorer...", len(passed_jobs))
    for job in passed_jobs:
        score, matched_skills, missing_skills, breakdown = scorer.score_job(job)
        if score >= 60.0:
            high_match_count += 1
        match_rows.append((
            job["id"], score, matched_skills, missing_skills,
            Jsonb(breakdown), None,  # reason_code = NULL (passed)
        ))

    # Record disqualified jobs with score=0 and reason_code
    for job, result in failed_jobs:
        match_rows.append((
            job["id"], 0.0, [], [],
            Jsonb({"hard_filter": result.reason.value, "detail": result.detail}),
            result.reason.value,
        ))

    # Upsert into job_matches (add reason_code column if not exists — migration guard)
    _ensure_reason_code_column()

    sql = """
        INSERT INTO job_matches (
            job_id, match_score, matched_skills, missing_skills, score_breakdown, reason_code, scored_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, NOW()
        )
        ON CONFLICT (job_id) DO UPDATE SET
            match_score = EXCLUDED.match_score,
            matched_skills = EXCLUDED.matched_skills,
            missing_skills = EXCLUDED.missing_skills,
            score_breakdown = EXCLUDED.score_breakdown,
            reason_code = EXCLUDED.reason_code,
            scored_at = NOW();
    """

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, match_rows)
        conn.commit()

    logger.info(
        "Done. Scored %d jobs, %d disqualified, %d strong matches (>=60).",
        len(passed_jobs), len(failed_jobs), high_match_count,
    )

    # Top 5 matches from passed jobs only
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT j.title, j.company_name, j.experience_level, j.is_remote,
                       m.match_score, m.matched_skills, m.reason_code
                FROM job_matches m
                JOIN jobs j ON j.id = m.job_id
                WHERE m.reason_code IS NULL
                ORDER BY m.match_score DESC
                LIMIT 5;
            """)
            top = cur.fetchall()

    return {
        "total": len(jobs),
        "passed_filter": len(passed_jobs),
        "disqualified": len(failed_jobs),
        "reason_counts": reason_counts,
        "pass_rate": pass_rate,
        "high_matches": high_match_count,
        "top_5": top,
    }


def _ensure_reason_code_column() -> None:
    """Add reason_code column to job_matches if it doesn't exist (safe to call repeatedly)."""
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                ALTER TABLE job_matches
                ADD COLUMN IF NOT EXISTS reason_code TEXT DEFAULT NULL;
            """)


if __name__ == "__main__":
    res = score_all_jobs()
    print(f"\n=== HARD FILTER RESULTS ===")
    print(f"  Total jobs:      {res['total']}")
    print(f"  Passed filter:   {res['passed_filter']} ({res['pass_rate']*100:.0f}%)")
    print(f"  Disqualified:    {res['disqualified']}")
    for reason, count in res['reason_counts'].items():
        if count:
            print(f"    {reason}: {count}")
    print(f"\n=== TOP 5 MATCHED JOBS ===")
    for idx, j in enumerate(res["top_5"], 1):
        print(f"{idx}. [{j['match_score']}%] {j['title']} @ {j['company_name']} ({j['experience_level']})")
        print(f"   Skills: {j['matched_skills']}")




