"""Read-only pipeline funnel report.

For the last N days (default 7), prints per-source:
  Fetched (from raw_job_listings) -> New (rows inserted into jobs) -> Passed HardFilter -> Scored >= 60
  Split into two columns: HardFilter reasons and MatchScorer reasons.

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
MATCH_SCORER_REASONS = {
    "SENIOR", "NO_TECH_SIGNAL", "LOW_SCORE", "PLACEHOLDER",
}


def run_report(days: int = 7) -> None:
    """Query DB and print funnel table with split rejection columns."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            # 1. All distinct sources across raw and normalized jobs + remotive
            cur.execute(
                """
                SELECT DISTINCT source FROM (
                    SELECT source FROM raw_job_listings
                    UNION
                    SELECT source FROM jobs
                    UNION
                    SELECT 'remotive'
                ) s ORDER BY source;
                """
            )
            all_sources = [r["source"] for r in cur.fetchall()]

            # 2a. Read Fetched from source_runs table (observability)
            cur.execute(
                """
                SELECT source, SUM(fetched) AS fetched, COUNT(*) AS run_count
                FROM source_runs
                WHERE started_at >= NOW() - %s * INTERVAL '1 day'
                GROUP BY source;
                """,
                (days,),
            )
            sr_rows = cur.fetchall()
            sr_map = {r["source"]: int(r["fetched"] or 0) for r in sr_rows}

            # 2b. Fallback query from raw_job_listings for earlier days / untracked runs
            cur.execute(
                """
                SELECT source, COUNT(*) AS fetched
                FROM raw_job_listings
                WHERE fetched_at >= NOW() - %s * INTERVAL '1 day'
                GROUP BY source;
                """,
                (days,),
            )
            raw_fallback_map = {r["source"]: r["fetched"] for r in cur.fetchall()}

            # 3. New rows actually inserted into jobs in the window
            cur.execute(
                """
                SELECT
                    j.source,
                    COUNT(DISTINCT j.id) AS new_jobs,
                    COUNT(DISTINCT j.id) FILTER (
                        WHERE m.reason_code IS NULL
                           OR m.reason_code NOT IN (
                               'NON_ENGLISH','GERMAN_ONLY','UNPAID',
                               'REGION_LOCKED','NOT_REMOTE','NON_TECHNICAL'
                           )
                    ) AS passed_hf,
                    COUNT(DISTINCT j.id) FILTER (
                        WHERE m.match_score >= 60.0
                          AND m.reason_code IS NULL
                    ) AS scored_60
                FROM jobs j
                LEFT JOIN job_matches m ON j.id = m.job_id
                WHERE j.created_at >= NOW() - %s * INTERVAL '1 day'
                GROUP BY j.source;
                """,
                (days,),
            )
            new_map = {r["source"]: r for r in cur.fetchall()}

            # 4. Rejection breakdown per source in the window
            cur.execute(
                """
                SELECT j.source, m.reason_code, COUNT(*) AS cnt
                FROM jobs j
                JOIN job_matches m ON j.id = m.job_id
                WHERE j.created_at >= NOW() - %s * INTERVAL '1 day'
                  AND m.reason_code IS NOT NULL
                GROUP BY j.source, m.reason_code
                ORDER BY j.source, cnt DESC;
                """,
                (days,),
            )
            rejection_rows = cur.fetchall()

    # Split rejections into HardFilter and MatchScorer buckets
    hf_rejections: dict[str, list[tuple[str, int]]] = {}
    ms_rejections: dict[str, list[tuple[str, int]]] = {}

    for row in rejection_rows:
        src = row["source"]
        code = row["reason_code"]
        cnt = row["cnt"]
        if code in HARD_FILTER_REASONS:
            hf_rejections.setdefault(src, []).append((code, cnt))
        else:
            ms_rejections.setdefault(src, []).append((code, cnt))

    # Resolve Fetched per source: prefer source_runs, fall back to raw_job_listings
    fetched_map = {}
    fallback_sources = []
    for s in all_sources:
        if s in sr_map:
            fetched_map[s] = sr_map[s]
        else:
            fetched_map[s] = raw_fallback_map.get(s, 0)
            if raw_fallback_map.get(s, 0) > 0:
                fallback_sources.append(s)

    # Sort sources by fetched DESC (then source name)
    sources_sorted = sorted(
        all_sources,
        key=lambda s: (fetched_map.get(s, 0), new_map.get(s, {}).get("new_jobs", 0)),
        reverse=True,
    )

    divider = "-" * 132
    print(f"\n{'=' * 132}")
    print(f"  PIPELINE FUNNEL REPORT  (last {days} days)")
    if fallback_sources:
        print(f"  * Note: Fetched reads from source_runs table. Fell back to raw_job_listings query for")
        print(f"          earlier days without source_runs: {', '.join(fallback_sources)}")
    else:
        print(f"  * Note: Fetched reads from source_runs table.")
    print(f"{'=' * 132}")
    print(
        f"  {'Source':<16} {'Fetched':>8} {'New':>7} {'PassedHF':>9} {'Scored>=60':>10} | "
        f"{'HardFilter Rejections':<38} | {'MatchScorer Rejections':<35}"
    )
    print(f"  {divider}")

    totals = {
        "fetched": 0,
        "new": 0,
        "passed_hf": 0,
        "scored_60": 0,
        "hf_rej": 0,
        "ms_rej": 0,
    }

    for src in sources_sorted:
        fetched = fetched_map.get(src, 0)
        n_info = new_map.get(src, {})
        new_jobs = n_info.get("new_jobs", 0)
        passed_hf = n_info.get("passed_hf", 0)
        scored_60 = n_info.get("scored_60", 0)

        hf_list = hf_rejections.get(src, [])
        ms_list = ms_rejections.get(src, [])

        hf_total = sum(c for _, c in hf_list)
        ms_total = sum(c for _, c in ms_list)

        totals["fetched"] += fetched
        totals["new"] += new_jobs
        totals["passed_hf"] += passed_hf
        totals["scored_60"] += scored_60
        totals["hf_rej"] += hf_total
        totals["ms_rej"] += ms_total

        # Format initial row with source stats and total rejection counts
        hf_summary = f"{hf_total:,} disqualified" if hf_total else "-"
        ms_summary = f"{ms_total:,} disqualified" if ms_total else "-"
        print(
            f"  {src:<16} {fetched:>8,} {new_jobs:>7,} {passed_hf:>9,} {scored_60:>10,} | "
            f"{hf_summary:<38} | {ms_summary:<35}"
        )

        # Print detailed reasons in two columns side-by-side
        max_reasons = max(len(hf_list), len(ms_list))
        for i in range(max_reasons):
            if i < len(hf_list):
                r_code, r_cnt = hf_list[i]
                pct = (r_cnt / fetched * 100) if fetched else 0.0
                hf_str = f"  -> {r_code}: {r_cnt:,} ({pct:.1f}%)"
            else:
                hf_str = ""

            if i < len(ms_list):
                r_code, r_cnt = ms_list[i]
                pct = (r_cnt / fetched * 100) if fetched else 0.0
                ms_str = f"  -> {r_code}: {r_cnt:,} ({pct:.1f}%)"
            else:
                ms_str = ""

            print(f"  {'':<16} {'':>8} {'':>7} {'':>9} {'':>10} | {hf_str:<38} | {ms_str:<35}")

    print(f"  {divider}")
    tot_hf = f"{totals['hf_rej']:,} disqualified"
    tot_ms = f"{totals['ms_rej']:,} disqualified"
    print(
        f"  {'TOTAL':<16} {totals['fetched']:>8,} {totals['new']:>7,} {totals['passed_hf']:>9,} {totals['scored_60']:>10,} | "
        f"{tot_hf:<38} | {tot_ms:<35}"
    )
    print(f"{'=' * 132}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline funnel report (read-only).")
    parser.add_argument(
        "--days", type=int, default=7, help="Look-back window in days (default: 7)"
    )
    args = parser.parse_args()
    run_report(days=args.days)


if __name__ == "__main__":
    main()
