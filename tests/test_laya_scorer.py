"""Unit tests for src/matching/laya_scorer.py — Task 7.4."""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
import pytest

from src.matching.laya_scorer import LayaScorer, LayaScoreResult


class MockDecisionResult:
    """Mock Laya decide output to test scoring logic rapidly."""
    def __init__(self, values, confidence, probabilities, usage=None):
        self.values = values
        self.confidence = confidence
        self.probabilities = probabilities
        self.usage = usage or {"input_tokens": 420}


@pytest.fixture
def mock_scorer(monkeypatch):
    """Create a LayaScorer with mocked model loading for fast formula testing."""
    monkeypatch.setattr("laya.load", lambda *args, **kwargs: None)
    scorer = LayaScorer.__new__(LayaScorer)
    scorer.config_path = Path(__file__).resolve().parent.parent / "config" / "laya_questions.yaml"
    scorer.device = "cpu"
    scorer.config = scorer._load_config()
    scorer.confidence_threshold = 0.65
    scorer.agent = None
    scorer.formatted_questions = scorer._build_laya_questions()
    return scorer


def test_scorer_loads_yaml_config(mock_scorer):
    assert "score_questions" in mock_scorer.config
    assert "gate_questions" in mock_scorer.config
    assert "penalty_questions" in mock_scorer.config
    assert "choice_questions" in mock_scorer.config
    assert "skills_match" in mock_scorer.formatted_questions
    assert "is_real_job" in mock_scorer.formatted_questions


def test_scorer_disqualifies_bad_gate(mock_scorer):
    # Simulate a job that requires country residency (bad_answer=True for needs_work_authorization)
    values = {
        "is_real_job": {"noul": 0.95, "answer_confidence": 0.95},
        "remote_from_nepal": {"noul": 0.85, "answer_confidence": 0.85},
        "needs_work_authorization": {"noul": 0.88, "answer_confidence": 0.88}, # Disqualifier!
        "unpaid_or_commission_only": {"noul": 0.05, "answer_confidence": 0.95},
        "requires_other_language": {"noul": 0.05, "answer_confidence": 0.95},
        "skills_match": {"score": 3.8, "answer_confidence": 0.8},
        "seniority_fit": {"score": 3.5, "answer_confidence": 0.8},
        "domain_fit": {"score": 4.0, "answer_confidence": 0.9},
        "growth_fit": {"score": 3.0, "answer_confidence": 0.7},
        "fixed_overlap_hours": {"noul": 0.1, "answer_confidence": 0.9},
        "needs_multi_years": {"noul": 0.1, "answer_confidence": 0.9},
        "role_type": {"choice": "backend", "answer_confidence": 0.85}
    }
    conf = {k: 0.85 for k in values}
    probs = {k: {} for k in values}

    mock_res = MockDecisionResult(values, conf, probs)
    result = mock_scorer._evaluate_decision("test-id", "Backend Dev", "Acme", mock_res)

    assert result.is_passed is False
    assert result.disqualification_reason == "REGION_LOCKED"
    assert result.final_score == 0.0


def test_scorer_calculates_high_score_and_bonus(mock_scorer):
    # Perfect junior backend role
    values = {
        "is_real_job": {"noul": 0.99, "answer_confidence": 0.99},
        "remote_from_nepal": {"noul": 0.90, "answer_confidence": 0.90},
        "needs_work_authorization": {"noul": 0.02, "answer_confidence": 0.98},
        "unpaid_or_commission_only": {"noul": 0.01, "answer_confidence": 0.99},
        "requires_other_language": {"noul": 0.01, "answer_confidence": 0.99},
        "skills_match": {"score": 4.0, "answer_confidence": 0.95},     # 100% * 0.35 = 35
        "seniority_fit": {"score": 4.0, "answer_confidence": 0.95},    # 100% * 0.30 = 30
        "domain_fit": {"score": 4.0, "answer_confidence": 0.95},       # 100% * 0.20 = 20
        "growth_fit": {"score": 4.0, "answer_confidence": 0.95},       # 100% * 0.15 = 15
        "fixed_overlap_hours": {"noul": 0.05, "answer_confidence": 0.95}, # 0 penalty
        "needs_multi_years": {"noul": 0.05, "answer_confidence": 0.95},   # 0 penalty
        "role_type": {"choice": "web_fullstack", "answer_confidence": 0.9} # +5 bonus
    }
    conf = {k: 0.95 for k in values}
    probs = {k: {} for k in values}

    mock_res = MockDecisionResult(values, conf, probs)
    result = mock_scorer._evaluate_decision("test-id-2", "Fullstack Dev", "Acme", mock_res)

    assert result.is_passed is True
    assert result.disqualification_reason is None
    # 100 base + 5 bonus clamped to 100 max
    assert result.final_score == 100.0
    assert result.needs_review is False
    assert result.role_type == "web_fullstack"


