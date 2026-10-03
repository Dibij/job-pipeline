"""Export unlabeled jobs to a CSV for human labeling (Task 7.8).

Runs jobs through JD extractor, truncator, and LayaScorer.
Sorts least-confident predictions first so human attention is focused where
the model is most uncertain, while mixing in random jobs to avoid dataset bias.
"""
import argparse
import csv
from datetime import datetime
import logging
from pathlib import Path
import random
import sys
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.laya_scorer import LayaScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def export_unlabeled_jobs(batch_size: int = 50, output_dir: Optional[Path] = None):
    out_dir = output_dir or (PROJECT_ROOT / "data")
    out_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    csv_path = out_dir / f"labeling_batch_{today_str}.csv"

    logger.info("Fetching jobs not yet labeled from PostgreSQL...")
    rows = execute_query("""
        SELECT j.id, j.title, j.company_name, j.location_raw, j.apply_url, j.description_text
        FROM jobs j
        LEFT JOIN laya_labels l ON j.id = l.job_id
        WHERE l.id IS NULL
          AND j.detected_language = 'english'
        LIMIT %s;
    """, (batch_size * 2,))

    if not rows:
        logger.info("No unlabeled jobs found in database.")
        return

    logger.info("Initializing LayaScorer...")
    scorer = LayaScorer(device="cpu")

    scored_entries = []
    logger.info("Scoring %d candidate jobs with Laya...", len(rows))

    for i, job in enumerate(rows, 1):
        try:
            res = scorer.score_job(job)
            
            # Compute average confidence across questions
            confidences = [q.confidence for q in res.questions.values()]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.5

            is_real = res.questions.get("is_real_job")
            remote = res.questions.get("remote_from_nepal")

            scored_entries.append({
                "job_id": str(job["id"]),
                "title": job["title"],
                "company": job["company_name"],
                "apply_url": job["apply_url"],
                "laya_score": res.final_score,
                "laya_role": res.role_type,
                "avg_confidence": round(avg_conf, 3),
                "is_real_job": "YES" if (is_real and is_real.raw_value) else "NO",
                "remote_from_nepal": "YES" if (remote and remote.raw_value) else "NO",
                "my_label": "",  # Empty for human labeler (good_fit / maybe / bad_fit)
                "notes": ""
            })
            if i % 10 == 0:
                logger.info("Scored %d/%d jobs...", i, len(rows))
        except Exception as e:
            logger.warning("Error scoring job %s: %s", job["id"], e)

    # Strategy: 70% lowest confidence (active learning) + 30% random (unbiased distribution)
    scored_entries.sort(key=lambda x: x["avg_confidence"])
    
    k_active = int(batch_size * 0.70)
    k_random = batch_size - k_active

    active_pool = scored_entries[:k_active]
    remaining_pool = scored_entries[k_active:]
    random_pool = random.sample(remaining_pool, min(k_random, len(remaining_pool)))

    selected = active_pool + random_pool
    # Shuffle slightly so labeler does not see strictly monotonic confidence
    random.shuffle(selected)

    fieldnames = [
        "job_id", "title", "company", "apply_url", "laya_score",
        "laya_role", "avg_confidence", "is_real_job", "remote_from_nepal",
        "my_label", "notes"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)

    logger.info("Successfully exported %d jobs for labeling to: %s", len(selected), csv_path)
    print(f"\nCreated labeling CSV: {csv_path}")
    print(f"Please review and fill in 'my_label' column with: good_fit, maybe, or bad_fit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export jobs for human labeling.")
    parser.add_argument("--batch-size", type=int, default=30, help="Number of jobs to export.")
    args = parser.parse_args()
    export_unlabeled_jobs(batch_size=args.batch_size)
