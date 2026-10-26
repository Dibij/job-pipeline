import hashlib
import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional
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
