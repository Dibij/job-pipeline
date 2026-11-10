"""Deterministic scam risk assessment for opportunity listings.

Assesses risk based on text patterns, compensation structure, and opportunity
characteristics. Never fabricates unknown information. All risk scores and flags
are explainable and deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

VAGUE_DESCRIPTION_THRESHOLD = 0.7
UNREALISTIC_RATE_THRESHOLD = 0.8
UPFRONT_PAYMENT_THRESHOLD = 0.9
UNPAID_TEST_PROJECT_THRESHOLD = 0.7

VAGUE_PROJECT_PHRASES = [
    "simple project",
    "quick win",
    "easy money",
    "no experience needed",
    "part-time assistance",
    "help needed asap",
    "urgent hire",
]

UPFRONT_PAYMENT_PHRASES = [
    "upfront",
    "pay first",
    "advance payment",
    "security deposit",
    "verification fee",
    "training cost",
    "equipment fee",
    "background check fee",
]

HOURLY_RATE_RE = re.compile(r"[$\s](\d+(?:,\d{3})*(?:\.\d+)?)\s*/\s*hr", re.IGNORECASE)

# Words that flip an upfront-payment mention into a denial.
_NEGATION_WORDS = frozenset({
    "no", "not", "never", "without", "none", "zero",
    "don't", "dont", "doesn't", "doesnt", "isn't", "isnt",
    "won't", "wont", "cannot", "can't", "cant",
})


@dataclass(frozen=True)
class RiskAssessment:
    """Result of deterministic scam risk assessment."""

    scam_risk_score: float
    risk_flags: List[str]
    risk_explanation: Optional[str]
    score_components: Dict[str, float]


def assess_risk(listing_data: Dict[str, Any]) -> RiskAssessment:
    """Assess scam risk for an opportunity listing."""
    description = listing_data.get("description_text", "") or ""
    comp_type = (listing_data.get("compensation_type") or "").lower()
    budget_min = listing_data.get("budget_min")
    desc_words = len(description.split())
    description_lower = description.lower()

    components: Dict[str, float] = {
        "vague_description": 0.0,
        "unrealistic_rate": 0.0,
        "upfront_payment": 0.0,
        "unpaid_test": 0.0,
        "total": 0.0,
    }
    flags: List[str] = []
    explanation_parts: List[str] = []

    # 1. Vague description: short text makes scope impossible to judge.
    if desc_words > 0 and desc_words < 15:
        vague_score = VAGUE_DESCRIPTION_THRESHOLD * (1.0 - min(desc_words / 15.0, 1.0))
        components["vague_description"] = round(vague_score, 2)
        flags.append("vague_description")
        explanation_parts.append(
            f"Very brief description ({desc_words} words) makes scope unclear"
        )

    for phrase in VAGUE_PROJECT_PHRASES:
        if phrase in description_lower:
            components["vague_description"] = max(
                components["vague_description"], VAGUE_DESCRIPTION_THRESHOLD
            )
            if "vague_description" not in flags:
                flags.append("vague_description")
                explanation_parts.append(
                    f"Contains vague project phrase: '{phrase}'"
                )
            break

    # 2. Unrealistic hourly rate.
    hourly_match = HOURLY_RATE_RE.search(description)
    if hourly_match:
        hourly_rate = float(hourly_match.group(1).replace(",", ""))
        if hourly_rate > 150:
            components["unrealistic_rate"] = min(
                UNREALISTIC_RATE_THRESHOLD, hourly_rate / 300.0
            )
            if components["unrealistic_rate"] > 0.5:
                flags.append("unrealistic_rate")
                explanation_parts.append(
                    f"Hourly rate {hourly_rate:g} per hour appears above market median"
                )

    # 3. Upfront payment requests are a strong scam signal.
    def _is_negated(text: str, start: int, end: int) -> bool:
        """True when a negation word sits before the phrase in its clause.

        We look backwards to the previous clause boundary only. Forward
        lookahead is deliberately avoided: "pay a fee first, no experience
        needed" must still flag the fee.
        """
        window = text[max(0, start - 60):start]
        # Cut at the nearest clause/sentence boundary.
        for sep in (". ", "; ", "! ", "? ", "\n", ", "):
            cut = window.rfind(sep)
            if cut != -1:
                window = window[cut + len(sep):]
        words = re.findall(r"[a-z']+", window)
        if any(w in _NEGATION_WORDS for w in words):
            return True
        # Postfix denial: "pay first is not required", "deposit is never asked".
        tail = text[end:end + 40].lower()
        for sep in (". ", "; ", "! ", "? ", "\n", ", "):
            cut = tail.find(sep)
            if cut != -1:
                tail = tail[:cut]
        return bool(re.search(r"\b(?:is|are|was|were)\s+(?:not|never)\b", tail))

    upfront_matches = []
    for phrase in UPFRONT_PAYMENT_PHRASES:
        start = description_lower.find(phrase)
        while start != -1:
            if not _is_negated(description_lower, start, start + len(phrase)):
                upfront_matches.append(phrase)
                break
            start = description_lower.find(phrase, start + 1)

    if upfront_matches:
        components["upfront_payment"] = UPFRONT_PAYMENT_THRESHOLD
        flags.append("upfront_payment")
        explanation_parts.append(
            "Requests upfront payment: " + ", ".join(upfront_matches[:3])
        )

    # 4. Unpaid work. Portfolio-backed unpaid work is lower risk than bare asks.
    if comp_type == "unpaid":
        if "portfolio" in description_lower:
            components["unpaid_test"] = 0.3
        else:
            components["unpaid_test"] = UNPAID_TEST_PROJECT_THRESHOLD
            flags.append("unpaid_test")
            explanation_parts.append(
                "Unpaid project with no portfolio/context explanation"
            )

    total_score = min(sum(components.values()), 1.0)

    explanation = "; ".join(explanation_parts) if explanation_parts else None

    return RiskAssessment(
        scam_risk_score=round(total_score, 2),
        risk_flags=flags,
        risk_explanation=explanation,
        score_components={k: round(v, 2) for k, v in components.items()},
    )


def quick_assess(
    title: str, description: str, comp_type: Optional[str] = None
) -> Dict[str, Any]:
    """Quick risk assessment returning a JSON-serialisable dict."""
    result = assess_risk(
        {
            "title": title,
            "description_text": description,
            "compensation_type": comp_type,
        }
    )
    return {
        "scam_risk_score": result.scam_risk_score,
        "risk_flags": result.risk_flags,
        "risk_explanation": result.risk_explanation,
        "score_components": result.score_components,
    }
