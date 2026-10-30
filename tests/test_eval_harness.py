"""Tests for evaluation harness (evals package).

Pure in-memory unit tests using synthetic fixtures (no database required).
"""
import pytest
import numpy as np

from src.evals.leakage import (
    LeakageViolationError,
    check_guideline_integrity,
    check_split_leakage,
    normalize_company,
)
from src.evals.metrics import (
    check_training_gates,
    compute_precision_at_k,
    compute_recall_at_k,
    bootstrap_ci,
    evaluate_binary_predictions,
    evaluate_multiclass_predictions,
)
from src.evals.registry import (
    get_model,
    list_registered_models,
    TitleKeywordRuleScorer,
    CharNgramTitleClassifierScorer,
    MatchScorerWrapper,
)
from scripts.run_evals import build_grouped_folds


def test_leakage_detector_catches_job_id_overlap():
    train = [{"job_id": "job_1", "company": "Acme", "description_hash": "h1"}]
    test = [{"job_id": "job_1", "company": "Beta", "description_hash": "h2"}]
    with pytest.raises(LeakageViolationError, match="Job ID overlap detected"):
        check_split_leakage(train, test)


def test_leakage_detector_catches_company_overlap():
    train = [{"job_id": "job_1", "company": "Acme Corp", "description_hash": "h1"}]
    test = [{"job_id": "job_2", "company": "acme corp", "description_hash": "h2"}]
    with pytest.raises(LeakageViolationError, match="Company overlap detected"):
        check_split_leakage(train, test)


def test_leakage_detector_catches_duplicate_description_hash():
    train = [{"job_id": "job_1", "company": "Alpha", "description_hash": "hash_abc"}]
    test = [{"job_id": "job_2", "company": "Beta", "description_hash": "hash_abc"}]
    with pytest.raises(LeakageViolationError, match="Duplicate description hash overlap"):
        check_split_leakage(train, test)


def test_leakage_detector_passes_clean_splits():
    train = [
        {"job_id": "job_1", "company": "Alpha", "description_hash": "h1"},
        {"job_id": "job_2", "company": "Beta", "description_hash": "h2"},
    ]
    test = [
        {"job_id": "job_3", "company": "Gamma", "description_hash": "h3"},
    ]
    res = check_split_leakage(train, test)
    assert res["status"] == "clean"


def test_guideline_integrity_rejection():
    # Only v2_role_fit_only allowed
    records = [
        {"job_id": "j1", "guideline_version": "v2_role_fit_only"},
        {"job_id": "j2", "guideline_version": "v1"},
    ]
    with pytest.raises(LeakageViolationError, match="Protocol violation"):
        check_guideline_integrity(records)


def test_training_gate_status_checks():
    # Under-threshold scenario (current state: 147 labels, 5 good_fit)
    gate = check_training_gates(total_distinct_labels=147, distinct_good_fit=5, fold_positives=[1, 1, 1, 1, 1])
    assert gate["passed"] is False
    assert gate["status"] == "BLOCKED"
    assert len(gate["reasons"]) == 3

    # Unlocked scenario
    gate_ok = check_training_gates(total_distinct_labels=160, distinct_good_fit=35, fold_positives=[4, 5, 4, 3, 4])
    assert gate_ok["passed"] is True
    assert gate_ok["status"] == "UNLOCKED"
    assert len(gate_ok["reasons"]) == 0


def test_ranking_metrics_precision_and_recall_at_k():
    y_true = np.array([1, 1, 0, 0, 1, 0])
    y_score = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.1])
    # Top 2 items: [1, 1] -> precision@2 = 1.0, recall@2 = 2/3
    assert compute_precision_at_k(y_true, y_score, k=2) == 1.0
    assert pytest.approx(compute_recall_at_k(y_true, y_score, k=2), 0.01) == 2 / 3

    # Top 3 items: [1, 1, 0] -> precision@3 = 2/3
    assert pytest.approx(compute_precision_at_k(y_true, y_score, k=3), 0.01) == 2 / 3


def test_bootstrap_ci_coverage():
    y_true = np.array([1] * 10 + [0] * 40)
    y_score = np.array([0.9] * 10 + [0.1] * 40)
    pt, lo, hi = bootstrap_ci(
        y_true, y_score, lambda yt, ys: compute_precision_at_k(yt, ys, k=10), n_bootstrap=200
    )
    assert pt == 1.0
    assert 0.4 <= lo <= 1.0
    assert hi == 1.0


def test_grouped_cv_folds_zero_company_leakage():
    # Synthetic records with multiple jobs per company
    records = [
        {"job_id": f"j_{i}", "company": f"Company_{i % 5}", "label": "good_fit" if i % 4 == 0 else "bad_fit"}
        for i in range(25)
    ]
    folds = build_grouped_folds(records, n_splits=5, random_state=42)
    assert len(folds) == 5

    for train_recs, test_recs, _ in folds:
        train_comps = {normalize_company(r["company"]) for r in train_recs}
        test_comps = {normalize_company(r["company"]) for r in test_recs}
        assert len(train_comps.intersection(test_comps)) == 0


def test_model_registry_and_scoring():
    models = list_registered_models()
    assert "title_keyword_rule" in models
    assert "char_ngram_title_clf" in models
    assert "match_scorer" in models

    rule_scorer = get_model("title_keyword_rule")
    jobs = [
        {"title": "Software Engineer Backend Python", "company": "TechInc"},
        {"title": "Senior Sales Recruiter", "company": "StaffingCo"},
    ]
    scores = rule_scorer.score_jobs(jobs)
    assert len(scores) == 2
    # Tech role should score substantially higher than sales recruiter
    assert scores[0] > scores[1]
