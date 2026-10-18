"""Tests for the job enrichment engine."""
import pytest
from src.enrichment.enricher import JobEnricher


def test_detect_seniority_title():
    """Verify seniority detected accurately from job titles."""
    assert JobEnricher.detect_seniority("Junior Python Developer", "") == "junior"
    assert JobEnricher.detect_seniority("Software Engineering Intern", "") == "intern"
    assert JobEnricher.detect_seniority("Senior Full Stack Engineer", "") == "senior"
    assert JobEnricher.detect_seniority("Lead Architect", "") == "senior"
    assert JobEnricher.detect_seniority("Backend Developer", "") == "unspecified"


def test_detect_seniority_title_wins_over_body():
    """Title signal must override any body signal."""
    # Title says Junior — even if body mentions 5+ years (e.g. copy-paste JD mistake)
    assert JobEnricher.detect_seniority("Junior Developer", "5+ years of Python required.") == "junior"
    # Title says Senior — even if body says no experience required
    assert JobEnricher.detect_seniority("Senior Engineer", "no experience required.") == "senior"


def test_detect_seniority_false_positives_5b1_audit():
    """Regression tests for false positives found in the 5b.1 seniority audit.

    Previously, any JD body mentioning '5+ years' was labeled 'senior', which
    caused many genuinely junior/unspecified roles to be filtered out incorrectly.
    """
    generic_desc_5yr = "We are looking for someone with 5+ years of experience preferred."
    assert JobEnricher.detect_seniority("Backend Developer", generic_desc_5yr) == "unspecified"

    generic_desc_6yr = "Ideally 6+ years with Python, though we consider all levels."
    assert JobEnricher.detect_seniority("Python Engineer", generic_desc_6yr) == "unspecified"

    # The word 'seniority' itself should NOT trigger senior
    seniority_word = "Seniority level: not specified. We welcome applicants of all levels."
    assert JobEnricher.detect_seniority("Software Developer", seniority_word) == "unspecified"


def test_detect_seniority_body_strong_senior():
    """Body-only senior: must have explicit must-have language AND 7+ years."""
    strong = "You must have a minimum of 8+ years of backend engineering experience."
    assert JobEnricher.detect_seniority("Backend Engineer", strong) == "senior"

    strong2 = "10+ years required in distributed systems."
    assert JobEnricher.detect_seniority("Systems Engineer", strong2) == "senior"


def test_detect_seniority_body_mid():
    """Body mid-level signals."""
    mid_desc = "We're looking for someone with 3+ years of React experience."
    assert JobEnricher.detect_seniority("Frontend Developer", mid_desc) == "mid"

    mid_desc2 = "2-4 years of experience preferred."
    assert JobEnricher.detect_seniority("Developer", mid_desc2) == "mid"



def test_detect_german():
    """Verify language detection based on keywords, stopwords, and tags."""
    assert JobEnricher.detect_language("Softwareentwickler (m/w/d)", "Wir suchen einen Entwickler.") == "german"
    assert JobEnricher.detect_language("Python Engineer", "Looking for a software engineer.") == "english"
    assert JobEnricher.detect_language("Sr REACT NATIVE", "Qué es Deazy: Deazy es una plataforma de software para conectar empresas con agencias de desarrollo en todo el mundo.") == "spanish"
    assert JobEnricher.detect_language("Technicien (F/H)", "Notre entreprise recherche un collaborateur pour rejoindre notre équipe.") == "french"


def test_detect_unpaid():
    """Verify unpaid jobs are detected."""
    assert JobEnricher.detect_unpaid("Volunteer Web Developer", "Unpaid internship.") is True
    assert JobEnricher.detect_unpaid("Junior Developer", "Competitive salary.") is False


# ---------------------------------------------------------------------------
# 6c Regression tests: Contextual UNPAID detection (Credit Wellness fix)
# ---------------------------------------------------------------------------

