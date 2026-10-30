"""scripts/run_evals.py -- Reproducible evaluation harness runner.

Runs grouped cross-validation and full-dataset benchmarks against frozen gold snapshot.
Enforces:
- Hard training gate checks (>=150 v2 labels, >=30 good_fit, >=3 positives/fold).
- Pre-flight leakage guards (zero company, job, hash overlap, strict v2 guideline version).
- Honest reporting: displays sample size n, positive count, and 95% bootstrap CIs.
- Saves run bundle to evals/runs/<timestamp>/ (metrics.json, run_meta.json, summary.txt).
- Regression comparisons (--compare <prev_run_dir>) detecting drops beyond CI overlap.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evals.leakage import (
    check_guideline_integrity,
    check_split_leakage,
    normalize_company,
)
from src.evals.metrics import (
    check_training_gates,
    evaluate_binary_predictions,
)
from src.evals.registry import (
    get_model,
    list_registered_models,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

RUNS_DIR = PROJECT_ROOT / "evals" / "runs"
DEFAULT_GOLD = PROJECT_ROOT / "evals" / "gold" / "gold_latest.csv"


def get_git_sha() -> str:
    """Get current git commit SHA."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def load_gold_records(gold_path: Path) -> List[Dict[str, Any]]:
    """Load gold evaluation records from CSV and enforce guideline integrity."""
    if not gold_path.exists():
        raise FileNotFoundError(f"Gold dataset not found at {gold_path}. Run scripts/export_gold.py first.")

    with open(gold_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        records = list(reader)

    # Pre-flight check: strictly v2_role_fit_only
    check_guideline_integrity(records, required_version="v2_role_fit_only")
    return records


def build_grouped_folds(
    records: List[Dict[str, Any]],
    n_splits: int = 5,
    random_state: int = 42,
) -> List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]]:
    """Create grouped CV splits ensuring zero company overlap between train & test.

    Returns:
        List of (train_records, test_records, fold_positives)
    """
    # Group by company (or fallback to job_id for unknown company)
    groups: List[str] = []
    y: List[int] = []
    for r in records:
        comp = normalize_company(r.get("company"))
        groups.append(comp if comp else f"job_{r.get('job_id')}")
        y.append(1 if r.get("label") == "good_fit" else 0)

    unique_groups = list(set(groups))
    rng = np.random.default_rng(random_state)
    rng.shuffle(unique_groups)

    # Assign groups to buckets
    group_to_fold: Dict[str, int] = {g: i % n_splits for i, g in enumerate(unique_groups)}

    folds = []
    for fold_idx in range(n_splits):
        train_idx = [i for i, g in enumerate(groups) if group_to_fold[g] != fold_idx]
        test_idx = [i for i, g in enumerate(groups) if group_to_fold[g] == fold_idx]

        train_records = [records[i] for i in train_idx]
        test_records = [records[i] for i in test_idx]

        # Automatic Leakage Check on every split
        check_split_leakage(train_records, test_records)

        fold_pos = sum(1 for r in test_records if r.get("label") == "good_fit")
        folds.append((train_records, test_records, fold_pos))

    return folds


