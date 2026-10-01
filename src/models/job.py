"""Pydantic model for normalized job listings."""
import hashlib
import re
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class NormalizedJob(BaseModel):
    """Unified job listing schema matching PostgreSQL jobs table."""

    source: str
    external_id: str
    title: str
    company_name: str
    company_url: Optional[str] = None
    location_raw: Optional[str] = None
    is_remote: bool = False
    remote_restriction: Optional[str] = None
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

    @field_validator("title", "company_name", mode="before")
    @classmethod
    def clean_strings(cls, value: str) -> str:
        if isinstance(value, str):
            return value.strip()
        return str(value or "")

    def compute_fingerprint(self) -> str:
        """Generate SHA-256 fingerprint from title + company_name + location/remote."""
        norm_title = re.sub(r"\s+", " ", self.title.lower().strip())
        norm_company = re.sub(r"\s+", " ", self.company_name.lower().strip())
        norm_remote = "remote" if self.is_remote else "onsite"
        raw_key = f"{norm_title}|{norm_company}|{norm_remote}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def model_post_init(self, __context):
        """Ensure fingerprint_hash is calculated if not explicitly provided."""
        if not self.fingerprint_hash:
            self.fingerprint_hash = self.compute_fingerprint()
