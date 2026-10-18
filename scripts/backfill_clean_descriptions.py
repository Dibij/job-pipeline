"""Backfill HTML/entity/mojibake cleaning into existing jobs.description_text.

Keeps raw payloads in raw_job_listings untouched.
Updates jobs.description_text in batches and reports before/after counts.
"""
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection, execute_query
from src.models.transformers import clean_description_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 250


def backfill_clean_descriptions(batch_size: int = BATCH_SIZE) -> int:
    """Read jobs in batches, clean description_text, and update modified rows."""
    total_jobs_row = execute_query("SELECT COUNT(*) as cnt FROM jobs;")
    total_jobs = total_jobs_row[0]["cnt"] if total_jobs_row else 0
    logger.info("Found %d total jobs in jobs table.", total_jobs)

    offset = 0
    total_changed = 0
    sample_diffs: list[dict] = []

    while offset < total_jobs:
        rows = execute_query(
            "SELECT id, title, description_text FROM jobs ORDER BY id LIMIT %s OFFSET %s;",
            (batch_size, offset)
        )
        if not rows:
            break

        updates = []
        for r in rows:
            raw_desc = r["description_text"] or ""
            cleaned = clean_description_text(raw_desc)
            if cleaned != raw_desc:
                updates.append((cleaned, r["id"]))
                if len(sample_diffs) < 5:
                    sample_diffs.append({
                        "id": str(r["id"]),
                        "title": r.get("title", ""),
                        "before": raw_desc[:120],
                        "after": cleaned[:120],
                    })

        if updates:
            with get_connection(autocommit=False) as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        UPDATE jobs
                        SET description_text = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        updates,
                    )
                conn.commit()
            total_changed += len(updates)
            logger.info("Batch offset %d: cleaned and updated %d rows.", offset, len(updates))

        offset += batch_size

    print("\n" + "=" * 68)
    print("  DESCRIPTION TEXT CLEANING BACKFILL REPORT")
    print("=" * 68)
    print(f"  Total jobs inspected:      {total_jobs}")
    print(f"  Total jobs changed/cleaned: {total_changed}")
    print(f"  Unchanged jobs:             {total_jobs - total_changed}")
    print(f"  Raw payloads:               UNTOUCHED (raw_job_listings unchanged)")

    if sample_diffs:
        print("\n  Sample Before / After Diffs (up to 5):")
        for i, s in enumerate(sample_diffs, 1):
            print(f"\n  [{i}] Job {s['id']} ({s['title'][:40]}):")
            print(f"      BEFORE: {s['before']!r}")
            print(f"      AFTER:  {s['after']!r}")
    print("=" * 68 + "\n")

    return total_changed


if __name__ == "__main__":
    backfill_clean_descriptions()
