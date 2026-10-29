"""scripts/report_labels.py — Human Label & Model Evaluation Report (Task 7.9).

Generates comprehensive reporting across:
1. Label breakdown by guideline version (v2_role_fit_only vs legacy v1/None).
2. Per-source counts and good_fit positive yield.
3. Per-stratum counts and good_fit yield.
4. Model Training Gate status (150 total v2 labels / 30 role-fit good_fit).
5. Scorer comparative metrics (MatchScorer vs Title Rule vs Laya) with bootstrap 95% CIs.

Usage:
    python scripts/report_labels.py
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.metrics import average_precision_score, precision_score, recall_score

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.matching.scorer import MatchScorer
from scripts.make_labeling_batch import score_title_rule

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def bootstrap_metric_ci(
    y_true: np.ndarray,
    scores: np.ndarray,
    companies: np.ndarray,
    metric_fn,
    n_bootstraps: int = 500,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Compute point estimate and 95% bootstrap confidence interval clustered by company."""
    point = metric_fn(y_true, scores)
    rng = np.random.RandomState(seed)
    unique_comps = np.unique(companies)

    boot_vals = []
    for _ in range(n_bootstraps):
        boot_comps = rng.choice(unique_comps, size=len(unique_comps), replace=True)
        boot_idx = np.concatenate([np.where(companies == c)[0] for c in boot_comps])
        if len(np.unique(y_true[boot_idx])) < 2:
            continue
        try:
            boot_vals.append(metric_fn(y_true[boot_idx], scores[boot_idx]))
        except Exception:
            continue

    if not boot_vals:
        return float(point), float(point), float(point)

    low = float(np.percentile(boot_vals, 2.5))
    high = float(np.percentile(boot_vals, 97.5))
    return float(point), low, high


