"""Task 7.8a: Temperature Calibration of Laya Confidence on Labeled Data.

Reads human-labeled data from PostgreSQL `laya_labels`.
Fits temperature scaling parameters using Laya's calibration engine (`laya.fit_temperatures`).
Saves versioned temperature map to config/laya_temperatures_{version}.json.

NOTE on ECE: Laya's fit_temperatures buckets records by question type and excludes
small buckets from ECE evaluation. With <150 labels a 25% val split leaves too few
records per bucket, causing n_eval=0 and temperature=[1.0,1.0,1.0] — which looks
like success but means nothing was calibrated. Fix: use ALL labels for fitting,
skip ECE until we accumulate ECE_MIN_LABELS. Temperatures are still useful even
without ECE validation.
"""
import argparse
import json
import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import laya
from src.db.connection import execute_query
from src.matching.laya_scorer import LayaScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CONFIG_DIR = PROJECT_ROOT / "config"

# ECE evaluation requires enough samples per Laya bucket type.
# Below this count, skip ECE to avoid the n_eval=0 silent-no-op bug.
ECE_MIN_LABELS = 150


def build_records(scorer: LayaScorer, jobs: list) -> list:
    """Score labeled jobs and return (qtype_code, probs, target_idx) records."""
    import numpy as np

    qtype_map = {"choice": 0, "score": 1, "noul": 2}
    records = []

    for job in jobs:
        res = scorer.score_job(job)
        label = job["label"]
        # Map human label → numeric target score (0–4 scale)
        target_score = 4.0 if label == "good_fit" else (2.0 if label == "maybe" else 0.0)

        for q_id, q_res in res.questions.items():
            qt_code = qtype_map.get(q_res.question_type, 0)

            if q_res.probabilities:
                probs = np.array(list(q_res.probabilities.values()), dtype=np.float32)
            else:
                probs = np.array(
                    [1.0 - q_res.normalized_value, q_res.normalized_value],
                    dtype=np.float32,
                )

            k = len(probs)
            target_idx = 1 if target_score >= 2.0 else 0
            if qt_code == 1:  # score question — 5 levels (0..4)
                target_idx = max(0, min(4, int(target_score)))
            target_idx = min(target_idx, k - 1)

            records.append((qt_code, probs, target_idx))

    return records


def run_temperature_calibration(
    version: str = "v1",
    min_labels: int = 15,
    seed: int = 42,
):
    logger.info("=" * 60)
    logger.info("  LAYA TEMPERATURE CALIBRATION (Task 7.8a)")
    logger.info("=" * 60)

    # 1. Fetch labeled jobs from DB
    rows = execute_query("""
        SELECT l.job_id, l.label, j.title, j.company_name, j.location_raw, j.description_text
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        ORDER BY l.job_id;
    """)

    if len(rows) < min_labels:
        logger.warning(
            "Found only %d labeled rows — minimum is %d. "
            "Run: python scripts/export_for_labeling.py --batch-size 30",
            len(rows), min_labels,
        )
        print(f"\n[CALIBRATION NOTICE] Only {len(rows)}/{min_labels} labels found. Need more.")
        return

    # 2. Deduplicate by job_id (keep latest label per job)
    unique_jobs = {str(r["job_id"]): r for r in rows}
    all_jobs = list(unique_jobs.values())
    n_total = len(all_jobs)

    # Decide whether to compute ECE
    compute_ece = n_total >= ECE_MIN_LABELS
    logger.info(
        "Found %d unique labeled jobs. ECE evaluation: %s (%s)",
        n_total,
        "ENABLED" if compute_ece else "SKIPPED",
        f"need {ECE_MIN_LABELS - n_total} more labels" if not compute_ece else "sufficient data",
    )

    # 3. Load Laya and score all labeled jobs
    logger.info("Loading Laya scorer (device=cpu)...")
    scorer = LayaScorer(device="cpu")

    logger.info("Scoring %d labeled jobs to collect prediction records...", n_total)
    all_records = build_records(scorer, all_jobs)
    logger.info("Built %d question records from %d jobs.", len(all_records), n_total)

    # 4. Fit temperatures on ALL records (no train/val split).
    #    Splitting with <150 labels causes buckets to have too few records,
    #    which fit_temperatures silently excludes → temperature=[1.0,1.0,1.0], n_eval=0.
    logger.info(
        "Calling laya.fit_temperatures on %d records (compute_ece=%s)...",
        len(all_records), compute_ece,
    )
    calib_result = laya.fit_temperatures(all_records, compute_ece=compute_ece, seed=seed)
    logger.info("fit_temperatures result: %s", calib_result)

    # 5. Sanity check — warn if temperatures are still all 1.0
    temps = calib_result.get("temperature", [])
    if temps and all(abs(t - 1.0) < 1e-6 for t in temps):
        logger.warning(
            "All fitted temperatures are 1.0 — the model may already be "
            "well-calibrated for these buckets, or more labeled data is needed. "
            "Check n_by_bucket: %s",
            calib_result.get("n_by_bucket"),
        )
    else:
        logger.info("Temperatures differ from 1.0 — calibration had an effect: %s", temps)

    # 6. Persist versioned config
    out_config = CONFIG_DIR / f"laya_temperatures_{version}.json"
    calib_payload = {
        "version": version,
        "n_labels_used": n_total,
        "ece_computed": compute_ece,
        "calibration_results": calib_result,
        "_note": (
            f"ECE skipped: only {n_total} labels (need {ECE_MIN_LABELS}). "
            "Temperatures fitted on full labeled set — usable but unvalidated by ECE."
        ) if not compute_ece else "ECE computed on held-out split.",
    }

    with open(out_config, "w", encoding="utf-8") as f:
        json.dump(calib_payload, f, indent=2)

    logger.info("Saved temperature config to: %s", out_config)

    # 7. Pretty summary
    report = calib_result.get("report", {})
    print(f"\n{'=' * 50}")
    print(f"  CALIBRATION REPORT [{version}]")
    print(f"{'=' * 50}")
    print(f"  Labels used:          {n_total}")
    print(f"  Question records:     {len(all_records)}")
    print(f"  ECE computed:         {compute_ece}")
    print(f"  Fitted temperatures:  {temps}")
    print(f"  n_by_bucket:          {calib_result.get('n_by_bucket', 'N/A')}")
    print(f"  ECE Before:           {report.get('ece_before', 'N/A (skipped)')}")
    print(f"  ECE After:            {report.get('ece_after', 'N/A (skipped)')}")
    print(f"  Config saved:         {out_config}")
    if not compute_ece:
        print(f"\n  Add {ECE_MIN_LABELS - n_total} more labels then re-run for ECE validation.")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calibrate Laya confidence temperatures (Task 7.8a).")
    parser.add_argument("--version", type=str, default="v1", help="Version tag for output config file.")
    parser.add_argument("--min-labels", type=int, default=10, help="Minimum labeled rows required to proceed.")
    args = parser.parse_args()
    run_temperature_calibration(version=args.version, min_labels=args.min_labels)
