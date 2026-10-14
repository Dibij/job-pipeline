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


# ---------------------------------------------------------------------------
# 6a Regression tests: remote_restriction defaults (Bug: was "Worldwide")
# ---------------------------------------------------------------------------

def test_arbeitnow_remote_restriction_is_unspecified():
    """Arbeitnow does not expose a restriction field — must store 'unspecified', never 'Worldwide'."""
    job = transform_arbeitnow({"slug": "s1", "title": "Dev", "company_name": "C", "remote": True})
    assert job.remote_restriction == "unspecified", (
        f"Expected 'unspecified', got {job.remote_restriction!r}. "
        "Defaulting to 'Worldwide' incorrectly marks all Arbeitnow jobs as Nepal-accessible."
    )


def test_arbeitnow_non_remote_restriction_is_unspecified():
    """Arbeitnow non-remote job also has no restriction field."""
    job = transform_arbeitnow({"slug": "s2", "title": "Dev", "company_name": "C", "remote": False})
    assert job.remote_restriction == "unspecified"


def test_remotive_empty_location_is_unspecified():
    """Remotive job with no candidate_required_location must store 'unspecified', never 'Worldwide'."""
    job = transform_remotive({"id": 1, "title": "Dev", "company_name": "C", "candidate_required_location": ""})
    assert job.remote_restriction == "unspecified", (
        f"Expected 'unspecified', got {job.remote_restriction!r}. "
        "Source said nothing about location — 'Worldwide' is a false assumption."
    )


def test_remotive_none_location_is_unspecified():
    """Remotive job with missing candidate_required_location key must store 'unspecified'."""
    job = transform_remotive({"id": 2, "title": "Dev", "company_name": "C"})
    assert job.remote_restriction == "unspecified"


def test_remotive_explicit_worldwide_preserved():
    """When Remotive explicitly says 'Worldwide', preserve it (this makes the job ACCESSIBLE)."""
    job = transform_remotive({"id": 3, "title": "Dev", "company_name": "C", "candidate_required_location": "Worldwide"})
    assert job.remote_restriction == "Worldwide"


def test_remotive_explicit_usa_preserved():
    """When Remotive explicitly says 'USA', preserve it (this will be BLOCKED)."""
    job = transform_remotive({"id": 4, "title": "Dev", "company_name": "C", "candidate_required_location": "USA"})
    assert job.remote_restriction == "USA"


def test_himalayas_transformation():
    """Verify Himalayas raw item transforms into NormalizedJob accurately."""
    from src.models.transformers import transform_himalayas

    raw_payload = {
        "guid": "https://himalayas.app/companies/acme/jobs/backend-engineer",
        "title": "Senior Backend Engineer",
        "companyName": "Acme Global",
        "companyLogo": "https://example.com/logo.png",
        "locationRestrictions": ["Worldwide"],
        "employmentType": "Full Time",
        "pubDate": 1727730000,
        "applicationLink": "https://example.com/apply",
        "categories": ["Engineering", "Python"],
        "seniority": ["Senior"],
        "description": "<p>We are building global distributed systems.</p>",
    }

    job = transform_himalayas(raw_payload)
    assert job.source == "himalayas"
    assert job.external_id == "https://himalayas.app/companies/acme/jobs/backend-engineer"
    assert job.title == "Senior Backend Engineer"
    assert job.company_name == "Acme Global"
    assert job.is_remote is True
    assert job.remote_restriction == "Worldwide"
    assert job.description_text == "We are building global distributed systems."
    assert "Engineering" in job.tags
    assert "Python" in job.tags
    assert "Senior" in job.tags
    assert job.fingerprint_hash is not None


