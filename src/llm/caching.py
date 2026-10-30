"""Caching layer for LLM extractions, triage suggestions, and explanations.

Keyed by: (job_id, feature_type, prompt_version, model_digest).
Invalidated automatically if the job's content_hash changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional
import psycopg
from psycopg.types.json import Jsonb

from src.db.connection import get_connection

logger = logging.getLogger(__name__)


def compute_job_content_hash(job: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash over relevant job fields."""
    title = str(job.get("title") or "").strip()
    company = str(job.get("company_name") or job.get("company") or "").strip()
    desc = str(job.get("description_text") or job.get("description") or "").strip()
    raw = f"{title}\n{company}\n{desc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_llm_feature(
    job_id: str,
    feature_type: str,
    prompt_version: str,
    model_digest: str,
    content_hash: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch cached LLM feature JSON from DB if available and content hash matches."""
    query = """
        SELECT content_hash, json_data
        FROM job_llm_features
        WHERE job_id = %s
          AND feature_type = %s
          AND prompt_version = %s
          AND model_digest = %s;
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (job_id, feature_type, prompt_version, model_digest))
                row = cur.fetchone()
                if not row:
                    return None

                cached_hash = row.get("content_hash")
                # Invalidate cache if job content has changed
                if content_hash and cached_hash != content_hash:
                    logger.debug("Job content hash changed for %s; bypassing cache.", job_id)
                    return None

                data = row.get("json_data")
                if isinstance(data, str):
                    return json.loads(data)
                return data
    except Exception as exc:
        logger.debug("Cache lookup failed for %s (%s): %s", job_id, feature_type, exc)
        return None


def store_llm_feature(
    job_id: str,
    feature_type: str,
    prompt_version: str,
    model: str,
    model_digest: str,
    content_hash: str,
    json_data: Dict[str, Any],
) -> None:
    """Persist structured LLM output to job_llm_features table."""
    insert_sql = """
        INSERT INTO job_llm_features (
            job_id, feature_type, prompt_version, model, model_digest, content_hash, json_data, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (job_id, feature_type, prompt_version, model_digest)
        DO UPDATE SET
            content_hash = EXCLUDED.content_hash,
            json_data = EXCLUDED.json_data,
            created_at = NOW();
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    insert_sql,
                    (
                        job_id,
                        feature_type,
                        prompt_version,
                        model,
                        model_digest,
                        content_hash,
                        Jsonb(json_data),
                    ),
                )
            conn.commit()
    except Exception as exc:
        logger.warning("Failed to store LLM feature for job %s: %s", job_id, exc)
