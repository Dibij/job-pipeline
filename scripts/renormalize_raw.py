"""Re-normalize all raw_job_listings through the fixed transformers.

Fixes 6a: remote_restriction was incorrectly defaulted to 'Worldwide' for
all Arbeitnow jobs and Remotive jobs with no location. This script re-runs
the transformer and enricher over every raw row and updates the jobs table
with correct values.
"""
import json
import sys

from src.db.connection import get_connection
from src.models.transformers import transform_raw_listing
from src.enrichment.enricher import JobEnricher


def main() -> None:
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id, source, payload FROM raw_job_listings ORDER BY id")
        rows = cur.fetchall()
        print(f"Total raw rows: {len(rows)}")

        updated = 0
        skipped = 0
        errors = 0

        for row in rows:
            row_id = row["id"]
            source = row["source"]
            raw_payload = row["payload"]
            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                job = transform_raw_listing(source, payload)
                enrichment = JobEnricher.enrich_job(job.model_dump())

                cur.execute(
                    """
                    UPDATE jobs
                    SET remote_restriction   = %s,
                        accessibility        = %s,
                        nepal_accessible     = %s,
                        reachable_from_nepal = %s,
                        reachable_reason     = %s
                    WHERE source = %s AND external_id = %s
                    """,
                    (
                        job.remote_restriction,
                        enrichment["accessibility"],
                        enrichment["nepal_accessible"],
                        enrichment["reachable_from_nepal"],
                        enrichment["reachable_reason"],
                        job.source,
                        job.external_id,
                    ),
                )
                if cur.rowcount:
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                if errors <= 5:
                    print(f"  ERR raw row {row_id}: {exc}", file=sys.stderr)

        conn.commit()
        print(f"Updated: {updated}  Skipped (no matching jobs row): {skipped}  Errors: {errors}")

        # Show reachable_from_nepal distribution
        cur.execute(
            """
            SELECT reachable_from_nepal, COUNT(*) 
            FROM jobs 
            GROUP BY reachable_from_nepal 
            ORDER BY reachable_from_nepal
            """
        )
        print("\nreachable_from_nepal distribution after re-normalization:")
        for r_row in cur.fetchall():
            print(f"  {r_row['reachable_from_nepal'] or 'NULL'}: {r_row['count']}")

        # Print 10 random rows per state
        print("\nSample 10 rows per state:")
        for state in ["accessible", "unknown", "blocked"]:
            print(f"\n--- State: {state.upper()} ---")
            cur.execute(
                """
                SELECT title, company_name, location_raw, remote_restriction, reachable_reason
                FROM jobs
                WHERE reachable_from_nepal = %s
                ORDER BY RANDOM()
                LIMIT 10;
                """,
                (state,),
            )
            samples = cur.fetchall()
            for idx, s in enumerate(samples, 1):
                loc = s['location_raw'] or 'None'
                restr = s['remote_restriction'] or 'None'
                print(f"  {idx}. [{s['company_name']}] {s['title']} | loc: {loc} | restr: {restr} | reason: {s['reachable_reason']}")


if __name__ == "__main__":
    main()
