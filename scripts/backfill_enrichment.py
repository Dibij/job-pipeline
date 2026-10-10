"""Task 6d: Backfill enrichment metadata for all stored jobs.

Enriches all jobs with:
  - experience_level (junior, mid, senior, intern, unspecified)
  - detected_language (english, german, etc.)
  - is_unpaid (contextual pattern check)
  - nepal_accessible & accessibility (3-state)
  - tags (standardized tech stack keywords)

Prints before/after experience_level distributions.
"""
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.enrichment.enricher import JobEnricher


def backfill_all_jobs() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, description_text, location_raw, remote_restriction,
                       is_remote, experience_level, tags
                FROM jobs
                ORDER BY id;
            """)
            rows = cur.fetchall()

    print(f"Total jobs to backfill: {len(rows)}")

    before_counts = Counter((r["experience_level"] or "unspecified").lower() for r in rows)
    after_counts = Counter()

    updates = []
    for r in rows:
        job_dict = {
            "title": r["title"] or "",
            "description_text": r["description_text"] or "",
            "location_raw": r["location_raw"] or "",
            "remote_restriction": r["remote_restriction"] or "",
            "is_remote": r["is_remote"],
            "tags": r["tags"] or [],
        }
        enriched = JobEnricher.enrich_job(job_dict)
        new_exp = (enriched["experience_level"] or "unspecified").lower()
        after_counts[new_exp] += 1

        updates.append((
            enriched["experience_level"],
            enriched["detected_language"],
            enriched["is_unpaid"],
            enriched["nepal_accessible"],
            enriched["accessibility"],
            enriched["tags"],
            r["id"],
        ))

    print("\n--- experience_level distribution BEFORE backfill ---")
    for k in sorted(before_counts.keys()):
        print(f"  {k}: {before_counts[k]}")

    print("\n--- experience_level distribution AFTER backfill ---")
    for k in sorted(after_counts.keys()):
        print(f"  {k}: {after_counts[k]}")

    update_sql = """
        UPDATE jobs
        SET experience_level  = %s,
            detected_language = %s,
            is_unpaid         = %s,
            nepal_accessible  = %s,
            accessibility     = %s,
            tags              = %s,
            updated_at        = NOW()
        WHERE id = %s;
    """

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.executemany(update_sql, updates)
        conn.commit()

    print(f"\nSuccessfully backfilled {len(updates)} jobs in database.")


if __name__ == "__main__":
    backfill_all_jobs()
