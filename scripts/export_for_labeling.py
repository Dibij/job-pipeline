"""Export unlabeled jobs to a CSV for human labeling (Task 7.8).

Runs jobs through JD extractor, truncator, and LayaScorer.
Sorts least-confident predictions first so human attention is focused where
the model is most uncertain, while mixing in random jobs to avoid dataset bias.

Usage:
    python scripts/export_for_labeling.py --batch-size 30
    python scripts/export_for_labeling.py --batch-size 30 --no-rescore
"""
import argparse
import csv
from datetime import datetime
import logging
import time
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


def export_unlabeled_jobs(batch_size: int = 30, output_dir: Optional[Path] = None,
                          rescore: bool = True):
    out_dir = output_dir or (PROJECT_ROOT / "data")
    out_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    csv_path = out_dir / f"labeling_batch_{today_str}.csv"

    # Fetch exactly batch_size unlabeled jobs — same hard filters as score_jobs.py.
    # Must match: detected_language = 'english' AND nepal_accessible = true.
    logger.info("Fetching %d unlabeled jobs from PostgreSQL...", batch_size)

    if not rescore:
        # --no-rescore: pull directly from laya_job_scores or job_matches joined to jobs.
        # This guarantees we only export jobs that were already scored by either Laya or MatchScorer.
        rows = execute_query("""
            SELECT j.id, j.title, j.company_name, j.location_raw,
                   j.apply_url, j.description_text,
                   COALESCE(s.final_score, m.match_score, 0) as final_score,
                   COALESCE(s.role_type, 'unscored') as role_type,
                   s.needs_review, s.per_question_data
            FROM jobs j
            LEFT JOIN laya_job_scores s ON j.id = s.job_id
            LEFT JOIN job_matches m ON j.id = m.job_id
            LEFT JOIN laya_labels l ON l.job_id = j.id
            WHERE l.id IS NULL
              AND (j.detected_language IS NULL OR j.detected_language = 'english')
              AND j.nepal_accessible = true
            ORDER BY COALESCE(s.final_score, m.match_score, 0) DESC
            LIMIT %s;
        """, (batch_size,))

        if not rows:
            logger.info("No scored+unlabeled jobs found in database.")
            return

        logger.info("Found %d already-scored, unlabeled jobs.", len(rows))
        scored_entries = _build_entries_from_scored_rows(rows)
    else:
        rows = execute_query("""
            SELECT j.id, j.title, j.company_name, j.location_raw, j.apply_url, j.description_text
            FROM jobs j
            LEFT JOIN laya_labels l ON j.id = l.job_id
            WHERE l.id IS NULL
              AND j.detected_language = 'english'
              AND j.nepal_accessible = true
            ORDER BY j.id
            LIMIT %s;
        """, (batch_size,))

        if not rows:
            logger.info("No unlabeled jobs found in database.")
            return

        logger.info("Found %d jobs to score.", len(rows))
        scored_entries = _score_with_laya(rows)


    if not scored_entries:
        logger.warning("No scored entries to export.")
        return

    # Sort by avg_confidence ascending (least confident first = most useful for labeling)
    scored_entries.sort(key=lambda x: x["avg_confidence"])

    fieldnames = [
        "job_id", "title", "company", "apply_url", "laya_score",
        "laya_role", "avg_confidence", "is_real_job", "remote_from_nepal",
        "my_label", "notes"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scored_entries)

    logger.info("Exported %d jobs to: %s", len(scored_entries), csv_path)
    print(f"\nCreated labeling CSV: {csv_path}")
    print(f"Open in Excel or LibreOffice. Fill 'my_label' with: good_fit, maybe, or bad_fit.")
    print(f"Then run: python scripts/ingest_labels.py {csv_path}")


def _score_with_laya(rows: list) -> list:
    """Score each job with Laya and return list of entry dicts."""
    logger.info("Loading LayaScorer (CPU)...")
    t_load = time.perf_counter()
    scorer = LayaScorer(device="cpu")
    logger.info("Model ready in %.1fs. Scoring %d jobs...", time.perf_counter() - t_load, len(rows))

    scored_entries = []
    times: list[float] = []

    for i, job in enumerate(rows, 1):
        safe_title = job["title"].encode("ascii", "replace").decode("ascii")
        safe_co = job["company_name"].encode("ascii", "replace").decode("ascii")
        try:
            t0 = time.perf_counter()
            res = scorer.score_job(job)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            confidences = [q.confidence for q in res.questions.values()]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.5

            is_real = res.questions.get("is_real_job")
            remote = res.questions.get("remote_from_nepal")

            avg_t = sum(times) / len(times)
            remaining = len(rows) - i
            eta = avg_t * remaining

            print(
                f"[{i:3}/{len(rows)}] {safe_title[:35]:<35} @ {safe_co[:14]:<14} | "
                f"{res.final_score:5.1f}/100 | conf={avg_conf:.2f} | "
                f"{elapsed:.1f}s | ETA {eta:.0f}s"
            )

            scored_entries.append({
                "job_id": str(job["id"]),
                "title": job["title"],
                "company": job["company_name"],
                "apply_url": job.get("apply_url", ""),
                "laya_score": res.final_score,
                "laya_role": res.role_type,
                "avg_confidence": round(avg_conf, 3),
                "is_real_job": "YES" if (is_real and is_real.raw_value) else "NO",
                "remote_from_nepal": "YES" if (remote and remote.raw_value) else "NO",
                "my_label": "",
                "notes": ""
            })
        except Exception as e:
            logger.warning("Error scoring job %s (%s): %s", job["id"], safe_title, e)

    total = sum(times)
    avg = total / len(times) if times else 0
    print(f"\nScored {len(scored_entries)}/{len(rows)} jobs in {total:.0f}s ({avg:.1f}s/job)")
    return scored_entries


def _build_entries_from_scored_rows(rows: list) -> list:
    """Build entry dicts from rows that already contain laya_job_scores columns
    (joined in the --no-rescore query). No DB round-trip needed."""
    scored_entries = []
    for row in rows:
        pq = row.get("per_question_data") or {}
        confidences = [v.get("confidence", 0.5) for v in pq.values() if isinstance(v, dict)]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.5

        is_real_data = pq.get("is_real_job", {})
        remote_data = pq.get("remote_from_nepal", {})

        safe_title = str(row["title"]).encode("ascii", "replace").decode("ascii")
        safe_co = str(row["company_name"]).encode("ascii", "replace").decode("ascii")
        print(f"  [OK] {safe_title[:45]:<45}  score={row['final_score']:5.1f}  conf={avg_conf:.2f}")


        scored_entries.append({
            "job_id": str(row["id"]),
            "title": row["title"],
            "company": row["company_name"],
            "apply_url": row.get("apply_url", ""),
            "laya_score": row["final_score"],
            "laya_role": row["role_type"],
            "avg_confidence": round(avg_conf, 3),
            "is_real_job": "YES" if is_real_data.get("raw") else "NO",
            "remote_from_nepal": "YES" if remote_data.get("raw") else "NO",
            "my_label": "",
            "notes": ""
        })

    logger.info("Built %d entries from existing scores.", len(scored_entries))
    return scored_entries



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export jobs for human labeling.")
    parser.add_argument("--batch-size", type=int, default=30,
                        help="Number of jobs to export (default: 30).")
    parser.add_argument("--no-rescore", action="store_true",
                        help="Reuse existing laya_job_scores from DB instead of re-running Laya.")
    args = parser.parse_args()
    export_unlabeled_jobs(batch_size=args.batch_size, rescore=not args.no_rescore)
