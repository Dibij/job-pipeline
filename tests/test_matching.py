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
