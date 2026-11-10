"""Outreach assistant for generating human-reviewable proposal drafts.

Creates contextually appropriate outreach messages for freelance, bounty and
open-source opportunities. Drafts are always human-reviewable; nothing is sent
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

HIGH_RISK_THRESHOLD = 0.8
MEDIUM_RISK_THRESHOLD = 0.3


@dataclass
class OutreachDraft:
    """Contextually generated outreach draft for human review."""

    title: str
    description: str
    opportunity_type: str
    matched_skills: List[str]
    scam_risk_score: float
    proposal: str
    confidence_score: float
    clarification_questions: List[str] = field(default_factory=list)
    technical_angle: Optional[str] = None


def _clarification_questions(
    opportunity_type: str, risk_score: float
) -> List[str]:
    """Questions a human should resolve before sending the draft."""
    questions: List[str] = []
    if opportunity_type in {"freelance", "bounty", "open_source"}:
        questions.append("What is the delivery deadline and definition of done?")
        questions.append("How and when is payment released?")
    if risk_score >= MEDIUM_RISK_THRESHOLD:
        questions.append("Can you share examples of previous work and references?")
    if risk_score >= HIGH_RISK_THRESHOLD:
        questions.append("Is any upfront payment required from the contractor?")
    return questions


def _technical_angle(opportunity_type: str, matched_skills: List[str]) -> Optional[str]:
    if not matched_skills:
        return None
    lead = ", ".join(matched_skills[:3])
    return f"Propose a concrete plan using {lead}, starting with a short discovery step."


def generate_outreach_draft(listing_data: Dict[str, Any]) -> OutreachDraft:
    """Generate a human-reviewable outreach draft for an opportunity."""
    title = listing_data.get("title") or "Opportunity"
    description = listing_data.get("description_text") or ""
    opportunity_type = listing_data.get("opportunity_type") or "job"
    matched_skills = list(listing_data.get("matched_skills") or [])
    scam_risk_score = float(listing_data.get("scam_risk_score") or 0.0)
    confidence_score = float(listing_data.get("confidence_score") or 0.0)

    parts: List[str] = []

    if opportunity_type in {"freelance", "bounty", "open_source"}:
        parts.append(f"Hi, I'm interested in your {opportunity_type} opportunity.")
        if len(matched_skills) >= 2:
            parts.append(f"I have strong experience in: {', '.join(matched_skills)}.")
            parts.append("I can deliver quality work on this project.")
        else:
            parts.append(
                "I'd like to learn more about the scope before proposing an approach."
            )
        if scam_risk_score >= MEDIUM_RISK_THRESHOLD:
            parts.append(
                "Could we clarify the scope and compensation details before proceeding?"
            )
    else:
        parts.append("I'm interested in your job opening.")
        if matched_skills:
            parts.append(
                f"With my experience in {', '.join(matched_skills[:3])}, "
                "I believe I can contribute effectively."
            )
        parts.append("I'm available to start soon and can work remotely.")

    if scam_risk_score >= HIGH_RISK_THRESHOLD:
        parts.append(
            "Note: this listing scored high on scam-risk heuristics and should be "
            "reviewed carefully before responding."
        )

    parts.append("Looking forward to hearing from you.")
    proposal = "\n".join(parts)

    return OutreachDraft(
        title=title,
        description=description,
        opportunity_type=opportunity_type,
        matched_skills=matched_skills,
        scam_risk_score=scam_risk_score,
        proposal=proposal,
        confidence_score=confidence_score,
        clarification_questions=_clarification_questions(
            opportunity_type, scam_risk_score
        ),
        technical_angle=_technical_angle(opportunity_type, matched_skills),
    )


def generate_outreach_for_listing(listing_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate an outreach draft and return it as a plain dict."""
    draft = generate_outreach_draft(listing_data)
    return {
        "title": draft.title,
        "description": draft.description,
        "opportunity_type": draft.opportunity_type,
        "matched_skills": draft.matched_skills,
        "scam_risk_score": draft.scam_risk_score,
        "proposal": draft.proposal,
        "confidence_score": draft.confidence_score,
        "clarification_questions": draft.clarification_questions,
        "technical_angle": draft.technical_angle,
    }
