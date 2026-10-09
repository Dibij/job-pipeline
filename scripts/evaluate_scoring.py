"""Task 7.7: Evaluation script comparing MatchScorer vs Laya vs human labels.

Joins:
  - laya_labels (human ground truth: good_fit, maybe, bad_fit)
  - job_matches (MatchScorer score & reason_code from HardFilter)
  - laya_job_scores (Laya model score & is_passed flag)

Computes:
  - Classification metrics: accuracy, precision, recall, F1 (treating good_fit as positive)
  - Ranking correlation: Kendall's Tau-b between human rank order and model scores
  - Side-by-side comparison table saved to data/eval_report.txt and printed to console.
"""
from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.laya_scorer import LayaScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"

LABEL_RANK = {
    "bad_fit": 0,
    "maybe": 1,
    "good_fit": 2,
}


def kendall_tau_b(x: List[float], y: List[float]) -> float:
    """Compute Kendall's Tau-b correlation handling ties. Zero dependencies."""
    n = len(x)
    if n < 2:
        return 0.0

    p = 0  # concordant
    q = 0  # discordant
    tx = 0 # ties in x only
    ty = 0 # ties in y only

    for i in range(n):
        for j in range(i + 1, n):
            dx = x[i] - x[j]
            dy = y[i] - y[j]

            if dx == 0 and dy == 0:
                continue
            elif dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif (dx > 0 and dy > 0) or (dx < 0 and dy < 0):
                p += 1
            else:
                q += 1

    denom = math.sqrt((p + q + tx) * (p + q + ty))
    if denom == 0:
        return 0.0
    return (p - q) / denom


def compute_binary_metrics(
    y_true: List[bool],
    y_pred: List[bool],
) -> Dict[str, float]:
    """Calculate Precision, Recall, F1, and Accuracy for binary decisions."""
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt and yp)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if not yt and yp)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt and not yp)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if not yt and not yp)

    total = len(y_true)
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": round(accuracy, 3),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def fetch_evaluation_data() -> List[Dict[str, Any]]:
    """Fetch all unique labeled jobs and their corresponding scores."""
    rows = execute_query("""
        SELECT DISTINCT ON (l.job_id)
            j.id AS job_id,
            j.title,
            j.company_name,
            j.location_raw,
            j.description_text,
            j.is_remote,
            l.label,
            jm.match_score,
            jm.reason_code AS match_reason_code,
            ls.final_score AS laya_score,
            ls.is_passed AS laya_passed,
            ls.disqualification_reason AS laya_disq_reason
        FROM laya_labels l
        JOIN jobs j ON j.id = l.job_id
        LEFT JOIN job_matches jm ON jm.job_id = l.job_id
        LEFT JOIN LATERAL (
            SELECT final_score, is_passed, disqualification_reason
            FROM laya_job_scores
            WHERE job_id = l.job_id
            ORDER BY scored_at DESC
            LIMIT 1
        ) ls ON TRUE
        ORDER BY l.job_id, l.labeled_at DESC;
    """)
    return rows


