"""Tests for scripts/score_jobs.py — Task 7.6.

Focuses on:
- config version computation (deterministic, changes on file change)
- resumability: already-scored jobs are skipped (mocked DB)
- dry-run: no DB writes, only prints eligible jobs
- upsert_score serialises LayaScoreResult correctly to JSONB-safe dicts
"""
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# Import functions under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.score_jobs import compute_config_version, fetch_already_scored, upsert_score


# ---------------------------------------------------------------------------
# compute_config_version
# ---------------------------------------------------------------------------

def test_config_version_is_deterministic(tmp_path):
    yaml_file = tmp_path / "laya_questions.yaml"
    yaml_file.write_text("key: value\n", encoding="utf-8")

    v1 = compute_config_version(yaml_file)
    v2 = compute_config_version(yaml_file)

    assert v1 == v2
    assert len(v1) == 12  # short hash


def test_config_version_changes_on_content_change(tmp_path):
    yaml_file = tmp_path / "laya_questions.yaml"
    yaml_file.write_text("key: value\n", encoding="utf-8")
    v1 = compute_config_version(yaml_file)

    yaml_file.write_text("key: changed_value\n", encoding="utf-8")
    v2 = compute_config_version(yaml_file)

    assert v1 != v2


def test_config_version_matches_sha256(tmp_path):
    content = b"score_questions:\n  skills_match:\n    weight: 0.35\n"
    yaml_file = tmp_path / "laya_questions.yaml"
    yaml_file.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()[:12]
    assert compute_config_version(yaml_file) == expected


# ---------------------------------------------------------------------------
# fetch_already_scored
# ---------------------------------------------------------------------------

def test_fetch_already_scored_returns_set_of_ids():
    mock_rows = [
        {"job_id": "uuid-1"},
        {"job_id": "uuid-2"},
    ]
    with patch("scripts.score_jobs.execute_query", return_value=mock_rows) as mock_q:
        result = fetch_already_scored("convaiinnovations/laya", "abc123def456")

    assert result == {"uuid-1", "uuid-2"}
    mock_q.assert_called_once()


def test_fetch_already_scored_empty_db():
    with patch("scripts.score_jobs.execute_query", return_value=None):
        result = fetch_already_scored("convaiinnovations/laya", "abc123def456")
    assert result == set()


def test_fetch_already_scored_passes_correct_params():
    with patch("scripts.score_jobs.execute_query", return_value=[]) as mock_q:
        fetch_already_scored("my/checkpoint", "ver123")
    args = mock_q.call_args
    # Second positional arg is the params tuple
    assert args[0][1] == ("my/checkpoint", "ver123")


# ---------------------------------------------------------------------------
# upsert_score
# ---------------------------------------------------------------------------

def _make_fake_result():
    """Build a minimal LayaScoreResult-like object for serialisation testing."""
    from src.matching.laya_scorer import LayaQuestionResult, LayaScoreResult
    q1 = LayaQuestionResult(
        question_type="score",
        raw_value=3.5,
        normalized_value=87.5,
        confidence=0.82,
        answer_confidence=0.80,
        probabilities={"0": 0.1, "1": 0.9},
    )
    q2 = LayaQuestionResult(
        question_type="noul",
        raw_value=True,
        normalized_value=0.92,
        confidence=0.88,
        answer_confidence=0.88,
        probabilities={},
    )
    return LayaScoreResult(
        job_id="job-uuid-999",
        title="Test Engineer",
        company="Acme",
        final_score=72.5,
        is_passed=True,
        disqualification_reason=None,
        needs_review=False,
        role_type="backend",
        gate_warnings=[],
        questions={"skills_match": q1, "is_real_job": q2},
        tokens_used=420,
    )


def test_upsert_score_calls_execute_query_once():
    result = _make_fake_result()
    with patch("scripts.score_jobs.execute_query") as mock_q:
        upsert_score(result, "convaiinnovations/laya", "abc123def456")
    mock_q.assert_called_once()


def test_upsert_score_passes_correct_job_id():
    result = _make_fake_result()
    with patch("scripts.score_jobs.execute_query") as mock_q:
        upsert_score(result, "convaiinnovations/laya", "abc123def456")
    params = mock_q.call_args[0][1]
    assert params[0] == "job-uuid-999"   # job_id
    assert params[1] == 72.5             # final_score
    assert params[2] is True             # is_passed
    assert params[5] == "backend"        # role_type


def test_upsert_score_per_question_data_is_valid_json():
    result = _make_fake_result()
    captured = {}

    def capture_query(sql, params):
        captured["params"] = params

    with patch("scripts.score_jobs.execute_query", side_effect=capture_query):
        upsert_score(result, "convaiinnovations/laya", "abc123def456")

    per_question_json = captured["params"][7]  # per_question_data
    data = json.loads(per_question_json)
    assert "skills_match" in data
    assert data["skills_match"]["type"] == "score"
    assert data["skills_match"]["raw"] == 3.5
    assert data["is_real_job"]["type"] == "noul"
    assert data["is_real_job"]["raw"] is True   # bool preserved


def test_upsert_score_gate_warnings_serialised():
    result = _make_fake_result()
    result.gate_warnings = ["REGION_LOCKED:needs_work_authorization(p_bad=0.91)"]

    captured = {}

    def capture_query(sql, params):
        captured["params"] = params

    with patch("scripts.score_jobs.execute_query", side_effect=capture_query):
        upsert_score(result, "convaiinnovations/laya", "ver")

    gate_warnings_json = captured["params"][6]  # gate_warnings
    warnings = json.loads(gate_warnings_json)
    assert len(warnings) == 1
    assert "REGION_LOCKED" in warnings[0]
