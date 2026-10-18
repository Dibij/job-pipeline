"""Job ingestion and processing pipeline orchestrator."""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Callable
import uuid

from src.db.repository import JobRepository
from src.extractors import (
    ArbeitnowExtractor,
    RemotiveExtractor,
    HimalayasExtractor,
    WWRExtractor,
    RemoteOKExtractor,
    JobicyExtractor,
    HackerNewsExtractor,
)
from src.models import transform_raw_listing
from src.enrichment.enricher import JobEnricher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class JobPipeline:
    """Orchestrates extraction, staging, normalization, deduplication, and loading."""

    def __init__(self):
        self.repo = JobRepository()

    def _run_single_extractor(
        self,
        run_id: str,
        source_name: str,
        fetch_fn: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute one extractor and record execution metrics in source_runs table."""
        started_at = datetime.now(timezone.utc)
        try:
            res = fetch_fn()
            self.repo.record_source_run(
                run_id=run_id,
                source=source_name,
                started_at=started_at,
                fetched=res.get("total", 0),
                inserted=res.get("inserted", 0),
                skipped=res.get("skipped", 0),
            )
            return res
        except Exception as exc:
            logger.error("%s extractor failed: %s", source_name.title(), exc)
            self.repo.record_source_run(
                run_id=run_id,
                source=source_name,
                started_at=started_at,
                fetched=0,
                inserted=0,
                skipped=0,
                error=str(exc),
            )
            return {"error": str(exc)}

    def run_extractors(self) -> Dict[str, Any]:
        """Fetch raw listings from all enabled sources and stage into raw_job_listings."""
        stats = {}
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        logger.info("=== Starting Extraction Phase [run_id: %s] ===", run_id)

        # 1. Arbeitnow
        stats["arbeitnow"] = self._run_single_extractor(
            run_id, "arbeitnow",
            lambda: ArbeitnowExtractor(delay_seconds=1.0).stage_raw(
                ArbeitnowExtractor(delay_seconds=1.0).fetch_raw(max_pages=1)
            )
        )

        # 2. Remotive
        stats["remotive"] = self._run_single_extractor(
            run_id, "remotive",
            lambda: RemotiveExtractor(delay_seconds=2.0).stage_raw(
                RemotiveExtractor(delay_seconds=2.0).fetch_raw(category="software-dev", limit=50)
            )
        )

        # 3. Himalayas
        stats["himalayas"] = self._run_single_extractor(
            run_id, "himalayas",
            lambda: HimalayasExtractor(delay_seconds=2.0).stage_raw(
                HimalayasExtractor(delay_seconds=2.0).fetch_raw(limit=50, max_pages=1)
            )
        )

        # 4. We Work Remotely
        stats["weworkremotely"] = self._run_single_extractor(
            run_id, "weworkremotely",
            lambda: WWRExtractor(delay_seconds=2.0).stage_raw(
                WWRExtractor(delay_seconds=2.0).fetch_raw()
            )
        )

        # 5. Remote OK
        stats["remoteok"] = self._run_single_extractor(
            run_id, "remoteok",
            lambda: RemoteOKExtractor(delay_seconds=2.0).stage_raw(
                RemoteOKExtractor(delay_seconds=2.0).fetch_raw()
            )
        )

        # 6. Jobicy
        stats["jobicy"] = self._run_single_extractor(
            run_id, "jobicy",
            lambda: JobicyExtractor(delay_seconds=2.0).stage_raw(
                JobicyExtractor(delay_seconds=2.0).fetch_raw(count=50, max_pages=1)
            )
        )

        # 7. Hacker News (Who is hiring)
        stats["hackernews"] = self._run_single_extractor(
            run_id, "hackernews",
            lambda: HackerNewsExtractor(delay_seconds=0.1).stage_raw(
                HackerNewsExtractor(delay_seconds=0.1).fetch_raw(limit=50)
            )
        )

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
