"""Read-only pipeline funnel report.

For the last N days (default 7), prints per-source:
  fetched -> new -> passed HardFilter -> scored >= 60
  Top 3 rejection reasons with counts.

Usage:
    python scripts/funnel_report.py [--days N]
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection  # noqa: E402

HARD_FILTER_REASONS = {
    "NON_ENGLISH", "GERMAN_ONLY", "UNPAID", "REGION_LOCKED",
    "NOT_REMOTE", "NON_TECHNICAL",
}


def run_report(days: int = 7) -> None:
    """Query DB and print funnel table + rejection breakdown."""
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            # ── Funnel counts per source ──────────────────────────────────
            cur.execute(
                """
                SELECT
                    j.source,
                    COUNT(DISTINCT r.id)   AS fetched,
                    COUNT(DISTINCT j.id)   AS new_jobs,
                    COUNT(DISTINCT j.id)
                        FILTER (WHERE m.reason_code IS NULL
                                   OR m.reason_code NOT IN (
                                       'NON_ENGLISH','GERMAN_ONLY','UNPAID',
                                       'REGION_LOCKED','NOT_REMOTE','NON_TECHNICAL'
                                   ))    AS passed_hf,
                    COUNT(DISTINCT j.id)
                        FILTER (WHERE m.match_score >= 60.0
                                  AND m.reason_code IS NULL) AS scored_60_plus
                FROM jobs j
                LEFT JOIN raw_job_listings r
                       ON j.source = r.source AND j.external_id = r.external_id
                LEFT JOIN job_matches m ON j.id = m.job_id
                WHERE j.created_at >= NOW() - %s * INTERVAL '1 day'
                GROUP BY j.source
                ORDER BY fetched DESC;
                """,
                (days,),
            )
            funnel_rows = cur.fetchall()

            # ── Rejection reasons per source ──────────────────────────────
            cur.execute(
                """
                SELECT j.source, m.reason_code, COUNT(*) AS cnt
                FROM job_matches m
                JOIN jobs j ON j.id = m.job_id
                WHERE j.created_at >= NOW() - %s * INTERVAL '1 day'
                  AND m.reason_code IS NOT NULL
                GROUP BY j.source, m.reason_code
                ORDER BY j.source, cnt DESC;
                """,
                (days,),
            )
            rejection_rows = cur.fetchall()

    # Build rejection lookup: source -> [(reason, cnt), ...]
    rejection: dict[str, list[tuple[str, int]]] = {}
    for row in rejection_rows:
        rejection.setdefault(row["source"], []).append(
            (row["reason_code"], row["cnt"])
        )

    # Ensure UTF-8 output on Windows consoles if needed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # ── Print report ──────────────────────────────────────────────────────
    divider = "-" * 80
    print(f"\n{'=' * 80}")
    print(f"  PIPELINE FUNNEL REPORT  (last {days} days)")
    print(f"{'=' * 80}")
    print(
        f"  {'Source':<18} {'Fetched':>8} {'New':>7} {'PassedHF':>10}"
        f" {'Scored>=60':>10}  {'Yield':>6}"
    )
    print(f"  {divider}")

    totals = {"fetched": 0, "new": 0, "passed_hf": 0, "scored_60": 0}

    for row in funnel_rows:
        src = row["source"]
        fetched = row["fetched"] or 0
        new_jobs = row["new_jobs"] or 0
        passed_hf = row["passed_hf"] or 0
        scored_60 = row["scored_60_plus"] or 0
        yield_pct = (scored_60 / fetched * 100) if fetched else 0.0

        totals["fetched"] += fetched
        totals["new"] += new_jobs
        totals["passed_hf"] += passed_hf
        totals["scored_60"] += scored_60

        print(
            f"  {src:<18} {fetched:>8,} {new_jobs:>7,} {passed_hf:>10,}"
            f" {scored_60:>10,}  {yield_pct:>5.1f}%"
        )

        # Top 3 rejection reasons for this source
        reasons = rejection.get(src, [])[:3]
        for reason, cnt in reasons:
            pct = (cnt / fetched * 100) if fetched else 0.0
            print(f"    -> {reason:<20} {cnt:>5,}  ({pct:.1f}% of fetched)")

    print(f"  {divider}")
    total_yield = (
        (totals["scored_60"] / totals["fetched"] * 100) if totals["fetched"] else 0.0
    )
    print(
        f"  {'TOTAL':<18} {totals['fetched']:>8,} {totals['new']:>7,}"
        f" {totals['passed_hf']:>10,} {totals['scored_60']:>10,}  {total_yield:>5.1f}%"
    )
    print(f"{'=' * 80}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline funnel report (read-only).")
    parser.add_argument(
        "--days", type=int, default=7, help="Look-back window in days (default: 7)"
    )
    args = parser.parse_args()
    run_report(days=args.days)


if __name__ == "__main__":
    main()
