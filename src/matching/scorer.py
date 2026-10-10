"""CV Match and Ranking Engine with word-boundary skill matching."""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.enrichment.enricher import JobEnricher
from src.matching.jd_extractor import extract_sections

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "cv_profile.json"

# Skill → compiled regex pattern (word-boundary safe)
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


def _is_nepal_accessible(is_remote: bool, location_raw: str, remote_restriction: str) -> bool:
    """Determine if role is realistically accessible from Nepal (Kathmandu, UTC+5:45)."""
    loc = (location_raw or "").lower()
    restriction = (remote_restriction or "").lower()
    combined = f"{loc} {restriction}"

    if any(kw in combined for kw in ["nepal", "kathmandu", "lalitpur"]):
        return True

    if not is_remote:
        return False

    for pat in NEPAL_EXCLUDING_PATTERNS:
        if pat.search(combined):
            return False

    worldwide_kws = ["worldwide", "anywhere", "global", "all locations", "apac", "south asia", "asia"]
    if any(kw in combined for kw in worldwide_kws):
        return True

    if restriction:
        has_apac = any(kw in restriction for kw in ["apac", "asia", "nepal", "worldwide", "global", "anywhere"])
        has_americas_latam = re.search(r"\b(?:argentina|mexico|peru|brazil|colombia|chile|latam|latin america|northern america|usa|canada)\b", restriction, re.IGNORECASE)
        has_europe_only = re.search(r"\b(?:europe|france|germany|spain|portugal|netherlands|israel)\b", restriction, re.IGNORECASE)

        if (has_americas_latam or has_europe_only) and not has_apac:
            return False

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
        self.technical_title_signals = [
            s.lower() for s in self.profile.get("technical_title_signals", [
                "engineer", "developer", "programmer", "data scientist"
            ])
        ]
        self.placeholder_title_patterns = self.profile.get(
            "placeholder_title_patterns", ["template", "test"]
        )

    def is_placeholder_title(self, title: str) -> bool:
        """Check if job title matches known placeholder indicators ('template', 'test')."""
        t = (title or "").strip()
        for pat in self.placeholder_title_patterns:
            p_lower = pat.lower()
            if p_lower == "template":
                if re.search(r"\btemplate\b", t, re.IGNORECASE):
                    return True
            elif p_lower == "test":
                if re.search(r"^\s*\[?test\]?\s*$", t, re.IGNORECASE):
                    return True
                if re.search(r"\btest\s+(?:job|posting|position|role|title)\b", t, re.IGNORECASE):
                    return True
            else:
                if re.search(r"\b" + re.escape(pat) + r"\b", t, re.IGNORECASE):
                    return True
        return False

    def has_technical_title_signal(self, title: str) -> bool:
        """Check if job title contains a technical signal keyword from cv_profile.json."""
        t = (title or "").strip()
        return any(
            bool(re.search(r"\b" + re.escape(sig) + r"\b", t, re.IGNORECASE))
            for sig in self.technical_title_signals
        )

    def is_feed_eligible(self, title: str, matched_skills: List[str]) -> Tuple[bool, Optional[str]]:
        """Check whether a job meets the feed threshold (Task 6b):
        - Must NOT be a placeholder title ('template', 'test').
        - Must have matched skills OR a technical title signal.
        """
        if self.is_placeholder_title(title):
            return False, "PLACEHOLDER"
        if len(matched_skills) > 0 or self.has_technical_title_signal(title):
            return True, None
        return False, "NO_TECH_SIGNAL"

    def _skill_present(self, skill: str, title: str, target_text: str, tags: List[str]) -> bool:
        """Check if a skill is present in target sections or tags with word-boundary regex."""
        if skill in tags:
            return True

        pattern = SKILL_PATTERNS.get(skill)
        if pattern is None:
            safe = re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)
            return bool(safe.search(title) or safe.search(target_text))

        return bool(pattern.search(title) or pattern.search(target_text))

    def score_job(self, job: Dict[str, Any]) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """Compute match score (0.0 - 100.0), matched skills, missing skills, and score breakdown."""
        title = (job.get("title") or "")
        desc = (job.get("description_text") or "")
        tags = [str(t).lower().strip() for t in (job.get("tags") or [])]

        exp_level = (job.get("experience_level") or "unspecified").lower()
        if exp_level == "unspecified" or not exp_level:
            exp_level = JobEnricher.detect_seniority(title, desc)

        lang = (job.get("detected_language") or "english").lower()
        is_unpaid = bool(job.get("is_unpaid", False))
        is_remote = bool(job.get("is_remote", False))

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
        if lang in ("german", "non_english"):
            breakdown["language_adjustment"] = self.weights.get("german_language_penalty", -100)
            breakdown["reasons"].append("Requires non-English language")
            breakdown["flags"].append("NON_ENGLISH")

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

        if is_remote and nepal_accessible:
            breakdown["remote_bonus"] = self.weights.get("remote_bonus", 15)
            breakdown["reasons"].append("100% remote, globally open")

        # ── 2. TECH SKILLS MATCHING (Focus on core sections: requirements/responsibilities) ──
        sections = extract_sections(desc, title=title)
        core_text = f"{sections.requirements} {sections.responsibilities} {sections.nice_to_have}".strip()
        target_text = core_text if len(core_text) > 30 else desc

        matched_skills = []
        earned_skill_points = 0.0

        for skill, weight in self.all_skills.items():
            if self._skill_present(skill, title, target_text, tags):
                matched_skills.append(skill)
                earned_skill_points += weight

        max_possible_points = sum(self.all_skills.values())
        scaled_skill_score = min(
            self.weights.get("tech_stack_max_score", 50),
            (earned_skill_points / max_possible_points) * 100 * 1.5,
        )
        breakdown["skill_points"] = round(scaled_skill_score, 1)

        # ── 3. FEED THRESHOLD CHECKS (Task 6b) ─────────────────────────────
        if self.is_placeholder_title(title):
            breakdown["flags"].append("PLACEHOLDER")
            breakdown["reasons"].append("Placeholder title ('template' or 'test')")

        if len(matched_skills) == 0 and not self.has_technical_title_signal(title):
            breakdown["flags"].append("NO_TECH_SIGNAL")
            breakdown["reasons"].append("No matched skills and no technical title signal")

        # ── 4. TOTAL SCORE ─────────────────────────────────────────────────
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

        missing_skills = [
            t for t in tags
            if t not in matched_skills
            and len(t) < 25
            and not any(g in t for g in ["operations", "sales", "community", "marketing", "vente"])
        ][:5]

        return final_score, matched_skills, missing_skills, breakdown
