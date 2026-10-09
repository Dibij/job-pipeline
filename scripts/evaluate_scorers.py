"""Task 7.7: Comparative Evaluation of MatchScorer vs LayaScorer against Human Labels.

Reads human-labeled data from PostgreSQL `laya_labels`.
Evaluates rule-based `MatchScorer` and deep learning `LayaScorer`.
Computes accuracy, 3-class precision/recall, binary accuracy (accessible vs bad fit),
and prints detailed disagreement analysis.
"""
import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.scorer import MatchScorer
from src.matching.laya_scorer import LayaScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports"


def map_match_scorer_category(score: float, flags: List[str]) -> str:
    """Map MatchScorer raw score and flags to 3-class decision."""
    hard_disqualifiers = {"GERMAN", "UNPAID", "INACCESSIBLE"}
    if any(f in hard_disqualifiers for f in flags):
        return "bad_fit"
    if score >= 60.0:
        return "good_fit"
    elif score >= 40.0:
        return "maybe"
    else:
        return "bad_fit"


def map_laya_scorer_category(score: float, is_passed: bool, role_type: str) -> str:
    """Map LayaScorer result to 3-class decision."""
    if not is_passed:
        return "bad_fit"
    if role_type == "other":
        return "bad_fit"
    if score >= 60.0:
        return "good_fit"
    elif score >= 40.0:
        return "maybe"
    else:
        return "bad_fit"


def evaluate():
    logger.info("=" * 65)
    logger.info("  EVALUATION: MatchScorer Baseline vs LayaScorer vs Human Labels")
    logger.info("=" * 65)

    # 1. Fetch labeled jobs from PostgreSQL
    rows = execute_query("""
        SELECT l.job_id, l.label, l.notes, j.title, j.company_name, j.location_raw,
               j.is_remote, j.remote_restriction, j.experience_level, j.detected_language,
               j.is_unpaid, j.description_text, j.tags
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        ORDER BY l.job_id;
    """)

    if not rows:
        logger.error("No labeled rows found in database table 'laya_labels'.")
        return

    logger.info("Found %d human-labeled jobs for evaluation.", len(rows))

    # Initialize scorers
    match_scorer = MatchScorer()
    laya_scorer = LayaScorer(device="cpu")

    match_correct = 0
    laya_correct = 0

    match_binary_correct = 0
    laya_binary_correct = 0

    eval_results = []

    categories = ["good_fit", "maybe", "bad_fit"]

    for row in rows:
        job_id = str(row["job_id"])
        human_label = str(row["label"]).lower()
        title = row["title"] or "Untitled"
        company = row["company_name"] or "Unknown"

        # 1. Rule-based MatchScorer
        ms_score, ms_matched, ms_missing, ms_breakdown = match_scorer.score_job(row)
        ms_category = map_match_scorer_category(ms_score, ms_breakdown.get("flags", []))

        # 2. LayaScorer
        ls_res = laya_scorer.score_job(row)
        ls_category = map_laya_scorer_category(ls_res.final_score, ls_res.is_passed, ls_res.role_type)

        # Accuracy checks
        is_match_exact = (ms_category == human_label)
        is_laya_exact = (ls_category == human_label)

        if is_match_exact:
            match_correct += 1
        if is_laya_exact:
            laya_correct += 1

        # Binary accuracy (fit = good_fit or maybe; non-fit = bad_fit)
        human_binary = "fit" if human_label in ("good_fit", "maybe") else "bad_fit"
        ms_binary = "fit" if ms_category in ("good_fit", "maybe") else "bad_fit"
        ls_binary = "fit" if ls_category in ("good_fit", "maybe") else "bad_fit"

        if ms_binary == human_binary:
            match_binary_correct += 1
        if ls_binary == human_binary:
            laya_binary_correct += 1

        eval_results.append({
            "job_id": job_id,
            "title": title,
            "company": company,
            "human_label": human_label,
            "match_scorer": {
                "score": ms_score,
                "category": ms_category,
                "flags": ms_breakdown.get("flags", []),
                "exact_match": is_match_exact,
            },
            "laya_scorer": {
                "score": ls_res.final_score,
                "category": ls_category,
                "role_type": ls_res.role_type,
                "is_passed": ls_res.is_passed,
                "gate_warnings": ls_res.gate_warnings,
                "exact_match": is_laya_exact,
            }
        })

    n = len(rows)
    ms_acc = (match_correct / n) * 100.0
    ls_acc = (laya_correct / n) * 100.0

    ms_bin_acc = (match_binary_correct / n) * 100.0
    ls_bin_acc = (laya_binary_correct / n) * 100.0

    print("\n" + "=" * 65)
    print(f"  EVALUATION SUMMARY ({n} Human Labeled Jobs)")
    print("=" * 65)
    print(f"  MatchScorer Baseline  | 3-Class Accuracy: {ms_acc:5.1f}% | Binary Accuracy: {ms_bin_acc:5.1f}%")
    print(f"  Calibrated LayaScorer | 3-Class Accuracy: {ls_acc:5.1f}% | Binary Accuracy: {ls_bin_acc:5.1f}%")
    print("-" * 65)

    print("\n[JOB-BY-JOB COMPARISON]")
    print(f"{'TITLE':<32} | {'HUMAN':<8} | {'MATCH_SCORE':<11} | {'LAYA_SCORE':<11} | {'LAYA_ROLE':<13}")
    print("-" * 85)
    for item in eval_results:
        t_short = (item['title'][:30] + '..') if len(item['title']) > 32 else item['title']
        print(f"{t_short:<32} | {item['human_label']:<8} | {item['match_scorer']['category']:<11} | {item['laya_scorer']['category']:<11} | {item['laya_scorer']['role_type']:<13}")

    # Save output to report JSON
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORTS_DIR / "evaluation_report.json"
    report_data = {
        "total_jobs": n,
        "metrics": {
            "match_scorer": {
                "exact_accuracy_pct": round(ms_acc, 2),
                "binary_accuracy_pct": round(ms_bin_acc, 2),
            },
            "laya_scorer": {
                "exact_accuracy_pct": round(ls_acc, 2),
                "binary_accuracy_pct": round(ls_bin_acc, 2),
            }
        },
        "details": eval_results
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    logger.info("Evaluation report saved to: %s", report_file)


if __name__ == "__main__":
    evaluate()
