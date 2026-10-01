"""Batch scoring service matching database jobs against candidate profile."""
import json
import logging
from typing import Any, Dict, List
from psycopg.types.json import Jsonb

from src.db.connection import get_connection
from src.matching.scorer import MatchScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def score_all_jobs() -> Dict[str, Any]:
    """Score every stored job in PostgreSQL and write results to job_matches."""
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
        return {"total": 0, "scored": 0}

    logger.info("Scoring %d jobs against candidate CV profile...", len(jobs))

    match_rows = []
    high_match_count = 0

    for job in jobs:
        score, matched_skills, missing_skills, breakdown = scorer.score_job(job)
        if score >= 60.0:
            high_match_count += 1

        match_rows.append((
            job["id"],
            score,
            matched_skills,
            missing_skills,
            Jsonb(breakdown),
        ))

    # Upsert into job_matches
    sql = """
        INSERT INTO job_matches (
            job_id, match_score, matched_skills, missing_skills, score_breakdown, scored_at
        ) VALUES (
            %s, %s, %s, %s, %s, NOW()
        )
        ON CONFLICT (job_id) DO UPDATE SET
            match_score = EXCLUDED.match_score,
            matched_skills = EXCLUDED.matched_skills,
            missing_skills = EXCLUDED.missing_skills,
            score_breakdown = EXCLUDED.score_breakdown,
            scored_at = NOW();
    """

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, match_rows)
        conn.commit()

    logger.info("Scored %d jobs! Found %d strong matches (score >= 60%%).", len(jobs), high_match_count)

    # Print top 5 matches
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT j.title, j.company_name, j.experience_level, j.is_remote,
                       m.match_score, m.matched_skills, m.score_breakdown->>'flags' as flags
                FROM job_matches m
                JOIN jobs j ON j.id = m.job_id
                ORDER BY m.match_score DESC
                LIMIT 5;
            """)
            top = cur.fetchall()

    return {
        "total_scored": len(jobs),
        "high_matches": high_match_count,
        "top_5": top,
    }


if __name__ == "__main__":
    res = score_all_jobs()
    print("\n=== TOP 5 MATCHED JOBS ===")
    for idx, j in enumerate(res["top_5"], 1):
        print(f"{idx}. [{j['match_score']}%] {j['title']} @ {j['company_name']} ({j['experience_level']}) | Skills: {j['matched_skills']}")
