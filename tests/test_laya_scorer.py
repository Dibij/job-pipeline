"""Unit tests for src/matching/laya_scorer.py — Tasks 7.4 / 7.5 / gate-cleanup."""
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
    scorer.gates_warn_only = scorer.config.get("gates_warn_only", True)
    scorer.gate_disqualify_threshold = scorer.config.get("gate_disqualify_threshold", 0.90)
    scorer.gate_warn_threshold = scorer.config.get("gate_warn_threshold", 0.85)
    scorer.use_confidence_flag = scorer.config.get("use_confidence_flag", False)
    scorer.agent = None
    scorer.formatted_questions = scorer._build_laya_questions()
    return scorer


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def test_scorer_loads_yaml_config(mock_scorer):
    assert "score_questions" in mock_scorer.config
    assert "gate_questions" in mock_scorer.config
    assert "penalty_questions" in mock_scorer.config
    assert "choice_questions" in mock_scorer.config
    assert "skills_match" in mock_scorer.formatted_questions
    assert "is_real_job" in mock_scorer.formatted_questions
    # Gate-cleanup: requires_other_language must not appear
    assert "requires_other_language" not in mock_scorer.config.get("gate_questions", {})
    assert mock_scorer.gates_warn_only is True
    assert mock_scorer.gate_disqualify_threshold == 0.90
    assert mock_scorer.gate_warn_threshold == 0.85
    # Task 7.5: use_confidence_flag present and defaults to False
    assert mock_scorer.use_confidence_flag is False


# ---------------------------------------------------------------------------
# Gate warn-only mode (Task 7.4b)
# ---------------------------------------------------------------------------

def test_scorer_warn_only_mode_does_not_disqualify(mock_scorer):
    """When gates_warn_only=True, even bad gates only generate warnings without disqualifying."""
    mock_scorer.gates_warn_only = True
    values = {
        "is_real_job": {"noul": 0.95, "answer_confidence": 0.95},
        "remote_from_nepal": {"noul": 0.05, "answer_confidence": 0.85},  # p_bad=0.95 >= 0.85 -> warning
        "needs_work_authorization": {"noul": 0.95, "answer_confidence": 0.95},  # p_bad=0.95 >= 0.85 -> warning
        "unpaid_or_commission_only": {"noul": 0.05, "answer_confidence": 0.95},
        "skills_match": {"score": 3.8, "answer_confidence": 0.8},
        "seniority_fit": {"score": 3.5, "answer_confidence": 0.8},
        "domain_fit": {"score": 4.0, "answer_confidence": 0.9},
        "growth_fit": {"score": 3.0, "answer_confidence": 0.7},
        "fixed_overlap_hours": {"noul": 0.1, "answer_confidence": 0.9},
        "needs_multi_years": {"noul": 0.1, "answer_confidence": 0.9},
        "role_type": {"choice": "backend", "answer_confidence": 0.85}
    }
    mock_res = MockDecisionResult(values, {k: 0.85 for k in values}, {k: {} for k in values})
    result = mock_scorer._evaluate_decision("test-id", "Backend Dev", "Acme", mock_res)

    assert result.is_passed is True
    assert result.disqualification_reason is None
    assert result.final_score > 0.0
    # REGION_LOCKED should appear since p_bad=0.95 >= gate_warn_threshold=0.85
    assert any("REGION_LOCKED" in w for w in result.gate_warnings)