def calc_recall_at_k(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
    n_pos = np.sum(y_true == 1)
    if n_pos == 0:
        return 0.0
    top_k_idx = np.argsort(scores)[::-1][:k]
    return float(np.sum(y_true[top_k_idx] == 1) / n_pos)


def calc_precision_at_k(y_true: np.ndarray, scores: np.ndarray, k: int) -> float:
    if len(scores) == 0:
        return 0.0
    top_k_idx = np.argsort(scores)[::-1][:min(k, len(scores))]
    return float(np.mean(y_true[top_k_idx] == 1))


def main():
    parser = argparse.ArgumentParser(description="Generate human label and model metrics report.")
    args = parser.parse_args()

    print("\n" + "=" * 78)
    print("   JOB RADAR: HUMAN LABELS & SCORER EVALUATION REPORT (Task 7.9)")
    print("=" * 78)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Guideline version breakdown
            cur.execute("""
                SELECT COALESCE(label_guideline_version, 'legacy_None') AS guideline,
                       label,
                       COUNT(*) AS row_count,
                       COUNT(DISTINCT job_id) AS distinct_jobs
                FROM laya_labels
                GROUP BY 1, 2
                ORDER BY 1, 2;
            """)
            guideline_rows = cur.fetchall()

            # 2. Per-source counts and good_fit yield
            cur.execute("""
                SELECT j.source,
                       COUNT(DISTINCT l.job_id) AS total_labeled,
                       COUNT(DISTINCT CASE WHEN l.label = 'good_fit' THEN l.job_id END) AS good_fits,
                       COUNT(DISTINCT CASE WHEN l.label = 'maybe' THEN l.job_id END) AS maybes,
                       COUNT(DISTINCT CASE WHEN l.label = 'bad_fit' THEN l.job_id END) AS bad_fits
                FROM laya_labels l
                JOIN jobs j ON l.job_id = j.id
                GROUP BY j.source
                ORDER BY total_labeled DESC;
            """)
            source_rows = cur.fetchall()

            # 3. Per-stratum breakdown
            cur.execute("""
                SELECT COALESCE(sampling_stratum, 'unspecified') AS stratum,
                       COUNT(DISTINCT l.job_id) AS total_labeled,
                       COUNT(DISTINCT CASE WHEN l.label = 'good_fit' THEN l.job_id END) AS good_fits,
                       COUNT(DISTINCT CASE WHEN l.label = 'maybe' THEN l.job_id END) AS maybes,
                       COUNT(DISTINCT CASE WHEN l.label = 'bad_fit' THEN l.job_id END) AS bad_fits
                FROM laya_labels l
                GROUP BY 1
                ORDER BY total_labeled DESC;
            """)
            stratum_rows = cur.fetchall()

            # 4. Fetch distinct labeled jobs for metric evaluation
            cur.execute("""
                SELECT DISTINCT ON (l.job_id)
                       l.job_id, l.label, l.label_guideline_version, l.exclude_reason,
                       j.title, j.company_name, j.description_text, j.location_raw,
                       j.is_remote, j.remote_restriction, j.experience_level,
                       j.detected_language, j.is_unpaid, j.tags,
                       COALESCE(m.match_score, 0) AS match_score,
                       COALESCE(ls.final_score, 0) AS laya_score
                FROM laya_labels l
                JOIN jobs j ON l.job_id = j.id
                LEFT JOIN job_matches m ON j.id = m.job_id
                LEFT JOIN LATERAL (
                    SELECT final_score FROM laya_job_scores
                    WHERE job_id = j.id ORDER BY scored_at DESC LIMIT 1
                ) ls ON true
                ORDER BY l.job_id, l.labeled_at DESC;
            """)
            labeled_jobs = cur.fetchall()

    # Section 1: Guideline version summary
    print("\n[1] Labels by Guideline Version:")
    print("-" * 78)
    print(f"{'Guideline Version':<22} | {'Label':<10} | {'Rows':<8} | {'Distinct Jobs':<14}")
    print("-" * 78)
    v2_total_jobs = 0
    v2_good_jobs = 0
    for r in guideline_rows:
        g = r["guideline"]
        lbl = r["label"]
        rows = r["row_count"]
        djobs = r["distinct_jobs"]
        if g == "v2_role_fit_only":
            v2_total_jobs += djobs
            if lbl == "good_fit":
                v2_good_jobs += djobs
        print(f"{g:<22} | {lbl:<10} | {rows:<8} | {djobs:<14}")
    print("-" * 78)

    # Section 2: Gate status
    print("\n[2] Model Training Gate Status:")
    print("-" * 78)
    gate_labels_ok = (v2_total_jobs >= 150)
    gate_goods_ok = (v2_good_jobs >= 30)
    print(f"Total v2 role-fit labels:   {v2_total_jobs:3d} / 150 required  -> {'[PASS]' if gate_labels_ok else '[PENDING]'}")
    print(f"Role-fit good_fit labels:   {v2_good_jobs:3d} /  30 required  -> {'[PASS]' if gate_goods_ok else '[PENDING]'}")
    if not (gate_labels_ok and gate_goods_ok):
        print("\n  >> CAVEAT: good_fit count (< 30) is insufficient for trustworthy ranker")
        print("     training or high-confidence evaluation. Metrics below are indicative only.")
    print("-" * 78)

    # Section 3: Per-source yield
    print("\n[3] Per-Source Label Counts and Positive Yield:")
    print("-" * 78)
    print(f"{'Source':<20} | {'Total':<6} | {'Good':<5} | {'Maybe':<6} | {'Bad':<5} | {'Good %':<8}")
    print("-" * 78)
    for r in source_rows:
        tot = r["total_labeled"]
        good = r["good_fits"]
        pct = (good / tot * 100) if tot else 0.0
        print(f"{r['source']:<20} | {tot:<6} | {good:<5} | {r['maybes']:<6} | {r['bad_fits']:<5} | {pct:>6.1f}%")
    print("-" * 78)

    # Section 4: Per-stratum yield
    print("\n[4] Per-Stratum Label Counts and Positive Yield:")
    print("-" * 78)
    print(f"{'Stratum':<20} | {'Total':<6} | {'Good':<5} | {'Maybe':<6} | {'Bad':<5} | {'Good %':<8}")
    print("-" * 78)
    for r in stratum_rows:
        tot = r["total_labeled"]
        good = r["good_fits"]
        pct = (good / tot * 100) if tot else 0.0
        print(f"{r['stratum']:<20} | {tot:<6} | {good:<5} | {r['maybes']:<6} | {r['bad_fits']:<5} | {pct:>6.1f}%")
    print("-" * 78)

    # Section 5: Comparative Scorer Evaluation
    # Evaluate across all unexcluded labeled jobs
    eval_jobs = [j for j in labeled_jobs if not j.get("exclude_reason")]
    if len(eval_jobs) < 10:
        print("\n[5] Insufficient unexcluded labeled jobs for ranking evaluation.")
        return

    y_true = np.array([1 if j["label"] == "good_fit" else 0 for j in eval_jobs])
    companies = np.array([j.get("company_name") or "Unknown" for j in eval_jobs])
    ms_scores = np.array([float(j["match_score"]) for j in eval_jobs])
    ls_scores = np.array([float(j["laya_score"]) for j in eval_jobs])
    tr_scores = np.array([score_title_rule(j.get("title") or "") for j in eval_jobs])

    pos_count = int(np.sum(y_true == 1))
    print(f"\n[5] Comparative Scorer Ranking Performance (N={len(eval_jobs)}, Positives={pos_count}):")
    print("-" * 78)
    print(f"{'Scorer':<18} | {'Precision@10':<16} | {'Recall@10':<16} | {'Recall@20':<16} | {'PR-AUC':<14}")
    print("-" * 78)

    scorers = [
        ("Title Rule Score", tr_scores),
        ("MatchScorer", ms_scores),
        ("LayaScorer", ls_scores),
    ]

    for name, sc in scorers:
        p10, p10_l, p10_h = bootstrap_metric_ci(y_true, sc, companies, lambda y, s: calc_precision_at_k(y, s, 10))
        r10, r10_l, r10_h = bootstrap_metric_ci(y_true, sc, companies, lambda y, s: calc_recall_at_k(y, s, 10))
        r20, r20_l, r20_h = bootstrap_metric_ci(y_true, sc, companies, lambda y, s: calc_recall_at_k(y, s, 20))
        prauc, prauc_l, prauc_h = bootstrap_metric_ci(y_true, sc, companies, average_precision_score)

        print(
            f"{name:<18} | "
            f"{p10:.3f} [{p10_l:.2f},{p10_h:.2f}] | "
            f"{r10:.3f} [{r10_l:.2f},{r10_h:.2f}] | "
            f"{r20:.3f} [{r20_l:.2f},{r20_h:.2f}] | "
            f"{prauc:.3f} [{prauc_l:.2f},{prauc_h:.2f}]"
        )
    print("-" * 78)
    print("Report completed.\n")


if __name__ == "__main__":
    main()
