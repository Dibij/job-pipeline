"""Export unlabeled jobs to a CSV for human labeling (Task 7.7b).

Implements three-stratum sampling per TRAINING.md §6:
  - 40% random: unbiased sample from all eligible unlabeled jobs
  - 30% high_match_scorer: top MatchScorer-ranked jobs (good positive recall)
  - 30% laya_uncertainty: lowest Laya confidence (falls back to random when <7.8a)

IMPORTANT: Laya score and confidence columns are EXCLUDED from the output CSV
to prevent anchoring bias. The labeler must not see Laya's opinion.

Usage:
    python -m scripts.export_for_labeling --batch-size 30
    python -m scripts.export_for_labeling --batch-size 50 --output data/batch_YYYYMMDD.csv
"""
import argparse
import csv
from datetime import datetime
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LABEL_GUIDELINE_VERSION = "v1"
DATA_DIR = PROJECT_ROOT / "data"

# Stratum allocation fractions (must sum to 1.0)
STRATUM_FRACTIONS = {
    "random": 0.40,
    "high_match_scorer": 0.30,
    "laya_uncertainty": 0.30,
}

# NOTE: Laya internal score & confidence columns are intentionally OMITTED
# to prevent anchoring bias during manual labeling.
EXPORT_FIELDNAMES = [
    "job_id",
    "title",
    "company",
    "location",
    "experience_level",
    "match_score",
    "matched_skills",
    "apply_url",
    "sampling_stratum",
    "label_guideline_version",
    "my_label",    # labeler fills this in
    "notes",       # labeler fills this in
]


def _fetch_eligible_jobs() -> List[Dict[str, Any]]:
    """Return all unlabeled jobs that pass HardFilter pre-gate, with MatchScorer and Laya data."""
    from src.matching.hard_filter import apply as hard_filter_apply

    rows = execute_query("""
        SELECT
            j.id,
            j.title,
            j.company_name,
            j.location_raw,
            j.apply_url,
            j.company_url,
            j.is_remote,
            j.experience_level,
            j.accessibility,
            j.description_text,
            j.remote_restriction,
            j.detected_language,
            j.is_unpaid,
            j.reachable_from_nepal,
            j.reachable_reason,
            COALESCE(m.match_score, 0.0)        AS match_score,
            m.matched_skills,
            m.reason_code,
            -- Laya data: used ONLY for stratum selection, never exported
            l.final_score                        AS laya_final_score,
            l.per_question_data                  AS laya_per_question_data
        FROM jobs j
        LEFT JOIN job_matches m   ON j.canonical_job_id = m.job_id OR j.id = m.job_id
        LEFT JOIN laya_job_scores l ON j.id = l.job_id
        LEFT JOIN laya_labels lbl ON j.id = lbl.job_id
        WHERE lbl.id IS NULL
          AND j.canonical_job_id IS NULL
          AND j.is_remote = true
        ORDER BY m.match_score DESC NULLS LAST
    """)
    if not rows:
        return []

    # Step 6 Pre-gate: Only jobs clearing HardFilter are eligible for the labeling pool
    rows = [r for r in rows if hard_filter_apply(r).passed]
    if not rows:
        return []

    # Calculate average confidence per job from per_question_data
    for r in rows:
        per_q = r.get("laya_per_question_data")
        if isinstance(per_q, str):
            try:
                per_q = json.loads(per_q)
            except Exception:
                per_q = None
        if isinstance(per_q, dict) and per_q:
            confs = [
                float(v["confidence"])
                for v in per_q.values()
                if isinstance(v, dict) and v.get("confidence") is not None
            ]
            r["laya_avg_confidence"] = sum(confs) / len(confs) if confs else None
        else:
            r["laya_avg_confidence"] = None

    return rows


def _select_stratum(
    pool: List[Dict], target_n: int, key_fn, ascending: bool = False
) -> List[Dict]:
    """Select up to target_n items from pool by sorting on key_fn."""
    sorted_pool = sorted(pool, key=key_fn, reverse=not ascending)
    return sorted_pool[:target_n]


def _allocate(total: int, fractions: Dict[str, float]) -> Dict[str, int]:
    """Allocate total into per-stratum integer counts (floor, then give remainder to random)."""
    counts = {k: int(total * f) for k, f in fractions.items()}
    remainder = total - sum(counts.values())
    counts["random"] += remainder  # give rounding remainder to the baseline stratum
    return counts


