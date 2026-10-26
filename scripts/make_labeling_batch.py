"""Generate manual labeling batches with title-rule scoring and random discovery split.

Rules:
- Unlabeled jobs: no row in laya_labels.
- Pass HardFilter: evaluate to PASS or NEEDS_REVIEW.
- exclude_reason IS NULL.
- company != 'ElevenLabs'.
- Historical cap: drop any company with >= 5 labeled jobs in laya_labels.
- Batch cap: max 3 jobs per company in this batch, and historical + batch <= 5.
- Title-rule score:
  * Boost (+1): engineer, developer, software, full-stack, backend, frontend, python, ai, ml, data, junior, entry, associate, graduate, intern.
  * Penalty (-2): senior, lead, principal, director, manager, sales, support, marketing, designer, recruiter.
- Split: 70% top title-rule, 30% random.
- Columns: job_id, title, company, location, source, apply_url, sampling_stratum, label_guideline_version, my_label, notes.
- Stamps label_guideline_version='v2_role_fit_only', leaves my_label blank.
- Prints: 'role-fit good_fit (v2 only): X / 30'
"""
import argparse
import csv
from datetime import datetime
import logging
from pathlib import Path
import random
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.hard_filter import apply as apply_hard_filter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"

BOOST_WORDS = [
    "engineer", "developer", "software", "full-stack", "fullstack",
    "backend", "frontend", "python", "ai", "ml", "data",
    "junior", "entry", "associate", "graduate", "intern",
]

PENALTY_WORDS = [
    "senior", "lead", "principal", "director", "manager",
    "sales", "support", "marketing", "designer", "recruiter",
]

_BOOST_RES = [re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in BOOST_WORDS]
_PENALTY_RES = [re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in PENALTY_WORDS]


def score_title_rule(title: str) -> float:
    """Compute title-rule score based on positive keyword boosts and penalty terms."""
    t = title or ""
    score = 0.0
    for r in _BOOST_RES:
        if r.search(t):
            score += 1.0
    for r in _PENALTY_RES:
        if r.search(t):
            score -= 2.0
    return score


def get_historical_company_counts() -> Dict[str, int]:
    """Return map of company_name -> distinct job_ids labeled in laya_labels."""
    rows = execute_query("""
        SELECT LOWER(TRIM(j.company_name)) AS comp, COUNT(DISTINCT l.job_id) AS cnt
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        WHERE j.company_name IS NOT NULL
        GROUP BY LOWER(TRIM(j.company_name));
    """)
    return {r["comp"]: int(r["cnt"]) for r in rows}


def fetch_candidate_pool() -> List[Dict[str, Any]]:
    """Fetch unlabeled, unexcluded jobs passing HardFilter and not capped by company."""
    hist_counts = get_historical_company_counts()
    
    rows = execute_query("""
        SELECT
            j.id,
            j.title,
            j.company_name,
            j.location_raw,
            j.source,
            j.apply_url,
            j.company_url,
            j.description_text,
            j.remote_restriction,
            j.is_remote,
            j.experience_level,
            j.detected_language,
            j.is_unpaid,
            j.nepal_accessible,
            j.tags,
            j.accessibility,
            j.reachable_from_nepal,
            j.reachable_reason
        FROM jobs j
        LEFT JOIN laya_labels l ON j.id = l.job_id
        WHERE l.id IS NULL
          AND j.canonical_job_id IS NULL
          AND j.exclude_reason IS NULL
          AND LOWER(TRIM(COALESCE(j.company_name, ''))) != 'elevenlabs'
        ORDER BY j.created_at DESC;
    """)
    if not rows:
        return []

    eligible = []
    for r in rows:
        comp_clean = (r.get("company_name") or "").strip().lower()
        # Drop companies with >= 5 historical labels
        if hist_counts.get(comp_clean, 0) >= 5:
            continue
        
        # HardFilter pre-gate: only PASS or NEEDS_REVIEW are eligible
        hf_res = apply_hard_filter(r)
        if not hf_res.passed:
            continue
        
        r["title_score"] = score_title_rule(r.get("title") or "")
        eligible.append(r)

    logger.info("Fetched %d raw candidate rows -> %d eligible passing HardFilter", len(rows), len(eligible))
    return eligible


