"""Tests for CV matching and ranking engine."""
import pytest
from src.matching.scorer import MatchScorer


def test_scorer_disqualifies_german():
    """Verify German jobs receive heavy penalties resulting in 0 match score."""
    scorer = MatchScorer()
    job = {
        "title": "Softwareentwickler (m/w/d)",
        "description_text": "Wir suchen einen Entwickler f\u00fcr Python und Django.",
        "detected_language": "german",
        "experience_level": "junior",
        "is_unpaid": False,
        "is_remote": True,
        "nepal_accessible": True,
        "tags": ["python", "django"],
    }
    score, matched, missing, breakdown = scorer.score_job(job)
    assert score == 0.0
    assert "GERMAN" in breakdown["flags"]


def test_scorer_disqualifies_senior():
    """Verify senior roles receive heavy penalties."""
    scorer = MatchScorer()
    job = {
        "title": "Senior Staff Architect (10+ years)",
        "description_text": "Lead engineering teams.",
        "detected_language": "english",
        "experience_level": "senior",
        "is_unpaid": False,
        "is_remote": True,
        "nepal_accessible": True,
        "tags": ["python", "react"],
    }
    score, matched, missing, breakdown = scorer.score_job(job)
    assert score < 20.0
    assert "SENIOR" in breakdown["flags"]


def test_scorer_disqualifies_unpaid():
    """Verify unpaid volunteer listings receive score 0."""
    scorer = MatchScorer()
    job = {
        "title": "Unpaid Web Development Volunteer",
        "description_text": "Volunteer position with no salary.",
        "detected_language": "english",
        "experience_level": "junior",
        "is_unpaid": True,
        "is_remote": True,
        "nepal_accessible": True,
        "tags": ["python"],
    }
    score, matched, missing, breakdown = scorer.score_job(job)
    assert score == 0.0
    assert "UNPAID" in breakdown["flags"]


def test_scorer_boosts_junior_remote_tech_match():
    """Verify remote junior developer matching candidate stack receives high score."""
    scorer = MatchScorer()
    job = {
        "title": "Junior Full Stack Developer",
        "description_text": "Entry-level position building apps with Python, Django, React, and TypeScript.",
        "detected_language": "english",
        "experience_level": "junior",
        "is_unpaid": False,
        "is_remote": True,
        "nepal_accessible": True,
        "tags": ["python", "django", "react", "typescript"],
    }
    score, matched, missing, breakdown = scorer.score_job(job)
    assert score >= 60.0
    assert "python" in matched
    assert "django" in matched
    assert "react" in matched
    assert len(breakdown["flags"]) == 0
