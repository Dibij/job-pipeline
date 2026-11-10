"""Tests for the outreach draft generator."""

from src.opportunities.outreach import (
    OutreachDraft,
    generate_outreach_draft,
    generate_outreach_for_listing,
)


def _freelance(**overrides):
    data = {
        "title": "Build a RAG system",
        "description_text": "Build a Django + Postgres RAG service with tests.",
        "opportunity_type": "freelance",
        "matched_skills": ["python", "django", "rag"],
        "scam_risk_score": 0.1,
        "confidence_score": 0.9,
    }
    data.update(overrides)
    return data


def test_returns_outreach_draft():
    draft = generate_outreach_draft(_freelance())
    assert isinstance(draft, OutreachDraft)
    assert draft.title == "Build a RAG system"
    assert "freelance" in draft.proposal


def test_mentions_matched_skills():
    draft = generate_outreach_draft(_freelance())
    assert "python" in draft.proposal
    assert "django" in draft.proposal


def test_high_risk_adds_warning():
    draft = generate_outreach_draft(_freelance(scam_risk_score=0.95))
    assert "high" in draft.proposal.lower()


def test_low_risk_has_no_warning():
    draft = generate_outreach_draft(_freelance(scam_risk_score=0.05))
    assert "scored high" not in draft.proposal.lower()


def test_job_type_uses_job_wording():
    draft = generate_outreach_draft(_freelance(opportunity_type="job"))
    assert "job opening" in draft.proposal.lower()


def test_clarification_questions_for_freelance():
    draft = generate_outreach_draft(_freelance())
    assert draft.clarification_questions
    assert any("payment" in q.lower() for q in draft.clarification_questions)


def test_technical_angle_present_with_skills():
    draft = generate_outreach_draft(_freelance())
    assert draft.technical_angle
    assert "python" in draft.technical_angle


def test_technical_angle_absent_without_skills():
    draft = generate_outreach_draft(_freelance(matched_skills=[]))
    assert draft.technical_angle is None


def test_dict_helper_is_serialisable():
    result = generate_outreach_for_listing(_freelance())
    assert set(result) >= {
        "title", "proposal", "clarification_questions", "technical_angle",
    }
    assert isinstance(result["clarification_questions"], list)


def test_handles_missing_fields():
    draft = generate_outreach_draft({})
    assert draft.title == "Opportunity"
    assert draft.proposal
