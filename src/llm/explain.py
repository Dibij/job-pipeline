"""Feed explanation generator (Phase 2e).

Generates concise 2-sentence summaries:
- why this role fits the candidate's profile
- what is missing or presents a risk / gap
Cached in table job_llm_features under feature_type='explanation'.
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
from src.llm.prompts.explanation_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_explanation_user_message,
)
from src.llm.schemas import JobExplanation

logger = logging.getLogger(__name__)

FEATURE_TYPE = "explanation"


def generate_job_explanation(
    job: Dict[str, Any],
    prompt_version: str = PROMPT_VERSION,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    timeout: float = 30.0,
) -> Optional[JobExplanation]:
    """Generate or retrieve a cached 2-sentence explanation for a job posting.

    Args:
        job: Dict representing the job posting.
        prompt_version: Version of explanation prompt.
        model: Ollama model tag.
        force: If True, bypass cache.
        timeout: Timeout in seconds for Ollama.

    Returns:
        JobExplanation instance or None if unavailable.
    """
    job_id = str(job.get("id") or job.get("job_id") or "")
    title = str(job.get("title") or "")
    company = str(job.get("company_name") or job.get("company") or "")
    desc = str(job.get("description_text") or job.get("description") or "")

    if not title and not desc:
        return None

    content_hash = compute_job_content_hash(job)
    model_digest = get_model_digest(model)

    # 1. Cache check
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
                return JobExplanation.model_validate(cached)
            except Exception:
                pass

    # 2. Build prompt
    user_msg = build_explanation_user_message(
        title=title,
        company=company,
        description=desc,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # 3. Call structured Ollama
    try:
        explanation = call_structured_ollama(
            messages=messages,
            response_model=JobExplanation,
            model=model,
            temperature=0.0,
            seed=42,
            timeout=timeout,
        )
    except OllamaUnavailableError as oue:
        logger.debug("Ollama unavailable for explanation '%s': %s", title[:40], oue)
        return None
    except (OllamaGenerationError, Exception) as exc:
        logger.debug("Failed generating explanation for '%s': %s", title[:40], exc)
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
            json_data=explanation.model_dump(),
        )

    return explanation
