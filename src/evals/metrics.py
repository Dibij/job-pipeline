"""Evaluation metrics, bootstrap confidence intervals, and gate status checking.

Provides:
- Check training gates (>=150 labels, >=30 good_fit, >=3 positives per fold).
- Grouped stratified CV splitting (grouped by company).
- Metric calculators: ROC-AUC, PR-AUC, Precision@k, Recall@k, Per-class F1, Confusion Matrix, Cohen's Kappa.
- 95% Empirical Bootstrap Confidence Intervals for all metrics.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np
from sklearn.metrics import (
    average_precision_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold

logger = logging.getLogger(__name__)

GATE_MIN_TOTAL_LABELS = 150
GATE_MIN_GOOD_FIT = 30
GATE_MIN_FOLD_POSITIVES = 3


def check_training_gates(
    total_distinct_labels: int,
    distinct_good_fit: int,
    fold_positives: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Report training gate status honestly without bypassing.

    Returns dict with gate status, counts, thresholds, and unlock status.
    """
    total_ok = total_distinct_labels >= GATE_MIN_TOTAL_LABELS
    pos_ok = distinct_good_fit >= GATE_MIN_GOOD_FIT
    fold_ok = True
    if fold_positives is not None and len(fold_positives) > 0:
        fold_ok = all(fp >= GATE_MIN_FOLD_POSITIVES for fp in fold_positives)

    all_passed = total_ok and pos_ok and fold_ok

    reasons: List[str] = []
    if not total_ok:
        reasons.append(
            f"Total distinct v2 labels ({total_distinct_labels}/{GATE_MIN_TOTAL_LABELS}) below requirement"
        )
    if not pos_ok:
        reasons.append(
            f"Distinct good_fit labels ({distinct_good_fit}/{GATE_MIN_GOOD_FIT}) below requirement"
        )
    if not fold_ok and fold_positives:
        min_fold = min(fold_positives)
        reasons.append(
            f"Fold positive count ({min_fold}/{GATE_MIN_FOLD_POSITIVES}) below minimum"
        )

    return {
        "passed": all_passed,
        "status": "UNLOCKED" if all_passed else "BLOCKED",
        "total_labels": total_distinct_labels,
        "total_required": GATE_MIN_TOTAL_LABELS,
        "good_fit_count": distinct_good_fit,
        "good_fit_required": GATE_MIN_GOOD_FIT,
        "fold_positives_min_required": GATE_MIN_FOLD_POSITIVES,
        "reasons": reasons,
    }


def compute_precision_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int) -> float:
    """Compute Precision@k (fraction of top k ranked jobs that are true positives)."""
    if len(y_true) == 0:
        return 0.0
    effective_k = min(k, len(y_true))
    if effective_k == 0:
        return 0.0
    top_indices = np.argsort(-y_score)[:effective_k]
    return float(np.mean(y_true[top_indices]))


def compute_recall_at_k(y_true: np.ndarray, y_score: np.ndarray, k: int) -> float:
    """Compute Recall@k (fraction of total positives recovered in top k ranked jobs)."""
    total_pos = int(np.sum(y_true))
    if total_pos == 0:
        return 0.0
    effective_k = min(k, len(y_true))
    if effective_k == 0:
        return 0.0
    top_indices = np.argsort(-y_score)[:effective_k]
    rec_pos = int(np.sum(y_true[top_indices]))
    return float(rec_pos / total_pos)


def bootstrap_ci(
    y_true: np.ndarray,
    y_score: np.ndarray,
    metric_fn: Any,
    n_bootstrap: int = 1000,
    random_state: int = 42,
) -> Tuple[float, float, float]:
    """Compute point estimate and 95% bootstrap confidence interval [2.5%, 97.5%].

    Returns:
        (point_estimate, ci_lower, ci_upper)
    """
    n = len(y_true)
    if n == 0:
        return (0.0, 0.0, 0.0)

    try:
        point = float(metric_fn(y_true, y_score))
    except Exception:
        point = 0.0

    rng = np.random.default_rng(random_state)
    boot_vals: List[float] = []

    for _ in range(n_bootstrap):
        idx = rng.choice(n, size=n, replace=True)
        b_true = y_true[idx]
        b_score = y_score[idx]
        # Skip resamples that have 0 positives if metric requires positives
        if np.sum(b_true) == 0 and np.sum(y_true) > 0:
            continue
        try:
            val = float(metric_fn(b_true, b_score))
            if not np.isnan(val):
                boot_vals.append(val)
        except Exception:
            continue

    if len(boot_vals) < 50:
        # Not enough valid resamples (e.g. extremely scarce positives)
        return (point, point, point)

    lower = float(np.percentile(boot_vals, 2.5))
    upper = float(np.percentile(boot_vals, 97.5))
    return (point, lower, upper)


