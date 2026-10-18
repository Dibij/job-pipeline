"""Task 9.8: Backfill direct ATS links into jobs.apply_url from descriptions.

Finds jobs whose apply_url points to an aggregator or generic thread but
whose description_html or description_text contains a direct link to
Greenhouse, Lever, Ashby, or Workable. Updates jobs.apply_url in place.

Usage:
    python scripts/backfill_direct_ats_links.py [--dry-run]
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.models.transformers import _ATS_LINK_PATTERNS, extract_direct_ats_link


def backfill_direct_ats_links(dry_run: bool = False):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, source, title, apply_url, description_html, description_text
                FROM jobs
                WHERE description_html IS NOT NULL OR description_text IS NOT NULL;
            """)
            rows = cur.fetchall()

            updates = []
            for r in rows:
                curr_apply = r["apply_url"] or ""
                # Skip if already a known ATS link
                if any(pat.match(curr_apply) for pat in _ATS_LINK_PATTERNS):
                    continue

                ats_link = extract_direct_ats_link(r["description_html"]) or extract_direct_ats_link(r["description_text"])
                if ats_link and ats_link != curr_apply:
                    updates.append((ats_link, r["id"], r["source"], r["title"], curr_apply))

            print(f"Scanned {len(rows)} jobs.")
            print(f"Found {len(updates)} jobs with extractable direct ATS links.")

            if not updates:
                print("No updates needed.")
                return

            print("\nSample updates (first 10):")
            for new_url, jid, src, title, old_url in updates[:10]:
                print(f"  [{src}] {title[:35]}")
                print(f"    From: {old_url}")
                print(f"    To:   {new_url}")

            if dry_run:
                print("\n[DRY RUN] No database writes performed.")
                return

            # Execute batch update
            for new_url, jid, _, _, _ in updates:
                cur.execute(
                    "UPDATE jobs SET apply_url = %s WHERE id = %s;",
                    (new_url, jid)
                )
            conn.commit()
            print(f"\nSuccessfully updated {len(updates)} jobs in database.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill direct ATS links into jobs.apply_url")
    parser.add_argument("--dry-run", action="store_true", help="Report planned updates without writing to DB")
    args = parser.parse_args()
    backfill_direct_ats_links(dry_run=args.dry_run)