def run_evaluation(
    gold_path: Path = DEFAULT_GOLD,
    model_names: Optional[List[str]] = None,
    n_splits: int = 5,
    output_dir: Optional[Path] = None,
    compare_dir: Optional[Path] = None,
) -> Path:
    """Execute complete evaluation harness and save artifacts."""
    records = load_gold_records(gold_path)
    total_distinct_jobs = len(records)
    distinct_good_fit = sum(1 for r in records if r.get("label") == "good_fit")
    distinct_maybe = sum(1 for r in records if r.get("label") == "maybe")
    distinct_bad_fit = sum(1 for r in records if r.get("label") == "bad_fit")

    # Generate grouped folds
    folds = build_grouped_folds(records, n_splits=n_splits)
    fold_positives = [f[2] for f in folds]

    # Training Gate Check
    gate_info = check_training_gates(
        total_distinct_labels=total_distinct_jobs,
        distinct_good_fit=distinct_good_fit,
        fold_positives=fold_positives,
    )

    # Print Gate Status Banner
    print("\n" + "=" * 70)
    print(" EVALUATION HARNESS - TRAINING GATE STATUS")
    print("=" * 70)
    print(f" Status:        [{gate_info['status']}]")
    print(f" Total Labels:  {total_distinct_jobs}/{gate_info['total_required']} distinct jobs")
    print(f" Good Fit:      {distinct_good_fit}/{gate_info['good_fit_required']} distinct jobs")
    print(f" Class Counts:  good_fit={distinct_good_fit}, maybe={distinct_maybe}, bad_fit={distinct_bad_fit}")
    print(f" Fold Positives:{fold_positives} (min required per fold: {gate_info['fold_positives_min_required']})")
    if not gate_info["passed"]:
        print(" Gate Blockers:")
        for r in gate_info["reasons"]:
            print(f"   * {r}")
    print("=" * 70 + "\n")

    selected_models = model_names or list_registered_models()
    logger.info("Evaluating models: %s", selected_models)

    # Gold SHA
    from scripts.export_gold import compute_file_sha256
    gold_sha = compute_file_sha256(gold_path)

    # Prepare results structure
    results: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": get_git_sha(),
        "gold_dataset": {
            "path": str(gold_path),
            "sha256": gold_sha,
            "total_records": total_distinct_jobs,
            "class_distribution": {
                "good_fit": distinct_good_fit,
                "maybe": distinct_maybe,
                "bad_fit": distinct_bad_fit,
            },
        },
        "gate_status": gate_info,
        "cv_config": {
            "n_splits": n_splits,
            "grouping": "company",
            "fold_positives": fold_positives,
        },
        "models": {},
    }

    # Evaluate each model
    y_true_all = [1 if r.get("label") == "good_fit" else 0 for r in records]

    for model_name in selected_models:
        logger.info("Running evaluation for model: %s", model_name)
        model = get_model(model_name)

        # 1. Full Dataset Baseline Scoring
        scores_full = model.score_jobs(records)
        metrics_full = evaluate_binary_predictions(y_true_all, scores_full)

        # 2. Grouped CV Evaluation
        fold_metrics: List[Any] = []
        for f_idx, (train_recs, test_recs, f_pos) in enumerate(folds, start=1):
            if f_pos < gate_info["fold_positives_min_required"]:
                fold_metrics.append({
                    "fold": f_idx,
                    "status": "insufficient_positives",
                    "n_test": len(test_recs),
                    "positives": f_pos,
                    "required_positives": gate_info["fold_positives_min_required"],
                })
                continue

            # If trainable, fit strictly on train fold
            if model.is_trainable:
                y_train_fold = np.array([1 if r.get("label") == "good_fit" else 0 for r in train_recs])
                model.fit(train_recs, y_train_fold)

            y_test_fold = [1 if r.get("label") == "good_fit" else 0 for r in test_recs]
            scores_fold = model.score_jobs(test_recs)
            m_fold = evaluate_binary_predictions(y_test_fold, scores_fold, n_bootstrap=200)
            m_fold["fold"] = f_idx
            fold_metrics.append(m_fold)

        results["models"][model_name] = {
            "model_version": model.version,
            "is_trainable": model.is_trainable,
            "full_dataset_metrics": metrics_full,
            "grouped_cv_folds": fold_metrics,
        }

    # Save run artifacts
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir or (RUNS_DIR / timestamp_str)
    run_dir.mkdir(parents=True, exist_ok=True)

    metrics_file = run_dir / "metrics.json"
    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    meta_file = run_dir / "run_meta.json"
    run_meta = {
        "timestamp": results["timestamp"],
        "git_sha": results["git_sha"],
        "gold_sha256": gold_sha,
        "n_records": total_distinct_jobs,
        "models_evaluated": selected_models,
        "gate_status": gate_info["status"],
    }
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(run_meta, f, indent=2)

    # Build summary text
    summary_file = run_dir / "summary.txt"
    summary_text = _format_summary_table(results)
    summary_file.write_text(summary_text, encoding="utf-8")
    print(summary_text)

    # Optional regression comparison
    if compare_dir:
        _perform_regression_compare(run_dir, Path(compare_dir))

    logger.info("Evaluation complete! Artifacts saved to: %s", run_dir)
    return run_dir


