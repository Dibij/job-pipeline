"""Tests for BaseExtractor.stage_normalized_jobs serialisation logic."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.extractors.base import BaseExtractor
from src.models.job import NormalizedJob


class _Dummy(BaseExtractor):
    def fetch_raw(self, max_pages: int = 1):
        return []

    def extract_external_id(self, item):
        return str(item.get("id", ""))


def _job(ext_id: str) -> NormalizedJob:
    return NormalizedJob(
        source="dummy",
        external_id=ext_id,
        title="Test opportunity",
        company_name="",
        description_text="Build something with Python.",
        apply_url="https://example.com/job",
        opportunity_type="freelance",
        budget_min=Decimal("1500.00"),
        budget_max=Decimal("2000.00"),
        budget_currency="USD",
        posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        clarification_questions=["What is the deadline?"],
    )


def test_stage_returns_zero_for_empty_list():
    ext = _Dummy("dummy", delay_seconds=0)
    assert ext.stage_normalized_jobs([]) == {
        "total": 0, "inserted": 0, "skipped": 0,
    }


def test_stage_payload_is_json_safe():
    """model_dump(mode='json') must have already converted Decimal/datetime."""
    job = _job("safe-1")
    payload = job.model_dump(mode="json")
    import json
    json.dumps(payload)  # must not raise
    assert float(payload["budget_min"]) == 1500.0
    assert isinstance(payload["posted_at"], str)


def test_blank_external_id_counted_as_skipped(monkeypatch):
    ext = _Dummy("dummy", delay_seconds=0)
    captured = {}

    class _Cur:
        def execute(self, *a, **k):
            captured["executed"] = True

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "src.extractors.base.get_connection", lambda **kw: _Conn()
    )
    job = _job("   ")
    res = ext.stage_normalized_jobs([job])
    assert res["total"] == 1
    assert res["inserted"] == 0
    assert res["skipped"] == 1
    assert "executed" not in captured
