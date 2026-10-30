"""scripts/extract_batch.py -- Run structured JD extraction and explanation in batch.

Iterates over jobs, extracts structured criteria using Ollama,
caches results in table job_llm_features, and derives qualification/reachability suggestions.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.llm.client import is_ollama_available
from src.llm.explain import generate_job_explanation
from src.llm.extract import extract_jd_features
from src.llm.reachability import suggest_qualification_and_reachability

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def fetch_jobs_for_extraction(limit: int = 50, only_unextracted: bool = True) -> List[Dict[str, Any]]:
    """Fetch active jobs needing structured extraction."""
    join_clause = """
        LEFT JOIN job_llm_features f 
          ON f.job_id = j.id AND f.feature_type = 'extraction'
    """
    where_extra = "AND f.job_id IS NULL" if only_unextracted else ""

    query = f"""
        SELECT 
            j.id, j.title, j.company_name, j.location_raw, j.description_text,
            j.source, j.created_at, j.exclude_reason
        FROM jobs j
        {join_clause}
        WHERE j.exclude_reason IS NULL
          AND j.title IS NOT NULL
          AND j.description_text IS NOT NULL
          {where_extra}
        ORDER BY j.created_at DESC
        LIMIT {limit};
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall()


def run_batch_extraction(
    limit: int = 20,
    force: bool = False,
    explain: bool = True,
    no_llm: bool = False,
    model: str = "qwen2.5:3b",
) -> Dict[str, Any]:
    """Execute batch extraction on candidate jobs."""
    if no_llm:
        logger.info("Extraction skipped: --no-llm flag specified.")
        return {"processed": 0, "status": "skipped_no_llm"}

    if not is_ollama_available():
        logger.warning("Ollama daemon is not reachable at localhost:11434. Aborting extraction.")
        return {"processed": 0, "status": "ollama_unavailable"}

    jobs = fetch_jobs_for_extraction(limit=limit, only_unextracted=not force)
    logger.info("Found %d jobs to process for structured extraction.", len(jobs))

    successes = 0
    failures = 0
    start_time = time.time()

    for idx, job in enumerate(jobs, start=1):
        jid = str(job["id"])
        title = job.get("title") or "Untitled"
        company = job.get("company_name") or "Unknown"

        logger.info("[%d/%d] Extracting: '%s' @ '%s'...", idx, len(jobs), title[:40], company[:20])
        extraction = extract_jd_features(job=job, model=model, force=force)
        if not extraction or extraction.extraction_status == "failed":
            failures += 1
            continue

        successes += 1
        # Derive suggestions
        sugg = suggest_qualification_and_reachability(extraction)
        logger.info(
            "  Stack: %s | Seniority: %s | Reachable: %s",
            extraction.required_stack.value[:3],
            extraction.seniority.value,
            sugg["reachability"]["suggested_accessible"],
        )

        # Generate explanation if requested
        if explain:
            generate_job_explanation(job=job, model=model, force=force)

    elapsed = time.time() - start_time
    logger.info(
        "Batch extraction complete in %.1fs: %d succeeded, %d failed.",
        elapsed, successes, failures,
    )
    return {
        "processed": len(jobs),
        "successes": successes,
        "failures": failures,
        "duration": elapsed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch JD feature extraction.")
    parser.add_argument("--limit", type=int, default=10, help="Number of jobs to process")
    parser.add_argument("--force", action="store_true", help="Bypass DB cache and re-extract")
    parser.add_argument("--no-explain", action="store_true", help="Skip explanation generation")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM execution entirely")
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama model tag")
    args = parser.parse_args()

    run_batch_extraction(
        limit=args.limit,
        force=args.force,
        explain=not args.no_explain,
        no_llm=args.no_llm,
        model=args.model,
    )
