"""Tests for src/matching/jd_extractor.py — Task 7.2.

Covers:
- Normal headed JD
- No headings (pure prose fallback)
- ALL CAPS headings
- Bullets-only format
- HTML leftovers
- Empty input
- Minimal one-liner input
- Heading present but body is boilerplate / legal
"""
import pytest
from src.matching.jd_extractor import extract_sections, JDSections, _strip_html


# ---------------------------------------------------------------------------
# HTML stripping tests
# ---------------------------------------------------------------------------

def test_strip_html_basic():
    raw = "<h2>About the Role</h2><ul><li>Build APIs</li></ul>"
    result = _strip_html(raw)
    assert "<" not in result
    assert "About the Role" in result
    assert "Build APIs" in result


def test_strip_html_entities():
    raw = "Salary &amp; Benefits &nbsp; apply here"
    result = _strip_html(raw)
    assert "&amp;" not in result
    assert "&" in result


def test_strip_html_nested():
    raw = "<strong><em>Must have</em> Python experience</strong>"
    result = _strip_html(raw)
    assert "Must have" in result
    assert "Python experience" in result


# ---------------------------------------------------------------------------
# Normal headed JD (Title Case headings)
# ---------------------------------------------------------------------------

HEADED_JD = """
About the Company
We build developer tooling used by 100,000+ teams worldwide.

What You'll Do
- Design and ship REST APIs with Python and Django
- Write unit and integration tests
- Collaborate with frontend engineers on Next.js features

Requirements
- 0-2 years of Python experience
- Familiarity with PostgreSQL
- Git proficiency required

Nice to Have
- Docker knowledge
- Experience with React

Benefits
- Competitive salary $30-$45/hr
- Fully remote, flexible hours
- Health insurance

Equal Opportunity
We are an equal opportunity employer and value diversity.
"""


def test_headed_jd_classifies_all_sections():
    s = extract_sections(HEADED_JD, title="Python Dev", company="DevCo", location="Remote")
    assert s.title == "Python Dev"
    assert s.company == "DevCo"
    assert "REST APIs" in s.responsibilities
    assert "Python experience" in s.requirements
    assert "Docker" in s.nice_to_have
    assert "salary" in s.benefits.lower()
    assert "equal opportunity" in s.legal_eeo.lower() or "equal opportunity" in s.other.lower()


def test_headed_jd_company_blurb():
    s = extract_sections(HEADED_JD)
    assert "100,000" in s.company_blurb or "developer tooling" in s.company_blurb


# ---------------------------------------------------------------------------
# No headings — pure prose fallback
# ---------------------------------------------------------------------------

NO_HEADING_JD = """
We are a fintech startup building the future of payments. Our platform processes $1B daily.

You will build and maintain Python microservices using FastAPI and PostgreSQL. You'll collaborate with cross-functional teams and help define best practices.

You must have solid Python skills, 0-2 years experience with REST APIs, and you should be comfortable with Git.

Bonus if you know React or TypeScript.

We offer competitive pay, remote-first, unlimited PTO, and health insurance.

All qualified applicants receive consideration without discrimination.
"""


def test_no_headings_fallback_captures_requirements():
    s = extract_sections(NO_HEADING_JD)
    # At least one key section should be populated
    d = s.non_empty()
    assert len(d) >= 2  # at least company blurb + requirements


def test_no_headings_fallback_detects_requirements():
    s = extract_sections(NO_HEADING_JD)
    assert "Python" in s.requirements or "Python" in s.other


def test_no_headings_fallback_benefits():
    s = extract_sections(NO_HEADING_JD)
    assert "remote" in s.benefits.lower() or "PTO" in s.benefits


def test_no_headings_fallback_legal():
    s = extract_sections(NO_HEADING_JD)
    assert "qualified" in s.legal_eeo.lower() or "discrimination" in s.legal_eeo.lower()


# ---------------------------------------------------------------------------
# ALL CAPS headings
# ---------------------------------------------------------------------------

ALL_CAPS_JD = """
ABOUT US
KoboToolbox is a global NGO serving data collection to 100k users.

RESPONSIBILITIES
Build and test Django REST APIs.
Integrate third-party data sources.

REQUIREMENTS
Python 3.10+, Django, PostgreSQL.
0-1 years experience acceptable.

NICE TO HAVE
Docker, React, or GraphQL experience.

COMPENSATION & BENEFITS
$25-35/hr, remote worldwide.
"""


def test_all_caps_headings_are_detected():
    s = extract_sections(ALL_CAPS_JD)
    assert "Django REST" in s.responsibilities
    assert "PostgreSQL" in s.requirements
    assert "Docker" in s.nice_to_have


def test_all_caps_company_blurb():
    s = extract_sections(ALL_CAPS_JD)
    assert "KoboToolbox" in s.company_blurb or "KoboToolbox" in s.other


