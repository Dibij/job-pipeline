"""Unit tests for app.py feedback loop dashboard."""
import json
import pytest
from unittest.mock import MagicMock, patch
from app import AppServerHandler


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
