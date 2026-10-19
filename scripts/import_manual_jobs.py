"""Manual import tool for Nepal job listings (Brief §0).

HARD CONSTRAINT:
DO NOT SEARCH OR SCRAPE NEPALI JOB SITES.
This script performs ZERO network requests and ZERO web crawling.
It imports candidate-supplied local JSON or CSV files into the pipeline.

Permitted manual import sources (user-supplied exports only):
- merojob
- kumarijob
- jobaxle
- jobsnepal
- njobz
- Direct Nepali company career pages

Usage:
    python scripts/import_manual_jobs.py --file path/to/jobs.json
    python scripts/import_manual_jobs.py --file path/to/jobs.csv
"""
import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.db.repository import JobRepository
from src.enrichment.enricher import JobEnricher
from src.matching.hard_filter import apply as hard_filter_apply
from src.matching.scorer import MatchScorer
from src.models import transform_raw_listing
from psycopg.types.json import Jsonb

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_jobs_from_file(file_path: Path) -> List[Dict[str, Any]]:
    """Load job records from a local JSON or CSV file. No network calls."""
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data.get("jobs", [data])
            else:
                raise ValueError("JSON file must contain an array or object of jobs")
    elif suffix == ".csv":
        jobs = []
        with open(file_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert string booleans
                if "is_remote" in row:
                    row["is_remote"] = str(row["is_remote"]).strip().lower() in ("true", "1", "yes")
                if "tags" in row and isinstance(row["tags"], str):
                    row["tags"] = [t.strip() for t in row["tags"].split(",") if t.strip()]
                jobs.append(row)
        return jobs
    else:
        raise ValueError(f"Unsupported file format '{suffix}'. Use .json or .csv.")


def import_manual_jobs(
    jobs_data: List[Dict[str, Any]],
    source: str = "manual:nepal",
) -> Dict[str, Any]:
    """Process and ingest manually provided job listings into the pipeline.
    
    Stages:
      1. Insert into raw_job_listings
      2. Transform into NormalizedJob
      3. Enrich with JobEnricher
      4. Upsert into jobs table
      5. Apply HardFilter & MatchScorer -> upsert to job_matches
    """
    repo = JobRepository()
    scorer = MatchScorer()

    stats = {
        "total_read": len(jobs_data),
        "raw_staged": 0,
        "jobs_upserted": 0,
        "hard_filter_passed": 0,
        "hard_filter_disqualified": 0,
        "matches_scored": 0,
    }

    for idx, raw_record in enumerate(jobs_data):
        title = (raw_record.get("title") or "").strip()
        company = (raw_record.get("company_name") or raw_record.get("company") or "Unknown").strip()
        if not title:
            logger.warning("Skipping entry #%d: Missing 'title'", idx)
            continue

        ext_id = str(raw_record.get("external_id") or "").strip()
        if not ext_id:
            ext_id = f"manual_{abs(hash(f'{title}_{company}_{idx}'))}"
            raw_record["external_id"] = ext_id

        # 1. Stage into raw_job_listings
        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO raw_job_listings (source, external_id, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (source, external_id) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            retrieved_at = NOW();
                        """,
                        (source, ext_id, Jsonb(raw_record)),
                    )
            stats["raw_staged"] += 1
        except Exception as exc:
            logger.error("Failed staging raw listing '%s': %s", title, exc)
            continue

        # 2. Transform into NormalizedJob
        try:
            norm_job = transform_raw_listing(source, raw_record)
        except Exception as exc:
            logger.error("Failed transforming '%s': %s", title, exc)
            continue

        # 3. Enrich with JobEnricher
        try:
            enrichment = JobEnricher.enrich_job(norm_job.model_dump())
            norm_job.experience_level = enrichment["experience_level"]
            norm_job.detected_language = enrichment["detected_language"]
            norm_job.is_unpaid = enrichment["is_unpaid"]
            norm_job.nepal_accessible = enrichment["nepal_accessible"]
            norm_job.accessibility = enrichment["accessibility"]
            norm_job.reachable_from_nepal = enrichment["reachable_from_nepal"]
            norm_job.reachable_reason = enrichment["reachable_reason"]
            norm_job.tags = enrichment["tags"]
        except Exception as exc:
            logger.error("Failed enriching '%s': %s", title, exc)

        # 4. Upsert into jobs table
        job_id = None
        try:
            job_id = repo.upsert_job(norm_job)
            if job_id:
                stats["jobs_upserted"] += 1
        except Exception as exc:
            logger.error("Failed upserting job '%s': %s", title, exc)
            continue

        # 5. Filter & Score
        if job_id:
            job_dict = norm_job.model_dump()
            job_dict["id"] = job_id
            filter_res = hard_filter_apply(job_dict)

            if not filter_res.passed:
                stats["hard_filter_disqualified"] += 1
                logger.info("HardFilter DISQUALIFIED '%s': %s (%s)", title, filter_res.reason, filter_res.detail)
                # Disqualify in job_matches
                with get_connection(autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO job_matches (job_id, final_score, is_passed, disqualification_reason)
                            VALUES (%s, 0.0, FALSE, %s)
                            ON CONFLICT (job_id) DO UPDATE SET
                                final_score = 0.0,
                                is_passed = FALSE,
                                disqualification_reason = EXCLUDED.disqualification_reason;
                            """,
                            (job_id, filter_res.reason.value),
                        )
            else:
                stats["hard_filter_passed"] += 1
                score, matched, missing, breakdown = scorer.score_job(job_dict)
                is_passed = score >= 60.0
                disq = None if is_passed else "LOW_SCORE"

                with get_connection(autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO job_matches (
                                job_id, final_score, matched_skills, missing_skills,
                                score_breakdown, is_passed, disqualification_reason
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (job_id) DO UPDATE SET
                                final_score = EXCLUDED.final_score,
                                matched_skills = EXCLUDED.matched_skills,
                                missing_skills = EXCLUDED.missing_skills,
                                score_breakdown = EXCLUDED.score_breakdown,
                                is_passed = EXCLUDED.is_passed,
                                disqualification_reason = EXCLUDED.disqualification_reason;
                            """,
                            (
                                job_id,
                                score,
                                matched,
                                missing,
                                Jsonb(breakdown),
                                is_passed,
                                disq,
                            ),
                        )
                stats["matches_scored"] += 1
                logger.info("Scored '%s' -> %s (score=%.1f, matched=%s)", title, "PASSED" if is_passed else "LOW_SCORE", score, matched)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Import user-provided JSON/CSV jobs into the pipeline (NO web fetching)."
    )
    parser.add_argument(
        "--file",
        "-f",
        required=True,
        type=Path,
        help="Path to local JSON or CSV file containing job listings.",
    )
    parser.add_argument(
        "--source",
        "-s",
        default="manual:nepal",
        help="Source tag to record (default: manual:nepal).",
    )
    args = parser.parse_args()

    file_path = args.file
    logger.info("Loading manual jobs from %s...", file_path)
    records = load_jobs_from_file(file_path)
    logger.info("Loaded %d record(s). Ingesting with source='%s'...", len(records), args.source)

    stats = import_manual_jobs(records, source=args.source)
    print("\n=== Manual Import Summary ===")
    for k, v in stats.items():
        print(f"  {k:28s}: {v}")


if __name__ == "__main__":
    main()
