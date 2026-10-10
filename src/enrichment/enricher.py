"""Job enrichment engine: detects seniority, language, unpaid status, and Nepal accessibility."""
import re
from typing import Any, Dict, List, Set

GERMAN_INDICATORS = [
    r"\(m/w/d\)",
    r"\(d/m/w\)",
    r"\(w/m/d\)",
    r"\b(deutsch|deutschkenntnisse|flie\u00dfend deutsch|gute deutschkenntnisse)\b",
    r"\b(wir suchen|deine aufgaben|das bringst du mit|dein profil|unser angebot|bewerbung)\b",
    r"\b(berufserfahrung|erfolgreich|unternehmen|standort|bereich|kenntnisse)\b",
]

SENIOR_TITLE_PATTERNS = [
    r"\b(senior|sr\.|lead|principal|staff|director|vp|head of|chief|teamlead|teamleitung|architekt|architect|manager)\b"
]

JUNIOR_TITLE_PATTERNS = [
    r"\b(junior|jr\.|entry[- ]level|graduate|associate|trainee|apprentice|early[- ]career)\b"
]

INTERN_TITLE_PATTERNS = [
    r"\b(intern|internship|student|working student|werkstudent|praktikant|praktikum)\b"
]

UNPAID_PATTERNS = [
    r"\b(unpaid|non-paid|volunteer|volunteering|no compensation|equity only|unverg\u00fctet)\b"
]

TECH_KEYWORDS_MAP = {
    "python": r"\b(python|django|fastapi|flask)\b",
    "javascript": r"\b(javascript|js|es6)\b",
    "typescript": r"\b(typescript|ts)\b",
    "react": r"\b(react|react\.js|reactjs)\b",
    "next.js": r"\b(next\.js|nextjs)\b",
    "node.js": r"\b(node|node\.js|nodejs|express\.js|expressjs)\b",
    "postgresql": r"\b(postgres|postgresql)\b",
    "docker": r"\b(docker|docker-compose)\b",
    "ai/ml": r"\b(ai|ml|machine learning|deep learning|llm|rag|prompt engineering|langchain)\b",
    "flutter": r"\b(flutter|dart)\b",
    "sql": r"\b(sql|mysql|sqlite)\b",
    "git": r"\b(git|github|gitlab)\b",
    "rest-api": r"\b(rest|restful|api)\b",
}