def test_credit_wellness_not_unpaid():
    """Credit Wellness sales training ('Week 0: Unpaid Week 1: $100') must NOT be flagged unpaid."""
    cw_title = "Inside Sales Contractor"
    cw_desc = (
        "Commission with Guaranteed Minimums: You will receive commissions or guaranteed minimums, "
        "whichever amount benefits you most. Week 0: Unpaid Week 1: $100 guaranteed minimum "
        "Week 2: $150 guaranteed minimum Week 3: $200 guaranteed minimum"
    )
    assert JobEnricher.detect_unpaid(cw_title, cw_desc) is False, (
        "Credit Wellness was incorrectly disqualified as UNPAID due to bare 'unpaid' keyword."
    )


def test_real_unpaid_indiekidz_detected():
    """IndieKidz GmbH real unpaid internship must be detected."""
    title = "(Unpaid) Mandatory Internship : Software Test (QA) Automation Engineer"
    desc = "We are seeking a motivated intern. This is an unpaid mandatory internship for enrolled students."
    assert JobEnricher.detect_unpaid(title, desc) is True


def test_paid_volunteer_time_off_not_unpaid():
    """Perks mentioning 'paid volunteer time off' or 'volunteering day' must NOT be flagged unpaid."""
    title = "Senior Software Engineer, Prime"
    desc = "Competitive salary, 401(k), parental leave, and paid volunteer time off. 2 volunteering days per year."
    assert JobEnricher.detect_unpaid(title, desc) is False


def test_equity_only_detected():
    """Equity-only roles must be detected as unpaid."""
    assert JobEnricher.detect_unpaid("Founding Engineer", "This is an equity only co-founder role.") is True


def test_unpaid_position_phrase_detected():
    """Explicit phrases like 'this role is unpaid' must be detected."""
    assert JobEnricher.detect_unpaid("Frontend Intern", "Please note that this position is unpaid.") is True



def test_detect_nepal_accessible():
    """Verify geo-restriction checks."""
    # Worldwide remote
    assert JobEnricher.detect_nepal_accessible(True, "Remote", "Worldwide") is True
    # US only restriction
    assert JobEnricher.detect_nepal_accessible(True, "Remote", "USA only") is False
    # Onsite abroad
    assert JobEnricher.detect_nepal_accessible(False, "Berlin, Germany", "") is False
    # Onsite in Nepal
    assert JobEnricher.detect_nepal_accessible(False, "Kathmandu, Nepal", "") is True


def test_extract_tech_tags():
    """Verify tech stack keywords are extracted."""
    tags = JobEnricher.extract_tech_tags(
        "Fullstack Developer (Python/React)",
        "Building web applications with Django and Next.js and PostgreSQL.",
        existing_tags=["Engineering"]
    )
    assert "python" in tags
    assert "react" in tags
    assert "next.js" in tags
    assert "postgresql" in tags


# ---------------------------------------------------------------------------
# 6a Regression tests: detect_accessibility_3state
# ---------------------------------------------------------------------------

def test_accessibility_worldwide_explicit():
    """Remotive job that explicitly says 'Worldwide' → ACCESSIBLE."""
    assert JobEnricher.detect_accessibility_3state("Backend Dev", True, "", "Worldwide") == "ACCESSIBLE"


def test_accessibility_unspecified_restriction_is_unknown():
    """Arbeitnow remote job with no restriction info → UNKNOWN (not ACCESSIBLE)."""
    assert JobEnricher.detect_accessibility_3state("Backend Dev", True, "Remote", "unspecified") == "UNKNOWN"


def test_accessibility_empty_restriction_is_unknown():
    """Both location and restriction empty → UNKNOWN."""
    assert JobEnricher.detect_accessibility_3state("Backend Dev", True, "", "unspecified") == "UNKNOWN"


def test_accessibility_nepal_in_location():
    """Nepal mentioned in location_raw → ACCESSIBLE."""
    assert JobEnricher.detect_accessibility_3state("Dev", True, "Nepal or worldwide", "") == "ACCESSIBLE"


