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



def test_wwr_transformation():
    """Verify WWR RSS item transforms into NormalizedJob accurately."""
    from src.models.transformers import transform_weworkremotely

    raw_payload = {
        "title": "Tailscale: Brand Designer",
        "region": "Anywhere in the World",
        "category": "Sales and Marketing",
        "type": "Full-Time",
        "pubDate": "Wed, 14 Oct 2026 07:31:00 +0000",
        "guid": "https://weworkremotely.com/remote-jobs/tailscale-brand-designer-1",
        "link": "https://weworkremotely.com/remote-jobs/tailscale-brand-designer-1",
        "description": "<p>Design brand stuff.</p>",
    }

    job = transform_weworkremotely(raw_payload)
    assert job.source == "weworkremotely"
    assert job.title == "Brand Designer"
    assert job.company_name == "Tailscale"
    assert job.is_remote is True
    assert job.remote_restriction == "Anywhere in the World"
    assert job.location_raw == "Anywhere in the World"
    assert job.description_text == "Design brand stuff."
    assert job.posted_at is not None
    assert job.posted_at.year == 2026
    assert job.fingerprint_hash is not None


def test_wwr_transformation_usa_only():
    """Verify WWR job with 'USA Only' region sets restriction correctly."""
    from src.models.transformers import transform_weworkremotely

    raw_payload = {
        "title": "Acme: Backend Engineer",
        "region": "USA Only",
        "guid": "https://weworkremotely.com/remote-jobs/acme-backend",
        "description": "<p>US-based role.</p>",
    }

    job = transform_weworkremotely(raw_payload)
    assert job.remote_restriction == "USA Only"
    assert job.company_name == "Acme"
    assert job.title == "Backend Engineer"

def test_remoteok_transformation():
    """Verify Remote OK raw item transforms into NormalizedJob accurately."""
    from src.models.transformers import transform_remoteok

    raw_payload = {
        "id": "1137510",
        "slug": "remote-principal-pm-thyme-care-1137510",
        "position": "Principal Product Manager",
        "company": "Thyme Care",
        "company_logo": "https://example.com/logo.png",
        "location": "Remote",
        "date": "2026-10-13T08:00:11+00:00",
        "tags": ["product manager", "senior"],
        "description": "<p>Build great products.</p>",
        "apply_url": "https://remoteok.com/apply/1137510",
        "url": "https://remoteok.com/jobs/1137510",
    }

    job = transform_remoteok(raw_payload)
    assert job.source == "remoteok"
    assert job.external_id == "1137510"
    assert job.title == "Principal Product Manager"
    assert job.company_name == "Thyme Care"
    assert job.is_remote is True
    assert job.remote_restriction == "unspecified"
    assert job.description_text == "Build great products."
    assert "product manager" in job.tags
    assert job.fingerprint_hash is not None


def test_remoteok_transformation_worldwide():
    """Verify Remote OK job with 'Worldwide' location sets restriction correctly."""
    from src.models.transformers import transform_remoteok

    raw_payload = {
        "id": "999",
        "position": "DevOps Engineer",
        "company": "GlobalCo",
        "location": "Worldwide",
        "description": "<p>Deploy all the things.</p>",
    }

    job = transform_remoteok(raw_payload)
    assert job.remote_restriction == "Worldwide"
    assert job.location_raw == "Worldwide"

def test_jobicy_transformation():
    """Verify Jobicy raw item transforms into NormalizedJob accurately."""
    from src.models.transformers import transform_jobicy

    raw_payload = {
        "id": 153225,
        "url": "https://jobicy.com/jobs/153225-senior-sales-engineer-2",
        "jobSlug": "153225-senior-sales-engineer-2",
        "jobTitle": "Senior Sales Engineer",
        "companyName": "RevenueCat",
        "companyLogo": "https://example.com/logo.jpg",
        "jobIndustry": ["Sales"],
        "jobType": ["Full-Time"],
        "jobGeo": "Canada,  Europe,  USA",
        "jobLevel": "Senior",
        "pubDate": "2026-10-14T03:29:54+00:00",
        "jobDescription": "<p>Sell great products.</p>",
    }

    job = transform_jobicy(raw_payload)
    assert job.source == "jobicy"
    assert job.external_id == "153225"
    assert job.title == "Senior Sales Engineer"
    assert job.company_name == "RevenueCat"
    assert job.is_remote is True
    assert job.remote_restriction == "Canada,  Europe,  USA"
    assert job.description_text == "Sell great products."
    assert "Sales" in job.tags
    assert job.posted_at is not None
    assert job.fingerprint_hash is not None

