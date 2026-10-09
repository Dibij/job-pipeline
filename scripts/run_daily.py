"""Task 6-3: Daily Pipeline Runner.

Orchestrates full daily execution in sequence:
1. Fetch raw job listings from API sources (Arbeitnow, Remotive, etc.)
2. Normalize and deduplicate into jobs table
3. Run baseline MatchScorer rule matching on all jobs
4. Regenerate FEED.md with updated top recommendations
Prints a clean summary block at the end.
"""
import logging
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline import JobPipeline
from src.matching.service import score_all_jobs
from scripts.export_feed import export_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_daily_pipeline():
    start_time = time.time()
    logger.info("=" * 65)
    logger.info("  DAILY PIPELINE RUNNER (Task 6-3)")
    logger.info("=" * 65)

    pipeline = JobPipeline()

    # Phase 1: Fetch raw listings from API sources
    logger.info("[Step 1/4] Running Job Fetchers...")
    extract_stats = pipeline.run_extractors()

    # Phase 2: Normalize and deduplicate into jobs table
    logger.info("[Step 2/4] Normalizing and Deduplicating Staged Listings...")
    norm_stats = pipeline.process_staged()

    # Phase 3: Run baseline MatchScorer
    logger.info("[Step 3/4] Scoring Jobs against Candidate Profile...")
    match_stats = score_all_jobs()

    # Phase 4: Generate FEED.md
    logger.info("[Step 4/4] Exporting FEED.md...")
    feed_path = export_feed(top_n=100)

    duration = time.time() - start_time

    # Print Summary Block
    print("\n" + "=" * 65)
    print(f"  DAILY PIPELINE EXECUTION SUMMARY (Completed in {duration:.1f}s)")
    print("=" * 65)
    print(f"  1. Extraction  : {extract_stats}")
    print(f"  2. Normalized  : Processed {norm_stats.get('processed', 0)} raw -> Upserted {norm_stats.get('jobs_upserted', 0)} jobs")
    print(f"  3. MatchScorer : Scored {match_stats.get('total_scored', 0)} jobs -> {match_stats.get('high_matches', 0)} strong matches (score >= 60%)")
    print(f"  4. Feed Output : Saved top matches to {feed_path}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_daily_pipeline()