def export_labeling_batch(
    batch_size: int = 30,
    output_file: Optional[Path] = None,
    seed: int = 42,
) -> Path:
    random.seed(seed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if output_file is None:
        stamp = datetime.now().strftime("%Y%m%d")
        output_file = DATA_DIR / f"labeling_batch_{stamp}.csv"

    logger.info("Fetching eligible unlabeled jobs from DB...")
    all_jobs = _fetch_eligible_jobs()
    if not all_jobs:
        logger.warning("No unlabeled jobs found. Nothing to export.")
        return output_file

    logger.info("Eligible unlabeled pool: %d jobs", len(all_jobs))

    # --- Stratum selection ---
    alloc = _allocate(min(batch_size, len(all_jobs)), STRATUM_FRACTIONS)
    logger.info("Stratum allocation: %s", alloc)

    selected: Dict[str, List[Dict]] = {}

    # 1. high_match_scorer: top by match_score
    selected["high_match_scorer"] = _select_stratum(
        all_jobs, alloc["high_match_scorer"],
        key_fn=lambda r: float(r["match_score"] or 0),
        ascending=False,
    )

    # 2. laya_uncertainty: lowest avg_confidence among jobs that HAVE a Laya score
    #    Falls back to random sample when no scored jobs exist.
    scored = [r for r in all_jobs if r.get("laya_avg_confidence") is not None]
    if scored:
        selected["laya_uncertainty"] = _select_stratum(
            scored, alloc["laya_uncertainty"],
            key_fn=lambda r: float(r["laya_avg_confidence"] or 1.0),
            ascending=True,  # ascending → lowest confidence first
        )
    else:
        logger.info("No Laya-scored jobs found; laya_uncertainty falls back to random.")
        selected["laya_uncertainty"] = random.sample(
            all_jobs, min(alloc["laya_uncertainty"], len(all_jobs))
        )

    # 3. random: from what remains after the other two strata (de-duped by id)
    used_ids = {str(r["id"]) for pool in selected.values() for r in pool}
    remaining = [r for r in all_jobs if str(r["id"]) not in used_ids]
    n_random = min(alloc["random"], len(remaining))
    selected["random"] = random.sample(remaining, n_random) if remaining else []

    # Flatten and tag with stratum
    entries = []
    for stratum, rows in selected.items():
        for r in rows:
            entries.append((stratum, r))

    logger.info(
        "Selected %d jobs  (%d random, %d high_match_scorer, %d laya_uncertainty)",
        len(entries),
        len(selected["random"]),
        len(selected["high_match_scorer"]),
        len(selected["laya_uncertainty"]),
    )

    # --- Write CSV ---
    fieldnames = EXPORT_FIELDNAMES

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for stratum, r in entries:
            skills = r.get("matched_skills") or []
            if isinstance(skills, str):
                try:
                    import json
                    skills = json.loads(skills)
                except Exception:
                    skills = []
            link = r.get("apply_url") or r.get("company_url") or ""

            writer.writerow({
                "job_id": str(r["id"]),
                "title": r.get("title") or "Untitled",
                "company": r.get("company_name") or "Unknown",
                "location": r.get("location_raw") or ("Remote" if r.get("is_remote") else ""),
                "experience_level": r.get("experience_level") or "",
                "match_score": round(float(r.get("match_score") or 0), 1),
                "matched_skills": ", ".join(skills[:5]) if skills else "",
                "apply_url": link,
                "sampling_stratum": stratum,
                "label_guideline_version": LABEL_GUIDELINE_VERSION,
                "my_label": "",
                "notes": "",
            })

    print(f"\n{'=' * 65}")
    print(f"  LABELING BATCH EXPORTED: {output_file}")
    print(f"{'=' * 65}")
    print(f"  Total jobs:        {len(entries)}")
    print(f"  random:            {len(selected['random'])}")
    print(f"  high_match_scorer: {len(selected['high_match_scorer'])}")
    print(f"  laya_uncertainty:  {len(selected['laya_uncertainty'])}")
    print(f"  guideline version: {LABEL_GUIDELINE_VERSION}")
    print(f"{'-' * 65}")
    print(f"  Fill 'my_label': good_fit | maybe | bad_fit")
    print(f"  Do NOT look at Laya scores before labeling (they are not in this file).")
    print(f"  Ingest: python -m scripts.ingest_labels {output_file}\n")

    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export labeling batch with 3-stratum sampling.")
    parser.add_argument("--batch-size", type=int, default=30, help="Total jobs to export.")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    # Legacy flag retained for backward compatibility
    parser.add_argument("--no-rescore", action="store_true", help="(legacy, no-op)")
    args = parser.parse_args()

    out = Path(args.output) if args.output else None
    export_labeling_batch(batch_size=args.batch_size, output_file=out, seed=args.seed)
