"""Task 6-3: Daily Pipeline Runner.

Orchestrates full daily execution in sequence:
1. Fetch raw job listings from API sources (Arbeitnow, Remotive, etc.)
2. Normalize and deduplicate into jobs table
3. Run baseline MatchScorer rule matching on all jobs
4. Smart triage: score unlabeled jobs with MatchScorer+Laya, call Ollama on
   interesting candidates, save suggestions JSON for human review in app.py.
   (use_ollama=False by default -- enable manually or via --triage-ollama flag)
5. Regenerate FEED.md with updated top recommendations

Prints a clean summary block at the end.
"""
import argparse
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


def run_daily_pipeline(
    triage_limit: int = 500,
    triage_use_ollama: bool = True,
    triage_ollama_model: str = "qwen2.5:3b",
):
    """Run full daily pipeline.

    Args:
        triage_limit:       Max unlabeled jobs to pass to smart triage (default 500).
        triage_use_ollama:  Call Ollama during triage (default True -- Ollama is the
                            main active-learning engine; disable with --no-triage-ollama
                            if Ollama is not running).
        triage_ollama_model: Ollama model tag (default qwen2.5:3b).
    """
    start_time = time.time()
    logger.info("=" * 65)
    logger.info("  DAILY PIPELINE RUNNER (Task 6-3)")
    logger.info("=" * 65)

    pipeline = JobPipeline()

    # Step 1: Fetch raw listings from API sources
    logger.info("[Step 1/5] Running Job Fetchers...")
    extract_stats = pipeline.run_extractors()

    # Step 2: Normalize and deduplicate into jobs table
    logger.info("[Step 2/5] Normalizing and Deduplicating Staged Listings...")
    norm_stats = pipeline.process_staged()

    # Step 3: Run baseline MatchScorer
    logger.info("[Step 3/5] Scoring Jobs against Candidate Profile...")
    match_stats = score_all_jobs()

    # Step 4: Smart triage (active-learning pipeline)
    logger.info("[Step 4/5] Running Smart Label Triage...")
    triage_stats = {}
    try:
        from scripts.smart_label_triage import run_triage
        triage_stats = run_triage(
            limit=triage_limit,
            use_laya=False,          # stored scores only -- safe for scheduled run
            use_ollama=triage_use_ollama,
            ollama_model=triage_ollama_model,
        )
    except Exception as e:
        # Triage is non-critical: log but don't abort the pipeline
        logger.warning("Smart triage failed (non-critical): %s", e)
        triage_stats = {"error": str(e)}

    # Step 5: Generate FEED.md
    logger.info("[Step 5/5] Exporting FEED.md...")
    feed_path = export_feed(top_n=100)

    duration = time.time() - start_time

    # Summary block
    print("\n" + "=" * 65)
    print(f"  DAILY PIPELINE EXECUTION SUMMARY (Completed in {duration:.1f}s)")
    print("=" * 65)
    print(f"  1. Extraction  : {extract_stats}")
    print(f"  2. Normalized  : Processed {norm_stats.get('processed', 0)} raw -> "
          f"Upserted {norm_stats.get('jobs_upserted', 0)} jobs")
    print(f"  3. MatchScorer : Scored {match_stats.get('total_scored', 0)} jobs -> "
          f"{match_stats.get('high_matches', 0)} strong matches (score >= 60%)")

    if "error" in triage_stats:
        print(f"  4. Triage      : SKIPPED (error: {triage_stats['error']})")
    else:
        buckets = triage_stats.get("buckets", {})
        suggestions = triage_stats.get("suggestions_count", 0)
        eligible = triage_stats.get("eligible", 0)
        out_path = triage_stats.get("out_path")
        print(
            f"  4. Triage      : {eligible} eligible unlabeled | "
            f"STRONG={buckets.get('STRONG_CAND', 0)}  "
            f"CONFLICT={buckets.get('CONFLICT', 0)}  "
            f"UNCERTAIN={buckets.get('UNCERTAIN', 0)}  "
            f"BAD={buckets.get('OBVIOUS_BAD', 0)}"
        )
        if suggestions:
            print(f"     [!] {suggestions} Ollama suggestions -> {out_path}")
            print(f"     Review: python scripts/ingest_triage_suggestions.py {out_path}")
        elif triage_use_ollama:
            print("     No Ollama suggestions generated.")
        else:
            print("     Ollama disabled (run with --triage-ollama to enable).")

    print(f"  5. Feed Output : Saved top matches to {feed_path}")
    print("=" * 65 + "\n")

    return {
        "duration": duration,
        "extract_stats": extract_stats,
        "norm_stats": norm_stats,
        "match_stats": match_stats,
        "triage_stats": triage_stats,
        "feed_path": str(feed_path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the daily job pipeline.")
    parser.add_argument(
        "--no-triage-ollama", action="store_true",
        help="Disable Ollama during triage step (Ollama is ON by default).",
    )
    parser.add_argument(
        "--triage-limit", type=int, default=500,
        help="Max unlabeled jobs to triage per run (default: 500).",
    )
    parser.add_argument(
        "--ollama-model", default="qwen2.5:3b",
        help="Ollama model for triage (default: qwen2.5:3b).",
    )
    args = parser.parse_args()

    run_daily_pipeline(
        triage_limit=args.triage_limit,
        triage_use_ollama=not args.no_triage_ollama,
        triage_ollama_model=args.ollama_model,
    )
