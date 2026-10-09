"""Task 6-1: FEED.md Exporter.

Queries PostgreSQL for scored jobs and generates a clean Markdown feed (FEED.md)
ranked by match score for easy review.
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

    # Query job_matches joined with jobs and optional laya_job_scores
    rows = execute_query("""
        SELECT j.id, j.title, j.company_name, j.location_raw, j.is_remote, j.remote_restriction,
               j.apply_url, j.company_url, j.nepal_accessible, j.experience_level, j.detected_language, j.is_unpaid,
               m.match_score, m.matched_skills, m.missing_skills, m.score_breakdown,
               l.final_score AS laya_score, l.role_type, l.is_passed AS laya_passed, l.disqualification_reason
        FROM jobs j
        LEFT JOIN job_matches m ON j.id = m.job_id
        LEFT JOIN laya_job_scores l ON j.id = l.job_id
        ORDER BY COALESCE(l.final_score, m.match_score, 0) DESC, j.id DESC;
    """)

    if not rows:
        logger.warning("No jobs found in database.")
        return FEED_FILE

    total_jobs = len(rows)
    passed_jobs = []
    disqualified_counts: Dict[str, int] = {
        "INACCESSIBLE": 0,
        "GERMAN": 0,
        "UNPAID": 0,
        "SENIOR": 0,
        "NON_TECHNICAL": 0,
        "OTHER": 0
    }

    for r in rows:
        # Check hard disqualifiers / accessibility
        reasons = []
        is_accessible = r.get("nepal_accessible", True)
        lang = (r.get("detected_language") or "").lower()
        is_unpaid = bool(r.get("is_unpaid", False))
        exp = (r.get("experience_level") or "").lower()
        role = (r.get("role_type") or "").lower()

        if not is_accessible:
            disqualified_counts["INACCESSIBLE"] += 1
            continue
        if lang == "german":
            disqualified_counts["GERMAN"] += 1
            continue
        if is_unpaid:
            disqualified_counts["UNPAID"] += 1
            continue
        if exp == "senior":
            disqualified_counts["SENIOR"] += 1
            continue
        if role == "other":
            disqualified_counts["NON_TECHNICAL"] += 1
            continue

        passed_jobs.append(r)

    ranked_jobs = passed_jobs[:top_n]

    # Build FEED.md markdown content
    lines = []
    lines.append("# 🚀 Job Feed — Top Matched Roles")
    lines.append("")
    lines.append(f"> **Total Scanned Jobs:** {total_jobs} | **Eligible Matches:** {len(passed_jobs)} | **Showing Top:** {len(ranked_jobs)}")
    lines.append("")

    lines.append("| Rank | Score | Job Title | Company | Location / Remote | Matched Skills | Apply Link |")
    lines.append("| :---: | :---: | :--- | :--- | :--- | :--- | :---: |")

    for rank, j in enumerate(ranked_jobs, start=1):
        score = j.get("laya_score") or j.get("match_score") or 0.0
        title = (j.get("title") or "Untitled").replace("|", "-")
        company = (j.get("company_name") or "Unknown").replace("|", "-")
        is_remote = "🌐 Remote" if j.get("is_remote") else "🏢 On-site"
        loc = j.get("location_raw") or "Unspecified"
        loc_str = f"{is_remote} ({loc})" if loc != "Unspecified" else is_remote

        skills = j.get("matched_skills") or []
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except Exception:
                skills = []
        skills_str = ", ".join(skills[:4]) if skills else "—"

        link = j.get("apply_url") or j.get("company_url") or "#"
        apply_md = f"[Apply ↗]({link})" if link != "#" else "N/A"

        lines.append(f"| {rank} | **{score:.1f}** | {title} | {company} | {loc_str} | `{skills_str}` | {apply_md} |")

    lines.append("")
    lines.append("---")
    lines.append("### 📊 Disqualification Breakdown")
    lines.append("| Disqualification Reason | Jobs Killed |")
    lines.append("| :--- | :---: |")
    for reason, count in disqualified_counts.items():
        lines.append(f"| `{reason}` | {count} |")
    lines.append("")
    lines.append(f"*Generated automatically by `scripts/export_feed.py`.*")

    content = "\n".join(lines)
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Successfully generated %s with %d top jobs!", FEED_FILE, len(ranked_jobs))
    return FEED_FILE


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export FEED.md for candidate job review.")
    parser.add_argument("--top-n", type=int, default=100, help="Number of top jobs to include.")
    args = parser.parse_args()
    export_feed(top_n=args.top_n)