def test_scorer_disqualifies_when_warn_only_false_and_above_threshold(mock_scorer):
    """When gates_warn_only=False and p_bad >= 0.90, job is DISQUALIFIED."""
    mock_scorer.gates_warn_only = False
    values = {
        "is_real_job": {"noul": 0.95, "answer_confidence": 0.95},
        "remote_from_nepal": {"noul": 0.85, "answer_confidence": 0.85},
        "needs_work_authorization": {"noul": 0.92, "answer_confidence": 0.92},  # p_bad=0.92 >= 0.90
        "unpaid_or_commission_only": {"noul": 0.05, "answer_confidence": 0.95},
        "skills_match": {"score": 3.8, "answer_confidence": 0.8},
        "seniority_fit": {"score": 3.5, "answer_confidence": 0.8},
        "domain_fit": {"score": 4.0, "answer_confidence": 0.9},
        "growth_fit": {"score": 3.0, "answer_confidence": 0.7},
        "fixed_overlap_hours": {"noul": 0.1, "answer_confidence": 0.9},
        "needs_multi_years": {"noul": 0.1, "answer_confidence": 0.9},
        "role_type": {"choice": "backend", "answer_confidence": 0.85}
    }
    mock_res = MockDecisionResult(values, {k: 0.85 for k in values}, {k: {} for k in values})
    result = mock_scorer._evaluate_decision("test-id", "Backend Dev", "Acme", mock_res)

    assert result.is_passed is False
    assert result.disqualification_reason == "REGION_LOCKED"
    assert result.final_score == 0.0


# ---------------------------------------------------------------------------
# Gate polarity pin-down (Task 7.4b, updated for gate-cleanup)
# ---------------------------------------------------------------------------

def test_gate_polarity_pin_down(mock_scorer):
    """Verifies polarity direction for both bad_answer=True and bad_answer=False gates.
    requires_other_language is gone from config; only the 4 remaining gates are tested."""
    mock_scorer.gates_warn_only = False

    base_values = {
        "is_real_job": {"noul": 0.95},
        "remote_from_nepal": {"noul": 0.95},
        "needs_work_authorization": {"noul": 0.05},
        "unpaid_or_commission_only": {"noul": 0.05},
        "skills_match": {"score": 3.0},
        "seniority_fit": {"score": 3.0},
        "domain_fit": {"score": 3.0},
        "growth_fit": {"score": 3.0},
        "fixed_overlap_hours": {"noul": 0.05},
        "needs_multi_years": {"noul": 0.05},
        "role_type": {"choice": "backend"}
    }
    high_conf = {k: 0.9 for k in base_values}

    # 1. Test bad_answer=True: unpaid_or_commission_only with high noul (0.95) -> bad!
    val2 = dict(base_values, unpaid_or_commission_only={"noul": 0.95})
    res2 = mock_scorer._evaluate_decision("id2", "Dev", "Acme", MockDecisionResult(val2, {k: 0.9 for k in val2}, {}))
    assert res2.is_passed is False
    assert res2.disqualification_reason == "UNPAID"

    # 2. Test bad_answer=True: needs_work_authorization with high noul (0.95) -> bad!
    val_wa = dict(base_values, needs_work_authorization={"noul": 0.95})
    res_wa = mock_scorer._evaluate_decision("id_wa", "Dev", "Acme", MockDecisionResult(val_wa, {k: 0.9 for k in val_wa}, {}))
    assert res_wa.is_passed is False
    assert res_wa.disqualification_reason == "REGION_LOCKED"

    # 3. Test bad_answer=False: is_real_job with low noul (0.05) -> bad!
    val3 = dict(base_values, is_real_job={"noul": 0.05})
    res3 = mock_scorer._evaluate_decision("id3", "Dev", "Acme", MockDecisionResult(val3, {k: 0.9 for k in val3}, {}))
    assert res3.is_passed is False
    assert res3.disqualification_reason == "NOT_REAL_JOB"

    # 4. Test bad_answer=False: remote_from_nepal with low noul (0.05) -> bad!
    val4 = dict(base_values, remote_from_nepal={"noul": 0.05})
    res4 = mock_scorer._evaluate_decision("id4", "Dev", "Acme", MockDecisionResult(val4, {k: 0.9 for k in val4}, {}))
    assert res4.is_passed is False
    assert res4.disqualification_reason == "NOT_ACCESSIBLE"

    # 5. Threshold boundary check: p_bad = 0.85 (>= warn but < disqualify=0.90) -> warning only
    val5 = dict(base_values, needs_work_authorization={"noul": 0.85})
    res5 = mock_scorer._evaluate_decision("id5", "Dev", "Acme", MockDecisionResult(val5, {k: 0.9 for k in val5}, {}))
    assert res5.is_passed is True
    assert res5.disqualification_reason is None
    assert any("REGION_LOCKED" in w for w in res5.gate_warnings)

    # 6. Below warn threshold: p_bad = 0.70 -> no warning, passes cleanly
    val6 = dict(base_values, needs_work_authorization={"noul": 0.70})
    res6 = mock_scorer._evaluate_decision("id6", "Dev", "Acme", MockDecisionResult(val6, {k: 0.9 for k in val6}, {}))
    assert res6.is_passed is True
    assert res6.disqualification_reason is None
    assert not any("REGION_LOCKED" in w for w in res6.gate_warnings)


