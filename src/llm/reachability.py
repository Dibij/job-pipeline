"""Qualification and reachability suggestion engine (Phase 2c).

Translates structured LLM extraction into non-binding suggestions for:
- Nepal accessibility / remote reachability
- Candidate qualification fit (seniority, years of experience, degree)
- Advisory flags for HardFilter and human review.

CRITICAL: Outputs are strictly suggestions for human review and pre-filter audit,
never final judgments or auto-applied labels.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from src.llm.schemas import JDExtraction

logger = logging.getLogger(__name__)

# Regions that conflict with Nepal remote work
US_RESTRICTIONS = {"us only", "usa only", "united states only", "us citizen", "us citizens only"}
EU_RESTRICTIONS = {"eu only", "europe only", "uk only", "united kingdom only"}


def suggest_qualification_and_reachability(extraction: JDExtraction) -> Dict[str, Any]:
    """Derive qualification and reachability suggestions from extracted JD criteria.

    Returns:
        Dict with advisory flags, suggestions, and review notes.
    """
    suggestions: Dict[str, Any] = {
        "reachability": {
            "suggested_accessible": True,
            "confidence": "medium",
            "reasons": [],
            "flags": [],
        },
        "qualification": {
            "seniority_fit": "unknown",
            "experience_fit": "unknown",
            "degree_fit": "acceptable",
            "reasons": [],
        },
        "advisory_hard_filter_codes": [],
        "review_notes": "",
    }

    # 1. Reachability & Remote Policy Analysis
    remote_val = (extraction.remote_policy.value or "unknown").lower()
    regions = [r.lower() for r in extraction.region_restrictions.value]
    work_auth = (extraction.work_authorization.value or "").lower()

    if remote_val == "onsite":
        suggestions["reachability"]["suggested_accessible"] = False
        suggestions["reachability"]["reasons"].append("Role is onsite outside Nepal")
        suggestions["reachability"]["flags"].append("ONSITE_LOCATION")
        suggestions["advisory_hard_filter_codes"].append("NOT_REMOTE")
    elif remote_val == "hybrid":
        suggestions["reachability"]["suggested_accessible"] = False
        suggestions["reachability"]["reasons"].append("Role requires hybrid presence")
        suggestions["reachability"]["flags"].append("HYBRID_LOCATION")
        suggestions["advisory_hard_filter_codes"].append("NOT_REMOTE")

    # Check geographic restrictions
    for r in regions:
        if any(us in r for us in US_RESTRICTIONS) or "us only" in r:
            suggestions["reachability"]["suggested_accessible"] = False
            suggestions["reachability"]["reasons"].append(f"Geographic lock: {r}")
            suggestions["reachability"]["flags"].append("US_LOCKED")
            suggestions["advisory_hard_filter_codes"].append("REGION_LOCKED")
        elif any(eu in r for eu in EU_RESTRICTIONS) or "europe only" in r:
            suggestions["reachability"]["suggested_accessible"] = False
            suggestions["reachability"]["reasons"].append(f"Geographic lock: {r}")
            suggestions["reachability"]["flags"].append("EU_LOCKED")
            suggestions["advisory_hard_filter_codes"].append("REGION_LOCKED")

    # Check work authorization restrictions
    if "citizen" in work_auth or "security clearance" in work_auth or "no sponsorship" in work_auth:
        suggestions["reachability"]["suggested_accessible"] = False
        suggestions["reachability"]["reasons"].append(f"Work authorization barrier: {work_auth}")
        suggestions["reachability"]["flags"].append("WORK_AUTH_BARRIER")

    if not suggestions["reachability"]["reasons"]:
        suggestions["reachability"]["reasons"].append("No restrictive geographic or work auth barriers detected")
        suggestions["reachability"]["flags"].append("WORLDWIDE_OR_UNRESTRICTED")

    # 2. Qualification Analysis (Candidate profile: Junior/Entry/Mid, ~1-2 yrs)
    seniority = (extraction.seniority.value or "unknown").lower()
    min_years = extraction.years_experience_min.value

    if seniority in ("senior", "lead", "principal", "staff", "manager", "head"):
        suggestions["qualification"]["seniority_fit"] = "too_senior"
        suggestions["qualification"]["reasons"].append(f"High seniority requirement: {seniority}")
        suggestions["advisory_hard_filter_codes"].append("TOO_SENIOR")
    elif seniority in ("junior", "entry", "intern"):
        suggestions["qualification"]["seniority_fit"] = "junior_friendly"
        suggestions["qualification"]["reasons"].append(f"Junior-friendly seniority: {seniority}")
    elif seniority == "mid":
        suggestions["qualification"]["seniority_fit"] = "acceptable_mid"
    else:
        suggestions["qualification"]["seniority_fit"] = "unstated"

    if min_years is not None:
        if min_years > 3.0:
            suggestions["qualification"]["experience_fit"] = "too_senior"
            suggestions["qualification"]["reasons"].append(f"Requires {min_years} years exp (candidate target <= 3.0)")
            suggestions["advisory_hard_filter_codes"].append("DEGREE_OR_EXP")
        elif min_years <= 2.0:
            suggestions["qualification"]["experience_fit"] = "well_matched"
            suggestions["qualification"]["reasons"].append(f"Experience requirement ({min_years} yrs) aligns with profile")
        else:
            suggestions["qualification"]["experience_fit"] = "moderate_stretch"

    # Degree requirement
    if extraction.degree_required.value is True:
        suggestions["qualification"]["degree_fit"] = "degree_mandatory"
        suggestions["qualification"]["reasons"].append("University degree explicitly mandatory")

    # 3. Build Review Notes
    notes_parts = []
    if suggestions["reachability"]["reasons"]:
        notes_parts.append("Reachability: " + "; ".join(suggestions["reachability"]["reasons"]))
    if suggestions["qualification"]["reasons"]:
        notes_parts.append("Qualification: " + "; ".join(suggestions["qualification"]["reasons"]))
    suggestions["review_notes"] = " | ".join(notes_parts)

    return suggestions
