"""Service to enrich and update stored jobs in PostgreSQL."""
import logging
from typing import Dict, Any
from src.db.connection import get_connection
from src.enrichment.enricher import JobEnricher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def enrich_all_stored_jobs() -> Dict[str, Any]:
    """Reads all jobs from database, computes enrichments, and updates records."""
    logger.info("Starting enrichment on all stored jobs in PostgreSQL...")

    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, description_text, location_raw, remote_restriction, is_remote, tags
                FROM jobs;
            """)
            jobs = cur.fetchall()

    if not jobs:
        logger.info("No jobs found to enrich.")
        return {"total": 0, "enriched": 0}

    logger.info("Found %d jobs to enrich. Computing metadata...", len(jobs))
    stats = {
        "total": len(jobs),
        "german": 0,
        "english": 0,
        "junior_or_intern": 0,
        "senior": 0,
        "mid": 0,
        "unspecified": 0,
        "unpaid": 0,
        "nepal_accessible": 0,
    }

    update_payloads = []
    for j in jobs:
        enriched = JobEnricher.enrich_job(j)

        lang = enriched["detected_language"]
        exp = enriched["experience_level"]
        unpaid = enriched["is_unpaid"]
        accessible = enriched["nepal_accessible"]
        tags = enriched["tags"]

        if lang == "german":
            stats["german"] += 1
        else:
            stats["english"] += 1

        if exp in ("junior", "intern"):
            stats["junior_or_intern"] += 1
        elif exp == "senior":
            stats["senior"] += 1
        elif exp == "mid":
            stats["mid"] += 1
        else:
            stats["unspecified"] += 1

        if unpaid:
            stats["unpaid"] += 1
        if accessible:
            stats["nepal_accessible"] += 1

        update_payloads.append((lang, exp, unpaid, accessible, tags, j["id"]))

    # Batch update in database
    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE jobs SET
                    detected_language = %s,
                    experience_level = %s,
                    is_unpaid = %s,
                    nepal_accessible = %s,
                    tags = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                update_payloads,
            )
        conn.commit()

    logger.info("Enrichment complete! Summary: %s", stats)
    return stats


if __name__ == "__main__":
    enrich_all_stored_jobs()
