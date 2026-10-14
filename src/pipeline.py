"""Job ingestion and processing pipeline orchestrator."""
import logging
from typing import Dict, Any

from src.db.repository import JobRepository
from src.extractors import ArbeitnowExtractor, RemotiveExtractor, HimalayasExtractor, WWRExtractor, RemoteOKExtractor, JobicyExtractor
from src.models import transform_raw_listing
from src.enrichment.enricher import JobEnricher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class JobPipeline:
    """Orchestrates extraction, staging, normalization, deduplication, and loading."""

    def __init__(self):
        self.repo = JobRepository()

    def run_extractors(self) -> Dict[str, Any]:
        """Fetch raw listings from all enabled sources and stage into raw_job_listings."""
        stats = {}
        logger.info("=== Starting Extraction Phase ===")

        # 1. Arbeitnow
        try:
            arbeitnow = ArbeitnowExtractor(delay_seconds=1.0)
            items = arbeitnow.fetch_raw(max_pages=2)
            res = arbeitnow.stage_raw(items)
            stats["arbeitnow"] = res
        except Exception as exc:
            logger.error("Arbeitnow extractor failed: %s", exc)
            stats["arbeitnow"] = {"error": str(exc)}

        # 2. Remotive
        try:
            remotive = RemotiveExtractor(delay_seconds=2.0)
            items = remotive.fetch_raw(category="software-dev", limit=50)
            res = remotive.stage_raw(items)
            stats["remotive"] = res
        except Exception as exc:
            logger.error("Remotive extractor failed: %s", exc)
            stats["remotive"] = {"error": str(exc)}

        # 3. Himalayas
        try:
            himalayas = HimalayasExtractor(delay_seconds=2.0)
            items = himalayas.fetch_raw(limit=50, max_pages=1)
            res = himalayas.stage_raw(items)
            stats["himalayas"] = res
        except Exception as exc:
            logger.error("Himalayas extractor failed: %s", exc)
            stats["himalayas"] = {"error": str(exc)}

        # 4. We Work Remotely
        try:
            wwr = WWRExtractor(delay_seconds=2.0)
            items = wwr.fetch_raw()
            res = wwr.stage_raw(items)
            stats["weworkremotely"] = res
        except Exception as exc:
            logger.error("WWR extractor failed: %s", exc)
            stats["weworkremotely"] = {"error": str(exc)}

        # 5. Remote OK
        try:
            remoteok = RemoteOKExtractor(delay_seconds=2.0)
            items = remoteok.fetch_raw()
            res = remoteok.stage_raw(items)
            stats["remoteok"] = res
        except Exception as exc:
            logger.error("Remote OK extractor failed: %s", exc)
            stats["remoteok"] = {"error": str(exc)}

        # 6. Jobicy
        try:
            jobicy = JobicyExtractor(delay_seconds=2.0)
            items = jobicy.fetch_raw(count=50, max_pages=1)
            res = jobicy.stage_raw(items)
            stats["jobicy"] = res
        except Exception as exc:
            logger.error("Jobicy extractor failed: %s", exc)
            stats["jobicy"] = {"error": str(exc)}

        return stats

    def process_staged(self, limit: int = 1000) -> Dict[str, int]:
        """Transform raw staged listings into normalized jobs and upsert into jobs table."""
        logger.info("=== Starting Normalization & Deduplication Phase ===")
        raw_items = self.repo.get_unprocessed_raw(limit=limit)
        if not raw_items:
            logger.info("No unprocessed raw listings found.")
            return {"processed": 0, "jobs_upserted": 0}

        normalized_jobs = []
        processed_ids = []

        for item in raw_items:
            raw_id = item["id"]
            source = item["source"]
            payload = item["payload"]
            try:
                norm_job = transform_raw_listing(source, payload)
                # Task 6d: Run enrichment inside normalization pipeline
                enrichment = JobEnricher.enrich_job(norm_job.model_dump())
                norm_job.experience_level = enrichment["experience_level"]
                norm_job.detected_language = enrichment["detected_language"]
                norm_job.is_unpaid = enrichment["is_unpaid"]
                norm_job.nepal_accessible = enrichment["nepal_accessible"]
                norm_job.accessibility = enrichment["accessibility"]
                norm_job.reachable_from_nepal = enrichment["reachable_from_nepal"]
                norm_job.reachable_reason = enrichment["reachable_reason"]
                norm_job.tags = enrichment["tags"]

                normalized_jobs.append(norm_job)
                processed_ids.append(raw_id)
            except Exception as exc:
                logger.error("Failed to transform raw item #%d (%s): %s", raw_id, source, exc)

        res = self.repo.upsert_jobs(normalized_jobs)
        self.repo.mark_raw_processed(processed_ids)

        logger.info(
            "Processed %d raw listing(s) -> Upserted %d job(s) into database.",
            len(processed_ids),
            res["upserted"],
        )
        return {"processed": len(processed_ids), "jobs_upserted": res["upserted"]}


if __name__ == "__main__":
    pipeline = JobPipeline()
    pipeline.run_extractors()
    pipeline.process_staged()
