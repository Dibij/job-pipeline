"""Hard filter module (Task 5b-3): pre-scoring disqualification with typed reason codes.

Separates hard disqualifiers from MatchScorer so scoring only runs on jobs
that pass all hard filters. Each rule returns a typed FilterResult with a
reason code, making it easy to audit how many jobs each rule is killing.

Reason codes:
  GERMAN_ONLY         — JD is in German / requires German fluency
  UNPAID              — position is unpaid / equity-only / volunteer
  REGION_LOCKED       — explicitly restricted to regions Nepal cannot access
  NOT_REMOTE          — on-site job outside Nepal
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class FilterReason(str, Enum):
    GERMAN_ONLY = "GERMAN_ONLY"
    UNPAID = "UNPAID"
    REGION_LOCKED = "REGION_LOCKED"
    NOT_REMOTE = "NOT_REMOTE"
    PASS = "PASS"


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: FilterReason
    detail: str = ""

    @classmethod
    def ok(cls) -> "FilterResult":
        return cls(passed=True, reason=FilterReason.PASS)

    @classmethod
    def fail(cls, reason: FilterReason, detail: str = "") -> "FilterResult":
        return cls(passed=False, reason=reason, detail=detail)


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_GERMAN_PATTERNS = [
    re.compile(r"\(m/w/d\)|\(d/m/w\)|\(w/m/d\)", re.IGNORECASE),
    re.compile(
        r"\b(deutsch|deutschkenntnisse|flie\u00dfend deutsch|gute deutschkenntnisse)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(wir suchen|deine aufgaben|das bringst du mit|dein profil|unser angebot|bewerbung)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(berufserfahrung|erfolgreich|unternehmen|standort|bereich|kenntnisse)\b",
        re.IGNORECASE,
    ),
]
_GERMAN_THRESHOLD = 2  # need at least this many pattern hits to call it German

_UNPAID_PATTERNS = [
    re.compile(
        r"\b(unpaid|non-paid|volunteer|volunteering|no compensation|equity only|unvergütet)\b",
        re.IGNORECASE,
    ),
]

# Hard region locks — these phrases explicitly exclude Nepal
_REGION_LOCK_PATTERNS = [
    re.compile(r"\busa\s*only\b|\bunited\s+states\s*only\b", re.IGNORECASE),
    re.compile(r"\buk\s*only\b|\bunited\s+kingdom\s*only\b", re.IGNORECASE),
    re.compile(r"\beu\s*only\b|\beurope\s*only\b", re.IGNORECASE),
    re.compile(r"\bcanada\s*only\b", re.IGNORECASE),
    re.compile(r"\bgermany\s*only\b|\bdeutschland\s*only\b", re.IGNORECASE),
    re.compile(r"\blatam\s*only\b|\blatin\s+america\s*only\b", re.IGNORECASE),
    re.compile(r"\bauthorized\s+to\s+work\s+in\s+the\s+(us|uk|eu|canada)\b", re.IGNORECASE),
    re.compile(r"\bmust\s+(?:be|reside|live)\s+in\s+(?:the\s+)?(?:us|usa|uk|canada|eu|europe)\b", re.IGNORECASE),
]

# Regions that also exclude Nepal unless APAC/Asia/Worldwide is present
_AMERICAS_EU_PATTERNS = re.compile(
    r"\b(?:argentina|mexico|peru|brazil|colombia|chile|latam|latin america"
    r"|northern america|france|germany|spain|portugal|netherlands|israel)\b",
    re.IGNORECASE,
)
_APAC_PATTERNS = re.compile(
    r"\b(?:apac|asia|south asia|nepal|worldwide|global|anywhere|all locations)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Individual filter functions
# ---------------------------------------------------------------------------

def _check_german(title: str, description: str) -> FilterResult:
    combined = f"{title} {description}"
    hits = sum(1 for p in _GERMAN_PATTERNS if p.search(combined))
    if hits >= _GERMAN_THRESHOLD:
        return FilterResult.fail(FilterReason.GERMAN_ONLY, f"{hits} German indicators found")
    return FilterResult.ok()


def _check_unpaid(title: str, description: str) -> FilterResult:
    combined = f"{title} {description}"
    for pat in _UNPAID_PATTERNS:
        m = pat.search(combined)
        if m:
            return FilterResult.fail(FilterReason.UNPAID, f"matched: '{m.group()}'")
    return FilterResult.ok()


def _check_region(
    is_remote: bool,
    location_raw: str,
    remote_restriction: str,
    description: str,
) -> FilterResult:
    loc = (location_raw or "").lower()
    restriction = (remote_restriction or "").lower()
    desc_lower = (description or "").lower()
    combined = f"{loc} {restriction}"

    # Nepal / Kathmandu on-site — always accessible
    if any(kw in combined for kw in ["nepal", "kathmandu", "lalitpur"]):
        return FilterResult.ok()

    # On-site abroad — not accessible
    if not is_remote:
        return FilterResult.fail(FilterReason.NOT_REMOTE, f"on-site: '{location_raw}'")

    # Explicit hard region locks in location/restriction fields
    for pat in _REGION_LOCK_PATTERNS:
        m = pat.search(combined)
        if m:
            return FilterResult.fail(FilterReason.REGION_LOCKED, f"location field: '{m.group()}'")

    # Also check description for authorization language
    for pat in _REGION_LOCK_PATTERNS:
        m = pat.search(desc_lower)
        if m:
            return FilterResult.fail(FilterReason.REGION_LOCKED, f"description: '{m.group()}'")

    # Americas/EU listed without any APAC/Asia/Worldwide qualifier
    if _AMERICAS_EU_PATTERNS.search(combined) and not _APAC_PATTERNS.search(combined):
        return FilterResult.fail(
            FilterReason.REGION_LOCKED,
            "Americas/EU regions listed without APAC/Worldwide",
        )

    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(job: Dict[str, Any]) -> FilterResult:
    """Run all hard filters on a job dict. Returns first failure or PASS.

    Args:
        job: A job record dict with keys: title, description_text, location_raw,
             remote_restriction, is_remote, detected_language, is_unpaid.

    Returns:
        FilterResult — .passed=True means the job cleared all filters.
    """
    title = job.get("title") or ""
    desc = job.get("description_text") or ""
    location_raw = job.get("location_raw") or ""
    remote_restriction = job.get("remote_restriction") or ""
    is_remote = bool(job.get("is_remote", False))

    # Run filters in order of cheapest → most expensive
    result = _check_unpaid(title, desc)
    if not result.passed:
        return result

    result = _check_german(title, desc)
    if not result.passed:
        return result

    result = _check_region(is_remote, location_raw, remote_restriction, desc)
    if not result.passed:
        return result

    return FilterResult.ok()


def apply_batch(jobs: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply hard filter to a list of jobs. Returns passing jobs + reason-code counts.

    Returns:
        {
          "passed": [job, ...],
          "failed": [(job, FilterResult), ...],
          "reason_counts": {"GERMAN_ONLY": N, "UNPAID": N, ...},
          "pass_rate": 0.73,
        }
    """
    passed = []
    failed = []
    reason_counts: Dict[str, int] = {r.value: 0 for r in FilterReason if r != FilterReason.PASS}

    for job in jobs:
        result = apply(job)
        if result.passed:
            passed.append(job)
        else:
            failed.append((job, result))
            reason_counts[result.reason.value] = reason_counts.get(result.reason.value, 0) + 1

    total = len(jobs)
    return {
        "passed": passed,
        "failed": failed,
        "reason_counts": reason_counts,
        "pass_rate": round(len(passed) / total, 3) if total else 0.0,
    }
