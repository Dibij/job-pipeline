"""Pre-flight leakage and validation guards for evaluation harness.

Ensures complete data integrity across train and test splits:
- Zero job_id overlap between train and test.
- Zero company overlap between train and test (excluding generic 'unknown').
- Zero duplicate description SHA-256 hashes between train and test.
- Strict enforcement of label guideline version ('v2_role_fit_only').
- Fails loudly by raising LeakageViolationError on any detected leak.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set


class LeakageViolationError(Exception):
    """Raised when data leakage or protocol violation is detected between splits."""
    pass


def normalize_company(comp: str | None) -> str:
    """Normalize company name for overlap checking."""
    if not comp:
        return ""
    c = comp.strip().lower()
    return "" if c in ("unknown", "n/a", "none", "") else c


def check_guideline_integrity(records: Sequence[Dict[str, Any]], required_version: str = "v2_role_fit_only") -> None:
    """Assert all records belong strictly to the allowed gold guideline version."""
    invalid = []
    for r in records:
        ver = str(r.get("guideline_version") or "").strip()
        if ver != required_version:
            invalid.append((r.get("job_id"), ver))

    if invalid:
        sample = invalid[:5]
        raise LeakageViolationError(
            f"Protocol violation: {len(invalid)} records have guideline version != '{required_version}'. "
            f"Legacy labels must be strictly excluded from gold sets. Sample violating records: {sample}"
        )


def check_split_leakage(
    train_records: Sequence[Dict[str, Any]],
    test_records: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check for job_id, company, or JD-hash leakage between train and test folds.

    Raises:
        LeakageViolationError: if any leakage is detected.
    Returns:
        Summary dict of checked entities if clean.
    """
    violations: List[str] = []

    # 1. Job ID overlap
    train_job_ids = {str(r["job_id"]).strip() for r in train_records if r.get("job_id")}
    test_job_ids = {str(r["job_id"]).strip() for r in test_records if r.get("job_id")}
    job_overlap = train_job_ids.intersection(test_job_ids)
    if job_overlap:
        violations.append(
            f"Job ID overlap detected ({len(job_overlap)} jobs in both train & test): {list(job_overlap)[:5]}"
        )

    # 2. Company overlap (excluding empty/unknown)
    train_companies = {
        normalize_company(r.get("company"))
        for r in train_records
        if normalize_company(r.get("company"))
    }
    test_companies = {
        normalize_company(r.get("company"))
        for r in test_records
        if normalize_company(r.get("company"))
    }
    company_overlap = train_companies.intersection(test_companies)
    if company_overlap:
        violations.append(
            f"Company overlap detected ({len(company_overlap)} companies in both train & test): {list(company_overlap)[:5]}"
        )

    # 3. Description SHA-256 hash overlap (excluding empty)
    train_hashes = {
        str(r.get("description_hash")).strip()
        for r in train_records
        if r.get("description_hash") and str(r.get("description_hash")).strip()
    }
    test_hashes = {
        str(r.get("description_hash")).strip()
        for r in test_records
        if r.get("description_hash") and str(r.get("description_hash")).strip()
    }
    hash_overlap = train_hashes.intersection(test_hashes)
    if hash_overlap:
        violations.append(
            f"Duplicate description hash overlap ({len(hash_overlap)} identical JDs in both train & test): {list(hash_overlap)[:5]}"
        )

    if violations:
        msg = "Data leakage detected:\n" + "\n".join(f"  - {v}" for v in violations)
        raise LeakageViolationError(msg)

    return {
        "status": "clean",
        "train_jobs": len(train_job_ids),
        "test_jobs": len(test_job_ids),
        "train_companies": len(train_companies),
        "test_companies": len(test_companies),
    }