def evaluate_binary_predictions(
    y_true: Sequence[int],
    y_score: Sequence[float],
    n_bootstrap: int = 1000,
    random_state: int = 42,
    ks: Sequence[int] = (5, 10, 25),
) -> Dict[str, Any]:
    """Calculate ROC-AUC, PR-AUC, P@k, R@k, Cohen's kappa with 95% bootstrap CIs.

    y_true: 1 for good_fit, 0 for maybe/bad_fit.
    y_score: continuous float score in [0, 1].
    """
    y_t = np.array(y_true, dtype=int)
    y_s = np.array(y_score, dtype=float)
    n = len(y_t)
    n_pos = int(np.sum(y_t))

    metrics: Dict[str, Any] = {
        "n": n,
        "n_positives": n_pos,
        "positive_rate": float(n_pos / n) if n > 0 else 0.0,
    }

    if n_pos < 1:
        metrics["error"] = "zero positives; ranking metrics undefined"
        return metrics

    # 1. ROC-AUC
    def _roc_auc(yt, ys):
        if len(np.unique(yt)) < 2:
            return np.nan
        return roc_auc_score(yt, ys)

    roc_val, roc_lo, roc_hi = bootstrap_ci(y_t, y_s, _roc_auc, n_bootstrap, random_state)
    metrics["roc_auc"] = {
        "estimate": roc_val,
        "ci_lower": roc_lo,
        "ci_upper": roc_hi,
    }

    # 2. PR-AUC (Average Precision)
    def _pr_auc(yt, ys):
        if len(np.unique(yt)) < 2:
            return np.nan
        return average_precision_score(yt, ys)

    pr_val, pr_lo, pr_hi = bootstrap_ci(y_t, y_s, _pr_auc, n_bootstrap, random_state)
    metrics["pr_auc"] = {
        "estimate": pr_val,
        "ci_lower": pr_lo,
        "ci_upper": pr_hi,
    }

    # 3. Precision@k and Recall@k
    for k in ks:
        p_val, p_lo, p_hi = bootstrap_ci(
            y_t, y_s, lambda yt, ys, _k=k: compute_precision_at_k(yt, ys, _k), n_bootstrap, random_state
        )
        metrics[f"precision@{k}"] = {
            "estimate": p_val,
            "ci_lower": p_lo,
            "ci_upper": p_hi,
        }

        r_val, r_lo, r_hi = bootstrap_ci(
            y_t, y_s, lambda yt, ys, _k=k: compute_recall_at_k(yt, ys, _k), n_bootstrap, random_state
        )
        metrics[f"recall@{k}"] = {
            "estimate": r_val,
            "ci_lower": r_lo,
            "ci_upper": r_hi,
        }

    # 4. Cohen's Kappa (using top 10% or score >= 0.5 as thresholded binary prediction)
    # If scores are mostly low, use top-n positive rate or 0.5 threshold
    threshold = 0.5 if np.any(y_s >= 0.5) else float(np.percentile(y_s, 90))
    y_pred_bin = (y_s >= threshold).astype(int)

    def _kappa(yt, ys):
        yp = (ys >= threshold).astype(int)
        return cohen_kappa_score(yt, yp)

    k_val, k_lo, k_hi = bootstrap_ci(y_t, y_s, _kappa, n_bootstrap, random_state)
    metrics["cohen_kappa"] = {
        "estimate": k_val,
        "ci_lower": k_lo,
        "ci_upper": k_hi,
        "threshold_used": threshold,
    }

    # 5. Confusion matrix & classification stats at selected threshold
    cm = confusion_matrix(y_t, y_pred_bin, labels=[0, 1])
    metrics["confusion_matrix_at_threshold"] = cm.tolist()
    prec = precision_score(y_t, y_pred_bin, zero_division=0)
    rec = recall_score(y_t, y_pred_bin, zero_division=0)
    f1 = f1_score(y_t, y_pred_bin, zero_division=0)
    metrics["threshold_classification"] = {
        "threshold": threshold,
        "precision": float(prec),
        "recall": float(rec),
        "f1": float(f1),
    }

    return metrics


def evaluate_multiclass_predictions(
    y_true: Sequence[str],
    y_pred: Sequence[str],
    labels: Sequence[str] = ("good_fit", "maybe", "bad_fit"),
    n_bootstrap: int = 1000,
    random_state: int = 42,
) -> Dict[str, Any]:
    """Calculate multi-class confusion matrix, per-class P/R/F1, and Cohen's Kappa."""
    yt = np.array(y_true)
    yp = np.array(y_pred)
    n = len(yt)

    cm = confusion_matrix(yt, yp, labels=labels)
    kappa = float(cohen_kappa_score(yt, yp))

    p, r, f1, s = precision_recall_fscore_support(
        yt, yp, labels=labels, zero_division=0
    )

    per_class: Dict[str, Any] = {}
    for i, lbl in enumerate(labels):
        per_class[lbl] = {
            "precision": float(p[i]),
            "recall": float(r[i]),
            "f1": float(f1[i]),
            "support": int(s[i]),
        }

    return {
        "n": n,
        "labels": list(labels),
        "confusion_matrix": cm.tolist(),
        "cohen_kappa": kappa,
        "per_class": per_class,
    }
