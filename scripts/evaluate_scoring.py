"""Task 7.7 / 6e: Evaluation script comparing MatchScorer vs Laya decision model vs human labels.

Metrics protocol follows TRAINING.md §7:
  - Population: labeled postings that pass hard filters (reason_code IS NULL) by default.
  - Primary metric: recall@20
  - Ranking metrics: precision@10, precision@20, recall@10, recall@20, PR-AUC with bootstrap 95% CIs.
  - Never reports raw accuracy (dominated by bad_fit majority).
  - Reports sample size (n) and positive count (pos) alongside every metric.
  - Small-sample caveat displayed when pos < 30.
  - Feed precision: label breakdown of top 10 postings in FEED.md.
  - Terminology: 'decision model' for Laya.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import random
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

    p = 0   # concordant
    q = 0   # discordant
    tx = 0  # ties in x only
    ty = 0  # ties in y only

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


def compute_ranking_metrics(
    y_true: List[bool],
    scores: List[float],
    k_list: Tuple[int, ...] = (10, 20),
) -> Dict[str, float]:
    """Compute precision@k, recall@k, and PR-AUC over ranked scores."""
    n = len(y_true)
    n_pos = sum(1 for y in y_true if y)
    if n == 0:
        return {}

    # Sort descending by score
    sorted_pairs = sorted(zip(scores, y_true), key=lambda p: p[0], reverse=True)
    sorted_y = [p[1] for p in sorted_pairs]

    metrics: Dict[str, float] = {}
    for k in k_list:
        k_eff = min(k, n)
        top_k = sorted_y[:k_eff]
        prec = (sum(1 for y in top_k if y) / k_eff) if k_eff > 0 else 0.0
        rec = (sum(1 for y in top_k if y) / n_pos) if n_pos > 0 else 0.0
        metrics[f"precision@{k}"] = round(prec, 4)
        metrics[f"recall@{k}"] = round(rec, 4)

    # PR-AUC via trapezoidal integration over PR curve
    cum_tp = 0
    rec_points = [0.0]
    prec_points = [1.0]
    for i, y in enumerate(sorted_y, start=1):
        if y:
            cum_tp += 1
        r = (cum_tp / n_pos) if n_pos > 0 else 0.0
        p = cum_tp / i
        rec_points.append(r)
        prec_points.append(p)

    auc = 0.0
    for i in range(1, len(rec_points)):
        dx = rec_points[i] - rec_points[i - 1]
        dy = (prec_points[i] + prec_points[i - 1]) / 2.0
        auc += dx * dy

    metrics["pr_auc"] = round(auc, 4)
    metrics["n"] = n
    metrics["n_pos"] = n_pos
    return metrics


def bootstrap_ranking_metrics(
    y_true: List[bool],
    scores: List[float],
    n_bootstraps: int = 1000,
    seed: int = 42,
) -> Tuple[Dict[str, Tuple[float, float, float]], int, int]:
    """Compute 95% bootstrap confidence intervals for ranking metrics."""
    rng = random.Random(seed)
    n = len(y_true)
    base = compute_ranking_metrics(y_true, scores)
    if n < 2 or base.get("n_pos", 0) == 0:
        return (
            {k: (v, v, v) for k, v in base.items() if k not in ("n", "n_pos")},
            base.get("n", n),
            base.get("n_pos", 0),
        )

    boot_res: Dict[str, List[float]] = {k: [] for k in base if k not in ("n", "n_pos")}
    indices = list(range(n))

    for _ in range(n_bootstraps):
        sample_idx = [rng.choice(indices) for _ in range(n)]
        sample_y = [y_true[i] for i in sample_idx]
        if sum(1 for y in sample_y if y) == 0:
            continue
        sample_s = [scores[i] for i in sample_idx]
        m = compute_ranking_metrics(sample_y, sample_s)
        for k in boot_res:
            boot_res[k].append(m[k])

    cis: Dict[str, Tuple[float, float, float]] = {}
    for k in boot_res:
        vals = sorted(boot_res[k])
        if vals:
            low_idx = int(0.025 * len(vals))
            high_idx = int(0.975 * len(vals))
            cis[k] = (base[k], vals[low_idx], vals[high_idx])
        else:
            cis[k] = (base[k], base[k], base[k])

    return cis, int(base["n"]), int(base["n_pos"])


def fetch_evaluation_data(population: str = "survivors") -> List[Dict[str, Any]]:
    """Fetch unique canonical labeled postings and their scores.

    Args:
        population: 'survivors' (default) filters to postings passing hard filter;
                    'all' includes all labeled postings.
    """
    where_clause = "WHERE jm.reason_code IS NULL" if population == "survivors" else ""

    sql = f"""
        SELECT DISTINCT ON (COALESCE(j.canonical_job_id, j.id))
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
        LEFT JOIN LATERAL (
            SELECT match_score, reason_code
            FROM job_matches
            WHERE job_id = j.id
            ORDER BY scored_at DESC
            LIMIT 1
        ) jm ON TRUE
        LEFT JOIN LATERAL (
            SELECT final_score, is_passed, disqualification_reason
            FROM laya_job_scores
            WHERE job_id = j.id
            ORDER BY scored_at DESC
            LIMIT 1
        ) ls ON TRUE
        {where_clause}
        ORDER BY COALESCE(j.canonical_job_id, j.id), l.labeled_at DESC;
    """
    return execute_query(sql)


def fetch_feed_top_10() -> List[Dict[str, Any]]:
    """Fetch top 10 jobs currently displayed in FEED.md with their human labels."""
    sql = """
        SELECT
            j.id,
            j.title,
            j.company_name,
            jm.match_score,
            l.label
        FROM jobs j
        JOIN LATERAL (
            SELECT match_score, reason_code
            FROM job_matches
            WHERE job_id = j.id
            ORDER BY scored_at DESC
            LIMIT 1
        ) jm ON TRUE
        LEFT JOIN LATERAL (
            SELECT label
            FROM laya_labels
            WHERE job_id = j.id
            ORDER BY labeled_at DESC
            LIMIT 1
        ) l ON TRUE
        WHERE j.canonical_job_id IS NULL AND jm.reason_code IS NULL
        ORDER BY jm.match_score DESC, j.id
        LIMIT 10;
    """
    return execute_query(sql)


def run_evaluation(
    population: str = "survivors",
    compute_missing_laya: bool = False,
    device: str = "cpu",
) -> None:
    logger.info("Fetching evaluation dataset (population: %s)...", population)
    data = fetch_evaluation_data(population=population)

    if not data:
        print(f"\n[EVALUATION NOTICE] No labeled jobs found in population '{population}'.")
        return

    logger.info("Found %d unique canonical labeled postings.", len(data))

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

    # Prepare ground truth and prediction arrays (binary view: good_fit vs not)
    y_true_binary = [r["label"] == "good_fit" for r in data]
    y_true_rank = [LABEL_RANK.get(r["label"], 0) for r in data]

    match_scores = [
        float(r["match_score"]) if r.get("match_score") is not None else 0.0
        for r in data
    ]

    # MatchScorer bootstrap metrics
    match_cis, n_match, pos_match = bootstrap_ranking_metrics(y_true_binary, match_scores)
    tau_match = kendall_tau_b(y_true_rank, match_scores)

    # Decision model (Laya) metrics over postings with Laya score
    laya_items = [r for r in data if r.get("laya_score") is not None]
    if laya_items:
        laya_y_true = [r["label"] == "good_fit" for r in laya_items]
        laya_scores = [float(r["laya_score"]) for r in laya_items]
        laya_cis, n_laya, pos_laya = bootstrap_ranking_metrics(laya_y_true, laya_scores)
        tau_laya = kendall_tau_b(
            [LABEL_RANK.get(r["label"], 0) for r in laya_items],
            laya_scores,
        )
    else:
        laya_cis, n_laya, pos_laya = {}, 0, 0
        tau_laya = 0.0

    # Top 10 FEED.md Precision
    feed_10 = fetch_feed_top_10()
    feed_label_counts = Counter(r.get("label") or "unlabeled" for r in feed_10)

    # Format Output
    lines = []
    lines.append("=" * 82)
    lines.append(f"          MODEL EVALUATION REPORT (Population: {population.upper()})")
    lines.append("=" * 82)
    lines.append(f"Canonical Postings Evaluated: {len(data)}")
    lines.append("Ground Truth Distribution:")
    for lbl in ["good_fit", "maybe", "bad_fit"]:
        c = sum(1 for r in data if r["label"] == lbl)
        lines.append(f"  - {lbl:<10}: {c} ({c / len(data) * 100:.1f}%)")
    lines.append("-" * 82)

    # Small-sample caveat
    if pos_match < 30:
        lines.append(
            f"[!] CAVEAT: Total positive labels (good_fit) = {pos_match} (< 30).\n"
            f"    Per TRAINING.md §7, all metrics are INDICATIVE ONLY with small sample caveat."
        )
        lines.append("-" * 82)

    lines.append(f"{'METRIC':<22} | {'MatchScorer (Baseline)':<28} | {'Laya (Decision Model)':<28}")
    lines.append("-" * 82)

    for metric_name in ["recall@20", "recall@10", "precision@10", "precision@20", "pr_auc"]:
        m_val, m_lo, m_hi = match_cis.get(metric_name, (0.0, 0.0, 0.0))
        m_str = f"{m_val:.3f} [{m_lo:.3f}-{m_hi:.3f}]"

        if laya_cis and metric_name in laya_cis:
            l_val, l_lo, l_hi = laya_cis[metric_name]
            l_str = f"{l_val:.3f} [{l_lo:.3f}-{l_hi:.3f}]"
        else:
            l_str = "N/A (unscored)"

        label_display = metric_name + (" *" if metric_name == "recall@20" else "")
        lines.append(f"{label_display:<22} | {m_str:<28} | {l_str:<28}")

    lines.append(
        f"{'Sample size (n, pos)':<22} | {f'n={n_match}, pos={pos_match}':<28} | {f'n={n_laya}, pos={pos_laya}':<28}"
    )
    lines.append(
        f"{'Kendall Tau-b':<22} | {f'{tau_match:.3f}':<28} | {f'{tau_laya:.3f}':<28}"
    )
    lines.append("-" * 82)
    lines.append("* Primary evaluation metric per TRAINING.md §7.2.")
    lines.append("")

    # Feed Precision Section
    lines.append("FEED.md PRECISION (Top 10 Ranked Matches):")
    lines.append(f"  - good_fit : {feed_label_counts.get('good_fit', 0)} / 10")
    lines.append(f"  - maybe    : {feed_label_counts.get('maybe', 0)} / 10")
    lines.append(f"  - bad_fit  : {feed_label_counts.get('bad_fit', 0)} / 10")
    lines.append(f"  - unlabeled: {feed_label_counts.get('unlabeled', 0)} / 10")
    labeled_top_10 = 10 - feed_label_counts.get("unlabeled", 0)
    if labeled_top_10 > 0:
        prec_good = feed_label_counts.get("good_fit", 0) / labeled_top_10
        prec_good_maybe = (feed_label_counts.get("good_fit", 0) + feed_label_counts.get("maybe", 0)) / labeled_top_10
        lines.append(f"  Feed Precision among labeled: good_fit={prec_good:.1%}, good_fit+maybe={prec_good_maybe:.1%}")
    lines.append("-" * 82)

    # Per-job listing
    lines.append("\nPER-JOB BREAKDOWN IN EVALUATION SET:")
    lines.append(f"{'Job Title':<38} | {'Company':<18} | {'Label':<9} | {'Match':<7} | {'Laya'}")
    lines.append("-" * 85)
    for r in data:
        t = (r["title"] or "")[:38]
        c = (r["company_name"] or "")[:18]
        lbl = r["label"]
        ms = float(r["match_score"]) if r.get("match_score") is not None else 0.0
        ls = f"{float(r['laya_score']):.1f}" if r.get("laya_score") is not None else "N/A"
        lines.append(f"{t:<38} | {c:<18} | {lbl:<9} | {ms:<7.1f} | {ls}")
    lines.append("=" * 85)

    report_text = "\n".join(lines)
    print("\n" + report_text)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_file = DATA_DIR / "eval_report.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info("Evaluation report saved to: %s", out_file)


if __name__ == "__main__":
    from collections import Counter

    parser = argparse.ArgumentParser(description="Evaluate MatchScorer and Laya decision model against human labels.")
    parser.add_argument(
        "--population",
        choices=["survivors", "all"],
        default="survivors",
        help="Evaluation population: 'survivors' (hard-filter survivors, default) or 'all' (all labeled postings).",
    )
    parser.add_argument(
        "--compute-missing-laya",
        action="store_true",
        help="Compute Laya decision model scores on the fly for unscored jobs.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="Device for on-the-fly Laya inference (cuda/cpu).",
    )
    args = parser.parse_args()

    run_evaluation(
        population=args.population,
        compute_missing_laya=args.compute_missing_laya,
        device=args.device,
    )
