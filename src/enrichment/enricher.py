"""Job enrichment engine: detects seniority, language, unpaid status, and Nepal accessibility."""
import re
from typing import Any, Dict, List, Set, Tuple

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
    r"\b(?:unpaid|non-paid|unverg\u00fctet)\s+(?:internship|intern|position|role|job|opportunity|work|contract)\b",
    r"\b(?:this\s+(?:is\s+an?|role\s+is|position\s+is|internship\s+is))\s+(?:unpaid|non-paid|unverg\u00fctet)\b",
    r"\b(?:position|role|internship|job)\s+is\s+(?:unpaid|non-paid|unverg\u00fctet)\b",
    r"\bunpaid\s+volunteer\b",
    r"\b(?:no\s+compensation|equity\s+only)\b",
    r"^\s*\(?unpaid\)?\b",
    r"\bvolunteer\s+(?:developer|engineer|programmer|intern|position|role)\b",
    r"^\s*\(?volunteer\)?\s+\w+",
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


LANGUAGE_STOPWORDS = {
    "german": {"der", "die", "das", "und", "ist", "den", "von", "zu", "mit", "sich", "des", "auf", "für", "dem", "nicht", "ein", "eine", "als", "auch", "es", "an", "werden", "aus", "er", "hat", "dass", "sie", "nach", "wird", "bei", "einer", "um", "am", "sind", "wir", "ihr", "du", "uns"},
    "french": {"le", "la", "les", "de", "des", "du", "et", "en", "est", "un", "une", "que", "pour", "dans", "qui", "au", "par", "sur", "pas", "plus", "avec", "sont", "nous", "vous", "votre", "notre", "vos", "nos"},
    "spanish": {"el", "la", "de", "que", "y", "en", "un", "una", "los", "del", "las", "por", "para", "con", "no", "su", "al", "lo", "como", "pero", "sus", "le", "ya", "este", "ha", "son", "ellos", "nosotros", "más", "están"},
    "english": {"the", "and", "to", "of", "a", "in", "is", "that", "for", "you", "it", "with", "on", "as", "are", "be", "this", "our", "we", "from", "at", "or", "your", "all", "have", "new", "more", "an", "was", "by"},
}


