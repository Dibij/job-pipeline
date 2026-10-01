"""Tests for raw job payload transformers and NormalizedJob schema."""
import pytest
from src.models import (
    NormalizedJob,
    transform_arbeitnow,
    transform_remotive,
    transform_raw_listing,
)


def test_arbeitnow_transformation():
    """Verify Arbeitnow raw item transforms into NormalizedJob accurately."""
    raw_payload = {
        "slug": "senior-python-developer-acme-123",
        "company_name": "Acme Corp ",
        "title": " Senior Python Developer ",
        "description": "<p>We are hiring a <strong>Python</strong> dev!</p>",
        "remote": True,
        "url": "https://arbeitnow.com/view/123",
        "tags": ["Python", "Django"],
        "job_types": ["full-time"],
        "location": "Berlin / Remote",
        "created_at": 1727730000,
    }

    job = transform_arbeitnow(raw_payload)
    assert job.source == "arbeitnow"
    assert job.external_id == "senior-python-developer-acme-123"
    assert job.title == "Senior Python Developer"
    assert job.company_name == "Acme Corp"
    assert job.is_remote is True
    assert job.description_text == "We are hiring a Python dev!"
    assert job.tags == ["Python", "Django"]
    assert job.fingerprint_hash is not None
    assert len(job.fingerprint_hash) == 64


def test_remotive_transformation():
    """Verify Remotive raw item transforms into NormalizedJob accurately."""
    raw_payload = {
        "id": 999888,
        "title": "Fullstack Engineer",
        "company_name": "TechStart Inc",
        "company_logo_url": "https://remotive.com/logo.png",
        "candidate_required_location": "Worldwide",
        "job_type": "full_time",
        "publication_date": "2026-09-30T12:00:00Z",
        "url": "https://remotive.com/job/999888",
        "tags": ["React", "Node.js", "TypeScript"],
        "description": "<div>Build high quality web software.</div>",
    }

    job = transform_remotive(raw_payload)
    assert job.source == "remotive"
    assert job.external_id == "999888"
    assert job.title == "Fullstack Engineer"
    assert job.company_name == "TechStart Inc"
    assert job.is_remote is True
    assert job.remote_restriction == "Worldwide"
    assert job.description_text == "Build high quality web software."
    assert job.tags == ["React", "Node.js", "TypeScript"]
    assert job.fingerprint_hash is not None


def test_transformer_dispatcher():
    """Verify transform_raw_listing dispatches correctly or raises ValueError."""
    arb_job = transform_raw_listing("arbeitnow", {"slug": "s1", "title": "T1", "company_name": "C1"})
    assert arb_job.source == "arbeitnow"

    rem_job = transform_raw_listing("remotive", {"id": "r1", "title": "T2", "company_name": "C2"})
    assert rem_job.source == "remotive"

    with pytest.raises(ValueError, match="No transformer registered"):
        transform_raw_listing("unknown_source", {})
