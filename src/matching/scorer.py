"""CV Match and Ranking Engine with word-boundary skill matching."""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "cv_profile.json"

# Skill → compiled regex pattern (word-boundary safe)
# Patterns that shouldn't fire inside larger words get their own re.compile
SKILL_PATTERNS: Dict[str, re.Pattern] = {
    # Primary skills
    "python":       re.compile(r"\bpython\b", re.IGNORECASE),
    "django":       re.compile(r"\bdjango\b", re.IGNORECASE),
    "fastapi":      re.compile(r"\bfastapi\b", re.IGNORECASE),
    "react":        re.compile(r"\breact(?:\.js|js)?\b", re.IGNORECASE),
    "next.js":      re.compile(r"\bnext\.?js\b", re.IGNORECASE),
    "typescript":   re.compile(r"\btypescript\b", re.IGNORECASE),
    "node.js":      re.compile(r"\bnode(?:\.js|js)?\b", re.IGNORECASE),
    "postgresql":   re.compile(r"\bpostgre(?:sql|s)?\b", re.IGNORECASE),
    "javascript":   re.compile(r"\bjavascript\b|\bjs\b", re.IGNORECASE),
    # Deliberately strict — short words cause false positives
    "ai/ml":        re.compile(r"\b(?:machine\s+learning|deep\s+learning|ai/ml|llm|rag|langchain|prompt\s+engineer(?:ing)?)\b", re.IGNORECASE),
    "llm":          re.compile(r"\bllm\b|\blarge\s+language\s+model", re.IGNORECASE),
    "rag":          re.compile(r"\brag\b|\bretrieval[- ]augmented", re.IGNORECASE),
    # Secondary skills
    "docker":       re.compile(r"\bdocker\b", re.IGNORECASE),
    "flutter":      re.compile(r"\bflutter\b", re.IGNORECASE),
    "sql":          re.compile(r"\bsql\b|\bmysql\b|\bsqlite\b", re.IGNORECASE),
    "git":          re.compile(r"\bgit\b(?!hub|lab)", re.IGNORECASE),  # git but NOT github/gitlab
    "rest-api":     re.compile(r"\brest(?:ful)?\s*api[s]?\b|\brest\s+api[s]?\b", re.IGNORECASE),
    "tailwind":     re.compile(r"\btailwind\b", re.IGNORECASE),
}

# Countries/regions that definitively exclude Nepal
NEPAL_EXCLUDING_PATTERNS = [
    re.compile(r"\busa\s*only\b|\bunited\s+states\s*only\b", re.IGNORECASE),
    re.compile(r"\buk\s*only\b|\bunited\s+kingdom\s*only\b", re.IGNORECASE),
    re.compile(r"\beu\s*only\b|\beurope\s*only\b", re.IGNORECASE),
    re.compile(r"\bcanada\s*only\b", re.IGNORECASE),
    re.compile(r"\bgermany\s*only\b|\bdeutschland\s*only\b", re.IGNORECASE),
    re.compile(r"\blatam\s*only\b|\blatin\s+america\s*only\b", re.IGNORECASE),
]

# Listing contains ONLY these without APAC/Asia/Worldwide
STRICT_REGION_LISTS = [
    # If the restriction is strictly Americas only (no APAC)
    re.compile(r"\b(?:northern\s+)?america[n]?\b", re.IGNORECASE),
    re.compile(r"\blatam\b|\blatin\s+america\b", re.IGNORECASE),
]


def _is_nepal_accessible(is_remote: bool, location_raw: str, remote_restriction: str) -> bool:
    """Determine if role is realistically accessible from Nepal (Kathmandu, UTC+5:45)."""
    loc = (location_raw or "").lower()
    restriction = (remote_restriction or "").lower()
    combined = f"{loc} {restriction}"

    # Explicitly mentions Nepal or Kathmandu (on-site or remote)
    if any(kw in combined for kw in ["nepal", "kathmandu", "lalitpur"]):
        return True

    # On-site job not in Nepal → not accessible
    if not is_remote:
        return False

    # Hard exclusions
    for pat in NEPAL_EXCLUDING_PATTERNS:
        if pat.search(combined):
            return False

    # Worldwide / global / APAC friendly
    worldwide_kws = ["worldwide", "anywhere", "global", "all locations", "apac", "south asia", "asia"]
    if any(kw in combined for kw in worldwide_kws):
        return True

    # Strict lists that are Americas/LATAM/Europe only without APAC
    # e.g. "USA, Canada, Argentina, Mexico, Peru" — no Nepal, no Asia, no Worldwide
    # Check if restriction is non-empty and doesn't include any Asia-friendly word
    if restriction:
        # If it lists only specific non-Asian countries, exclude Nepal
        has_apac = any(kw in restriction for kw in ["apac", "asia", "nepal", "worldwide", "global", "anywhere"])
        has_americas_latam = re.search(r"\b(?:argentina|mexico|peru|brazil|colombia|chile|latam|latin america|northern america|usa|canada)\b", restriction, re.IGNORECASE)
        has_europe_only = re.search(r"\b(?:europe|france|germany|spain|portugal|netherlands|israel)\b", restriction, re.IGNORECASE)

        if (has_americas_latam or has_europe_only) and not has_apac:
            return False

    # Remote job, no explicit restriction → assume open
    return True


