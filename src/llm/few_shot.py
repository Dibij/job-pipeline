"""Few-shot example selection for LLM triage prompts (Phase 2d).

Retrieves reference examples strictly from human gold labels (v2_role_fit_only).
Crucially:
- STRICTLY EXCLUDES the target job being judged (zero self-leakage).
- In eval mode, STRICTLY EXCLUDES all job IDs in the current test fold.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GOLD_CSV = PROJECT_ROOT / "evals" / "gold" / "gold_latest.csv"

logger = logging.getLogger(__name__)


def load_human_gold_pool(gold_path: Path = GOLD_CSV) -> List[Dict[str, Any]]:
    """Load human gold pool from gold CSV snapshot."""
    if not gold_path.exists():
        logger.debug("Gold snapshot not found at %s", gold_path)
        return []

    records = []
    with open(gold_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("guideline_version") == "v2_role_fit_only":
                records.append(r)
    return records


def select_few_shot_examples(
    target_job_id: str,
    excluded_job_ids: Optional[Set[str]] = None,
    n_per_class: int = 1,
    gold_pool: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Select balanced few-shot examples from human labels, excluding target and test fold.

    Args:
        target_job_id: ID of the job being judged (never included).
        excluded_job_ids: Optional set of IDs to exclude (e.g. CV test fold).
        n_per_class: Number of examples per label class (good_fit, maybe, bad_fit).
        gold_pool: Optional pre-loaded pool of gold records.

    Returns:
        List of selected example dicts.
    """
    pool = gold_pool if gold_pool is not None else load_human_gold_pool()
    forbidden_ids = {str(target_job_id).strip()}
    if excluded_job_ids:
        forbidden_ids.update(str(jid).strip() for jid in excluded_job_ids)

    # Filter candidates
    by_class: Dict[str, List[Dict[str, Any]]] = {
        "good_fit": [],
        "maybe": [],
        "bad_fit": [],
    }
    for r in pool:
        jid = str(r.get("job_id") or "").strip()
        lbl = str(r.get("label") or "").strip()
        if jid and jid not in forbidden_ids and lbl in by_class:
            by_class[lbl].append(r)

    selected: List[Dict[str, Any]] = []
    # Deterministic selection order for reproducible prompts
    for lbl in ("good_fit", "maybe", "bad_fit"):
        available = by_class[lbl]
        for item in available[:n_per_class]:
            selected.append({
                "job_id": item.get("job_id"),
                "title": item.get("title", ""),
                "company": item.get("company", ""),
                "label": item.get("label", ""),
                "description_snippet": item.get("description_snippet", "")[:200],
            })

    return selected
