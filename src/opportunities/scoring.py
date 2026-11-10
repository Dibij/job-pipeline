"""Deterministic opportunity scoring for freelance, bounty, and open-source listings.

Separate from the job MatchScorer on purpose: a freelance project has a
deliverable + budget + deadline, and a bounty has an issue + (maybe) a reward,
not an employment arrangement. The job scorer's seniority/location/unpaid
penalties do not transfer; this module evaluates the *actual work* requested.

Rules are deterministic and explainable. Nothing here mutates the database; it
returns a verdict that the dashboard/FEED can display and a human can override.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.matching.scorer import MatchScorer, SKILL_PATTERNS
from src.opportunities.compensation import detect_compensation

# Complexity / scope signals (early-career developer's reachability)
_TEAM_RE = re.compile(
    r"\b(team of|we are a team|join a team|multiple developers?|agency|squad|"
    r"codebase is (?:large|huge|legacy|massive)|large team)\b",
    re.IGNORECASE,
)
_PRODUCTION_RE = re.compile(
    r"\b(production[- ]grade|production[- ]ready|production experience|enterprise|"
    r"mission[- ]critical|high[- ]availability|scale to|millions? of users)\b",
    re.IGNORECASE,
)
_SENIOR_RE = re.compile(
    r"\b(senior|staff|principal|architect|10\+?\s*years?|[7-9]\+?\s*years?|expert|guru)\b",
    re.IGNORECASE,
)
_MIN_EXPERIENCE_RE = re.compile(
    r"\b(?:[3-9]|[1-9][0-9])\+?\s*(?:years?|yrs)\b",
    re.IGNORECASE,
)
_VAGUE_DESC_LEN = 80


@dataclass
class OpportunityScore:
    opportunity_type: str
    label: str
    score: float  # 0-100
    matched_skills: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


def _skill_overlap(
    scorer: MatchScorer,
    title: str,
    desc: str,
    tags: List[str],
) -> Tuple[List[str], float]:
    """Return (matched skills, fraction of primary skills matched)."""
    tag_set = {str(t).lower().strip() for t in tags}
    matched: List[str] = []
    for skill in scorer.all_skills:
        pattern = SKILL_PATTERNS.get(skill)
        present = skill in tag_set
        if not present and pattern is not None:
            present = bool(pattern.search(title) or pattern.search(desc))
        elif not present:
            safe = re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)
            present = bool(safe.search(title) or safe.search(desc))
        if present:
            matched.append(skill)

    primary = set(scorer.primary_skills)
    primary_matched = [s for s in matched if s in primary]
    frac = (len(primary_matched) / len(primary)) if primary else 0.0
    return matched, frac


def _complexity_flags(text: str) -> List[str]:
    flags: List[str] = []
    if _TEAM_RE.search(text):
        flags.append("requires_a_team")
    if _PRODUCTION_RE.search(text):
        flags.append("production_grade_scope")
    if _SENIOR_RE.search(text):
        flags.append("senior_level")
    elif _MIN_EXPERIENCE_RE.search(text):
        flags.append("multi_year_experience")
    return flags


def score_freelance(job: Dict[str, Any]) -> OpportunityScore:
    title = job.get("title") or ""
    desc = job.get("description_text") or ""
    tags = [str(t) for t in (job.get("tags") or [])]
    text = f"{title}\n{desc}"

    scorer = MatchScorer()
    matched, frac = _skill_overlap(scorer, title, desc, tags)
    comp = detect_compensation(desc, kind="freelance")
    flags = _complexity_flags(text)

    if len(desc.strip()) < _VAGUE_DESC_LEN:
        return OpportunityScore(
            "freelance", "insufficient_information", 20.0, matched,
            ["description too short to evaluate the deliverable"],
        )

    if "requires_a_team" in flags or "production_grade_scope" in flags:
        return OpportunityScore(
            "freelance", "too_complex", 30.0, matched,
            ["scope exceeds an early-career solo developer"] + flags,
        )

    reasons: List[str] = []
    if comp.compensation_type != "unknown":
        reasons.append(
            f"compensation={comp.compensation_type} ({comp.payment_verification_status})"
        )

    # Thresholds calibrated for early-career reachability:
    # A single freelance contract typically focuses on 1-2 core technologies.
    # Matching >= 2 primary skills (or >= 20% of the entire 12-skill CV) with no senior/team blockers
    # represents a strong, achievable match.
    if len(matched) >= 2 and frac >= 0.15 and "senior_level" not in flags and "multi_year_experience" not in flags:
        label, score = "good_fit", 80.0
        reasons.append(f"strong skill alignment ({len(matched)} skills: {', '.join(matched[:3])})")
    elif len(matched) >= 1 or frac >= 0.08:
        label, score = "possible_fit", 55.0
        reasons.append(f"partial skill match ({len(matched)} skills: {', '.join(matched[:3])})")
    else:
        label, score = "bad_fit", 30.0
        reasons.append("minimal skill alignment with tech stack")

    return OpportunityScore("freelance", label, score, matched, reasons)


def score_bounty(job: Dict[str, Any]) -> OpportunityScore:
    """Score a bounty or open-source issue.

    Labels: doable | stretch | too_complex | unpaid_portfolio_value | skip
    """
    title = job.get("title") or ""
    desc = job.get("description_text") or ""
    tags = [str(t) for t in (job.get("tags") or [])]
    text = f"{title}\n{desc}"

    scorer = MatchScorer()
    matched, frac = _skill_overlap(scorer, title, desc, tags)
    comp = detect_compensation(desc, kind="bounty")
    flags = _complexity_flags(text)
    opportunity_type = job.get("opportunity_type") or "bounty"

    if opportunity_type == "open_source" or comp.compensation_type == "unpaid":
        return OpportunityScore(
            opportunity_type, "unpaid_portfolio_value", 40.0, matched,
            ["unpaid contribution; value is portfolio evidence, not income"],
        )

    if len(desc.strip()) < _VAGUE_DESC_LEN:
        return OpportunityScore(
            "bounty", "skip", 20.0, matched,
            ["issue body too short to assess scope"],
        )

    if "requires_a_team" in flags or "production_grade_scope" in flags:
        return OpportunityScore(
            "bounty", "too_complex", 30.0, matched,
            ["scope exceeds an early-career solo contributor"] + flags,
        )

    reasons: List[str] = []
    if comp.compensation_type == "bounty":
        status = comp.payment_verification_status
        reasons.append(f"bounty amount present ({status})" if comp.budget_min else f"bounty claimed ({status})")

    if len(matched) >= 2 and frac >= 0.15 and "senior_level" not in flags:
        label, score = "doable", 80.0
        reasons.append(f"strong skill alignment for scoped bounty ({len(matched)} skills)")
    elif frac >= 0.08:
        label, score = "stretch", 55.0
        reasons.append(f"{int(frac*100)}% of primary skills matched")
    else:
        label, score = "too_complex", 30.0
        reasons.append(f"only {int(frac*100)}% of primary skills matched")

    return OpportunityScore("bounty", label, score, matched, reasons)


def score_opportunity(job: Dict[str, Any]) -> OpportunityScore:
    """Dispatch to the right scorer based on opportunity_type."""
    ot = (job.get("opportunity_type") or "job").lower()
    if ot == "freelance":
        return score_freelance(job)
    if ot in ("bounty", "open_source"):
        return score_bounty(job)
    raise ValueError(f"No opportunity scorer for type: {ot!r} (use MatchScorer for 'job')")
