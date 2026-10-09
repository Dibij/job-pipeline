"""Tests for the job enrichment engine."""
import pytest
from src.enrichment.enricher import JobEnricher


def test_detect_seniority_title():
    """Verify seniority detected accurately from job titles."""
    assert JobEnricher.detect_seniority("Junior Python Developer", "") == "junior"
    assert JobEnricher.detect_seniority("Software Engineering Intern", "") == "intern"
    assert JobEnricher.detect_seniority("Senior Full Stack Engineer", "") == "senior"
    assert JobEnricher.detect_seniority("Lead Architect", "") == "senior"
    assert JobEnricher.detect_seniority("Backend Developer", "") == "unspecified"


def test_detect_seniority_title_wins_over_body():
    """Title signal must override any body signal."""
    # Title says Junior — even if body mentions 5+ years (e.g. copy-paste JD mistake)
    assert JobEnricher.detect_seniority("Junior Developer", "5+ years of Python required.") == "junior"
    # Title says Senior — even if body says no experience required
    assert JobEnricher.detect_seniority("Senior Engineer", "no experience required.") == "senior"


def test_detect_seniority_false_positives_5b1_audit():
    """Regression tests for false positives found in the 5b.1 seniority audit.

    Previously, any JD body mentioning '5+ years' was labeled 'senior', which
    caused many genuinely junior/unspecified roles to be filtered out incorrectly.
    """
    generic_desc_5yr = "We are looking for someone with 5+ years of experience preferred."
    assert JobEnricher.detect_seniority("Backend Developer", generic_desc_5yr) == "unspecified"

    generic_desc_6yr = "Ideally 6+ years with Python, though we consider all levels."
    assert JobEnricher.detect_seniority("Python Engineer", generic_desc_6yr) == "unspecified"

    # The word 'seniority' itself should NOT trigger senior
    seniority_word = "Seniority level: not specified. We welcome applicants of all levels."
    assert JobEnricher.detect_seniority("Software Developer", seniority_word) == "unspecified"


def test_detect_seniority_body_strong_senior():
    """Body-only senior: must have explicit must-have language AND 7+ years."""
    strong = "You must have a minimum of 8+ years of backend engineering experience."
    assert JobEnricher.detect_seniority("Backend Engineer", strong) == "senior"

    strong2 = "10+ years required in distributed systems."
    assert JobEnricher.detect_seniority("Systems Engineer", strong2) == "senior"


def test_detect_seniority_body_mid():
    """Body mid-level signals."""
    mid_desc = "We're looking for someone with 3+ years of React experience."
    assert JobEnricher.detect_seniority("Frontend Developer", mid_desc) == "mid"

    mid_desc2 = "2-4 years of experience preferred."
    assert JobEnricher.detect_seniority("Developer", mid_desc2) == "mid"



def test_detect_german():
    """Verify German job detection based on keywords and (m/w/d) tags."""
    assert JobEnricher.detect_language("Softwareentwickler (m/w/d)", "Wir suchen einen Entwickler.") == "german"
    assert JobEnricher.detect_language("Python Engineer", "Looking for a software engineer.") == "english"


def test_detect_unpaid():
    """Verify unpaid jobs are detected."""
    assert JobEnricher.detect_unpaid("Volunteer Web Developer", "Unpaid internship.") is True
    assert JobEnricher.detect_unpaid("Junior Developer", "Competitive salary.") is False


def test_detect_nepal_accessible():
    """Verify geo-restriction checks."""
    # Worldwide remote
    assert JobEnricher.detect_nepal_accessible(True, "Remote", "Worldwide") is True
    # US only restriction
    assert JobEnricher.detect_nepal_accessible(True, "Remote", "USA only") is False
    # Onsite abroad
    assert JobEnricher.detect_nepal_accessible(False, "Berlin, Germany", "") is False
    # Onsite in Nepal
    assert JobEnricher.detect_nepal_accessible(False, "Kathmandu, Nepal", "") is True


def test_extract_tech_tags():
    """Verify tech stack keywords are extracted."""
    tags = JobEnricher.extract_tech_tags(
        "Fullstack Developer (Python/React)",
        "Building web applications with Django and Next.js and PostgreSQL.",
        existing_tags=["Engineering"]
    )
    assert "python" in tags
    assert "react" in tags
    assert "next.js" in tags
    assert "postgresql" in tags