class JobEnricher:
    """Enriches job records with computed metadata."""

    @staticmethod
    def detect_language(title: str, description: str) -> str:
        """Detect whether the job description is primarily in German or English."""
        combined = f"{title} {description}".lower()
        german_hits = sum(1 for pattern in GERMAN_INDICATORS if re.search(pattern, combined, re.IGNORECASE))
        if german_hits >= 2 or re.search(r"\(m/w/d\)|\(w/m/d\)", combined, re.IGNORECASE):
            return "german"
        return "english"

    @staticmethod
    def detect_seniority(title: str, description: str) -> str:
        """Detect seniority level: intern, junior, mid, senior, or unspecified.

        Priority order:
          1. Title signals — highest confidence, always wins.
          2. Body signals — used only when title is ambiguous (returns "unspecified").
             Body-only senior: requires BOTH explicit must-have language AND 7+ years.
             Body-only 3-5 years alone = "mid" (not senior — many JDs say "preferred").
             Body-only 5-6 years alone = "unspecified" (not senior — false positive risk).
        """
        t_lower = title.lower()

        # 1. Title takes absolute priority
        for pat in INTERN_TITLE_PATTERNS:
            if re.search(pat, t_lower, re.IGNORECASE):
                return "intern"

        for pat in JUNIOR_TITLE_PATTERNS:
            if re.search(pat, t_lower, re.IGNORECASE):
                return "junior"

        for pat in SENIOR_TITLE_PATTERNS:
            if re.search(pat, t_lower, re.IGNORECASE):
                return "senior"

        # 2. Title gave no signal — fall back to body, with weaker confidence
        desc_lower = description.lower()

        # Junior signals in body
        if re.search(
            r"\b(0-1|0-2|no prior experience|no experience required|fresh graduate)\b",
            desc_lower,
        ):
            return "junior"

        # Strong senior: explicit must-have language + 7+ years
        # (5-6 years alone is intentionally NOT senior — audit found many false positives)
        strong_senior = (
            re.search(r"\b(?:required|must have|must-have|minimum|you must have)\b.{0,100}\b(?:[7-9]\+|10\+)\s*(?:years?|yrs)\b", desc_lower)
            or re.search(r"\b(?:[7-9]\+|10\+)\s*(?:years?|yrs)\b.{0,100}\b(?:required|mandatory|minimum|must)\b", desc_lower)
        )
        if strong_senior:
            return "senior"

        # Mid signals: 2-5 years mentioned (not gated by must-have — too noisy for senior)
        if re.search(r"\b(3-5|2-4|3\+|2\+)\s*(?:years?|yrs)\b", desc_lower):
            return "mid"

        return "unspecified"


    @staticmethod
    def detect_unpaid(title: str, description: str) -> bool:
        """Flag whether the listing indicates an unpaid position."""
        combined = f"{title} {description}".lower()
        return any(re.search(pat, combined, re.IGNORECASE) for pat in UNPAID_PATTERNS)

    @staticmethod
    def detect_accessibility_3state(
        title: str, is_remote: bool, location_raw: str, remote_restriction: str
    ) -> str:
        """Classify accessibility into 3 states: ACCESSIBLE, BLOCKED, or UNKNOWN.

        Rules:
          - ACCESSIBLE: explicit positive evidence (worldwide, anywhere, global,
            work from anywhere, all time zones, Nepal, Kathmandu, Lalitpur, or location
            string including Nepal).
          - BLOCKED: country/region lists excluding Nepal, region codes in title
            (EMEA, NA, EU, US, USA, LATAM), city-level locations (Berlin, Munich, Koln, Paris, etc.),
            or on-site abroad.
          - UNKNOWN: everything else, including APAC, Asia, South Asia (without explicit Nepal/worldwide),
            and generic/unspecified locations.
        """
        title_upper = (title or "").upper()
        loc = (location_raw or "").strip()
        restr = (remote_restriction or "").strip()
        if restr.lower() in ("worldwide", "remote", "unspecified"):
            combined = loc.lower()
            if restr.lower() == "worldwide":
                combined += " worldwide"
        else:
            combined = f"{loc} {restr}".lower()

        # 1. Region codes in title -> BLOCKED
        title_region_codes = ["EMEA", "NA", "EU", "US", "USA", "LATAM"]
        for code in title_region_codes:
            if re.search(rf"\b{code}\b", title_upper):
                return "BLOCKED"

        # 2. Nepal explicit mention -> ACCESSIBLE
        if any(term in combined for term in ["nepal", "kathmandu", "lalitpur"]):
            return "ACCESSIBLE"

        # 3. Explicit positive evidence -> ACCESSIBLE
        positive_terms = [
            "worldwide", "anywhere", "global", "work from anywhere",
            "all time zones", "all timezones", "everywhere"
        ]
        if any(term in combined for term in positive_terms):
            return "ACCESSIBLE"

        # 4. On-site abroad -> BLOCKED
        if not is_remote:
            return "BLOCKED"

        # 5. Exclusive country/region lists or city-level locations -> BLOCKED
        blocked_locations = [
            "usa", "united states", "us", "canada", "switzerland", "schweiz", "suisse",
            "germany", "deutschland", "france", "frankreich", "uk", "united kingdom",
            "australia", "ireland", "netherlands", "spain", "espagne", "poland", "japan",
            "turkey", "vietnam", "mexico", "norway", "israel", "brazil", "argentina",
            "americas", "europe", "latam", "latin america", "northern america",
            "berlin", "munich", "münchen", "köln", "cologne", "hamburg", "bonn",
            "bielefeld", "paris", "la chaux-de-fonds", "mendrisio", "homeoffice"
        ]

        for term in blocked_locations:
            if re.search(rf"\b{re.escape(term)}\b", combined):
                if not any(p in combined for p in positive_terms):
                    return "BLOCKED"

        # 6. UNKNOWN for everything else (including APAC, Asia, empty/unspecified)
        return "UNKNOWN"

    @staticmethod
    def detect_nepal_accessible(
        is_remote: bool, location_raw: str, remote_restriction: str
    ) -> bool:
        """Check if role is realistically accessible from Nepal (legacy boolean)."""
        loc_str = f"{location_raw or ''} {remote_restriction or ''}".lower()

        if any(term in loc_str for term in ["nepal", "kathmandu", "lalitpur"]):
            return True

        if not is_remote:
            return False

        restricted_regions = [
            "us only", "usa only", "united states only",
            "eu only", "europe only", "uk only", "united kingdom only",
            "canada only", "germany only", "deutschland only",
            "latam only", "france only", "brazil only"
        ]
        if any(re.search(rf"\b{re.escape(reg)}\b", loc_str) for reg in restricted_regions):
            return False

        worldwide_terms = [
            "worldwide", "anywhere", "global", "all locations",
            "apac", "asia", "south asia"
        ]
        if any(term in loc_str for term in worldwide_terms):
            return True

        return True

    @staticmethod
    def extract_tech_tags(title: str, description: str, existing_tags: List[str]) -> List[str]:
        """Extract standardized tech stack tags from title and description."""
        combined = f"{title} {description}".lower()
        found: Set[str] = set()

        # Keep valid existing tags
        if existing_tags:
            for t in existing_tags:
                clean_t = str(t).strip()
                if clean_t:
                    found.add(clean_t)

        # Detect tech keywords
        for canonical, pattern in TECH_KEYWORDS_MAP.items():
            if re.search(pattern, combined, re.IGNORECASE):
                found.add(canonical)

        return sorted(found)

    @classmethod
    def enrich_job(cls, job: Dict[str, Any]) -> Dict[str, Any]:
        """Produce full enrichment metadata dictionary for a job."""
        title = job.get("title") or ""
        desc = job.get("description_text") or ""
        loc = job.get("location_raw") or ""
        restriction = job.get("remote_restriction") or ""
        is_remote = bool(job.get("is_remote", False))
        existing_tags = job.get("tags") or []

        return {
            "detected_language": cls.detect_language(title, desc),
            "experience_level": cls.detect_seniority(title, desc),
            "is_unpaid": cls.detect_unpaid(title, desc),
            "nepal_accessible": cls.detect_nepal_accessible(is_remote, loc, restriction),
            "accessibility": cls.detect_accessibility_3state(title, is_remote, loc, restriction),
            "tags": cls.extract_tech_tags(title, desc, existing_tags),
        }
