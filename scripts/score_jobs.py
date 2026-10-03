"""scripts/score_jobs.py — Task 7.6: Batch Laya scoring pipeline.

Scores all jobs that pass the plain-code hard filters (detected_language = 'english'
and nepal_accessible = true) and writes results to laya_job_scores.

Resumable: jobs already scored with the same (laya_checkpoint, config_version)
are skipped automatically using the unique index on laya_job_scores.

Usage:
    # Score first 20 jobs and show timing (required before full run):
    python scripts/score_jobs.py --limit 20

    # Score all eligible jobs (only after reviewing --limit 20 timing):
    python scripts/score_jobs.py

    # Dry-run: show eligible jobs without scoring:
    python scripts/score_jobs.py --dry-run

    # Use a specific config file:
    python scripts/score_jobs.py --config path/to/laya_questions.yaml
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.laya_scorer import LayaScorer

LAYA_CHECKPOINT = "convaiinnovations/laya"


def compute_config_version(config_path: Path) -> str:
    """Return a short SHA-256 hash of the YAML config for version tracking."""
    with open(config_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return digest[:12]


def apply_migration():
    """Apply the laya_job_scores migration if the table does not yet exist.

    psycopg3 execute() only handles one statement at a time, so we strip
    line comments and split on semicolons before executing each statement.
    """
    migration_path = PROJECT_ROOT / "src" / "db" / "migrations" / "004_laya_job_scores.sql"
    if not migration_path.exists():
        print(f"[ERROR] Migration file not found: {migration_path}")
        sys.exit(1)
    raw_sql = migration_path.read_text(encoding="utf-8")

    # Strip single-line comments (-- ...) to avoid false semicolons inside comments
    lines = []
    for line in raw_sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue  # skip pure-comment lines
        # Inline comment: keep code before --
        if "--" in stripped:
            line = line[: line.index("--")]
        lines.append(line)
    clean_sql = "\n".join(lines)

    # Split on semicolons and execute each non-empty statement
    for stmt in clean_sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            execute_query(stmt + ";")
    print("[DB] Migration 004_laya_job_scores applied (or already exists).")


def fetch_eligible_jobs(limit: int | None = None) -> list[dict]:
    """Fetch jobs that pass the plain-code hard filters."""
    limit_clause = f"LIMIT {limit}" if limit is not None else ""
    rows = execute_query(f"""
        SELECT id, title, company_name, location_raw, is_remote, description_text
        FROM jobs
        WHERE detected_language = 'english'
          AND nepal_accessible = true
        ORDER BY id
        {limit_clause};
    """)
    return rows or []


def fetch_already_scored(checkpoint: str, config_version: str) -> set[str]:
    """Return the set of job_ids already scored with this checkpoint+config."""
    rows = execute_query("""
        SELECT job_id::text
        FROM laya_job_scores
        WHERE laya_checkpoint = %s
          AND config_version  = %s;
    """, (checkpoint, config_version))
    return {r["job_id"] for r in rows} if rows else set()


def upsert_score(result, checkpoint: str, config_version: str):
    """Insert a scored job into laya_job_scores; skip if already present."""
    # Serialize per-question data
    per_question: dict = {}
    for q_id, q_res in result.questions.items():
        per_question[q_id] = {
            "type": q_res.question_type,
            "raw": q_res.raw_value if not isinstance(q_res.raw_value, bool) else bool(q_res.raw_value),
            "normalized": round(q_res.normalized_value, 4),
            "confidence": round(q_res.confidence, 4),
            "answer_confidence": round(q_res.answer_confidence, 4),
            "probabilities": q_res.probabilities,
        }

    execute_query("""
        INSERT INTO laya_job_scores
            (job_id, final_score, is_passed, disqualification_reason,
             needs_review, role_type, gate_warnings, per_question_data,
             laya_checkpoint, config_version, tokens_used)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
        ON CONFLICT (job_id, laya_checkpoint, config_version)
        DO NOTHING;
    """, (
        result.job_id,
        result.final_score,
        result.is_passed,
        result.disqualification_reason,
        result.needs_review,
        result.role_type,
        json.dumps(result.gate_warnings),
        json.dumps(per_question),
        checkpoint,
        config_version,
        result.tokens_used,
    ))


def main():
    parser = argparse.ArgumentParser(description="Batch Laya job scorer (Task 7.6)")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max number of jobs to score this run. Omit to score all eligible jobs."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List eligible jobs without scoring them."
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="Path to laya_questions.yaml. Defaults to config/laya_questions.yaml."
    )
    args = parser.parse_args()

    config_path = args.config or (PROJECT_ROOT / "config" / "laya_questions.yaml")
    config_version = compute_config_version(config_path)
    checkpoint = LAYA_CHECKPOINT

    print("=" * 65)
    print("  BATCH LAYA SCORER (Task 7.6)")
    print("=" * 65)
    print(f"  Checkpoint  : {checkpoint}")
    print(f"  Config ver  : {config_version}")
    print(f"  Config path : {config_path}")
    if args.limit:
        print(f"  Limit       : {args.limit} jobs")
    else:
        print("  Limit       : ALL eligible jobs")
    print()

    # Ensure table exists
    if not args.dry_run:
        apply_migration()

    # Fetch eligible jobs
    jobs = fetch_eligible_jobs(limit=args.limit)
    print(f"[INFO] Found {len(jobs)} eligible job(s) matching hard filters.")

    if not jobs:
        print("[INFO] Nothing to score. Exiting.")
        return

    if args.dry_run:
        print("\n[DRY-RUN] Eligible jobs (not scored):")
        for i, job in enumerate(jobs, 1):
            print(f"  {i:3}. {job['title'][:50]:<50}  ({job['company_name']})")
        return

    # Find already-scored jobs
    already_done = fetch_already_scored(checkpoint, config_version)
    to_score = [j for j in jobs if str(j["id"]) not in already_done]

    print(f"[INFO] Already scored (this checkpoint+config): {len(already_done)}")
    print(f"[INFO] To score this run                      : {len(to_score)}")

    if not to_score:
        print("[INFO] All jobs already scored. Nothing to do.")
        return

    # Load model once
    print("\n[MODEL] Loading Laya...")
    t_load = time.perf_counter()
    scorer = LayaScorer(config_path=config_path, device="cpu")
    print(f"[MODEL] Ready in {time.perf_counter() - t_load:.1f}s\n")

    times: list[float] = []
    passed = 0
    failed = 0

    for i, job in enumerate(to_score, 1):
        safe_title = job["title"].encode("ascii", "replace").decode("ascii")
        safe_co = job["company_name"].encode("ascii", "replace").decode("ascii")

        t0 = time.perf_counter()
        result = scorer.score_job(job)
        elapsed = time.perf_counter() - t0
        times.append(elapsed)

        upsert_score(result, checkpoint, config_version)

        status = "PASS" if result.is_passed else "DISQ"
        if result.is_passed:
            passed += 1
        else:
            failed += 1

        # Running stats
        avg_t = sum(times) / len(times)
        remaining = len(to_score) - i
        eta_s = avg_t * remaining

        print(
            f"[{i:3}/{len(to_score)}] {safe_title[:35]:<35} @ {safe_co[:15]:<15} | "
            f"{status} {result.final_score:5.1f}/100 | "
            f"{elapsed:.1f}s | avg {avg_t:.1f}s | ETA {eta_s:.0f}s"
        )

    # Final summary
    total_t = sum(times)
    avg_t = total_t / len(times) if times else 0.0
    print()
    print("=" * 65)
    print(f"  Scored : {len(times)} jobs  |  PASSED: {passed}  |  DISQ: {failed}")
    print(f"  Time   : {total_t:.1f}s total  |  {avg_t:.1f}s per job")
    print("=" * 65)


if __name__ == "__main__":
    main()
