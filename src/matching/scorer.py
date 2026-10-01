"""CV Match and Ranking Engine."""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_PATH = Path(__file__).resolve().parent / "cv_profile.json"


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

    def score_job(self, job: Dict[str, Any]) -> Tuple[float, List[str], List[str], Dict[str, Any]]:
        """Compute match score (0.0 - 100.0), matched skills, missing skills, and score breakdown.
        
        Returns:
            (match_score, matched_skills, missing_skills, score_breakdown)
        """
        title = (job.get("title") or "").lower()
        desc = (job.get("description_text") or "").lower()
        tags = [str(t).lower() for t in (job.get("tags") or [])]
        combined_text = f"{title} {desc} {' '.join(tags)}"

        exp_level = (job.get("experience_level") or "unspecified").lower()
        lang = (job.get("detected_language") or "english").lower()
        is_unpaid = bool(job.get("is_unpaid", False))
        is_remote = bool(job.get("is_remote", False))
        nepal_accessible = bool(job.get("nepal_accessible", False))

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

        # Remote bonus
        if is_remote and nepal_accessible:
            breakdown["remote_bonus"] = self.weights.get("remote_bonus", 15)
            breakdown["reasons"].append("100% remote open globally")

        # ── 2. TECH SKILLS MATCHING ──────────────────────────────────────
        matched_skills = []
        earned_skill_points = 0.0

        for skill, weight in self.all_skills.items():
            if skill in tags or skill in title or skill in combined_text:
                matched_skills.append(skill)
                earned_skill_points += weight

        # Normalize skill points to max 50
        max_possible_points = sum(self.all_skills.values())
        scaled_skill_score = min(
            self.weights.get("tech_stack_max_score", 50),
            (earned_skill_points / max_possible_points) * 100 * 1.5
        )
        breakdown["skill_points"] = round(scaled_skill_score, 1)

        # ── 3. TOTAL SCORE CALCULATION ──────────────────────────────────
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

        # Identify missing technologies mentioned in job tags
        missing_skills = [
            t for t in tags 
            if t not in matched_skills and len(t) < 25 and not any(g in t for g in ["operations", "sales", "community"])
        ][:5]

        return final_score, matched_skills, missing_skills, breakdown