def make_labeling_batch(
    target_count: int = 40,
    output_file: Optional[Path] = None,
    seed: int = 42,
) -> Path:
    """Generate balanced labeling batch (70% top title-rule, 30% random) under company caps."""
    random.seed(seed)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    if output_file is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = DATA_DIR / f"labeling_batch_{stamp}.csv"

    pool = fetch_candidate_pool()
    hist_counts = get_historical_company_counts()

    if not pool:
        logger.warning("No eligible jobs found in candidate pool.")
        return output_file

    total_avail = len(pool)
    n_target = min(target_count, total_avail)
    n_rule = round(0.70 * n_target)
    n_random = n_target - n_rule

    # Track company counts in this batch
    batch_comp_counts: Dict[str, int] = {}
    selected_jobs: List[Tuple[str, Dict[str, Any]]] = []
    selected_ids: Set[str] = set()

    def can_add(job: Dict[str, Any]) -> bool:
        jid = str(job["id"])
        if jid in selected_ids:
            return False
        comp = (job.get("company_name") or "").strip().lower()
        current_in_batch = batch_comp_counts.get(comp, 0)
        hist = hist_counts.get(comp, 0)
        if current_in_batch >= 3:
            return False
        if current_in_batch + hist >= 5:
            return False
        return True

    def add_job(stratum: str, job: Dict[str, Any]):
        jid = str(job["id"])
        comp = (job.get("company_name") or "").strip().lower()
        selected_ids.add(jid)
        batch_comp_counts[comp] = batch_comp_counts.get(comp, 0) + 1
        selected_jobs.append((stratum, job))

    # 1. Stratum: top title-rule score (70%)
    sorted_by_rule = sorted(pool, key=lambda x: x.get("title_score", 0.0), reverse=True)
    for job in sorted_by_rule:
        if len([s for s, _ in selected_jobs if s == "top_title_rule"]) >= n_rule:
            break
        if can_add(job):
            add_job("top_title_rule", job)

    # 2. Stratum: random discovery (30%)
    remaining_candidates = [j for j in pool if can_add(j)]
    random.shuffle(remaining_candidates)
    for job in remaining_candidates:
        if len([s for s, _ in selected_jobs if s == "random"]) >= n_random:
            break
        if can_add(job):
            add_job("random", job)

    # If top_title_rule or random couldn't hit target due to pool size/caps, fill remaining if possible
    if len(selected_jobs) < n_target:
        fill_candidates = [j for j in pool if can_add(j)]
        random.shuffle(fill_candidates)
        for job in fill_candidates:
            if len(selected_jobs) >= n_target:
                break
            add_job("random", job)

    logger.info("Selected %d jobs (%d top_title_rule, %d random) for batch",
                len(selected_jobs),
                sum(1 for s, _ in selected_jobs if s == "top_title_rule"),
                sum(1 for s, _ in selected_jobs if s == "random"))

    # Write CSV
    fieldnames = [
        "job_id",
        "title",
        "company",
        "location",
        "source",
        "apply_url",
        "sampling_stratum",
        "label_guideline_version",
        "my_label",
        "notes",
    ]

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for stratum, j in selected_jobs:
            writer.writerow({
                "job_id": str(j["id"]),
                "title": j.get("title") or "",
                "company": j.get("company_name") or "",
                "location": j.get("location_raw") or "",
                "source": j.get("source") or "",
                "apply_url": j.get("apply_url") or j.get("company_url") or "",
                "sampling_stratum": stratum,
                "label_guideline_version": "v2_role_fit_only",
                "my_label": "",
                "notes": "",
            })

    # Query current role-fit good_fit (v2 only) count
    v2_good_fit_rows = execute_query("""
        SELECT COUNT(DISTINCT l.job_id) AS cnt
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        WHERE l.label_guideline_version = 'v2_role_fit_only'
          AND l.label = 'good_fit'
          AND j.exclude_reason IS NULL;
    """)
    v2_good_count = v2_good_fit_rows[0]["cnt"] if v2_good_fit_rows else 0

    print("\n" + "=" * 65)
    print(f"  LABELING BATCH EXPORTED: {output_file.name}")
    print("=" * 65)
    print(f"  Jobs in batch:      {len(selected_jobs)}")
    print(f"  Target requested:   {target_count}")
    print(f"  Pool available:     {total_avail}")
    print(f"  Output path:        {output_file}")
    print("-" * 65)
    print(f"role-fit good_fit (v2 only): {v2_good_count} / 30")
    print("=" * 65 + "\n")

    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate balanced labeling batch.")
    parser.add_argument("--count", type=int, default=40, help="Target number of jobs (default: 40)")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    out_p = Path(args.output) if args.output else None
    make_labeling_batch(target_count=args.count, output_file=out_p, seed=args.seed)
