"""Unit tests for app.py feedback loop dashboard."""
import json
import pytest
from unittest.mock import MagicMock, patch
from app import AppServerHandler, _opportunity_score_for


def test_app_handler_stats(monkeypatch):
    """Verify stats returns expected schema and fields."""
    handler = AppServerHandler.__new__(AppServerHandler)
    captured = []
    
    def fake_send_json(data, status=200):
        captured.append((data, status))
        
    handler._send_json = fake_send_json

    handler._handle_get_stats()
    assert len(captured) == 1
    data, status = captured[0]
    assert status == 200
    assert "last_run_display" in data
    assert "new_jobs_24h" in data
    assert "model_version" in data
    assert "v2_total" in data
    assert "v2_good_fit" in data
    assert "is_stale" in data


def test_app_post_label_validation(monkeypatch):
    """Verify validation on invalid label payload."""
    handler = AppServerHandler.__new__(AppServerHandler)
    captured = []
    
    def fake_send_json(data, status=200):
        captured.append((data, status))
        
    handler._send_json = fake_send_json

    # Mock invalid label
    body = b'{"job_id": "123", "label": "invalid"}'
    handler.headers = {"Content-Length": str(len(body))}
    import io
    handler.rfile = io.BytesIO(body)

    handler._handle_post_label()
    assert len(captured) == 1
    data, status = captured[0]
    assert status == 400
    assert "Invalid job_id or label" in data["error"]


def test_app_post_label_missing_job_returns_404(monkeypatch):
    """Stale browser tabs must get a 404, not a foreign-key 500."""
    import io
    import uuid
    from unittest.mock import patch

    handler = AppServerHandler.__new__(AppServerHandler)
    captured = []
    handler._send_json = lambda data, status=200: captured.append((data, status))

    body = json.dumps({
        "job_id": str(uuid.uuid4()),
        "label": "good_fit",
        "notes": "stale tab",
    }).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)

    with patch("app.execute_query", return_value=[]):
        handler._handle_post_label()

    assert captured[0][1] == 404
    assert "no longer exists" in captured[0][0]["error"]


def test_opportunity_score_skips_jobs():
    """Job rows must not get an opportunity score (MatchScorer handles them)."""
    assert _opportunity_score_for({"opportunity_type": "job", "title": "Dev"}) is None


def test_opportunity_score_freelance_good_fit():
    result = _opportunity_score_for({
        "opportunity_type": "freelance",
        "title": "Build a Django REST API",
        "description_text": (
            "We need a Django developer to build a REST API backed by PostgreSQL "
            "with a React dashboard, pytest tests and Docker deployment."
        ),
        "tags": ["python", "django", "react", "postgresql", "docker"],
    })
    assert result is not None
    assert result["label"] in {"good_fit", "possible_fit"}
    assert result["score"] > 0
    assert "python" in result["matched_skills"]


def test_opportunity_score_bounty_unpaid_portfolio():
    result = _opportunity_score_for({
        "opportunity_type": "open_source",
        "title": "Fix typo in docs",
        "description_text": "Small docs fix in the Python SDK. No payment, portfolio value only.",
        "tags": ["python"],
    })
    assert result is not None
    assert result["label"] == "unpaid_portfolio_value"


def test_opportunity_score_bad_input_returns_none():
    assert _opportunity_score_for({"opportunity_type": "weird_type"}) is None
