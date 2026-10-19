"""Hard filter module (Tasks 5b-3, 5c.2c, 5c.2d): pre-scoring disqualification.

Separates hard disqualifiers from MatchScorer so scoring only runs on jobs
that pass all hard filters. Each rule returns a typed FilterResult with a
reason code, making it easy to audit how many jobs each rule is killing.

Reason codes:
  NON_ENGLISH         -- JD is not in English (French, German, etc.)
  GERMAN_ONLY         -- Legacy alias kept so existing DB rows are not broken
  UNPAID              -- position is unpaid / equity-only / volunteer
  REGION_LOCKED       -- explicitly restricted to regions Nepal cannot access
  NOT_REMOTE          -- on-site job outside Nepal
  NON_TECHNICAL       -- role type is explicitly non-technical (per config blocklist)
  NEEDS_REVIEW        -- ambiguous region; passes but flagged for review

5c.2c changes:
  - Detect non-English generally using detected_language field first (cheap).
  - Fallback: pattern-match title+description for French/German indicators.
  - Reason code renamed NON_ENGLISH; GERMAN_ONLY kept as alias.

5c.2d changes:
  - Explicit country-only location strings that exclude Nepal are blocked.
  - Ambiguous regions (APAC, Asia, Worldwide) are NOT blocked but get
    NEEDS_REVIEW reason code so they appear in a separate feed bucket.
  - Swiss-only, USA-only, UK-only etc. detected from location_raw alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from src.enrichment.enricher import JobEnricher


class FilterReason(str, Enum):
    NON_ENGLISH = "NON_ENGLISH"
    GERMAN_ONLY = "NON_ENGLISH"    # legacy alias — same value, same DB rows
    UNPAID = "UNPAID"
    REGION_LOCKED = "REGION_LOCKED"
    NOT_REMOTE = "NOT_REMOTE"
    NON_TECHNICAL = "NON_TECHNICAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    # Allowlist-era codes (brief §5)
    NOT_ELIGIBLE_REGION = "NOT_ELIGIBLE_REGION"  # remote but region locked out of ALLOWED_REMOTE_TAGS
    TOO_SENIOR = "TOO_SENIOR"                    # title hits BLOCKED_SENIORITY
    DEGREE_OR_EXP = "DEGREE_OR_EXP"             # DEGREE_HARD_RE or YEARS_RE (3+ yrs)
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

    @classmethod
    def review(cls, detail: str = "") -> "FilterResult":
        """Pass but flag for human review (ambiguous region)."""
        return cls(passed=True, reason=FilterReason.NEEDS_REVIEW, detail=detail)


# ---------------------------------------------------------------------------
# Non-English detection (5c.2c)
# ---------------------------------------------------------------------------
# Known non-English detected_language values from the enricher
_NON_ENGLISH_LANGS = {
    "german", "french", "spanish", "portuguese", "dutch", "italian",
    "polish", "russian", "turkish", "arabic", "japanese", "chinese",
    "korean", "hindi",
}

# French text patterns (title/desc fallback when detected_language is missing/wrong)
_FRENCH_PATTERNS = [
    re.compile(r"\b(nous recherchons|votre mission|vos missions|profil recherch[eé])\b", re.IGNORECASE),
    re.compile(r"\b(d[eé]veloppeur|ing[eé]nieur|technicien|responsable|chef de)\b", re.IGNORECASE),
    re.compile(r"\b(poste [àa] pourvoir|rejoindre notre[eé]quipe|exp[eé]rience requise)\b", re.IGNORECASE),
]
_FRENCH_THRESHOLD = 2

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
_GERMAN_THRESHOLD = 2


def _check_language(title: str, description: str, detected_language: str) -> FilterResult:
    """Block non-English jobs. Uses detected_language first, then pattern fallback."""
    lang = (detected_language or "").lower().strip()

    # Fast path: enricher already classified it
    if lang and lang not in ("", "english", "en"):
        if lang in _NON_ENGLISH_LANGS or lang != "english":
            return FilterResult.fail(FilterReason.NON_ENGLISH, f"detected_language={lang!r}")

    # Fallback pattern check (catches mislabelled or undetected cases)
    combined = f"{title} {description}"
    french_hits = sum(1 for p in _FRENCH_PATTERNS if p.search(combined))
    if french_hits >= _FRENCH_THRESHOLD:
        return FilterResult.fail(FilterReason.NON_ENGLISH, f"{french_hits} French pattern hits")

    german_hits = sum(1 for p in _GERMAN_PATTERNS if p.search(combined))
    if german_hits >= _GERMAN_THRESHOLD:
        return FilterResult.fail(FilterReason.NON_ENGLISH, f"{german_hits} German pattern hits")

    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Unpaid detection
# ---------------------------------------------------------------------------
_UNPAID_PATTERNS = [
    re.compile(r"\b(?:unpaid|non-paid|unvergütet)\s+(?:internship|intern|position|role|job|opportunity|work|contract)\b", re.IGNORECASE),
    re.compile(r"\b(?:this\s+(?:is\s+an?|role\s+is|position\s+is|internship\s+is))\s+(?:unpaid|non-paid|unvergütet)\b", re.IGNORECASE),
    re.compile(r"\b(?:position|role|internship|job)\s+is\s+(?:unpaid|non-paid|unvergütet)\b", re.IGNORECASE),
    re.compile(r"\bunpaid\s+volunteer\b", re.IGNORECASE),
    re.compile(r"\b(?:no\s+compensation|equity\s+only)\b", re.IGNORECASE),
    re.compile(r"^\s*\(?unpaid\)?\b", re.IGNORECASE),
    re.compile(r"\bvolunteer\s+(?:developer|engineer|programmer|intern|position|role)\b", re.IGNORECASE),
    re.compile(r"^\s*\(?volunteer\)?\s+\w+", re.IGNORECASE),
]


def _check_unpaid(title: str, description: str) -> FilterResult:
    combined = f"{title} {description}"
    for pat in _UNPAID_PATTERNS:
        m = pat.search(combined)
        if m:
            return FilterResult.fail(FilterReason.UNPAID, f"matched: '{m.group()}'")
    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Gate 2 — Seniority & Degree check (brief §5)
# ---------------------------------------------------------------------------

BLOCKED_SENIORITY = frozenset({
    "senior", "staff", "principal", "lead", "manager", "director",
    "head", "vp", "vice president", "chief", "cto", "ceo", "coo", "cpo",
})

# Matches explicit degree requirement phrasing (bachelor's/degree + required/must)
_DEGREE_HARD_RE = re.compile(
    r"\b(bachelor'?s?|b\.?s\.?c?|degree)\b.{0,40}\b(required|must)\b",
    re.IGNORECASE,
)

# Matches 3+ years of experience requirement
_YEARS_RE = re.compile(
    r"\b([3-9]|[1-9][0-9])\+?\s*(?:years?|yrs?)\b.{0,30}\b(experience|exp\.?|background)\b",
    re.IGNORECASE,
)


def _check_seniority_degree(title: str, description: str) -> FilterResult:
    """Block roles that require seniority or a completed degree (Gate 2)."""
    title_lower = (title or "").lower()

    # Title seniority word check
    for word in BLOCKED_SENIORITY:
        if re.search(r"\b" + re.escape(word) + r"\b", title_lower):
            return FilterResult.fail(FilterReason.TOO_SENIOR, f"title contains seniority word: {word!r}")

    combined = f"{title} {description}"

    # Hard degree requirement in description
    m = _DEGREE_HARD_RE.search(combined)
    if m:
        return FilterResult.fail(FilterReason.DEGREE_OR_EXP, f"degree required: {m.group()!r}")

    # 3+ years of experience required
    m = _YEARS_RE.search(combined)
    if m:
        return FilterResult.fail(FilterReason.DEGREE_OR_EXP, f"experience required: {m.group()!r}")

    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Region / accessibility check (5c.2d)
# ---------------------------------------------------------------------------

# Hard country-only strings: single-country remote means Nepal cannot apply
# These match when the location_raw is ONLY that country (no open qualifier)
_COUNTRY_ONLY_PATTERNS = [
    # Single explicit country without qualifier
    re.compile(r"^(remote\s*[-–]?\s*)?(usa|united states?|us)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(uk|united kingdom|great britain)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(canada)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(switzerland|suisse|schweiz)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(germany|deutschland)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(france|frankreich)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(australia|australie)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(ireland|irland)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(netherlands|niederlande|pays-bas)$", re.IGNORECASE),
    re.compile(r"^(remote\s*[-–]?\s*)?(spain|spanien|espagne)$", re.IGNORECASE),
]

# Hard lock phrases in any field — definitely blocks Nepal
_HARD_LOCK_PATTERNS = [
    re.compile(r"\busa\s*only\b|\bunited\s+states?\s*only\b", re.IGNORECASE),
    re.compile(r"\buk\s*only\b|\bunited\s+kingdom\s*only\b", re.IGNORECASE),
    re.compile(r"\beu\s*only\b|\beurope\s*only\b", re.IGNORECASE),
    re.compile(r"\bcanada\s*only\b", re.IGNORECASE),
    re.compile(r"\bgermany\s*only\b|\bdeutschland\s*only\b", re.IGNORECASE),
    re.compile(r"\blatam\s*only\b|\blatin\s+america\s*only\b", re.IGNORECASE),
    re.compile(r"\bauthorized\s+to\s+work\s+in\s+the\s+(us|uk|eu|canada)\b", re.IGNORECASE),
    re.compile(r"\bmust\s+(?:be|reside|live)\s+in\s+(?:the\s+)?(?:us|usa|uk|canada|eu|europe)\b", re.IGNORECASE),
]

# Ambiguous multi-region qualifiers — may include Nepal: do NOT block, flag for review
_OPEN_QUALIFIERS = re.compile(
    r"\b(worldwide|global|anywhere|all locations|apac|asia|south asia|nepal|kathmandu)\b",
    re.IGNORECASE,
)

# Exclusive regions that exclude Nepal when listed WITHOUT an open qualifier
_EXCLUSIVE_REGION_PATTERN = re.compile(
    r"\b(?:argentina|mexico|peru|brazil|colombia|chile|latam|latin america"
    r"|northern america|usa|united states|canada|uk|united kingdom"
    r"|switzerland|france|germany|spain|netherlands|israel|norway|turkey)\b",
    re.IGNORECASE,
)


def _check_region(
    title: str,
    is_remote: bool,
    location_raw: str,
    remote_restriction: str,
    description: str,
    accessibility: Optional[str] = None,
    reachable_from_nepal: Optional[str] = None,
    reachable_reason: Optional[str] = None,
) -> FilterResult:
    reach = reachable_from_nepal
    reason = reachable_reason
    if not reach:
        reach, reason = JobEnricher.detect_reachability(
            title, description, location_raw, remote_restriction, is_remote
        )

    if reach == "blocked":
        if not is_remote:
            return FilterResult.fail(FilterReason.NOT_REMOTE, f"on-site: {location_raw!r}")
        return FilterResult.fail(FilterReason.REGION_LOCKED, f"{reason}: {location_raw!r}")
    elif reach == "unknown":
        return FilterResult.review(f"location not stated / unknown: {reason}")
    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Non-technical title check (5c.2e) — blocklist loaded from config
# ---------------------------------------------------------------------------
_CV_PROFILE_PATH = Path(__file__).resolve().parent / "cv_profile.json"
_NON_TECH_BLOCKLIST: List[str] = []

def _load_nontechnical_blocklist(path: Path = _CV_PROFILE_PATH) -> List[str]:
    """Load non_technical_title_blocklist from cv_profile.json."""
    try:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        return [kw.lower() for kw in profile.get("non_technical_title_blocklist", [])]
    except Exception:
        return []

# Loaded once at import time; can be reloaded in tests
def _get_blocklist() -> List[str]:
    global _NON_TECH_BLOCKLIST
    if not _NON_TECH_BLOCKLIST:
        _NON_TECH_BLOCKLIST = _load_nontechnical_blocklist()
    return _NON_TECH_BLOCKLIST


def _check_non_technical(title: str) -> FilterResult:
    """Block jobs whose title contains a non-technical keyword from the config blocklist."""
    title_lower = (title or "").lower()
    for kw in _get_blocklist():
        if re.search(r"\b" + re.escape(kw) + r"\b", title_lower):
            return FilterResult.fail(FilterReason.NON_TECHNICAL, f"title contains blocklist keyword: {kw!r}")
    return FilterResult.ok()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(job: Dict[str, Any]) -> FilterResult:
    """Run all hard filters on a job dict. Returns first failure or PASS.

    Args:
        job: dict with keys: title, description_text, location_raw,
             remote_restriction, is_remote, detected_language, is_unpaid.

    Returns:
        FilterResult — .passed=True means job cleared all filters.
                       reason=NEEDS_REVIEW means it passed but is flagged.
    """
    title = job.get("title") or ""
    desc = job.get("description_text") or ""
    location_raw = job.get("location_raw") or ""
    remote_restriction = job.get("remote_restriction") or ""
    is_remote = bool(job.get("is_remote", False))
    detected_language = job.get("detected_language") or ""

    # 0. Remote check: If not remote, and location is outside Nepal, immediately disqualify
    loc_combined = f"{location_raw} {remote_restriction}".lower()
    is_nepal_local = any(k in loc_combined for k in ["nepal", "kathmandu", "lalitpur", "pokhara", "patan"])
    if not is_remote and not is_nepal_local:
        return FilterResult.fail(FilterReason.NOT_REMOTE, f"on-site or hybrid role outside Nepal: {location_raw!r}")

    # Cheapest first
    result = _check_unpaid(title, desc)
    if not result.passed:
        return result

    result = _check_language(title, desc, detected_language)
    if not result.passed:
        return result

    # Gate 2 — seniority & degree (allowlist-era, brief §5)
    result = _check_seniority_degree(title, desc)
    if not result.passed:
        return result

    result = _check_non_technical(title)
    if not result.passed:
        return result

    accessibility = job.get("accessibility")
    reachable_from_nepal = job.get("reachable_from_nepal")
    reachable_reason = job.get("reachable_reason")
    result = _check_region(
        title, is_remote, location_raw, remote_restriction, desc,
        accessibility=accessibility,
        reachable_from_nepal=reachable_from_nepal,
        reachable_reason=reachable_reason,
    )
    if not result.passed:
        return result

    # NEEDS_REVIEW is a pass — return it so it can be stored
    if result.reason == FilterReason.NEEDS_REVIEW:
        return result

    return FilterResult.ok()


def apply_batch(jobs: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply hard filter to a list of jobs.

    Returns:
        {
          "passed": [job, ...],           # includes NEEDS_REVIEW
          "failed": [(job, FilterResult)],
          "needs_review": [(job, FilterResult)],
          "reason_counts": {"NON_ENGLISH": N, ...},
          "pass_rate": 0.73,
        }
    """
    passed = []
    needs_review = []
    failed = []
    reason_counts: Dict[str, int] = {
        r.value: 0 for r in FilterReason
        if r not in (FilterReason.PASS, FilterReason.NEEDS_REVIEW)
    }

    for job in jobs:
        result = apply(job)
        if result.passed:
            if result.reason == FilterReason.NEEDS_REVIEW:
                needs_review.append((job, result))
                passed.append(job)
            else:
                passed.append(job)
        else:
            failed.append((job, result))
            reason_counts[result.reason.value] = reason_counts.get(result.reason.value, 0) + 1

    total = len(jobs)
    return {
        "passed": passed,
        "failed": failed,
        "needs_review": needs_review,
        "reason_counts": reason_counts,
        "pass_rate": round(len(passed) / total, 3) if total else 0.0,
    }