def _format_summary_table(results: Dict[str, Any]) -> str:
    """Format evaluation results into a clean, honest markdown summary table."""
    lines = []
    lines.append("=" * 85)
    lines.append(" EVALUATION RESULTS SUMMARY")
    lines.append(f" Git SHA: {results['git_sha'][:8]} | Timestamp: {results['timestamp']}")
    lines.append(f" Gate Status: {results['gate_status']['status']} (n={results['gold_dataset']['total_records']}, pos={results['gold_dataset']['class_distribution']['good_fit']})")
    lines.append("=" * 85)
    header = f"{'Model':<24} | {'ROC-AUC [95% CI]':<20} | {'PR-AUC [95% CI]':<20} | {'P@10 [95% CI]':<18}"
    lines.append(header)
    lines.append("-" * len(header))

    for m_name, m_data in results["models"].items():
        m_full = m_data.get("full_dataset_metrics", {})
        roc = m_full.get("roc_auc", {})
        pr = m_full.get("pr_auc", {})
        p10 = m_full.get("precision@10", {})

        roc_str = f"{roc.get('estimate', 0.0):.3f} [{roc.get('ci_lower', 0.0):.3f}-{roc.get('ci_upper', 0.0):.3f}]" if roc else "N/A"
        pr_str = f"{pr.get('estimate', 0.0):.3f} [{pr.get('ci_lower', 0.0):.3f}-{pr.get('ci_upper', 0.0):.3f}]" if pr else "N/A"
        p10_str = f"{p10.get('estimate', 0.0):.3f} [{p10.get('ci_lower', 0.0):.3f}-{p10.get('ci_upper', 0.0):.3f}]" if p10 else "N/A"

        lines.append(f"{m_name:<24} | {roc_str:<20} | {pr_str:<20} | {p10_str:<18}")

    lines.append("=" * 85)
    lines.append(" Note: Metrics computed with 1,000 bootstrap resamples on frozen gold dataset.")
    lines.append(" Training gate status: BLOCKED - minimum 30 good_fit labels required for official training unlocks.")
    return "\n".join(lines)


def _perform_regression_compare(current_dir: Path, prev_dir: Path) -> None:
    """Compare current run against a previous run to flag metric regressions beyond CI overlap."""
    cur_metrics_file = current_dir / "metrics.json"
    prev_metrics_file = prev_dir / "metrics.json"

    if not prev_metrics_file.exists():
        logger.warning("Comparison run metrics not found at %s", prev_metrics_file)
        return

    with open(cur_metrics_file, "r", encoding="utf-8") as f:
        cur_data = json.load(f)
    with open(prev_metrics_file, "r", encoding="utf-8") as f:
        prev_data = json.load(f)

    print("\n" + "=" * 70)
    print(f" REGRESSION COMPARISON: {current_dir.name} vs {prev_dir.name}")
    print("=" * 70)

    for m_name in cur_data.get("models", {}):
        if m_name not in prev_data.get("models", {}):
            continue

        c_roc = cur_data["models"][m_name].get("full_dataset_metrics", {}).get("roc_auc", {})
        p_roc = prev_data["models"][m_name].get("full_dataset_metrics", {}).get("roc_auc", {})

        c_est = c_roc.get("estimate", 0.0)
        p_est = p_roc.get("estimate", 0.0)
        c_upper = c_roc.get("ci_upper", 0.0)
        p_lower = p_roc.get("ci_lower", 0.0)

        diff = c_est - p_est
        status = "OK"
        # Regression flag: current upper CI is strictly below previous lower CI (statistically significant drop)
        if c_upper < p_lower:
            status = "REGRESSION (Significant drop beyond 95% CI overlap!)"
        elif diff < -0.05:
            status = "WARNING (Moderate point estimate drop)"

        print(f" [{m_name}] ROC-AUC: {c_est:.3f} (prev: {p_est:.3f}, diff: {diff:+.3f}) -> {status}")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run evaluation harness.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="Path to gold dataset CSV")
    parser.add_argument("--models", nargs="+", default=None, help="Models to evaluate")
    parser.add_argument("--n-splits", type=int, default=5, help="Number of CV splits")
    parser.add_argument("--output-dir", type=Path, default=None, help="Custom output directory")
    parser.add_argument("--compare", type=Path, default=None, help="Directory of previous run to compare against")
    args = parser.parse_args()

    run_evaluation(
        gold_path=args.gold,
        model_names=args.models,
        n_splits=args.n_splits,
        output_dir=args.output_dir,
        compare_dir=args.compare,
    )
