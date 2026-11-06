"""Phase 3c: Sample gold jobs for hand-verification of LLM extraction accuracy.

Exports 40 gold jobs (stratified: ~20 bad_fit, 15 maybe, 5 good_fit) to a CSV
with their extracted fields and empty correction columns for human review.

Uses csv module only (no pandas/pyarrow).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

EXTRACTION_FIELDS = [
    "required_stack",
    "seniority",
    "years_experience_min",
    "degree_required",
    "remote_policy",
    "region_restrictions",
    "work_authorization",
    "salary_if_stated",
    "extraction_status",
]

STRATA_TARGETS = {
    "bad_fit": 20,
    "maybe": 15,
    "good_fit": 5,
}


def get_db_conn():
    import psycopg

    db_url = (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )
    return psycopg.connect(db_url)


def load_gold_stratified(conn, strata_targets: Dict[str, int], seed: int = 42) -> List[Dict]:
    """Load stratified sample of gold jobs from DB."""
    all_gold = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (ll.job_id)
                ll.job_id::text,
                ll.label,
                jp.title,
                jp.company_name,
                jp.description_text,
                jp.source
            FROM laya_labels ll
            JOIN job_postings jp ON jp.id = ll.job_id
            WHERE ll.label_guideline_version = 'v2_role_fit_only'
              AND ll.label IS NOT NULL
            ORDER BY ll.job_id, ll.labeled_at DESC
            """
        )
        cols = [d.name for d in cur.description]
        all_gold = [dict(zip(cols, r)) for r in cur.fetchall()]

    by_label: Dict[str, List] = {"bad_fit": [], "maybe": [], "good_fit": []}
    for r in all_gold:
        lbl = r.get("label", "")
        if lbl in by_label:
            by_label[lbl].append(r)

    rng = random.Random(seed)
    sampled = []
    for lbl, target_n in strata_targets.items():
        pool = by_label.get(lbl, [])
        n = min(target_n, len(pool))
        chosen = rng.sample(pool, n)
        sampled.extend(chosen)
        logger.info("Sampled %d/%d %s jobs", n, len(pool), lbl)

    return sampled


def load_cached_extraction(conn, job_id: str) -> Optional[Dict]:
    """Load the most recent extraction for a job from job_llm_features."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT json_data FROM job_llm_features
            WHERE job_id = %s::uuid
              AND feature_type = 'extraction'
            ORDER BY created_at DESC LIMIT 1
            """,
            (job_id,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return dict(row[0])
    return None


def run_extraction(job: Dict, timeout: float = 60.0) -> Optional[Dict]:
    """Run LLM extraction for one job, returns raw dict or None."""
    try:
        from src.llm.extract import extract_jd_features

        result = extract_jd_features(
            job_id=job["job_id"],
            description=job.get("description_text") or "",
        )
        if result:
            return result.model_dump()
    except Exception as e:
        logger.warning("Extraction failed for %s: %s", job["job_id"], e)
    return None


def flatten_extraction_field(value: Any) -> str:
    """Flatten nested extraction field to a readable string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        inner_val = value.get("value")
        if isinstance(inner_val, list):
            return ", ".join(str(v) for v in inner_val)
        return str(inner_val) if inner_val is not None else ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def main():
    parser = argparse.ArgumentParser(
        description="Sample gold jobs for hand-verification of LLM extraction accuracy."
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for stratified sampling.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM extraction, export blank fields.")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV path (default: data/extraction_check_<date>.csv)",
    )
    args = parser.parse_args()

    date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    output_path = Path(args.output) if args.output else DATA_DIR / f"extraction_check_{date_str}.csv"

    # --- Docker & DB ---
    from src.db.docker_control import ensure_docker_and_postgres

    ensure_docker_and_postgres()
    conn = get_db_conn()

    jobs = load_gold_stratified(conn, STRATA_TARGETS, seed=args.seed)
    logger.info("Total sampled: %d jobs", len(jobs))

    # --- Try to get/run extractions ---
    ollama_available = False
    if not args.no_llm:
        from src.llm.client import is_ollama_available

        ollama_available = is_ollama_available()
        if ollama_available:
            logger.info("Ollama available — will run extraction for uncached jobs")
        else:
            logger.warning("Ollama not available — extraction fields will be blank unless cached")

    rows_out = []
    for idx, job in enumerate(jobs):
        job_id = job["job_id"]
        desc = job.get("description_text") or ""
        snippet = desc[:200].replace("\n", " ") if desc else ""

        # Try cache first, then run if Ollama available
        extraction = load_cached_extraction(conn, job_id)

        if extraction is None and ollama_available and not args.no_llm:
            logger.info("[%d/%d] Extracting: %s @ %s", idx + 1, len(jobs), job.get("title", ""), job.get("company_name", ""))
            extraction = run_extraction(job)

        # Build row
        row = {
            "job_id": job_id,
            "label": job.get("label", ""),
            "title": job.get("title", ""),
            "company": job.get("company_name", ""),
            "source": job.get("source", ""),
            "description_snippet": snippet,
        }

        # Extraction fields
        for field in EXTRACTION_FIELDS:
            if extraction and field in extraction:
                row[f"extracted_{field}"] = flatten_extraction_field(extraction[field])
            else:
                row[f"extracted_{field}"] = ""

        # Empty correction columns for human review
        for field in EXTRACTION_FIELDS:
            row[f"correction_{field}"] = ""

        row["notes"] = ""
        rows_out.append(row)

    conn.close()

    # Write CSV
    fieldnames = (
        ["job_id", "label", "title", "company", "source", "description_snippet"]
        + [f"extracted_{f}" for f in EXTRACTION_FIELDS]
        + [f"correction_{f}" for f in EXTRACTION_FIELDS]
        + ["notes"]
    )

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\n✅ Extraction check CSV written: {output_path}")
    print(f"   Rows: {len(rows_out)}")
    print(f"   Columns: {len(fieldnames)}")
    print(f"\nInstructions:")
    print(f"  1. Open the CSV in Excel or Google Sheets.")
    print(f"  2. Fill the 'correction_*' columns where the extracted value is wrong or missing.")
    print(f"  3. Use the 'notes' column for any other observations.")
    print(f"  4. Save and run scripts/score_extraction_corrections.py (Phase 3c scoring).")
    label_counts = {}
    for r in rows_out:
        lbl = r["label"]
        label_counts[lbl] = label_counts.get(lbl, 0) + 1
    print(f"\n  Label distribution: {label_counts}")


if __name__ == "__main__":
    main()