# ---------------------------------------------------------------------------
# Score calculation tests
# ---------------------------------------------------------------------------

def test_scorer_calculates_high_score_and_bonus(mock_scorer):
    # Perfect junior backend role (no requires_other_language key)
    values = {
        "is_real_job": {"noul": 0.99, "answer_confidence": 0.99},
        "remote_from_nepal": {"noul": 0.90, "answer_confidence": 0.90},
        "needs_work_authorization": {"noul": 0.02, "answer_confidence": 0.98},
        "unpaid_or_commission_only": {"noul": 0.01, "answer_confidence": 0.99},
        "skills_match": {"score": 4.0, "answer_confidence": 0.95},     # 100% * 0.35 = 35
        "seniority_fit": {"score": 4.0, "answer_confidence": 0.95},    # 100% * 0.30 = 30
        "domain_fit": {"score": 4.0, "answer_confidence": 0.95},       # 100% * 0.20 = 20
        "growth_fit": {"score": 4.0, "answer_confidence": 0.95},       # 100% * 0.15 = 15
        "fixed_overlap_hours": {"noul": 0.05, "answer_confidence": 0.95},  # 0 penalty
        "needs_multi_years": {"noul": 0.05, "answer_confidence": 0.95},    # 0 penalty
        "role_type": {"choice": "web_fullstack", "answer_confidence": 0.9}  # +5 bonus
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
        "skills_match": {"score": 3.0, "answer_confidence": 0.8},   # 75%
        "seniority_fit": {"score": 2.0, "answer_confidence": 0.8},  # 50%
        "domain_fit": {"score": 3.0, "answer_confidence": 0.8},     # 75%
        "growth_fit": {"score": 3.0, "answer_confidence": 0.8},     # 75%
        "fixed_overlap_hours": {"noul": 0.85, "answer_confidence": 0.85},  # -15 penalty
        "needs_multi_years": {"noul": 0.90, "answer_confidence": 0.90},    # -20 penalty
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
        "skills_match": {"score": 2.5, "answer_confidence": 0.55},  # low confidence!
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


# ---------------------------------------------------------------------------
# Task 7.5: use_confidence_flag
# ---------------------------------------------------------------------------

def test_use_confidence_flag_false_does_not_block_scoring(mock_scorer):
    """When use_confidence_flag=False (default), needs_review is computed but
    does NOT affect the final score or pass/fail status."""
    assert mock_scorer.use_confidence_flag is False
    values = {
        "is_real_job": {"noul": 0.90},
        "remote_from_nepal": {"noul": 0.80},
        "needs_work_authorization": {"noul": 0.10},
        "unpaid_or_commission_only": {"noul": 0.10},
        "skills_match": {"score": 3.0},
        "seniority_fit": {"score": 3.0},
        "domain_fit": {"score": 3.0},
        "growth_fit": {"score": 3.0},
        "fixed_overlap_hours": {"noul": 0.05},
        "needs_multi_years": {"noul": 0.05},
        "role_type": {"choice": "backend"}
    }
    # All confidences below threshold -> would set needs_review=True
    conf = {k: 0.50 for k in values}
    mock_res = MockDecisionResult(values, conf, {})
    result = mock_scorer._evaluate_decision("test-7.5", "Dev", "Acme", mock_res)

    assert result.needs_review is True        # flag is computed
    assert result.is_passed is True           # not blocked (use_confidence_flag=False)
    assert result.final_score > 0.0           # score is still computed