def test_accessibility_usa_country_only_blocked():
    """Single-country restriction 'USA' → BLOCKED."""
    assert JobEnricher.detect_accessibility_3state("Backend Dev", True, "", "USA") == "BLOCKED"


def test_accessibility_switzerland_blocked():
    """Switzerland-only restriction → BLOCKED."""
    assert JobEnricher.detect_accessibility_3state("Dev", True, "", "Switzerland") == "BLOCKED"


def test_accessibility_emea_in_title_blocked():
    """EMEA region code in title → BLOCKED."""
    assert JobEnricher.detect_accessibility_3state("Backend Dev - EMEA", True, "", "unspecified") == "BLOCKED"


def test_accessibility_us_in_title_blocked():
    """US region code in title → BLOCKED."""
    assert JobEnricher.detect_accessibility_3state("Senior Dev (US)", True, "Remote", "unspecified") == "BLOCKED"


def test_accessibility_onsite_berlin_blocked():
    """On-site role in Berlin → BLOCKED."""
    assert JobEnricher.detect_accessibility_3state("Dev", False, "Berlin, Germany", "") == "BLOCKED"


def test_accessibility_apac_is_unknown():
    """APAC is ambiguous — may or may not include Nepal → UNKNOWN."""
    assert JobEnricher.detect_accessibility_3state("Dev", True, "", "APAC") == "UNKNOWN"


def test_accessibility_asia_is_unknown():
    """'Asia' is ambiguous → UNKNOWN (not ACCESSIBLE)."""
    assert JobEnricher.detect_accessibility_3state("Dev", True, "Asia", "unspecified") == "UNKNOWN"


def test_accessibility_remote_generic_is_unknown():
    """Generic 'Remote' with no restriction info → UNKNOWN."""
    assert JobEnricher.detect_accessibility_3state("Dev", True, "Remote", "unspecified") == "UNKNOWN"


# ---------------------------------------------------------------------------
# Phase B Real-world Reachability Tests (detect_reachability)
# ---------------------------------------------------------------------------

def test_reachability_swarmaero_itar_blocked():
    """Swarmaero ITAR requirement -> blocked."""
    title = "Flight Software Engineer"
    desc = (
        "ITAR requirement: Due to federal regulations, this position requires applicants "
        "to be a U.S. citizen, lawful permanent resident (Green Card holder)."
    )
    status, reason = JobEnricher.detect_reachability(title, desc, "Remote", "unspecified", True)
    assert status == "blocked"
    assert "itar" in reason or "citizen" in reason


def test_reachability_elevenlabs_europe_us_east_coast_blocked():
    """ElevenLabs 'anywhere in Europe and the US East Coast' -> blocked."""
    title = "Product Designer"
    desc = "This role can be based anywhere in Europe and the US East Coast, operating in GMT-5 to GMT+1."
    status, reason = JobEnricher.detect_reachability(title, desc, "Remote", "unspecified", True)
    assert status == "blocked"
    assert reason == "regional_restriction_excludes_nepal"


def test_reachability_elevenlabs_devexp_globally_accessible():
    """ElevenLabs Developer Experience Engineer 'can be executed globally' -> accessible."""
    title = "Developer Experience Engineer"
    desc = "This role can be executed globally. We are an international team working across timezones."
    status, reason = JobEnricher.detect_reachability(title, desc, "Remote", "unspecified", True)
    assert status == "accessible"
    assert reason == "can_be_executed_globally"


def test_reachability_duna_remote_unknown():
    """Duna 'Remote' with no location rule -> unknown."""
    title = "Backend Engineer"
    desc = "Join Duna to build modern microservices. We care about clean code and performance."
    status, reason = JobEnricher.detect_reachability(title, desc, "Remote", "unspecified", True)
    assert status == "unknown"
    assert reason == "no_location_restriction_stated"


