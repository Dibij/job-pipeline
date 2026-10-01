"""Transformers converting source-specific raw payloads into NormalizedJob models."""
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from bs4 import BeautifulSoup

from src.models.job import NormalizedJob


def strip_html(html_content: Optional[str]) -> str:
    """Clean HTML tags and normalize whitespace into plain text."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def parse_timestamp(dt_val: Any) -> Optional[datetime]:
    """Parse various datetime representations into UTC datetime."""
    if not dt_val:
        return None

    if isinstance(dt_val, (int, float)):
        # Epoch timestamp
        return datetime.fromtimestamp(dt_val, tz=timezone.utc)

    if isinstance(dt_val, str):
        dt_str = dt_val.strip()
        if not dt_str:
            return None
        # Try ISO format
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    return None


def transform_arbeitnow(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Arbeitnow raw item into NormalizedJob."""
    raw_desc = payload.get("description", "")
    plain_desc = strip_html(raw_desc) or payload.get("title", "")

    posted_at = parse_timestamp(payload.get("created_at"))
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    job_types = payload.get("job_types") or []
    job_type_str = job_types[0] if isinstance(job_types, list) and job_types else None

    return NormalizedJob(
        source="arbeitnow",
        external_id=str(payload.get("slug") or payload.get("url") or "").strip(),
        title=payload.get("title", "Untitled Position"),
        company_name=payload.get("company_name", "Unknown Company"),
        location_raw=payload.get("location"),
        is_remote=bool(payload.get("remote", False)),
        remote_restriction="Worldwide" if payload.get("remote") else None,
        job_type=job_type_str,
        description_text=plain_desc,
        description_html=raw_desc,
        apply_url=payload.get("url", ""),
        tags=[str(t).strip() for t in tags if t],
        posted_at=posted_at,
    )


def transform_remotive(payload: Dict[str, Any]) -> NormalizedJob:
    """Transform Remotive raw item into NormalizedJob."""
    raw_desc = payload.get("description", "")
    plain_desc = strip_html(raw_desc) or payload.get("title", "")

    posted_at = parse_timestamp(payload.get("publication_date"))
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    location = payload.get("candidate_required_location") or ""
    is_remote = True  # All Remotive jobs are remote
    remote_restriction = location.strip() if location else "Worldwide"

    return NormalizedJob(
        source="remotive",
        external_id=str(payload.get("id") or payload.get("url") or "").strip(),
        title=payload.get("title", "Untitled Position"),
        company_name=payload.get("company_name", "Unknown Company"),
        company_url=payload.get("company_logo_url"),
        location_raw=location,
        is_remote=is_remote,
        remote_restriction=remote_restriction,
        job_type=payload.get("job_type"),
        description_text=plain_desc,
        description_html=raw_desc,
        apply_url=payload.get("url", ""),
        tags=[str(t).strip() for t in tags if t],
        posted_at=posted_at,
    )


def transform_raw_listing(source: str, payload: Dict[str, Any]) -> NormalizedJob:
    """Dispatcher transforming raw item payload based on source name."""
    source_lower = source.lower().strip()
    if source_lower == "arbeitnow":
        return transform_arbeitnow(payload)
    elif source_lower == "remotive":
        return transform_remotive(payload)
    else:
        raise ValueError(f"No transformer registered for source: '{source}'")
