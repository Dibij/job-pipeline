"""Evaluate and train the learned title role-type classifier (Step 3).

Performs grouped-by-company 5-fold CV on human labeled titles, comparing
the learned model against the keyword blocklist on Precision, Recall, and
False Positive Rate on good_fit (must be zero).
"""
import logging
from pathlib import Path
import sys
import numpy as np
from sklearn.model_selection import GroupKFold

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.matching.hard_filter import _check_non_technical
from src.matching.title_classifier import (
    build_training_dataset,
    create_pipeline,
    train_and_save_model,
    MODEL_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_evaluation_and_training():
    print("\n" + "=" * 75)
    print("  STEP 3: LEARNED TITLE ROLE-TYPE MODEL (EVALUATION & TRAINING)")
    print("=" * 75)

    titles, companies, labels, is_eval, eval_user_labels = build_training_dataset()

    titles_arr = np.array(titles)
    companies_arr = np.array(companies)
    labels_arr = np.array(labels)
    is_eval_arr = np.array(is_eval)
    eval_user_arr = np.array(eval_user_labels)

    eval_idx = np.where(is_eval_arr)[0]
    eval_companies = companies_arr[eval_idx]

    print(f"Total training titles pool:      {len(titles_arr)} ({sum(labels_arr)} tech, {len(labels_arr)-sum(labels_arr)} non-tech)")
    print(f"Human labeled evaluation subset: {len(eval_idx)} titles across {len(set(eval_companies))} companies")

    # 5-fold Grouped CV
    gkf = GroupKFold(n_splits=5)
    oof_probs = np.zeros(len(eval_idx))
    oof_preds = np.zeros(len(eval_idx))

    for fold, (train_sub_idx, test_sub_idx) in enumerate(gkf.split(eval_idx, groups=eval_companies), 1):
        real_test_idx = eval_idx[test_sub_idx]
        real_train_eval_idx = eval_idx[train_sub_idx]

        test_comps = set(companies_arr[real_test_idx])
        # Add weak supervision from companies not in this test fold
        weak_train_idx = np.where((~is_eval_arr) & (~np.isin(companies_arr, list(test_comps))))[0]

        fold_train_idx = np.concatenate([real_train_eval_idx, weak_train_idx])

        pipe = create_pipeline()
        pipe.fit(titles_arr[fold_train_idx], labels_arr[fold_train_idx])

        probs = pipe.predict_proba(titles_arr[real_test_idx])[:, 1]
        oof_probs[test_sub_idx] = probs
        oof_preds[test_sub_idx] = (probs >= 0.35).astype(int)

    # Ground truth: 1=tech, 0=non-tech.
    # Non-tech detection metrics:
    y_true_non_tech = (labels_arr[eval_idx] == 0).astype(int)

    # 1. Blocklist
    bl_pred_non_tech = np.array([int(not _check_non_technical(t).passed) for t in titles_arr[eval_idx]])
    bl_tp = np.sum((bl_pred_non_tech == 1) & (y_true_non_tech == 1))
    bl_fp = np.sum((bl_pred_non_tech == 1) & (y_true_non_tech == 0))
    bl_fn = np.sum((bl_pred_non_tech == 0) & (y_true_non_tech == 1))
    bl_prec = bl_tp / (bl_tp + bl_fp) if (bl_tp + bl_fp) else 0.0
    bl_rec = bl_tp / (bl_tp + bl_fn) if (bl_tp + bl_fn) else 0.0

    good_mask = np.array([eval_user_arr[i] == "good_fit" for i in range(len(eval_idx))])
    total_good = np.sum(good_mask)
    bl_good_killed = np.sum(bl_pred_non_tech[good_mask] == 1)
    bl_good_fpr = bl_good_killed / total_good if total_good else 0.0

    # 2. Learned Model (OOF)
    m_pred_non_tech = (oof_preds == 0).astype(int)
    m_tp = np.sum((m_pred_non_tech == 1) & (y_true_non_tech == 1))
    m_fp = np.sum((m_pred_non_tech == 1) & (y_true_non_tech == 0))
    m_fn = np.sum((m_pred_non_tech == 0) & (y_true_non_tech == 1))
    m_prec = m_tp / (m_tp + m_fp) if (m_tp + m_fp) else 0.0
    m_rec = m_tp / (m_tp + m_fn) if (m_tp + m_fn) else 0.0
    m_good_killed = np.sum(m_pred_non_tech[good_mask] == 1)
    m_good_fpr = m_good_killed / total_good if total_good else 0.0

    print("\n" + "-" * 75)
    print("  MODEL COMPARISON ON HUMAN LABELED TITLES (Grouped CV)")
    print("-" * 75)
    print(f"{'Method':<25} | {'Precision':<10} | {'Recall':<10} | {'good_fit Killed':<15} | {'FPR (good_fit)':<12}")
    print("-" * 75)
    print(f"{'Keyword Blocklist':<25} | {bl_prec:<10.3f} | {bl_rec:<10.3f} | {bl_good_killed:<15} | {bl_good_fpr:<12.3f}")
    print(f"{'Learned Model (OOF)':<25} | {m_prec:<10.3f} | {m_rec:<10.3f} | {m_good_killed:<15} | {m_good_fpr:<12.3f}")
    print("-" * 75)

    if m_good_killed == 0 and m_rec >= bl_rec:
        print("\n  >> SUCCESS: Learned model beats blocklist recall without killing any good_fit!")
    else:
        print("\n  >> WARNING: Learned model did not strictly satisfy criteria.")

    # Retrain on full dataset and save artifact
    print("\nRetraining final model on all data and saving artifact...")
    train_and_save_model(MODEL_PATH)
    print(f"Model saved: {MODEL_PATH}")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    run_evaluation_and_training()
