"""src/matching/eligibility.py — Unified Candidate Eligibility Service (Task 8.5).

Provides a single source of truth for candidate job eligibility across:
  - run_daily.py (daily scoring & feed generation)
  - service.py (batch scoring service)
  - export_for_labeling.py / make_labeling_batch.py (manual labeling queues)
  - app.py (live web feed & rejection inspector)

Ensures consistent handling of:
  1. DB/Normalization exclude_reason flags (e.g. unparseable_title, board_not_junior_friendly)
  2. HardFilter 5-gate allowlist checks (location, seniority, degree/exp, clearance, language, pay)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.matching.hard_filter import (
    apply as apply_hard_filter,
    FilterReason,
    FilterResult,
)

logger = logging.getLogger(__name__)


def check_eligibility(job: Dict[str, Any] | Any) -> Tuple[bool, FilterResult]:
    """Check whether a single job posting is eligible for candidate scoring and feed.

    Args:
        job: Dictionary or object with job metadata (title, description_text,
             location_raw, remote_restriction, is_remote, detected_language,
             is_unpaid, exclude_reason, etc.).

    Returns:
        (is_eligible, FilterResult):
          - is_eligible is True if the job passes HardFilter (including NEEDS_REVIEW).
          - FilterResult contains the specific reason code and diagnostic detail.
    """
    # 1. Check persistent exclude_reason flag (DB / normalization hygiene)
    exclude_reason = None
    if isinstance(job, dict):
        exclude_reason = job.get("exclude_reason")
    elif hasattr(job, "exclude_reason"):
        exclude_reason = getattr(job, "exclude_reason")

    if exclude_reason:
        return False, FilterResult.fail(
            FilterReason.NON_TECHNICAL,
            f"excluded: {exclude_reason}",
        )

    # 2. Run HardFilter 5-gate allowlist check
    result = apply_hard_filter(job)
    return result.passed, result


def evaluate_batch(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate candidate eligibility across a batch of jobs.

    Returns:
        Dict with keys:
          - passed: List of jobs that passed (includes NEEDS_REVIEW)
          - failed: List of tuples (job, FilterResult)
          - needs_review: List of tuples (job, FilterResult)
          - excluded: List of tuples (job, FilterResult) disqualified via exclude_reason
          - reason_counts: Dict of failure reason code -> count
          - pass_rate: Float ratio of passed / total
          - total: Total number of evaluated jobs
    """
    passed = []
    needs_review = []
    failed = []
    excluded = []
    reason_counts: Dict[str, int] = {
        r.value: 0
        for r in FilterReason
        if r not in (FilterReason.PASS, FilterReason.NEEDS_REVIEW)
    }

    for job in jobs:
        is_ok, result = check_eligibility(job)
        if is_ok:
            if result.reason == FilterReason.NEEDS_REVIEW:
                needs_review.append((job, result))
            passed.append(job)
        else:
            if "excluded:" in result.detail:
                excluded.append((job, result))
            failed.append((job, result))
            reason_counts[result.reason.value] = reason_counts.get(result.reason.value, 0) + 1

    total = len(jobs)
    return {
        "passed": passed,
        "failed": failed,
        "needs_review": needs_review,
        "excluded": excluded,
        "reason_counts": reason_counts,
        "pass_rate": round(len(passed) / total, 3) if total else 0.0,
        "total": total,
    }
