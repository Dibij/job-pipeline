"""Reprocess and re-filter ATS jobs in the database with the corrected remote/reachability logic."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.models import transform_raw_listing
from src.enrichment.enricher import JobEnricher
from src.matching.hard_filter import apply as hard_filter_apply
from src.matching.scorer import MatchScorer

def main():
    scorer = MatchScorer()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, source, external_id, payload
                FROM raw_job_listings
                WHERE source LIKE 'ats%';
            """)
            raw_rows = cur.fetchall()

            print(f"Reprocessing {len(raw_rows)} ATS raw listings...")

            updated_jobs = 0
            disqualified_count = 0
            passed_count = 0

            for item in raw_rows:
                source = item["source"]
                payload = item["payload"]
                ext_id = item["external_id"]

                try:
                    norm_job = transform_raw_listing(source, payload)
                    enrichment = JobEnricher.enrich_job(norm_job.model_dump())
                    
                    # Update jobs table
                    cur.execute("""
                        UPDATE jobs
                        SET location_raw = %s,
                            remote_restriction = %s,
                            is_remote = %s,
                            accessibility = %s,
                            nepal_accessible = %s,
                            reachable_from_nepal = %s,
                            reachable_reason = %s,
                            updated_at = NOW()
                        WHERE source = %s AND external_id = %s
                        RETURNING id;
                    """, (
                        norm_job.location_raw,
                        norm_job.remote_restriction,
                        norm_job.is_remote,
                        enrichment["accessibility"],
                        enrichment["nepal_accessible"],
                        enrichment["reachable_from_nepal"],
                        enrichment["reachable_reason"],
                        source,
                        ext_id,
                    ))
                    job_row = cur.fetchone()
                    if not job_row:
                        continue

                    job_id = job_row["id"]
                    updated_jobs += 1

                    # Re-check HardFilter
                    job_dict = {
                        "id": job_id,
                        "title": norm_job.title,
                        "description_text": norm_job.description_text,
                        "location_raw": norm_job.location_raw,
                        "remote_restriction": norm_job.remote_restriction,
                        "is_remote": norm_job.is_remote,
                        "detected_language": enrichment["detected_language"],
                        "accessibility": enrichment["accessibility"],
                        "reachable_from_nepal": enrichment["reachable_from_nepal"],
                        "reachable_reason": enrichment["reachable_reason"],
                    }

                    hf_result = hard_filter_apply(job_dict)
                    if not hf_result.passed:
                        disqualified_count += 1
                        # Delete from job_matches or set score to 0
                        cur.execute("DELETE FROM job_matches WHERE job_id = %s;", (job_id,))
                    else:
                        passed_count += 1
                        score, matched, missing, breakdown = scorer.score_job(job_dict)
                        # Upsert job_matches
                        cur.execute("""
                            INSERT INTO job_matches (job_id, match_score, matched_skills, missing_skills, score_breakdown, scored_at)
                            VALUES (%s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (job_id) DO UPDATE
                            SET match_score = EXCLUDED.match_score,
                                matched_skills = EXCLUDED.matched_skills,
                                missing_skills = EXCLUDED.missing_skills,
                                score_breakdown = EXCLUDED.score_breakdown,
                                scored_at = NOW();
                        """, (
                            job_id, score, matched, missing, psycopg_json(breakdown)
                        ))

                except Exception as exc:
                    print(f"Error processing {source} {ext_id}: {exc}")

            conn.commit()

    print(f"\nDone!")
    print(f"Updated jobs in DB: {updated_jobs}")
    print(f"HardFilter Disqualified (removed from job_matches): {disqualified_count}")
    print(f"Passed HardFilter: {passed_count}")

def psycopg_json(obj):
    from psycopg.types.json import Jsonb
    return Jsonb(obj)

if __name__ == "__main__":
    main()
