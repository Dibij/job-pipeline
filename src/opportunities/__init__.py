"""Opportunity intelligence components.

Adds freelance/bounty/open-source aware logic on top of the existing job
pipeline: compensation extraction, risk assessment, opportunity scoring,
outreach drafts, and freshness lifecycle. Reuses src.extractors / src.models /
src.db conventions.
"""

from src.opportunities.compensation import Compensation, detect_compensation
from src.opportunities.risk import RiskAssessment, assess_risk, quick_assess
from src.opportunities.outreach import (
    OutreachDraft,
    generate_outreach_draft,
    generate_outreach_for_listing,
)
from src.opportunities.freshness import FreshnessManager, freshness_manager

__all__ = [
    "Compensation",
    "detect_compensation",
    "RiskAssessment",
    "assess_risk",
    "quick_assess",
    "OutreachDraft",
    "generate_outreach_draft",
    "generate_outreach_for_listing",
    "FreshnessManager",
    "freshness_manager",
]
