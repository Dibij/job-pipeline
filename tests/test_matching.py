"""Extra tests for false-positive prevention in skill matching."""
import pytest
from src.matching.scorer import MatchScorer


def make_job(**kwargs):
    defaults = {
        "title": "Test Job",
        "description_text": "",
        "detected_language": "english",
        "experience_level": "junior",
        "is_unpaid": False,
        "is_remote": True,
        "location_raw": "Remote",
        "remote_restriction": "Worldwide",
        "tags": [],
    }
    defaults.update(kwargs)
    return defaults


def test_rag_does_not_match_leverage():
    """'rag' skill should NOT match the word 'leverage' in description."""
    scorer = MatchScorer()
    job = make_job(description_text="We leverage cloud infrastructure to drive growth.")
    _, matched, _, _ = scorer.score_job(job)
    assert "rag" not in matched


def test_git_does_not_match_digitize():
    """'git' should NOT match 'digitize' or 'digital'."""
    scorer = MatchScorer()
    job = make_job(description_text="We want to digitize our digital processes using digital tools.")
    _, matched, _, _ = scorer.score_job(job)
    assert "git" not in matched


def test_ai_does_not_match_again_or_paid():
    """'ai/ml' should NOT match 'again', 'paid', or 'detail'."""
    scorer = MatchScorer()
    job = make_job(description_text="Apply again for unpaid work in detail.")
    _, matched, _, _ = scorer.score_job(job)
    assert "ai/ml" not in matched


def test_sql_does_not_match_visual():
    """'sql' should NOT match 'visual' but should match 'SQL database'."""
    scorer = MatchScorer()
    job_no = make_job(description_text="We use visual design tools.")
    _, matched_no, _, _ = scorer.score_job(job_no)
    assert "sql" not in matched_no

    job_yes = make_job(description_text="Must know SQL and MySQL databases.")
    _, matched_yes, _, _ = scorer.score_job(job_yes)
    assert "sql" in matched_yes


def test_genuine_match_still_detected():
    """Actual matching keywords in title/description should still be caught."""
    scorer = MatchScorer()
    job = make_job(
        title="Junior Python Django Developer",
        description_text="Build REST APIs with Django REST Framework and PostgreSQL.",
    )
    _, matched, _, _ = scorer.score_job(job)
    assert "python" in matched
    assert "django" in matched
    assert "postgresql" in matched
    assert "rest-api" in matched


def test_usa_canada_latam_restriction_excludes_nepal():
    """Restriction like 'USA, Canada, Argentina, Mexico, Peru' should be INACCESSIBLE."""
    scorer = MatchScorer()
    job = make_job(
        is_remote=True,
        location_raw="USA, Canada, Argentina, Mexico, Peru",
        remote_restriction="USA, Canada, Argentina, Mexico, Peru",
    )
    _, _, _, breakdown = scorer.score_job(job)
    assert "INACCESSIBLE" in breakdown["flags"]


def test_worldwide_restriction_accessible():
    """'Worldwide' or 'Anywhere' remote jobs should be accessible from Nepal."""
    scorer = MatchScorer()
    for restriction in ["Worldwide", "Anywhere", "Global", "APAC"]:
        job = make_job(is_remote=True, location_raw="Remote", remote_restriction=restriction)
        _, _, _, breakdown = scorer.score_job(job)
        assert "INACCESSIBLE" not in breakdown["flags"], f"Failed for restriction: {restriction}"


# ---------------------------------------------------------------------------
# 6b Regression tests: Feed threshold & placeholder filtering
# ---------------------------------------------------------------------------

def test_placeholder_title_template_flagged():
    """Roles titled 'Non-Eng Template' or containing 'template' are dropped as placeholders."""
    scorer = MatchScorer()
    assert scorer.is_placeholder_title("Non-Eng Template") is True
    assert scorer.is_placeholder_title("Template of Member of Technical Staff") is True
    eligible, reason = scorer.is_feed_eligible("Non-Eng Template", [])
    assert eligible is False
    assert reason == "PLACEHOLDER"

    job = make_job(title="Non-Eng Template", description_text="")
    _, _, _, breakdown = scorer.score_job(job)
    assert "PLACEHOLDER" in breakdown["flags"]


def test_placeholder_title_test_flagged():
    """Literal test titles ('test', '[TEST]', 'Test Job') are dropped as placeholders."""
    scorer = MatchScorer()
    assert scorer.is_placeholder_title("test") is True
    assert scorer.is_placeholder_title("[TEST]") is True
    assert scorer.is_placeholder_title("Test Job") is True
    assert scorer.is_placeholder_title("test role") is True
    eligible, reason = scorer.is_feed_eligible("Test Job", [])
    assert eligible is False
    assert reason == "PLACEHOLDER"


def test_real_qa_test_engineer_not_placeholder():
    """Legitimate QA/Test engineer positions must NOT be dropped as placeholders."""
    scorer = MatchScorer()
    assert scorer.is_placeholder_title("Manufacturing Test Automation Engineer") is False
    assert scorer.is_placeholder_title("Software Test (QA) Automation Engineer") is False
    assert scorer.is_placeholder_title("Senior ATE Test Engineer") is False
    eligible, reason = scorer.is_feed_eligible("Software Test (QA) Automation Engineer", [])
    assert eligible is True
    assert reason is None


def test_zero_skill_non_technical_role_dropped():
    """A role with no matched skills and no technical title signal must NOT qualify via remote bonus alone."""
    scorer = MatchScorer()
    # Content Editor, Value Strategist, Video Creator have no technical signal in title
    assert scorer.has_technical_title_signal("Content Editor") is False
    assert scorer.has_technical_title_signal("Value Strategist") is False
    assert scorer.has_technical_title_signal("In-House Content Creator (Freelance)") is False

    eligible, reason = scorer.is_feed_eligible("Content Editor", [])
    assert eligible is False
    assert reason == "NO_TECH_SIGNAL"

    job = make_job(title="Content Editor", description_text="Edit written articles.")
    _, matched, _, breakdown = scorer.score_job(job)
    assert len(matched) == 0
    assert "NO_TECH_SIGNAL" in breakdown["flags"]


def test_zero_skill_technical_role_kept():
    """Roles like 'Full-stack Engineer - Creative Agents' with 0 matched skills MUST be kept."""
    scorer = MatchScorer()
    assert scorer.has_technical_title_signal("Full-stack Engineer - Creative Agents") is True
    assert scorer.has_technical_title_signal("Full-Stack Engineer (Backend Leaning) - Creative Agents") is True
    assert scorer.has_technical_title_signal("Data Scientist - Product Analytics") is True
    assert scorer.has_technical_title_signal("Junior Frontend Developer") is True
    assert scorer.has_technical_title_signal("Python Programmer") is True

    eligible, reason = scorer.is_feed_eligible("Full-stack Engineer - Creative Agents", [])
    assert eligible is True
    assert reason is None

    job = make_job(title="Full-stack Engineer - Creative Agents", description_text="Work on creative agent products.")
    _, _, _, breakdown = scorer.score_job(job)
    assert "NO_TECH_SIGNAL" not in breakdown["flags"]


def test_non_technical_role_with_matched_skills_kept():
    """If a role matches candidate skills, it is kept even if the title is non-standard."""
    scorer = MatchScorer()
    eligible, reason = scorer.is_feed_eligible("Remote Office Assistant", ["git"])
    assert eligible is True
    assert reason is None

