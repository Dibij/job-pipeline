"""Tests for deterministic opportunity scoring (no network)."""
from src.opportunities.scoring import score_freelance, score_bounty, score_opportunity


FREELANCE_GOOD = {
    "title": "Build a Django REST API",
    "description_text": (
        "We need a developer to build a small Django REST API with PostgreSQL and Docker. "
        "Deliver a working API with tests and documentation. Budget is $800 fixed price."
    ),
    "tags": ["python", "django", "rest-api"],
    "opportunity_type": "freelance",
}


def test_freelance_good_fit():
    r = score_freelance(FREELANCE_GOOD)
    assert r.label == "good_fit"
    assert "python" in r.matched_skills or "django" in r.matched_skills


def test_freelance_insufficient_information():
    r = score_freelance({
        "title": "Help",
        "description_text": "Need help with something.",
        "tags": [],
        "opportunity_type": "freelance",
    })
    assert r.label == "insufficient_information"


def test_freelance_too_complex_team_scope():
    r = score_freelance({
        "title": "Build an enterprise platform",
        "description_text": (
            "We need a team of engineers to build a production-grade, mission-critical "
            "platform scaling to millions of users."
        ),
        "tags": ["python"],
        "opportunity_type": "freelance",
    })
    assert r.label == "too_complex"


BOUNTY_DOABLE = {
    "title": "Fix pagination bug in Django view",
    "description_text": (
        "The list view pagination is broken. Add Django tests and fix it. "
        "$300 bounty available."
    ),
    "tags": ["python", "django"],
    "opportunity_type": "bounty",
}


def test_bounty_doable():
    r = score_bounty(BOUNTY_DOABLE)
    assert r.label == "doable"


def test_bounty_unpaid_portfolio_value():
    r = score_bounty({
        "title": "Improve docs",
        "description_text": "Help improve our README and examples for new contributors.",
        "tags": [],
        "opportunity_type": "open_source",
    })
    assert r.label == "unpaid_portfolio_value"


def test_score_opportunity_dispatch():
    r = score_opportunity(FREELANCE_GOOD)
    assert r.opportunity_type == "freelance"
    r2 = score_opportunity(BOUNTY_DOABLE)
    assert r2.opportunity_type == "bounty"


def test_score_opportunity_rejects_job_type():
    import pytest
    with pytest.raises(ValueError):
        score_opportunity({"opportunity_type": "job", "title": "x", "description_text": "y"})