class JobEnricher:
    """Enriches job records with computed metadata."""

    @staticmethod
    def detect_language(title: str, description: str) -> str:
        """Detect language of a job using title and first 500 chars of description.

        Supports German, French, Spanish, and English.
        """
        t = title or ""
        d = (description or "")[:500]
        text = f"{t} {d}".lower()

        if re.search(r"\(m/w/d\)|\(w/m/d\)|\(d/m/w\)", text):
            return "german"
        if re.search(r"\(f/h\)|\(h/f\)", text):
            return "french"
        if sum(1 for p in GERMAN_INDICATORS if re.search(p, text, re.I)) >= 2:
            return "german"

        words = re.findall(r"\b[a-zA-Z\u00c0-\u00ff]+\b", text)
        word_counts = {}
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1

        scores = {}
        for lang, sw in LANGUAGE_STOPWORDS.items():
            scores[lang] = sum(word_counts[w] for w in sw if w in word_counts)

        best_lang, best_score = max(scores.items(), key=lambda x: x[1])
        if best_score < 3:
            return "english"
        if best_lang == "english":
            for other in ["german", "french", "spanish"]:
                if scores[other] >= 5 and scores[other] >= scores["english"] * 0.8:
                    return other
            return "english"
        return best_lang

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
    def detect_reachability(
        title: str,
        description: str,
        location_raw: str,
        remote_restriction: str,
        is_remote: bool,
    ) -> Tuple[str, str]:
        """Determine reachable_from_nepal ('accessible', 'unknown', 'blocked') and reason.

        Rules:
          - blocked: clear text such as "US citizens only", ITAR, security clearance,
            work authorization requirements, location lists that exclude Nepal (e.g.
            "anywhere in Europe and the US East Coast", "Europe only", "EU residents"),
            timezone windows that need overlap in GMT-5 to GMT+1 only, title region codes
            (EMEA, NA, EU, US, LATAM), and onsite abroad.
          - accessible: text clearly says worldwide / anywhere / global /
            "can be executed globally", or location includes Nepal / South Asia.
          - unknown: everything else (default; never default to accessible).
        """
        title_upper = (title or "").upper()
        loc = (location_raw or "").strip()
        restr = (remote_restriction or "").strip()
        desc = (description or "").lower()
        combined_loc = f"{loc} {restr}".lower()

        # 1. Legal / Clearance / Citizen Requirements (in title, desc, or location)
        if re.search(r"\bITAR\b", f"{title} {description}", re.I):
            return ("blocked", "itar_requirement")
        if re.search(r"\b(?:security\s+clearance|active\s+clearance|secret\s+clearance|ts/sci|polygraph)\b", desc, re.I):
            return ("blocked", "security_clearance_required")
        if re.search(r"\b(?:u\.?s\.?\s+citizens?\s+(?:only|or\s+permanent\s+residents?)|u\.?s\.?\s+citizenship\s+required|us\s+citizens?\s+only)\b", desc, re.I):
            return ("blocked", "us_citizen_only")
        if re.search(r"\bto\s+conform\s+to\s+u\.?s\.?\s+government\s+export\s+regulations,\s+applicant\s+must\s+be\s+a\s+u\.?s\.?\s+citizen\b", desc, re.I):
            return ("blocked", "us_citizen_only")
        if re.search(r"\b(?:work\s+authorization\s+required\s+for|(?:must\s+have|requires?)\s+(?:valid\s+)?work\s+authorization\s+in|(?:authorized|eligible)\s+to\s+work\s+in\s+(?:the\s+)?(?:u\.?s\.?|united\s+states|canada|uk|germany|europe|eu))\b", desc, re.I):
            return ("blocked", "work_authorization_required")

        # 2. Regional restrictions excluding Nepal in description
        if re.search(r"anywhere\s+in\s+europe\s+(?:and|or)\s+(?:on\s+)?(?:the\s+)?us\s+east\s+coast", desc, re.I):
            return ("blocked", "regional_restriction_excludes_nepal")
        if re.search(r"\banywhere\s+in\s+europe\b", desc, re.I):
            return ("blocked", "regional_restriction_excludes_nepal")
        if re.search(r"\b(?:us\s+east\s+coast|eu\s+residents?|europe\s+only|eu\s+only|us\s+only|usa\s+only|uk\s+only|canada\s+only)\b", desc, re.I):
            return ("blocked", "regional_restriction_excludes_nepal")

        # 3. Timezone restrictions excluding Nepal
        if re.search(r"\b(?:gmt-5\s+to\s+gmt\+1|cet\s+timezones?\s+required|gmt\+0\s+to\s+gmt\+2|cet\s*/\s*et)\b", desc, re.I):
            return ("blocked", "timezone_excludes_nepal")

        # 4. Region code in title
        for code in ["EMEA", "NA", "EU", "US", "USA", "LATAM"]:
            if re.search(rf"\b{code}\b", title_upper):
                return ("blocked", "title_region_code")

        # 5. Explicit positive evidence (accessible)
        if "can be executed globally" in desc:
            return ("accessible", "can_be_executed_globally")
        if any(term in desc or term in combined_loc for term in ["nepal", "kathmandu", "lalitpur"]):
            return ("accessible", "nepal_explicit")
        if any(term in combined_loc for term in ["worldwide", "work from anywhere", "anywhere in the world"]):
            return ("accessible", "explicit_worldwide_location")
        if "remote (worldwide)" in desc or "remote(worldwide)" in desc:
            return ("accessible", "worldwide_in_description")

        # 6. Not remote -> blocked
        if not is_remote:
            return ("blocked", "onsite_abroad")

        # 7. Blocked locations (single country abroad or non-Nepal cities)
        blocked_locations = [
            "usa", "united states", "us", "canada", "switzerland", "schweiz", "suisse",
            "germany", "deutschland", "france", "frankreich", "uk", "united kingdom",
            "australia", "ireland", "netherlands", "spain", "espagne", "poland", "japan",
            "turkey", "vietnam", "mexico", "norway", "israel", "brazil", "argentina",
            "americas", "europe", "latam", "latin america", "northern america",
            "berlin", "munich", "münchen", "köln", "cologne", "hamburg", "bonn",
            "bielefeld", "paris", "amsterdam", "london"
        ]
        if any(re.search(rf"\b{re.escape(term)}\b", combined_loc) for term in blocked_locations):
            return ("blocked", "location_excludes_nepal")

        # 8. Everything else stays unknown
        return ("unknown", "no_location_restriction_stated")

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

        reach_status, reach_reason = cls.detect_reachability(
            title, desc, loc, restriction, is_remote
        )

        return {
            "detected_language": cls.detect_language(title, desc),
            "experience_level": cls.detect_seniority(title, desc),
            "is_unpaid": cls.detect_unpaid(title, desc),
            "nepal_accessible": cls.detect_nepal_accessible(is_remote, loc, restriction),
            "accessibility": cls.detect_accessibility_3state(title, is_remote, loc, restriction),
            "reachable_from_nepal": reach_status,
            "reachable_reason": reach_reason,
            "tags": cls.extract_tech_tags(title, desc, existing_tags),
        }