class MatchScorer:
    """Scores and ranks jobs based on candidate CV profile and hard constraints."""

    def __init__(self, profile_path: Path = DEFAULT_PROFILE_PATH):
        with open(profile_path, "r", encoding="utf-8") as f:
            self.profile = json.load(f)

        self.candidate = self.profile.get("candidate", {})
        self.primary_skills = {s["name"].lower(): s["weight"] for s in self.profile.get("skills", {}).get("primary", [])}
        self.secondary_skills = {s["name"].lower(): s["weight"] for s in self.profile.get("skills", {}).get("secondary", [])}
        self.all_skills = {**self.primary_skills, **self.secondary_skills}
        self.weights = self.profile.get("scoring_weights", {})

    def _skill_present(self, skill: str, title: str, desc: str, tags: List[str]) -> bool:
        """Check if a skill is present with word-boundary regex (no substring false positives)."""
        # First: exact tag match (most reliable)
        if skill in tags:
            return True

        pattern = SKILL_PATTERNS.get(skill)
        if pattern is None:
            # Fallback: safe word-boundary check for skills without a custom pattern
            safe = re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)
            return bool(safe.search(title) or safe.search(desc))

        return bool(pattern.search(title) or pattern.search(desc))

    def score_job(self, job: Dict[str, Any]) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """Compute match score (0.0 - 100.0), matched skills, missing skills, and score breakdown."""
        title = (job.get("title") or "")
        desc = (job.get("description_text") or "")
        tags = [str(t).lower().strip() for t in (job.get("tags") or [])]

        exp_level = (job.get("experience_level") or "unspecified").lower()
        lang = (job.get("detected_language") or "english").lower()
        is_unpaid = bool(job.get("is_unpaid", False))
        is_remote = bool(job.get("is_remote", False))

        # Re-evaluate nepal accessibility with improved logic (don't trust stale DB value alone)
        location_raw = job.get("location_raw") or ""
        remote_restriction = job.get("remote_restriction") or ""
        nepal_accessible = _is_nepal_accessible(is_remote, location_raw, remote_restriction)

        breakdown = {
            "skill_points": 0,
            "seniority_adjustment": 0,
            "language_adjustment": 0,
            "unpaid_adjustment": 0,
            "location_adjustment": 0,
            "remote_bonus": 0,
            "reasons": [],
            "flags": [],
        }

        # ── 1. HARD DISQUALIFIERS & HEAVY PENALTIES ───────────────────────
        if lang == "german":
            breakdown["language_adjustment"] = self.weights.get("german_language_penalty", -100)
            breakdown["reasons"].append("Requires German language")
            breakdown["flags"].append("GERMAN")

        if is_unpaid:
            breakdown["unpaid_adjustment"] = self.weights.get("unpaid_penalty", -100)
            breakdown["reasons"].append("Unpaid or volunteer position")
            breakdown["flags"].append("UNPAID")

        if not nepal_accessible:
            breakdown["location_adjustment"] = self.weights.get("nepal_inaccessible_penalty", -80)
            breakdown["reasons"].append("Region-locked / not accessible from Nepal")
            breakdown["flags"].append("INACCESSIBLE")

        if exp_level == "senior":
            breakdown["seniority_adjustment"] = self.weights.get("senior_penalty", -80)
            breakdown["reasons"].append("Senior / Lead position requiring extensive experience")
            breakdown["flags"].append("SENIOR")
        elif exp_level in ("junior", "intern"):
            breakdown["seniority_adjustment"] = self.weights.get("junior_intern_bonus", 30)
            breakdown["reasons"].append(f"Entry-friendly role ({exp_level.upper()})")

        # Remote bonus only if actually accessible
        if is_remote and nepal_accessible:
            breakdown["remote_bonus"] = self.weights.get("remote_bonus", 15)
            breakdown["reasons"].append("100% remote, globally open")

        # ── 2. TECH SKILLS MATCHING (word-boundary safe) ──────────────────
        matched_skills = []
        earned_skill_points = 0.0

        for skill, weight in self.all_skills.items():
            if self._skill_present(skill, title, desc, tags):
                matched_skills.append(skill)
                earned_skill_points += weight

        # Normalize skill points to a max of 50
        max_possible_points = sum(self.all_skills.values())
        scaled_skill_score = min(
            self.weights.get("tech_stack_max_score", 50),
            (earned_skill_points / max_possible_points) * 100 * 1.5,
        )
        breakdown["skill_points"] = round(scaled_skill_score, 1)

        # ── 3. TOTAL SCORE ─────────────────────────────────────────────────
        raw_total = (
            breakdown["skill_points"]
            + breakdown["seniority_adjustment"]
            + breakdown["language_adjustment"]
            + breakdown["unpaid_adjustment"]
            + breakdown["location_adjustment"]
            + breakdown["remote_bonus"]
        )

        final_score = max(0.0, min(100.0, round(raw_total, 2)))
        breakdown["final_score"] = final_score

        # Missing skills (from job tags that we don't have)
        missing_skills = [
            t for t in tags
            if t not in matched_skills
            and len(t) < 25
            and not any(g in t for g in ["operations", "sales", "community", "marketing", "vente"])
        ][:5]

        return final_score, matched_skills, missing_skills, breakdown
