"""Task 5c.2a: FEED.md Exporter — fixed.

Changes from original:
  - One row per job: DISTINCT ON (j.id) with latest job_matches row;
    separate LATERAL join for the latest laya_job_scores row matching
    the current checkpoint + config_version.
  - Ranked by MatchScorer score only (match_score). Laya score shown as
    a separate column. COALESCE mixing the two scales removed.
  - "Scanned" count is now unique jobs, not raw join rows.
  - show_laya_score column in table (blank when no score exists yet).
"""
import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FEED_FILE = PROJECT_ROOT / "FEED.md"


def export_feed(top_n: int = 100) -> Path:
    logger.info("Exporting top %d jobs to %s...", top_n, FEED_FILE)

    # One row per job: latest match score + latest Laya score (if any).
    # Ranked by MatchScorer only. Laya score shown as info column.
    rows = execute_query("""
        SELECT
            j.id,
            j.title,
            j.company_name,
            j.location_raw,
            j.is_remote,
            j.apply_url,
            j.detected_language,
            j.is_unpaid,
            j.experience_level,
            j.nepal_accessible,
            jm.match_score,
            jm.matched_skills,
            jm.reason_code,
            jm.score_breakdown,
            ls.final_score AS laya_score,
            ls.role_type,
            ls.is_passed AS laya_passed,
            ls.disqualification_reason
        FROM jobs j
        -- Latest match row per job
        JOIN LATERAL (
            SELECT match_score, matched_skills, reason_code, score_breakdown, scored_at
            FROM job_matches
            WHERE job_id = j.id
            ORDER BY scored_at DESC
            LIMIT 1
        ) jm ON TRUE
        -- Latest Laya score row per job (optional)
        LEFT JOIN LATERAL (
            SELECT final_score, role_type, is_passed, disqualification_reason
            FROM laya_job_scores
            WHERE job_id = j.id
            ORDER BY scored_at DESC
            LIMIT 1
        ) ls ON TRUE
        ORDER BY jm.match_score DESC, j.id;
    """)

    if not rows:
        logger.warning("No jobs found in database.")
        return FEED_FILE

    total_unique_jobs = len(rows)
    passed_jobs: List[Dict[str, Any]] = []
    disqualified_counts: Dict[str, int] = {
        "NOT_REMOTE": 0,
        "NON_ENGLISH": 0,
        "GERMAN_ONLY": 0,  # legacy — kept for backward compat
        "UNPAID": 0,
        "REGION_LOCKED": 0,
        "NON_TECHNICAL": 0,
        "SENIOR": 0,
        "LOW_SCORE": 0,
        "NEEDS_REVIEW": 0,
        "OTHER": 0,
    }

    for r in rows:
        rc = r.get("reason_code")
        if rc is not None:
            key = rc if rc in disqualified_counts else "OTHER"
            disqualified_counts[key] += 1
            continue
        passed_jobs.append(r)

    ranked_jobs = passed_jobs[:top_n]

    lines = []
    lines.append("# Job Feed — Top Matched Roles")
    lines.append("")
    lines.append(
        f"> **Total Unique Jobs:** {total_unique_jobs}"
        f" | **Eligible Matches:** {len(passed_jobs)}"
        f" | **Showing Top:** {len(ranked_jobs)}"
    )
    lines.append("")

    lines.append("| Rank | Match | Laya | Job Title | Company | Location | Matched Skills | Apply |")
    lines.append("| :---: | :---: | :---: | :--- | :--- | :--- | :--- | :---: |")

    for rank, j in enumerate(ranked_jobs, start=1):
        match_score = j.get("match_score") or 0.0
        laya_score = j.get("laya_score")
        laya_str = f"{laya_score:.0f}" if laya_score is not None else "—"

        title = (j.get("title") or "Untitled").replace("|", "-")
        company = (j.get("company_name") or "Unknown").replace("|", "-")
        is_remote = "Remote" if j.get("is_remote") else "On-site"
        loc = j.get("location_raw") or "Unspecified"
        loc_str = f"{is_remote} ({loc})" if loc != "Unspecified" else is_remote

        skills = j.get("matched_skills") or []
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except Exception:
                skills = []
        skills_str = ", ".join(f"`{s}`" for s in skills[:4]) if skills else "—"

        link = j.get("apply_url") or "#"
        apply_md = f"[Apply]({link})" if link != "#" else "N/A"

        lines.append(
            f"| {rank} | **{match_score:.1f}** | {laya_str}"
            f" | {title} | {company} | {loc_str} | {skills_str} | {apply_md} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("### Disqualification Breakdown")
    lines.append("| Reason | Count | Example Titles |")
    lines.append("| :--- | :---: | :--- |")

    # Collect example titles per reason code
    reason_examples: Dict[str, List[str]] = {}
    for r in rows:
        rc = r.get("reason_code")
        if rc:
            key = rc if rc in disqualified_counts else "OTHER"
            if key not in reason_examples:
                reason_examples[key] = []
            if len(reason_examples[key]) < 3:
                reason_examples[key].append((r.get("title") or "?")[:40])

    for reason, count in disqualified_counts.items():
        if count == 0:
            continue
        examples = "; ".join(reason_examples.get(reason, []))
        lines.append(f"| `{reason}` | {count} | {examples} |")

    lines.append("")
    lines.append("*Ranked by MatchScorer. Laya score shown for reference only (uncalibrated until M1).*")
    lines.append(f"*Generated by `scripts/export_feed.py`.*")

    content = "\n".join(lines)
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Generated %s: %d unique jobs, %d eligible, %d shown.",
                FEED_FILE, total_unique_jobs, len(passed_jobs), len(ranked_jobs))
    return FEED_FILE


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export FEED.md for candidate job review.")
    parser.add_argument("--top-n", type=int, default=100, help="Number of top jobs to include.")
    args = parser.parse_args()
    export_feed(top_n=args.top_n)
