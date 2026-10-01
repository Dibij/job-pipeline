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