def test_scorer_applies_penalties(mock_scorer):
    # Good skills but requires fixed US timezone and 3+ years
    values = {
        "is_real_job": {"noul": 0.99, "answer_confidence": 0.99},
        "remote_from_nepal": {"noul": 0.90, "answer_confidence": 0.90},
        "needs_work_authorization": {"noul": 0.02, "answer_confidence": 0.98},
        "unpaid_or_commission_only": {"noul": 0.01, "answer_confidence": 0.99},
        "requires_other_language": {"noul": 0.01, "answer_confidence": 0.99},
        "skills_match": {"score": 3.0, "answer_confidence": 0.8}, # 75%
        "seniority_fit": {"score": 2.0, "answer_confidence": 0.8}, # 50%
        "domain_fit": {"score": 3.0, "answer_confidence": 0.8}, # 75%
        "growth_fit": {"score": 3.0, "answer_confidence": 0.8}, # 75%
        "fixed_overlap_hours": {"noul": 0.85, "answer_confidence": 0.85}, # -15 penalty
        "needs_multi_years": {"noul": 0.90, "answer_confidence": 0.90},   # -20 penalty
        "role_type": {"choice": "other", "answer_confidence": 0.8}
    }
    conf = {k: 0.85 for k in values}
    probs = {k: {} for k in values}

    mock_res = MockDecisionResult(values, conf, probs)
    result = mock_scorer._evaluate_decision("test-id-3", "Dev", "Acme", mock_res)

    assert result.is_passed is True
    # Weighted base = (75*0.35 + 50*0.30 + 75*0.20 + 75*0.15) = 26.25 + 15 + 15 + 11.25 = 67.5
    # Penalties = -15 + -20 = -35. Final = 67.5 - 35 = 32.5
    assert 32.0 <= result.final_score <= 33.0


def test_scorer_flags_low_confidence_for_review(mock_scorer):
    values = {
        "is_real_job": {"noul": 0.90, "answer_confidence": 0.50},
        "remote_from_nepal": {"noul": 0.80, "answer_confidence": 0.80},
        "needs_work_authorization": {"noul": 0.10, "answer_confidence": 0.90},
        "unpaid_or_commission_only": {"noul": 0.10, "answer_confidence": 0.90},
        "requires_other_language": {"noul": 0.10, "answer_confidence": 0.90},
        "skills_match": {"score": 2.5, "answer_confidence": 0.55}, # low confidence!
        "seniority_fit": {"score": 2.5, "answer_confidence": 0.80},
        "domain_fit": {"score": 2.5, "answer_confidence": 0.80},
        "growth_fit": {"score": 2.5, "answer_confidence": 0.80},
        "fixed_overlap_hours": {"noul": 0.10, "answer_confidence": 0.80},
        "needs_multi_years": {"noul": 0.10, "answer_confidence": 0.80},
        "role_type": {"choice": "frontend", "answer_confidence": 0.80}
    }
    # One question has confidence below 0.65 threshold
    conf = {k: 0.80 for k in values}
    conf["skills_match"] = 0.55  # Below 0.65 threshold!

    mock_res = MockDecisionResult(values, conf, {})
    result = mock_scorer._evaluate_decision("test-id-4", "Dev", "Acme", mock_res)

    assert result.needs_review is True
