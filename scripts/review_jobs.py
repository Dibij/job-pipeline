"""Task 6-2: Interactive CLI Job Review Tool.

Resumable CLI tool that steps through top matched jobs, presenting key details
and saving user decisions (interested / skipped) to data/reviewed_jobs.json.
"""
import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REVIEWED_FILE = PROJECT_ROOT / "data" / "reviewed_jobs.json"


def load_reviewed() -> Dict[str, Dict[str, Any]]:
    if not REVIEWED_FILE.exists():
        return {}
    try:
        with open(REVIEWED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Could not read %s: %s. Starting fresh.", REVIEWED_FILE, e)
        return {}


def save_reviewed(reviewed_data: Dict[str, Dict[str, Any]]):
    REVIEWED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REVIEWED_FILE, "w", encoding="utf-8") as f:
        json.dump(reviewed_data, f, indent=2)


def run_review(limit: int = 50):
    reviewed = load_reviewed()
    reviewed_ids = set(reviewed.keys())

    logger.info("Loaded %d previously reviewed job decisions.", len(reviewed_ids))

    # Fetch top eligible jobs
    rows = execute_query("""
        SELECT j.id, j.title, j.company_name, j.location_raw, j.is_remote,
               j.apply_url, j.company_url, j.nepal_accessible, j.experience_level,
               j.description_text,
               COALESCE(l.final_score, m.match_score, 0) AS score,
               COALESCE(l.role_type, 'other') AS role_type,
               m.matched_skills
        FROM jobs j
        LEFT JOIN job_matches m ON j.id = m.job_id
        LEFT JOIN laya_job_scores l ON j.id = l.job_id
        WHERE j.nepal_accessible = true
          AND (j.detected_language IS NULL OR j.detected_language != 'german')
          AND j.is_unpaid = false
        ORDER BY COALESCE(l.final_score, m.match_score, 0) DESC, j.id DESC;
    """)

    unreviewed_jobs = [r for r in rows if str(r["id"]) not in reviewed_ids][:limit]

    if not unreviewed_jobs:
        print("\n🎉 No new unreviewed jobs matching candidate criteria!")
        print(f"Total reviewed so far: {len(reviewed)} jobs in {REVIEWED_FILE}")
        return

    print("\n" + "=" * 65)
    print(f"  INTERACTIVE JOB REVIEW TOOL (Task 6-2)")
    print(f"  Unreviewed queue: {len(unreviewed_jobs)} jobs | Total reviewed: {len(reviewed)}")
    print("  Commands: [y]es interested | [n]o skip | [s]kip for now | [q]uit")
    print("=" * 65)

    for idx, job in enumerate(unreviewed_jobs, start=1):
        job_id = str(job["id"])
        title = job["title"] or "Untitled"
        company = job["company_name"] or "Unknown"
        score = float(job["score"] or 0.0)
        role_type = job["role_type"] or "other"
        loc = job["location_raw"] or ("Remote" if job.get("is_remote") else "Unspecified")
        skills = job.get("matched_skills") or []
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except Exception:
                skills = []
        skills_str = ", ".join(skills) if skills else "None"
        link = job.get("apply_url") or job.get("company_url") or "N/A"
        snippet = (job.get("description_text") or "")[:250].replace("\n", " ")

        print(f"\n--- Job [{idx}/{len(unreviewed_jobs)}] (ID: {job_id}) ---")
        print(f"  Title      : {title}")
        print(f"  Company    : {company}")
        print(f"  Score      : {score:.1f}% | Role: {role_type}")
        print(f"  Location   : {loc}")
        print(f"  Skills     : {skills_str}")
        print(f"  Apply Link : {link}")
        print(f"  Snippet    : {snippet}...")
        print("-" * 65)

        while True:
            try:
                choice = input("Decision [y/n/s/q]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "q"

            if choice in ("y", "yes"):
                reviewed[job_id] = {
                    "title": title,
                    "company": company,
                    "score": score,
                    "decision": "interested",
                    "apply_url": link,
                }
                save_reviewed(reviewed)
                print(" -> Marked as INTERESTED [✓]")
                break
            elif choice in ("n", "no"):
                reviewed[job_id] = {
                    "title": title,
                    "company": company,
                    "score": score,
                    "decision": "skipped",
                    "apply_url": link,
                }
                save_reviewed(reviewed)
                print(" -> Marked as SKIPPED [✗]")
                break
            elif choice in ("s", "skip"):
                print(" -> Skipped for now.")
                break
            elif choice in ("q", "quit"):
                save_reviewed(reviewed)
                print(f"\nSaved {len(reviewed)} total decisions to {REVIEWED_FILE}. Goodbye!")
                return
            else:
                print("Invalid input. Please enter 'y' (yes), 'n' (no), 's' (skip), or 'q' (quit).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interactive CLI Job Review Tool.")
    parser.add_argument("--limit", type=int, default=50, help="Number of unreviewed jobs to review.")
    args = parser.parse_args()
    run_review(limit=args.limit)
