"""Backfill detected_language in PostgreSQL jobs table and evaluate HardFilter.

Evaluates each job's title and first 500 chars using JobEnricher.detect_language.
Updates changed jobs in batches.
Compares HardFilter NON_ENGLISH count and eligible pass count before vs after.
"""
import logging
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection, execute_query
from src.enrichment.enricher import JobEnricher
from src.matching.hard_filter import apply as hard_filter_apply

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 250


def evaluate_hard_filter(jobs: list[dict]) -> tuple[int, dict[str, int]]:
    """Run HardFilter across a list of job dicts; return (passed_count, reason_counts)."""
    passed = 0
    reasons: dict[str, int] = {}
    for j in jobs:
        res = hard_filter_apply(j)
        if res.passed:
            passed += 1
        else:
            r = res.reason.value
            reasons[r] = reasons.get(r, 0) + 1
    return passed, reasons


def backfill_languages() -> None:
    logger.info("Fetching all jobs for language evaluation...")
    rows = execute_query("""
        SELECT id, title, description_text, location_raw, remote_restriction, is_remote, detected_language, is_unpaid
        FROM jobs
        ORDER BY id;
    """)
    total_jobs = len(rows)
    logger.info("Fetched %d jobs.", total_jobs)

    # 1. Evaluate BEFORE backfill
    before_passed, before_reasons = evaluate_hard_filter(rows)

    # 2. Compute language changes
    updates = []
    change_pairs = []
    for r in rows:
        old_lang = r["detected_language"] or "english"
        new_lang = JobEnricher.detect_language(r["title"], r["description_text"])
        if new_lang != old_lang:
            updates.append((new_lang, r["id"]))
            change_pairs.append((old_lang, new_lang))
            # Update local dict in-memory for post-evaluation
            r["detected_language"] = new_lang

    print("\n" + "=" * 68)
    print("  LANGUAGE BACKFILL PRE-CHECK")
    print("=" * 68)
    print(f"  Total jobs inspected:              {total_jobs}")
    print(f"  Jobs requiring language update:    {len(updates)}")
    print(f"  Language transitions:              {dict(Counter(change_pairs))}")

    # 3. Apply DB batch updates
    if updates:
        logger.info("Writing %d language updates to database...", len(updates))
        with get_connection(autocommit=False) as conn:
            with conn.cursor() as cur:
                for i in range(0, len(updates), BATCH_SIZE):
                    batch = updates[i:i + BATCH_SIZE]
                    cur.executemany(
                        """
                        UPDATE jobs
                        SET detected_language = %s,
                            updated_at = NOW()
                        WHERE id = %s;
                        """,
                        batch,
                    )
            conn.commit()
        logger.info("Successfully updated %d rows in jobs table.", len(updates))
    else:
        logger.info("No updates needed; all languages match current detector.")

    # 4. Evaluate AFTER backfill
    after_passed, after_reasons = evaluate_hard_filter(rows)

    print("\n" + "=" * 68)
    print("  HARDFILTER COMPARISON REPORT (BEFORE vs AFTER BACKFILL)")
    print("=" * 68)
    print(f"  Total jobs:                   {total_jobs}")
    print(f"  Eligible jobs (Passed):       {before_passed}  -->  {after_passed}  (delta: {after_passed - before_passed:+d})")
    print(f"  NON_ENGLISH rejections:       {before_reasons.get('NON_ENGLISH', 0)}  -->  {after_reasons.get('NON_ENGLISH', 0)}  (delta: {after_reasons.get('NON_ENGLISH', 0) - before_reasons.get('NON_ENGLISH', 0):+d})")
    print("\n  Full Rejections Breakdown (After):")
    for r, c in sorted(after_reasons.items(), key=lambda x: -x[1]):
        delta = c - before_reasons.get(r, 0)
        delta_str = f"({delta:+d})" if delta != 0 else ""
        print(f"    - {r:<22}: {c:5} {delta_str}")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    backfill_languages()
