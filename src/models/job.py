import hashlib
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


def build_job_text(title: str, description: str) -> str:
    """Format unified job representation text: 'TITLE: {title}\\n\\n{description}'."""
    t = (title or "").strip()
    d = (description or "").strip()
    return f"TITLE: {t}\n\n{d}" if t else d


class NormalizedJob(BaseModel):
    """Unified job listing schema matching PostgreSQL jobs table."""

    source: str
    external_id: str
    title: str
    company_name: str
    company_url: Optional[str] = None
    location_raw: Optional[str] = None
    is_remote: bool = False
    remote_restriction: Optional[str] = "unspecified"
    accessibility: Optional[str] = "UNKNOWN"
    reachable_from_nepal: str = "unknown"
    reachable_reason: Optional[str] = "no_location_restriction_stated"
    detected_language: Optional[str] = "english"
    is_unpaid: bool = False
    nepal_accessible: bool = False
    job_type: Optional[str] = None
    experience_level: Optional[str] = "unspecified"
    description_text: str
    description_html: Optional[str] = None
    apply_url: str
    salary_min: Optional[Decimal] = None
    salary_max: Optional[Decimal] = None
    salary_currency: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    posted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    fingerprint_hash: Optional[str] = None
    exclude_reason: Optional[str] = None
    # ── Opportunity model extensions (backward compatible; default = 'job') ──
    opportunity_type: str = "job"
    compensation_type: Optional[str] = None
    budget_min: Optional[Decimal] = None
    budget_max: Optional[Decimal] = None
    budget_currency: Optional[str] = None
    deadline: Optional[datetime] = None
    payment_verification_status: str = "unknown"
    scam_risk_score: float = 0.0
    risk_flags: List[str] = Field(default_factory=list)
    risk_explanation: Optional[str] = None
    status: str = "open"
    source_url: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    # Outreach context — human-reviewable drafts, never auto-sent
    outreach_draft: Optional[str] = None
    technical_angle: Optional[str] = None
    clarification_questions: List[str] = Field(default_factory=list)
    # ── Bounty verdict fields ──
    bounty_verdict: Optional[str] = None
    reject_reasons: List[str] = Field(default_factory=list)
    funding_evidence: Optional[Dict[str, Any]] = None
    bounty_confidence: Optional[int] = None
    reject_evidence: Optional[str] = None
    # ── GitHub quality scoring fields ──
    score: Optional[int] = None
    score_breakdown: Optional[Dict[str, Any]] = None
    why: Optional[str] = None
    notes: Optional[str] = None
    lane: Optional[str] = None
    # ── GitHub issue state / provenance (migration 019) ──
    issue_state: Optional[str] = None
    issue_state_reason: Optional[str] = None
    issue_closed_at: Optional[datetime] = None
    author_login: Optional[str] = None
    author_association: Optional[str] = None
    assignee_logins: List[str] = Field(default_factory=list)
    issue_created_at: Optional[datetime] = None
    labels_with_actor: Optional[Any] = None
    parent_issue_url: Optional[str] = None
    sub_issue_urls: Optional[Any] = None
    # ── Fresh re-check (Step 2) ──
    fetched_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    verification_status: str = "UNVERIFIED"

    @model_validator(mode="before")
    @classmethod
    def truncate_and_clean_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        job_id = data.get("external_id") or "unknown"
        fields_to_truncate = ["title", "company_name", "location_raw", "remote_restriction"]

        for field in fields_to_truncate:
            val = data.get(field)
            if val is not None and isinstance(val, str):
                cleaned = val.strip()
                if len(cleaned) > 255:
                    logger.warning(
                        "Truncating %s for job id '%s' from %d to 255 characters",
                        field, job_id, len(cleaned)
                    )
                    data[field] = cleaned[:255].strip()
                else:
                    data[field] = cleaned
        return data

    def compute_fingerprint(self) -> str:
        """Generate SHA-256 fingerprint from title + company_name + location/remote.

        For non-job opportunity types the type is folded into the key so a GitHub
        bounty and a job posting with an identical title/org can't collide. Job
        fingerprints are intentionally unchanged to preserve existing DB rows.
        """
        norm_title = re.sub(r"\s+", " ", self.title.lower().strip())
        norm_company = re.sub(r"\s+", " ", self.company_name.lower().strip())
        norm_remote = "remote" if self.is_remote else "onsite"
        raw_key = f"{norm_title}|{norm_company}|{norm_remote}"
        if getattr(self, "opportunity_type", "job") != "job":
            raw_key = f"{self.opportunity_type}|{raw_key}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def model_post_init(self, __context):
        """Ensure fingerprint_hash is calculated if not explicitly provided."""
        if not self.fingerprint_hash:
            self.fingerprint_hash = self.compute_fingerprint()
