"""Wrapper for scheduled execution of daily job pipeline (Step 6).

Features:
- File lock prevents overlapping executions.
- Rotating log file handler in logs/scheduled_run.log.
- Comprehensive error handling with non-zero exit on failure.
- Records execution run metrics to PostgreSQL source_runs.
- Regenerates FEED.md and scores all jobs with current ranker.
"""
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time
import traceback
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from scripts.run_daily import run_daily_pipeline
from scripts.export_feed import export_feed

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "scheduled_run.log"
LOCK_FILE = PROJECT_ROOT / "data" / "pipeline.lock"
LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

# Configure rotating file logging
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(file_formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(file_formatter)

logger = logging.getLogger("scheduled_runner")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


class LockAcquisitionError(Exception):
    pass


class ProcessFileLock:
    """Cross-platform file lock preventing concurrent scheduled pipeline runs."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.handle = None

    def acquire(self):
        try:
            if sys.platform == "win32":
                import msvcrt
                self.handle = open(self.lock_path, "w")
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                self.handle = open(self.lock_path, "w")
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as exc:
            if self.handle:
                try:
                    self.handle.close()
                except Exception:
                    pass
            raise LockAcquisitionError(f"Could not acquire lock on {self.lock_path}: {exc}")

    def release(self):
        if self.handle:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
                self.handle.close()
            except Exception as exc:
                logger.warning("Error releasing lock: %s", exc)


def record_runner_execution(
    run_id: str,
    started_at: datetime,
    fetched: int,
    inserted: int,
    skipped: int,
    error: str = None,
):
    """Log scheduled run outcome to PostgreSQL source_runs."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO source_runs (
                        run_id, source, started_at, fetched, inserted, skipped, error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        run_id,
                        "scheduled_runner",
                        started_at,
                        fetched,
                        inserted,
                        skipped,
                        error,
                    ),
                )
            conn.commit()
    except Exception as exc:
        logger.error("Failed to record runner execution in source_runs: %s", exc)


def main():
    run_id = f"sched_{uuid.uuid4().hex[:8]}"
    start_time = datetime.now(timezone.utc)
    lock = ProcessFileLock(LOCK_FILE)

    logger.info("=" * 65)
    logger.info("  STARTING SCHEDULED PIPELINE RUN [%s]", run_id)
    logger.info("=" * 65)

    try:
        lock.acquire()
        logger.info("Lock acquired on %s", LOCK_FILE)
    except LockAcquisitionError as e:
        logger.error("Execution aborted: %s", e)
        sys.exit(2)

    try:
        # Run daily pipeline (fetch, normalize, score, feed)
        stats = run_daily_pipeline()

        extract_stats = stats.get("extract_stats", {})
        norm_stats = stats.get("norm_stats", {})

        total_fetched = sum(s.get("fetched", 0) for s in extract_stats.values()) if isinstance(extract_stats, dict) else 0
        total_inserted = norm_stats.get("jobs_upserted", 0) if isinstance(norm_stats, dict) else 0
        total_skipped = max(0, total_fetched - total_inserted)

        # Regenerate FEED.md explicitly
        feed_p = export_feed(top_n=100)
        logger.info("FEED.md refreshed: %s", feed_p)

        record_runner_execution(
            run_id=run_id,
            started_at=start_time,
            fetched=total_fetched,
            inserted=total_inserted,
            skipped=total_skipped,
            error=None,
        )

        logger.info("Scheduled pipeline completed successfully in %.1fs", (datetime.now(timezone.utc) - start_time).total_seconds())
        sys.exit(0)

    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.error("Scheduled pipeline FAILED: %s\n%s", err_msg, traceback.format_exc())

        record_runner_execution(
            run_id=run_id,
            started_at=start_time,
            fetched=0,
            inserted=0,
            skipped=0,
            error=err_msg,
        )
        sys.exit(1)

    finally:
        lock.release()
        logger.info("Lock released.")


if __name__ == "__main__":
    main()
