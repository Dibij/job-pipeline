"""Structured JD extraction module (Phase 2a).

Extracts criteria using Ollama with JSON schema enforcement:
- required_stack
- seniority
- years_experience_min
- degree_required
- remote_policy
- region_restrictions
- work_authorization
- salary_if_stated
with evidence quotes, Pydantic validation, and DB caching.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.llm.caching import (
    compute_job_content_hash,
    get_cached_llm_feature,
    store_llm_feature,
)
from src.llm.client import (
    DEFAULT_MODEL,
    OllamaGenerationError,
    OllamaUnavailableError,
    call_structured_ollama,
    get_model_digest,
)
from src.llm.prompts.extraction_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_message,
)
from src.llm.schemas import JDExtraction

logger = logging.getLogger(__name__)

FEATURE_TYPE = "extraction"


def extract_jd_features(
    job: Dict[str, Any],
    prompt_version: str = PROMPT_VERSION,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    timeout: float = 45.0,
) -> Optional[JDExtraction]:
    """Extract structured criteria from a job posting using Ollama.

    Args:
        job: Dict representing the job posting.
        prompt_version: Version of the extraction prompt.
        model: Ollama model tag.
        force: If True, bypass cache and re-extract.
        timeout: Max seconds to wait for Ollama response.

    Returns:
        JDExtraction instance, or None if Ollama is unavailable / fails.
    """
    job_id = str(job.get("id") or job.get("job_id") or "")
    title = str(job.get("title") or "")
    company = str(job.get("company_name") or job.get("company") or "")
    location = str(job.get("location_raw") or "")
    desc = str(job.get("description_text") or job.get("description") or "")

    if not title and not desc:
        logger.warning("Cannot extract features for empty job %s", job_id)
        return None

    content_hash = compute_job_content_hash(job)
    model_digest = get_model_digest(model)

    # 1. Check cache
    if not force and job_id:
        cached = get_cached_llm_feature(
            job_id=job_id,
            feature_type=FEATURE_TYPE,
            prompt_version=prompt_version,
            model_digest=model_digest,
            content_hash=content_hash,
        )
        if cached:
            try:
                return JDExtraction.model_validate(cached)
            except Exception as exc:
                logger.debug("Failed parsing cached extraction for %s: %s", job_id, exc)

    # 2. Build prompt
    user_msg = build_user_message(
        title=title,
        company=company,
        location=location,
        description=desc,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # 3. Call structured Ollama
    try:
        extraction = call_structured_ollama(
            messages=messages,
            response_model=JDExtraction,
            model=model,
            temperature=0.0,
            seed=42,
            timeout=timeout,
        )
    except OllamaUnavailableError as oue:
        logger.warning("Ollama unavailable during extraction for '%s': %s", title[:40], oue)
        return None
    except OllamaGenerationError as oge:
        logger.warning("Ollama failed extraction for '%s': %s", title[:40], oge)
        # Record failed placeholder extraction instead of guessing
        return JDExtraction(extraction_status="failed")
    except Exception as exc:
        logger.error("Unexpected error in extract_jd_features for '%s': %s", title[:40], exc)
        return None

    # 4. Cache output in database
    if job_id:
        store_llm_feature(
            job_id=job_id,
            feature_type=FEATURE_TYPE,
            prompt_version=prompt_version,
            model=model,
            model_digest=model_digest,
            content_hash=content_hash,
            json_data=extraction.model_dump(),
        )

    return extraction
