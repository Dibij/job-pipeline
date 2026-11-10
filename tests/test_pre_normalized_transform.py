"""Tests for python_org / reddit round-trip normalisation."""

from datetime import datetime, timezone

from src.models.transformers import transform_pre_normalized, transform_raw_listing


def _python_org_payload():
    return {
        "source": "python_org",
        "external_id": "https://www.python.org/jobs/1234/",
        "title": "Senior Python Developer",
        "company_name": "",
        "location_raw": "Remote",
        "is_remote": True,
        "description_text": "Build Python services. Budget: $5,000 fixed price.",
        "apply_url": "https://www.python.org/jobs/1234/",
        "posted_at": "2026-01-01T10:00:00+00:00",
        "opportunity_type": "job",
        "compensation_type": "fixed_price",
        "budget_min": 5000.0,
        "budget_max": 5000.0,
        "budget_currency": "USD",
        "tags": ["python"],
        "last_seen_at": "2026-01-02T10:00:00+00:00",
    }


def test_python_org_payload_round_trips():
    job = transform_pre_normalized("python_org", _python_org_payload())
    assert job is not None
    assert job.source == "python_org"
    assert job.opportunity_type == "job"
    assert job.budget_min == 5000
    assert job.posted_at == datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    assert job.fingerprint_hash


def test_reddit_payload_round_trips():
    payload = _python_org_payload()
    payload.update(
        source="reddit",
        external_id="abc",
        title="[HIRING] Django dev",
        opportunity_type="freelance",
        compensation_type="hourly",
        budget_min=60.0,
        budget_max=80.0,
    )
    job = transform_pre_normalized("reddit", payload)
    assert job is not None
    assert job.opportunity_type == "freelance"
    assert job.budget_min == 60


def test_blank_title_returns_none():
    assert transform_pre_normalized("reddit", {"title": ""}) is None
    assert transform_pre_normalized("reddit", {}) is None


def test_dispatcher_routes_new_sources():
    assert transform_raw_listing("python_org", _python_org_payload()) is not None
    reddit_payload = _python_org_payload()
    reddit_payload.update(source="reddit", external_id="xyz")
    assert transform_raw_listing("reddit", reddit_payload) is not None


def test_invalid_datetime_becomes_none():
    payload = _python_org_payload()
    payload["posted_at"] = "not-a-date"
    job = transform_pre_normalized("python_org", payload)
    assert job is not None
    assert job.posted_at is None


def test_fingerprint_recomputed_not_reused():
    payload = _python_org_payload()
    payload["fingerprint_hash"] = "stale-hash"
    job = transform_pre_normalized("python_org", payload)
    assert job.fingerprint_hash != "stale-hash"
