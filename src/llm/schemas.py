"""Pydantic schemas for structured LLM extraction, triage, and explanations."""
from __future__ import annotations

from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field


class StringFieldWithQuote(BaseModel):
    value: Optional[str] = Field(default=None, description="Extracted string value, or null if unstated")
    evidence_quote: str = Field(default="", description="Verbatim quote or short snippet from JD as proof")


class FloatFieldWithQuote(BaseModel):
    value: Optional[float] = Field(default=None, description="Extracted numeric value, or null if unstated")
    evidence_quote: str = Field(default="", description="Verbatim quote or short snippet from JD as proof")


class BoolFieldWithQuote(BaseModel):
    value: Optional[bool] = Field(default=None, description="Extracted boolean value, or null if unstated")
    evidence_quote: str = Field(default="", description="Verbatim quote or short snippet from JD as proof")


class ListStringFieldWithQuote(BaseModel):
    value: List[str] = Field(default_factory=list, description="Extracted list of items")
    evidence_quote: str = Field(default="", description="Verbatim quote or short snippet from JD as proof")


class JDExtraction(BaseModel):
    """Structured extraction of job posting criteria."""
    required_stack: ListStringFieldWithQuote = Field(
        default_factory=ListStringFieldWithQuote,
        description="Explicit required programming languages, libraries, tools, and frameworks",
    )
    seniority: StringFieldWithQuote = Field(
        default_factory=lambda: StringFieldWithQuote(value="unknown"),
        description="Seniority level: 'intern', 'junior', 'mid', 'senior', 'lead', or 'unknown'",
    )
    years_experience_min: FloatFieldWithQuote = Field(
        default_factory=FloatFieldWithQuote,
        description="Minimum required years of professional experience (e.g. 2.0). null if not stated",
    )
    degree_required: BoolFieldWithQuote = Field(
        default_factory=BoolFieldWithQuote,
        description="True if a university / Bachelor's degree is strictly required, false if explicitly not, null if unstated",
    )
    remote_policy: StringFieldWithQuote = Field(
        default_factory=lambda: StringFieldWithQuote(value="unknown"),
        description="'remote', 'hybrid', 'onsite', or 'unknown'",
    )
    region_restrictions: ListStringFieldWithQuote = Field(
        default_factory=ListStringFieldWithQuote,
        description="Explicit geographic boundaries (e.g. ['US only', 'Europe only']). Empty if globally open",
    )
    work_authorization: StringFieldWithQuote = Field(
        default_factory=StringFieldWithQuote,
        description="Explicit visa/citizenship restrictions (e.g. 'Must be US Citizen', 'No visa sponsorship'). null if unstated",
    )
    salary_if_stated: StringFieldWithQuote = Field(
        default_factory=StringFieldWithQuote,
        description="Stated salary range or compensation (e.g. '$80k - $110k', '€50,000'). null if not stated",
    )
    extraction_status: Literal["success", "partial", "failed"] = Field(
        default="success",
        description="Status of the extraction operation",
    )


class TriageResult(BaseModel):
    """Schema-validated triage prediction with confidence and reasoning."""
    label: Literal["good_fit", "maybe", "bad_fit"] = Field(
        description="Predicted suitability label for candidate profile",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0",
    )
    reason: str = Field(
        description="Brief concise reason (1-2 sentences) justifying the decision",
    )
    evidence_quote: str = Field(
        default="",
        description="Verbatim text quote from JD supporting the label",
    )


class JobExplanation(BaseModel):
    """Two-sentence feed summary for candidate review."""
    why_fits: str = Field(
        description="1-2 sentences highlighting matching skills and candidate fit",
    )
    what_missing: str = Field(
        description="1-2 sentences identifying gaps, seniority risk, or missing requirements",
    )
