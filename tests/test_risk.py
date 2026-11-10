"""Tests for the deterministic scam risk assessment engine."""

import pytest

from src.opportunities.risk import assess_risk, quick_assess, RiskAssessment


def test_clean_listing_has_low_risk():
    """A well-described, properly compensated listing should have low risk."""
    result = assess_risk({
        "title": "Build a Django REST API",
        "description_text": (
            "We need a developer to build a small Django REST API with PostgreSQL "
            "and Docker. The API should handle user authentication, CRUD operations "
            "for resources, and include comprehensive tests and documentation. "
            "Budget is $2,000 fixed price. We have a clear scope and deliverables."
        ),
        "compensation_type": "fixed_price",
        "budget_min": 2000.0,
    })
    assert isinstance(result, RiskAssessment)
    assert result.scam_risk_score < 0.3, f"Expected low risk, got {result.scam_risk_score}"
    assert "vague_description" not in result.risk_flags
    assert "upfront_payment" not in result.risk_flags


def test_upfront_payment_flag():
    """Any request for upfront payment should be flagged."""
    result = assess_risk({
        "title": "Fix my app",
        "description_text": "I need someone to fix my app. Pay me $500 upfront first.",
        "compensation_type": "fixed_price",
    })
    assert "upfront_payment" in result.risk_flags
    assert result.scam_risk_score >= 0.9


def test_vague_description_flag():
    """A very short description should be flagged as vague."""
    result = assess_risk({
        "title": "Help needed",
        "description_text": "Need developer for project. Pay me.",
        "compensation_type": "fixed_price",
    })
    assert "vague_description" in result.risk_flags or "minimal_description" in result.risk_flags


def test_clean_listing_no_flags():
    """A well-described listing should have no risk flags."""
    result = assess_risk({
        "title": "Build a RAG system for company documents",
        "description_text": (
            "We need a developer to build a small Django REST API with PostgreSQL "
            "and Docker. The API should handle user authentication, CRUD operations "
            "for resources, and include comprehensive tests and documentation. "
            "Budget is $800 fixed price. We have a clear scope and deliverables."
        ),
        "compensation_type": "fixed_price",
        "budget_min": 800.0,
    })
    assert result.risk_flags == [], f"Expected no flags, got {result.risk_flags}"


def test_quick_assess_returns_dict():
    """quick_assess should return a dict with expected keys."""
    result = quick_assess(
        "Build a Django REST API",
        "We need a developer to build a small Django REST API with PostgreSQL and Docker. Budget is $2000 fixed price.",
        "fixed_price",
    )
    assert "scam_risk_score" in result
    assert "risk_flags" in result
    assert "risk_explanation" in result
    assert "score_components" in result


def test_score_components_are_deterministic():
    """Same input should produce same score components."""
    listing = {
        "title": "Build a Django REST API",
        "description_text": "We need a developer to build a small Django REST API with PostgreSQL and Docker. Budget is $2000 fixed price.",
        "compensation_type": "fixed_price",
    }
    r1 = assess_risk(listing)
    r2 = assess_risk(listing)
    assert r1.scam_risk_score == r2.scam_risk_score
    assert r1.risk_flags == r2.risk_flags


def test_unrealistic_rate_flag():
    """An unrealistically high hourly rate should be flagged."""
    result = assess_risk({
        "title": "Developer needed",
        "description_text": "Need developer for project. Pay $500/hr for beginners.",
        "compensation_type": "hourly",
    })
    assert "unrealistic_rate" in result.risk_flags


def test_score_capped_at_one():
    """Risk score should never exceed 1.0."""
    result = assess_risk({
        "title": "Fix my app",
        "description_text": "Pay me $500 upfront first. Easy money. No experience needed. Urgent hire.",
        "compensation_type": "unpaid",
        "budget_min": 0.0,
    })
    assert result.scam_risk_score <= 1.0


def test_negated_upfront_payment_not_flagged():
    """Saying 'no upfront payment' must not raise the upfront flag."""
    result = assess_risk({
        "title": "Django developer for MVP",
        "description_text": (
            "We need a Django developer to build an MVP with tests and docs. "
            "Payment is released on delivery. No upfront payment required. "
            "Budget is 1500 USD fixed price."
        ),
        "compensation_type": "fixed_price",
        "budget_min": 1500.0,
    })
    assert "upfront_payment" not in result.risk_flags, result.risk_flags
    assert result.scam_risk_score < 0.5


def test_pay_first_is_not_required_not_flagged():
    result = assess_risk({
        "title": "Backend contract",
        "description_text": (
            "Backend contract work on a Django API with PostgreSQL. "
            "Pay first is not required; we pay on milestones. Budget 900 USD."
        ),
        "compensation_type": "fixed_price",
        "budget_min": 900.0,
    })
    assert "upfront_payment" not in result.risk_flags


def test_real_upfront_still_flagged():
    result = assess_risk({
        "title": "Quick gig",
        "description_text": (
            "Easy money project. You must pay a verification fee before we share "
            "the full project details and materials."
        ),
        "compensation_type": "fixed_price",
    })
    assert "upfront_payment" in result.risk_flags


@pytest.mark.parametrize("text,expect_flag", [
    ("Easy money. Pay verification fee first, then we send details. No experience needed.", True),
    ("No upfront payment required, we pay on delivery.", False),
    ("Pay first is not required; we pay on milestones.", False),
    ("You must pay a verification fee before we share details.", True),
    ("We never ask for a security deposit.", False),
    ("No deposit needed. We pay per milestone with a clear contract and tests.", False),
])
def test_upfront_payment_negation_matrix(text, expect_flag):
    result = assess_risk({
        "title": "Contract work",
        "description_text": text + " Budget is 500 USD fixed price with tests and docs.",
        "compensation_type": "fixed_price",
        "budget_min": 500.0,
    })
    assert ("upfront_payment" in result.risk_flags) is expect_flag
