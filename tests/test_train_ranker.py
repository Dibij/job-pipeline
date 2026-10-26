"""Unit tests for scripts/train_ranker.py."""
import pytest
from scripts.train_ranker import load_dataset, evaluate_models


def test_load_dataset():
    dataset, total_v2, total_v2_good = load_dataset()
    assert isinstance(dataset, list)
    assert total_v2 >= 0
    assert total_v2_good >= 0
    # Every row in dataset must be v2 and unexcluded
    for row in dataset:
        assert row["binary_target"] in (0, 1)
        assert "title_rule_score" in row
        assert "description_clean" in row


def test_refuse_fold_under_3_positives():
    # Synthetic dataset with only 2 positive cases across 5 folds
    mock_data = [
        {"title": f"Job {i}", "company": f"Comp {i % 5}", "binary_target": 1 if i < 2 else 0,
         "description_clean": "Clean description text", "title_rule_score": 1.0}
        for i in range(20)
    ]
    res = evaluate_models(mock_data, n_splits=5, n_seeds=1)
    assert res is None, "Should refuse to report metrics when folds have < 3 positive cases"