def run_evaluation(
    match_threshold: float = 50.0,
    laya_threshold: float = 50.0,
    compute_missing_laya: bool = True,
    device: str = "cpu",
) -> None:
    logger.info("Fetching evaluation dataset...")
    data = fetch_evaluation_data()

    if not data:
        print("\n[EVALUATION NOTICE] No labeled jobs found in laya_labels table.")
        return

    logger.info("Found %d unique labeled jobs.", len(data))

    # If any job is missing Laya score and compute_missing_laya is True, score it on the fly
    missing_laya = [r for r in data if r.get("laya_score") is None]
    if missing_laya and compute_missing_laya:
        logger.info(
            "%d jobs missing precomputed Laya scores. Computing with LayaScorer (%s)...",
            len(missing_laya), device,
        )
        scorer = LayaScorer(device=device)
        for r in missing_laya:
            job_dict = {
                "id": r["job_id"],
                "title": r["title"],
                "company_name": r["company_name"],
                "location_raw": r["location_raw"],
                "description_text": r["description_text"],
                "is_remote": r["is_remote"],
            }
            res = scorer.score_job(job_dict)
            r["laya_score"] = res.final_score
            r["laya_passed"] = res.is_passed
            r["laya_disq_reason"] = res.disqualification_reason

    # Prepare ground truth and prediction arrays
    y_true_binary = []  # True for good_fit, False for bad_fit (maybe counted as False)
    y_true_rank = []    # 0, 1, 2

    match_scores = []
    match_pred_binary = []

    laya_scores = []
    laya_pred_binary = []

    report_rows = []

    for r in data:
        label = r["label"]
        y_true_binary.append(label == "good_fit")
        y_true_rank.append(LABEL_RANK.get(label, 0))

        # MatchScorer: passed filter (no reason_code) and score >= threshold
        ms = float(r["match_score"]) if r.get("match_score") is not None else 0.0
        ms_passed = r.get("match_reason_code") is None
        match_scores.append(ms if ms_passed else 0.0)
        match_pred_binary.append(ms_passed and ms >= match_threshold)

        # Laya: is_passed and score >= threshold
        ls = float(r["laya_score"]) if r.get("laya_score") is not None else 0.0
        ls_passed = bool(r.get("laya_passed", True))
        laya_scores.append(ls if ls_passed else 0.0)
        laya_pred_binary.append(ls_passed and ls >= laya_threshold)

        report_rows.append({
            "title": (r["title"] or "")[:35],
            "company": (r["company_name"] or "")[:18],
            "label": label,
            "match_score": f"{ms:.1f}" if ms_passed else f"0.0 ({r.get('match_reason_code')})",
            "laya_score": f"{ls:.1f}" if ls_passed else f"0.0 ({r.get('laya_disq_reason') or 'FAIL'})",
        })

    # Metrics
    match_metrics = compute_binary_metrics(y_true_binary, match_pred_binary)
    laya_metrics = compute_binary_metrics(y_true_binary, laya_pred_binary)

    tau_match = kendall_tau_b(y_true_rank, match_scores)
    tau_laya = kendall_tau_b(y_true_rank, laya_scores)

    # Format Output
    output_lines = []
    output_lines.append("=" * 78)
    output_lines.append(f"          MODEL EVALUATION REPORT (Sample Size: {len(data)})")
    output_lines.append("=" * 78)
    output_lines.append(f"Ground Truth Distribution:")
    for lbl in ["good_fit", "maybe", "bad_fit"]:
        c = sum(1 for r in data if r["label"] == lbl)
        output_lines.append(f"  - {lbl:<10}: {c} ({c / len(data) * 100:.1f}%)")
    output_lines.append("-" * 78)

    output_lines.append(f"{'METRIC':<25} | {'MatchScorer (Baseline)':<22} | {'Laya (LLM Head)':<22}")
    output_lines.append("-" * 78)
    output_lines.append(f"{'Accuracy':<25} | {match_metrics['accuracy']:<22} | {laya_metrics['accuracy']:<22}")
    output_lines.append(f"{'Precision (good_fit)':<25} | {match_metrics['precision']:<22} | {laya_metrics['precision']:<22}")
    output_lines.append(f"{'Recall (good_fit)':<25} | {match_metrics['recall']:<22} | {laya_metrics['recall']:<22}")
    output_lines.append(f"{'F1 Score':<25} | {match_metrics['f1']:<22} | {laya_metrics['f1']:<22}")
    output_lines.append(f"{'Kendall Tau-b (Ranking)':<25} | {tau_match:<22.3f} | {tau_laya:<22.3f}")
    output_lines.append("-" * 78)

    output_lines.append("\nPER-JOB BREAKDOWN:")
    output_lines.append(f"{'Job Title':<35} | {'Company':<18} | {'Human':<9} | {'MatchScorer':<14} | {'Laya'}")
    output_lines.append("-" * 95)
    for row in report_rows:
        output_lines.append(
            f"{row['title']:<35} | {row['company']:<18} | {row['label']:<9} | {row['match_score']:<14} | {row['laya_score']}"
        )
    output_lines.append("=" * 95)

    report_text = "\n".join(output_lines)
    print("\n" + report_text)

    # Save to data/eval_report.txt
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_file = DATA_DIR / "eval_report.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info("Evaluation report saved to: %s", out_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate MatchScorer and Laya against human labels.")
    parser.add_argument("--match-threshold", type=float, default=50.0, help="Score threshold for MatchScorer positive prediction")
    parser.add_argument("--laya-threshold", type=float, default=50.0, help="Score threshold for Laya positive prediction")
    parser.add_argument("--device", type=str, default="cuda", help="Device for on-the-fly Laya inference (cuda/cpu)")
    args = parser.parse_args()

    run_evaluation(
        match_threshold=args.match_threshold,
        laya_threshold=args.laya_threshold,
        device=args.device,
    )
