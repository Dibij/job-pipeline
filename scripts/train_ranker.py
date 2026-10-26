"""Ranker Training & Evaluation Script (Step 4).

Compares:
  (a) Title-rule score alone (from Step 2)
  (b) TF-IDF (word n-gram 1-2 on clean description + char n-gram 3-5 on title) + LogisticRegression
  (c) LogisticRegression with title-rule score added as an explicit feature

Evaluation:
  StratifiedGroupKFold (groups=company, n_splits=5, 10 seeds).
  Pooled out-of-fold AUC (good_fit vs {maybe, bad_fit}) with bootstrap 95% CI across companies.
  ElevenLabs ablation.

GATES:
  - REFUSE to train or report any model if v2 labels < 150 OR role-fit good_fit < 30.
  - REFUSE to report metrics for any fold with < 3 positive cases.
"""
import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.make_labeling_batch import score_title_rule

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOOKKEEPING_PATH = PROJECT_ROOT / "data" / "labeled_jobs_bookkeeping.jsonl"
TRAINING_PATH = PROJECT_ROOT / "data" / "labeled_jobs_training.jsonl"


def load_dataset() -> Tuple[List[Dict[str, Any]], int, int]:
    """Join bookkeeping and training jsonl on job_id, strictly filtering v2 and unexcluded rows."""
    if not BOOKKEEPING_PATH.exists() or not TRAINING_PATH.exists():
        logger.error("Required dataset files missing (%s or %s)", BOOKKEEPING_PATH, TRAINING_PATH)
        return [], 0, 0

    training_map: Dict[str, Dict[str, Any]] = {}
    with open(TRAINING_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            training_map[str(obj["job_id"])] = obj

    bookkeeping_rows: List[Dict[str, Any]] = []
    with open(BOOKKEEPING_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            bookkeeping_rows.append(json.loads(line))

    # Strict v2 filtering
    joined: List[Dict[str, Any]] = []
    total_v2_count = 0
    total_v2_good_count = 0

    for b in bookkeeping_rows:
        jid = str(b["job_id"])
        guideline = b.get("label_guideline_version")
        exclude_reason = b.get("exclude_reason")
        label = b.get("label")

        if guideline == "v2_role_fit_only" and not exclude_reason:
            total_v2_count += 1
            if label == "good_fit":
                total_v2_good_count += 1

            if jid in training_map:
                t = training_map[jid]
                item = {
                    "job_id": jid,
                    "title": b.get("title") or "",
                    "company": b.get("company") or "Unknown",
                    "label": label,
                    "binary_target": 1 if label == "good_fit" else 0,
                    "description_clean": b.get("description_clean") or "",
                    "training_text": t.get("text") or "",
                    "title_rule_score": score_title_rule(b.get("title") or ""),
                }
                joined.append(item)

    return joined, total_v2_count, total_v2_good_count


def bootstrap_auc_ci(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    companies: np.ndarray,
    n_bootstraps: int = 1000,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Compute pooled AUC and 95% bootstrap CI clustered by company."""
    rng = np.random.RandomState(seed)
    unique_companies = np.unique(companies)
    auc_base = roc_auc_score(y_true, y_pred)

    boot_aucs = []
    for _ in range(n_bootstraps):
        boot_comps = rng.choice(unique_companies, size=len(unique_companies), replace=True)
        boot_indices = np.concatenate([np.where(companies == c)[0] for c in boot_comps])
        if len(np.unique(y_true[boot_indices])) < 2:
            continue
        boot_aucs.append(roc_auc_score(y_true[boot_indices], y_pred[boot_indices]))

    if not boot_aucs:
        return auc_base, auc_base, auc_base

    low = float(np.percentile(boot_aucs, 2.5))
    high = float(np.percentile(boot_aucs, 97.5))
    return float(auc_base), low, high


def compute_company_sample_weights(companies: np.ndarray, cap: int = 5) -> np.ndarray:
    """Downweight companies having more than `cap` rows so they effectively count at most `cap`."""
    weights = np.ones(len(companies), dtype=float)
    unique_comps, counts = np.unique(companies, return_counts=True)
    comp_count_map = dict(zip(unique_comps, counts))
    for i, c in enumerate(companies):
        cnt = comp_count_map[c]
        if cnt > cap:
            weights[i] = cap / cnt
    return weights


def evaluate_models(
    dataset: List[Dict[str, Any]],
    n_splits: int = 5,
    n_seeds: int = 10,
) -> Optional[Dict[str, Any]]:
    """Run cross-validation on models (a), (b), (c) under strict fold gates."""
    titles = np.array([r["title"] for r in dataset])
    descriptions = np.array([r["description_clean"] for r in dataset])
    companies = np.array([r["company"] for r in dataset])
    y = np.array([r["binary_target"] for r in dataset])
    title_scores = np.array([r["title_rule_score"] for r in dataset])

    weights = compute_company_sample_weights(companies, cap=5)

    oof_preds_a = []
    oof_preds_b = []
    oof_preds_c = []
    eval_y = []
    eval_companies = []

    for seed in range(n_seeds):
        sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)

        for fold_idx, (train_idx, test_idx) in enumerate(sgkf.split(dataset, y, groups=companies), 1):
            y_test = y[test_idx]
            pos_test = np.sum(y_test == 1)

            # Strict Gate: Refuse fold if < 3 positive cases
            if pos_test < 3:
                logger.warning("Fold %d (seed %d) has only %d positive cases (< 3). Rejecting fold.",
                               fold_idx, seed, pos_test)
                return None

            w_train = weights[train_idx]

            # Vectorizers
            vec_title = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)
            vec_desc = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_features=1000, sublinear_tf=True)

            X_title_train = vec_title.fit_transform(titles[train_idx])
            X_desc_train = vec_desc.fit_transform(descriptions[train_idx])
            X_text_train = sparse.hstack([X_title_train, X_desc_train]).tocsr()

            X_title_test = vec_title.transform(titles[test_idx])
            X_desc_test = vec_desc.transform(descriptions[test_idx])
            X_text_test = sparse.hstack([X_title_test, X_desc_test]).tocsr()

            # (a) Title rule score alone
            pred_a = title_scores[test_idx]

            # (b) Text TF-IDF + LogisticRegression
            clf_b = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)
            clf_b.fit(X_text_train, y[train_idx], sample_weight=w_train)
            pred_b = clf_b.predict_proba(X_text_test)[:, 1]

            # (c) Text TF-IDF + Title-rule score as explicit feature
            rule_train = sparse.csr_matrix(title_scores[train_idx, None])
            rule_test = sparse.csr_matrix(title_scores[test_idx, None])
            X_comb_train = sparse.hstack([X_text_train, rule_train]).tocsr()
            X_comb_test = sparse.hstack([X_text_test, rule_test]).tocsr()

            clf_c = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)
            clf_c.fit(X_comb_train, y[train_idx], sample_weight=w_train)
            pred_c = clf_c.predict_proba(X_comb_test)[:, 1]

            oof_preds_a.extend(pred_a)
            oof_preds_b.extend(pred_b)
            oof_preds_c.extend(pred_c)
            eval_y.extend(y_test)
            eval_companies.extend(companies[test_idx])

    y_arr = np.array(eval_y)
    comp_arr = np.array(eval_companies)

    auc_a, a_low, a_high = bootstrap_auc_ci(y_arr, np.array(oof_preds_a), comp_arr)
    auc_b, b_low, b_high = bootstrap_auc_ci(y_arr, np.array(oof_preds_b), comp_arr)
    auc_c, c_low, c_high = bootstrap_auc_ci(y_arr, np.array(oof_preds_c), comp_arr)

    return {
        "model_a": {"auc": auc_a, "ci_lower": a_low, "ci_upper": a_high},
        "model_b": {"auc": auc_b, "ci_lower": b_low, "ci_upper": b_high},
        "model_c": {"auc": auc_c, "ci_lower": c_low, "ci_upper": c_high},
    }


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate ranker models.")
    parser.add_argument("--force", action="store_true", help="Bypass training gates (for testing only)")
    args = parser.parse_args()

    print("\n" + "=" * 75)
    print("  STEP 4: RANKER MODEL TRAINING & EVALUATION GATE CHECK")
    print("=" * 75)

    dataset, total_v2, total_v2_good = load_dataset()

    print(f"Current Status:")
    print(f"  - v2 role-fit labels (exclude_reason IS NULL): {total_v2} / 150 required")
    print(f"  - v2 role-fit good_fit labels:                 {total_v2_good} / 30 required")
    print(f"  - Usable joined records for training:          {len(dataset)}")

    # Strict Training Gate Check
    gate_failed = (total_v2 < 150) or (total_v2_good < 30)

    if gate_failed and not args.force:
        print("\n" + "!" * 75)
        print(f"TRAINING GATE NOT MET: have {total_v2}/150 v2 labels and {total_v2_good}/30 role-fit good_fit.")
        print("Refusing to train to prevent repeating the Head v2 overfitting failure.")
        print("!" * 75 + "\n")
        sys.exit(0)

    if gate_failed and args.force:
        print("\n[WARNING] --force flag supplied. Bypassing safety gates for dry run.")

    print("\nRunning StratifiedGroupKFold evaluation across 10 seeds...")
    results = evaluate_models(dataset)

    if results is None:
        print("\n" + "!" * 75)
        print("GATE FAILURE: Folds contained fewer than 3 positive cases.")
        print("Refusing to report unreliable metrics on undersized test splits.")
        print("!" * 75 + "\n")
        return

    print("\n" + "-" * 75)
    print("  OUT-OF-FOLD AUC EVALUATION (Bootstrap 95% CI)")
    print("-" * 75)
    print(f"(a) Title-rule score alone:        {results['model_a']['auc']:.3f} [{results['model_a']['ci_lower']:.3f}, {results['model_a']['ci_upper']:.3f}]")
    print(f"(b) TF-IDF (Text) + LR:             {results['model_b']['auc']:.3f} [{results['model_b']['ci_lower']:.3f}, {results['model_b']['ci_upper']:.3f}]")
    print(f"(c) TF-IDF (Text) + Title-rule + LR: {results['model_c']['auc']:.3f} [{results['model_c']['ci_lower']:.3f}, {results['model_c']['ci_upper']:.3f}]")
    print("-" * 75)

    # ElevenLabs Ablation
    dataset_no_eleven = [r for r in dataset if r["company"].strip().lower() != "elevenlabs"]
    print(f"\nRunning ElevenLabs ablation (N={len(dataset_no_eleven)})...")
    res_no_eleven = evaluate_models(dataset_no_eleven)
    if res_no_eleven:
        print(f"Without ElevenLabs (c) AUC:        {res_no_eleven['model_c']['auc']:.3f} [{res_no_eleven['model_c']['ci_lower']:.3f}, {res_no_eleven['model_c']['ci_upper']:.3f}]")

    # Promotion Rule
    c_lower = results["model_c"]["ci_lower"]
    c_auc = results["model_c"]["auc"]
    a_auc = results["model_a"]["auc"]
    promoted = (c_lower > 0.70) and ((c_auc - a_auc) >= 0.05)

    print("\n" + "=" * 75)
    print(f"Promotion Rule Check:")
    print(f"  - Model (c) lower CI > 0.70:       {c_lower:.3f} > 0.70 -> {c_lower > 0.70}")
    print(f"  - Model (c) beats (a) by >= 0.05:  +{c_auc - a_auc:.3f} >= 0.05 -> {(c_auc - a_auc) >= 0.05}")
    print(f"  - Status: {'PROMOTED to FEED.md ranker' if promoted else 'NOT PROMOTED — Title-rule remains the ranker'}")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    main()
