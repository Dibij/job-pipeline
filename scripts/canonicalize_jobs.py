"""5c.2b: Detect and mark cross-posted duplicate job listings.

Canonical key strategy (in priority order):
  1. Same arbeitnow listing ID: the numeric suffix at the end of the
     apply_url path (e.g. -165068). If two rows share the same number,
     they are the same listing on different regional boards (.ch / .fr / .com).
     The one with the highest match_score (or oldest created_at) is kept as
     the canonical; the other gets canonical_job_id = canonical.id.
  2. Fallback: normalized(company_slug + title_slug). Used only when the
     URL path ID differs but the content looks identical.

IMPORTANT facts from the audit:
  - LILT Mongolian: IDs 165068 vs 174541 — DIFFERENT listings (genuinely
    two postings). NOT merged.
  - PRECIA MOLEN: all 4 rows have different job titles/locations — NOT
    the same role. NOT merged.
  - The 17 duplicate label pairs all agree on label, so collapsing is safe.

Usage:
    python scripts/canonicalize_jobs.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query, get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _extract_listing_id(url: str) -> Optional[str]:
    """Extract the numeric listing ID from the end of an Arbeitnow URL path.

    e.g. https://www.arbeitnow.ch/.../linguist-mongolian-...-165068  -> '165068'
    Returns None if no numeric suffix found.
    """
    if not url:
        return None
    slug = url.rstrip("/").split("/")[-1]
    m = re.search(r"-(\d{4,})$", slug)
    return m.group(1) if m else None


def _normalize_key(company: str, title: str) -> str:
    """Stable slug for fallback canonical matching."""
    def slug(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return f"{slug(company)}|{slug(title)}"


def find_duplicates(rows: List[Dict]) -> List[Tuple[List[Dict], str]]:
    """Return groups of duplicate rows and the reason they matched.

    Each group is (list_of_rows, reason_string).
    Groups with exactly 1 member are not returned.
    """
    # Group by listing_id first
    by_listing_id: Dict[str, List[Dict]] = defaultdict(list)
    no_id: List[Dict] = []
    for r in rows:
        lid = _extract_listing_id(r["apply_url"])
        if lid:
            by_listing_id[lid].append(r)
        else:
            no_id.append(r)

    groups = []
    for lid, group in by_listing_id.items():
        if len(group) > 1:
            groups.append((group, f"same listing_id={lid}"))

    # Fallback: company+title slug for rows that had no numeric ID
    by_slug: Dict[str, List[Dict]] = defaultdict(list)
    for r in no_id:
        key = _normalize_key(r["company_name"], r["title"])
        by_slug[key].append(r)
    for slug, group in by_slug.items():
        if len(group) > 1:
            groups.append((group, f"same company+title slug={slug[:60]}"))

    return groups


def choose_canonical(group: List[Dict]) -> Dict:
    """Pick the best canonical from a group: highest match_score, then oldest."""
    def sort_key(r: Dict):
        score = r.get("match_score") or 0.0
        # older = smaller created_at = better (already crawled, stable)
        created = r.get("created_at") or ""
        return (-score, str(created))
    return sorted(group, key=sort_key)[0]


def run(dry_run: bool = False) -> None:
    logger.info("Loading all jobs...")
    rows = execute_query("""
        SELECT j.id, j.title, j.company_name, j.apply_url, j.source,
               j.created_at, j.canonical_job_id,
               jm.match_score
        FROM jobs j
        LEFT JOIN LATERAL (
            SELECT match_score FROM job_matches
            WHERE job_id = j.id ORDER BY scored_at DESC LIMIT 1
        ) jm ON TRUE
        ORDER BY j.created_at
    """)
    logger.info("Loaded %d job rows.", len(rows))

    # Only consider rows that don't already have a canonical assigned
    unresolved = [r for r in rows if r["canonical_job_id"] is None]
    duplicates = find_duplicates(unresolved)

    logger.info("Found %d duplicate groups.", len(duplicates))

    updates: List[Tuple[str, str]] = []  # (canonical_id, duplicate_id)
    for group, reason in duplicates:
        canonical = choose_canonical(group)
        non_canonical = [r for r in group if r["id"] != canonical["id"]]
        logger.info(
            "Group (%s): canonical=%s (%s), merging %d others",
            reason, str(canonical["id"])[:8], canonical["title"][:40], len(non_canonical)
        )
        for r in non_canonical:
            logger.info("  -> %s (%s | %s)", str(r["id"])[:8], r["source"], r["apply_url"][-50:])
            updates.append((str(canonical["id"]), str(r["id"])))

    if not updates:
        logger.info("No duplicates found. Nothing to update.")
        return

    if dry_run:
        logger.info("[DRY RUN] Would set canonical_job_id for %d rows.", len(updates))
        return

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            for canonical_id, dup_id in updates:
                cur.execute(
                    "UPDATE jobs SET canonical_job_id = %s WHERE id = %s",
                    (canonical_id, dup_id)
                )
        conn.commit()

    logger.info("Marked %d rows as non-canonical.", len(updates))

    # Report
    print(f"\n[CANONICALIZE] {len(duplicates)} duplicate groups found.")
    print(f"  {len(updates)} rows marked as non-canonical.")
    print("  Run export_feed.py to regenerate FEED.md with deduplicated results.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mark cross-posted duplicate jobs.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing.")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