def test_hackernews_transformation():
    """Verify Hacker News comment transforms into NormalizedJob accurately."""
    from src.models.transformers import transform_hackernews

    raw_payload = {
        "id": 49926618,
        "by": "futohq",
        "time": 1727730000,
        "text": 'FUTO | <a href="https://futo.tech/" rel="nofollow">https://futo.tech/</a> | Austin, TX | REMOTE(Worldwide) or ONSITE | Full Time<p>FUTO is an organization dedicated to open software.</p>',
    }

    job = transform_hackernews(raw_payload)
    assert job.source == "hackernews"
    assert job.external_id == "49926618"
    assert job.company_name == "FUTO"
    assert job.is_remote is True
    assert job.remote_restriction == "Worldwide"
    assert job.location_raw == "Worldwide"
    assert "FUTO is an organization" in job.description_text
    assert job.posted_at is not None
    assert job.apply_url == "https://futo.tech/"
    assert job.fingerprint_hash is not None


def test_hackernews_transformation_dash_delimiter():
    """Verify Hacker News comment with em-dash delimiters transforms accurately."""
    from src.models.transformers import transform_hackernews

    raw_payload = {
        "id": 49922584,
        "by": "mwest1066",
        "time": 1727730000,
        "text": "PrairieLearn (Remote US) \u2014 Full-Stack Software Engineer \u2014 TypeScript / Postgres / React / AI<p>PrairieLearn is building edtech tools.</p>",
    }

    job = transform_hackernews(raw_payload)
    assert job.company_name == "PrairieLearn"
    assert job.title == "Full-Stack Software Engineer"
    assert job.is_remote is True
    assert job.remote_restriction == "Remote US"


def test_hackernews_no_pipes_5000_chars():
    """Verify a 5,000-character HN comment without pipes gets fallback title and full text in description."""
    from src.models.transformers import transform_hackernews

    huge_text = "We are an innovative company building autonomous agents for healthcare. " * 80
    raw_payload = {
        "id": 49999999,
        "by": "builder",
        "time": 1727730000,
        "text": huge_text,
    }

    job = transform_hackernews(raw_payload)
    assert job.title == "Hacker News Role"
    assert job.company_name == "Unknown Company"
    assert len(job.description_text) >= 5000
    assert len(job.title) <= 255
    assert len(job.company_name) <= 255


def test_hackernews_messy_header_fallback():
    """Verify HN post with dash intro but no pipes gets clean company and fallback title (item 49924674 pattern)."""
    from src.models.transformers import transform_hackernews

    raw_payload = {
        "id": 49924674,
        "by": "ddg_recruiter",
        "time": 1727730000,
        "text": "DuckDuckGo - we are looking for candidates that are excited to join us on a mission. Senior Web Security Engineer. <a href='https://duckduckgo.com/jobs'>Link</a>",
    }

    job = transform_hackernews(raw_payload)
    assert job.company_name == "DuckDuckGo"
    assert job.title == "Hacker News Role"
    assert len(job.company_name) <= 255
    assert "DuckDuckGo" in job.description_text


def test_field_truncation_255_chars(caplog):
    """Verify NormalizedJob model truncates fields > 255 chars and logs a warning with job id."""
    import logging

    with caplog.at_level(logging.WARNING):
        job = NormalizedJob(
            source="test",
            external_id="ext-999",
            title="A" * 300,
            company_name="B" * 280,
            location_raw="C" * 260,
            remote_restriction="D" * 270,
            description_text="Valid description",
            apply_url="https://example.com/apply",
        )

    assert len(job.title) == 255
    assert len(job.company_name) == 255
    assert len(job.location_raw) == 255
    assert len(job.remote_restriction) == 255
    assert "Truncating title for job id 'ext-999'" in caplog.text
    assert "Truncating company_name for job id 'ext-999'" in caplog.text

