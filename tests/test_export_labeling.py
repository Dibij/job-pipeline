"""Unit tests for 7.7b export_for_labeling stratum sampling logic.

These tests cover the allocation and stratum-selection functions in isolation —
no database connection required.
"""
import pytest
import sys
from pathlib import Path
import importlib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import the module under test (pure logic, no DB calls at import time)
import scripts.export_for_labeling as efl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_job(job_id: str, match_score: float = 0.0, laya_conf: float | None = None):
    return {
        "id": job_id,
        "title": f"Job {job_id}",
        "company_name": "ACME",
        "location_raw": "Remote",
        "apply_url": "https://example.com",
        "company_url": None,
        "is_remote": True,
        "experience_level": "mid",
        "accessibility": "ACCESSIBLE",
        "match_score": match_score,
        "matched_skills": [],
        "reason_code": None,
        "laya_final_score": laya_conf,
        "laya_avg_confidence": laya_conf,
    }


# ---------------------------------------------------------------------------
# _allocate
# ---------------------------------------------------------------------------

def test_allocate_sums_to_total():
    counts = efl._allocate(30, efl.STRATUM_FRACTIONS)
    assert sum(counts.values()) == 30


def test_allocate_sums_to_total_odd():
    """Remainders go to 'random'."""
    counts = efl._allocate(7, efl.STRATUM_FRACTIONS)
    assert sum(counts.values()) == 7


def test_allocate_no_negative():
    counts = efl._allocate(3, efl.STRATUM_FRACTIONS)
    for v in counts.values():
        assert v >= 0


# ---------------------------------------------------------------------------
# _select_stratum
# ---------------------------------------------------------------------------

def test_select_stratum_high_picks_highest_score():
    pool = [make_job(str(i), match_score=float(i)) for i in range(10)]
    selected = efl._select_stratum(pool, 3, key_fn=lambda r: float(r["match_score"]), ascending=False)
    scores = [r["match_score"] for r in selected]
    assert scores == sorted(scores, reverse=True), "Should pick highest 3 scores"
    assert len(selected) == 3


def test_select_stratum_uncertainty_picks_lowest_confidence():
    pool = [make_job(str(i), laya_conf=float(i) * 0.1) for i in range(10)]
    selected = efl._select_stratum(pool, 3, key_fn=lambda r: float(r["laya_avg_confidence"] or 1.0), ascending=True)
    confs = [r["laya_avg_confidence"] for r in selected]
    assert confs == sorted(confs), "Should pick lowest 3 confidences"


def test_select_stratum_respects_limit():
    pool = [make_job(str(i)) for i in range(5)]
    selected = efl._select_stratum(pool, 10, key_fn=lambda r: 0)
    assert len(selected) <= 5  # can't exceed pool size


# ---------------------------------------------------------------------------
# Laya columns must NOT appear in CSV fieldnames
# ---------------------------------------------------------------------------

def test_laya_columns_absent_from_fieldnames():
    """laya_final_score and laya_avg_confidence must not appear in the exported CSV."""
    forbidden = {"laya_final_score", "laya_avg_confidence", "laya_score", "avg_confidence"}
    fieldnames_set = set(efl.EXPORT_FIELDNAMES)
    for col in forbidden:
        assert col not in fieldnames_set, (
            f"Column '{col}' (Laya internal) must not appear in the exported CSV fieldnames"
        )


# ---------------------------------------------------------------------------
# sampling_stratum and label_guideline_version must be in output columns
# ---------------------------------------------------------------------------

def test_required_columns_present_in_fieldnames():
    fieldnames_set = set(efl.EXPORT_FIELDNAMES)
    assert "sampling_stratum" in fieldnames_set, "sampling_stratum must be a CSV column"
    assert "label_guideline_version" in fieldnames_set, "label_guideline_version must be a CSV column"


# ---------------------------------------------------------------------------
# Laya fallback: when no scored jobs exist, laya_uncertainty uses random
# ---------------------------------------------------------------------------

def test_laya_uncertainty_fallback_to_random_when_no_scored_jobs(monkeypatch):
    """When no jobs have Laya scores, laya_uncertainty should still produce output."""
    import random as _random

    pool = [make_job(str(i), match_score=float(i)) for i in range(20)]
    # No job has laya_avg_confidence
    assert all(r["laya_avg_confidence"] is None for r in pool)

    scored = [r for r in pool if r.get("laya_avg_confidence") is not None]
    assert len(scored) == 0  # confirms the fallback path triggers

    # Simulate the fallback logic from export_labeling_batch
    alloc = efl._allocate(10, efl.STRATUM_FRACTIONS)
    if scored:
        uncertainty_sample = efl._select_stratum(scored, alloc["laya_uncertainty"],
                                                  key_fn=lambda r: float(r["laya_avg_confidence"] or 1.0),
                                                  ascending=True)
    else:
        uncertainty_sample = _random.sample(pool, min(alloc["laya_uncertainty"], len(pool)))

    assert len(uncertainty_sample) > 0
