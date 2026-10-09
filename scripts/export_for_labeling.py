"""Export unlabeled jobs to a single master CSV for human labeling (Task 7.8).

Uses stratified sampling across score bands (high, medium, low) to ensure a balanced
mix of positive, borderline, and negative examples for Laya model calibration/training.
Preserves existing human labels in data/labeling_master.csv.

Usage:
    python scripts/export_for_labeling.py --batch-size 50
"""
import argparse
import csv
from datetime import datetime
import logging
import os
from pathlib import Path
import random
import sys
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MASTER_CSV_PATH = PROJECT_ROOT / "data" / "labeling_master.csv"


def load_existing_master_labels() -> Dict[str, Dict[str, str]]:
    """Load existing labels and notes from data/labeling_master.csv if present."""
    if not MASTER_CSV_PATH.exists():
        return {}

    existing = {}
    try:
        with open(MASTER_CSV_PATH, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                jid = row.get("job_id")
                if jid:
                    existing[jid] = {
                        "my_label": (row.get("my_label") or "").strip(),
                        "notes": (row.get("notes") or "").strip()
                    }
    except Exception as e:
        logger.warning("Could not read existing master CSV: %s", e)

    return existing


def export_unlabeled_jobs(batch_size: int = 50, output_file: Optional[Path] = None):
    target_path = output_file or MASTER_CSV_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    existing_master_labels = load_existing_master_labels()

    # Query all unlabeled jobs passing basic location & language filters
    # joined with laya_job_scores and job_matches
    logger.info("Fetching candidate jobs for labeling from PostgreSQL...")

    rows = execute_query("""
        SELECT j.id, j.title, j.company_name, j.location_raw, j.apply_url, j.company_url,
               j.is_remote, j.experience_level,
               COALESCE(l.final_score, m.match_score, 0) AS score,
               COALESCE(l.role_type, 'unscored') AS role_type,
               m.matched_skills
        FROM jobs j
        LEFT JOIN laya_job_scores l ON j.id = l.job_id
        LEFT JOIN job_matches m ON j.id = m.job_id
        LEFT JOIN laya_labels lbl ON j.id = lbl.job_id
        WHERE lbl.id IS NULL
          AND j.is_remote = true
          AND (j.detected_language IS NULL OR j.detected_language != 'german')
          AND j.is_unpaid = false
        ORDER BY COALESCE(l.final_score, m.match_score, 0) DESC;
    """)

    if not rows:
        logger.info("No unlabeled jobs found in database.")
        return

    logger.info("Found %d eligible unlabeled jobs.", len(rows))

    # Stratified Sampling: Divide into 3 bands (High score >= 50, Mid 35-50, Low < 35)
    high_band = [r for r in rows if r["score"] >= 50.0]
    mid_band = [r for r in rows if 35.0 <= r["score"] < 50.0]
    low_band = [r for r in rows if r["score"] < 35.0]

    logger.info("Stratified Pool Breakdown: High (%d), Mid (%d), Low (%d)",
                len(high_band), len(mid_band), len(low_band))

    # Allocate target sample counts per band
    target_high = min(len(high_band), max(1, batch_size // 3))
    target_mid = min(len(mid_band), max(1, batch_size // 3))
    target_low = min(len(low_band), batch_size - target_high - target_mid)

    selected_high = high_band[:target_high]
    selected_mid = mid_band[:target_mid]
    selected_low = low_band[:target_low]

    selected_rows = selected_high + selected_mid + selected_low
    logger.info("Selected %d jobs (%d High, %d Mid, %d Low) for labeling master file.",
                len(selected_rows), len(selected_high), len(selected_mid), len(selected_low))

    fieldnames = [
        "job_id", "title", "company", "score", "role_type",
        "location", "matched_skills", "apply_url", "my_label", "notes"
    ]

    entries = []
    for r in selected_rows:
        jid = str(r["id"])
        prev = existing_master_labels.get(jid, {})
        skills = r.get("matched_skills") or []
        if isinstance(skills, str):
            try:
                import json
                skills = json.loads(skills)
            except Exception:
                skills = []
        skills_str = ", ".join(skills[:4]) if skills else ""
        link = r.get("apply_url") or r.get("company_url") or ""

        entries.append({
            "job_id": jid,
            "title": r["title"] or "Untitled",
            "company": r["company_name"] or "Unknown",
            "score": round(float(r["score"] or 0.0), 1),
            "role_type": r["role_type"],
            "location": r["location_raw"] or ("Remote" if r.get("is_remote") else ""),
            "matched_skills": skills_str,
            "apply_url": link,
            "my_label": prev.get("my_label", ""),
            "notes": prev.get("notes", "")
        })

    with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(entries)

    print(f"\n" + "=" * 65)
    print(f"  MASTER LABELING FILE UPDATED: {target_path}")
    print("=" * 65)
    print(f"  Total Exported Queue: {len(entries)} jobs")
    print(f"  Stratified Mix      : {len(selected_high)} High Score (>=50), {len(selected_mid)} Mid (35-50), {len(selected_low)} Low (<35)")
    print("-" * 65)
    print(f"  Open {target_path} in Excel/VS Code.")
    print("  Fill 'my_label' with: good_fit, maybe, or bad_fit.")
    print(f"  Then ingest anytime via: python scripts/ingest_labels.py {target_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export master labeling CSV.")
    parser.add_argument("--batch-size", type=int, default=50, help="Total jobs to include in master CSV.")
    parser.add_argument("--no-rescore", action="store_true", help="Legacy flag (retained for backward compatibility).")
    args = parser.parse_args()
    export_unlabeled_jobs(batch_size=args.batch_size)