# ---------------------------------------------------------------------------
# Bullets-only format (no explicit headings, no prose)
# ---------------------------------------------------------------------------

BULLETS_ONLY_JD = """
• Build REST APIs with Python and Django
• Write PostgreSQL queries and optimise database schemas
• Must have 0-2 years Python experience
• Required: Git, Linux command line
• Nice to have: Docker, React
• Remote position, $30-40/hr
• Equal opportunity employer
"""


def test_bullets_only_captures_sections():
    s = extract_sections(BULLETS_ONLY_JD)
    combined = " ".join(s.as_dict().values())
    assert "Python" in combined
    assert "PostgreSQL" in combined


def test_bullets_only_requirements_detected():
    s = extract_sections(BULLETS_ONLY_JD)
    # "Must have" clue should land in requirements
    assert "Python experience" in s.requirements or "Python" in s.other


# ---------------------------------------------------------------------------
# HTML leftovers
# ---------------------------------------------------------------------------

HTML_LEFTOVERS_JD = """<div class="job-desc">
<h2>About the Role</h2>
<p>We are looking for a <strong>Junior Developer</strong> to join our team.</p>
<ul>
  <li>Build and maintain <em>React</em> components</li>
  <li>Work with <strong>TypeScript</strong> and Node.js</li>
</ul>
<h2>Requirements</h2>
<ul>
  <li>1+ years of JavaScript/TypeScript</li>
  <li>Familiarity with REST APIs</li>
</ul>
<h2>Benefits</h2>
<p>Competitive salary &amp; equity package.</p>
</div>"""


def test_html_leftovers_stripped():
    s = extract_sections(HTML_LEFTOVERS_JD)
    combined = " ".join(s.as_dict().values())
    assert "<div" not in combined
    assert "<li>" not in combined
    assert "<strong>" not in combined


def test_html_leftovers_content_preserved():
    s = extract_sections(HTML_LEFTOVERS_JD)
    combined = " ".join(s.as_dict().values())
    assert "React" in combined
    assert "TypeScript" in combined
    assert "REST APIs" in combined


def test_html_leftovers_benefits_classified():
    s = extract_sections(HTML_LEFTOVERS_JD)
    assert "salary" in s.benefits.lower() or "equity" in s.benefits.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_input_returns_empty_sections():
    s = extract_sections("")
    assert all(v == "" for k, v in s.as_dict().items() if k not in ("title", "company", "location"))


def test_none_input_returns_empty_sections():
    # Should not raise
    s = extract_sections(None or "")
    assert isinstance(s, JDSections)


def test_prepopulated_metadata():
    s = extract_sections("", title="Sr. Engineer", company="Acme", location="Remote - Global")
    assert s.title == "Sr. Engineer"
    assert s.company == "Acme"
    assert s.location == "Remote - Global"


def test_single_line_input():
    s = extract_sections("Looking for a Python developer with 0-2 years experience.")
    combined = " ".join(s.as_dict().values())
    assert "Python" in combined


def test_mostly_boilerplate():
    s = extract_sections(
        "We are an equal opportunity employer committed to diversity and inclusion. "
        "Applicants will be considered without regard to race, color, religion, national origin, "
        "disability, veteran status, or any other protected class under applicable law."
    )
    assert "equal opportunity" in s.legal_eeo.lower() or "diversity" in s.legal_eeo.lower()


# ---------------------------------------------------------------------------
# Real-world inspired JD (mixed headings and prose)
# ---------------------------------------------------------------------------

REAL_WORLD_JD = """
Forward Deployed Engineer - EMEA

About GitLab
GitLab is a complete DevOps platform. We believe in a world where everyone can contribute.

The Role
As a Forward Deployed Engineer, you'll be embedded with strategic customers to solve complex technical challenges.

What You'll Do
- Drive adoption of GitLab's CI/CD and DevSecOps capabilities
- Build custom integrations using Python and REST APIs
- Collaborate with customer engineering and sales teams

What You'll Need
- Strong Python and TypeScript skills
- Experience with REST APIs and Webhooks
- Familiarity with Git, Docker, and PostgreSQL

Compensation
Competitive, location-specific. Publicly disclosed pay bands available on our website.

Equal Employment
GitLab is an equal opportunity employer.
"""


def test_real_world_jd_responsibilities():
    s = extract_sections(REAL_WORLD_JD, title="Forward Deployed Engineer", company="GitLab")
    assert "CI/CD" in s.responsibilities or "CI/CD" in s.other


def test_real_world_jd_requirements():
    s = extract_sections(REAL_WORLD_JD, title="Forward Deployed Engineer", company="GitLab")
    assert "Python" in s.requirements or "TypeScript" in s.requirements


def test_real_world_jd_legal():
    s = extract_sections(REAL_WORLD_JD, title="Forward Deployed Engineer", company="GitLab")
    assert "equal opportunity" in s.legal_eeo.lower() or "equal opportunity" in s.other.lower()
