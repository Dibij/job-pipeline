"""tests/test_eligibility.py — Verification of unified eligibility service."""
import pytest
from src.matching.eligibility import check_eligibility, evaluate_batch
from src.matching.hard_filter import FilterReason


def test_check_eligibility_exclude_reason():
    job = {
        "title": "Software Developer",
        "description_text": "Good junior role with Python",
        "location_raw": "Remote",
        "remote_restriction": "Worldwide",
        "is_remote": True,
        "exclude_reason": "unparseable_title",
    }
    is_ok, result = check_eligibility(job)
    assert is_ok is False
    assert result.reason == FilterReason.NON_TECHNICAL
    assert "unparseable_title" in result.detail


def test_check_eligibility_passing_remote_job():
    job = {
        "title": "Junior Python Developer",
        "description_text": "Entry-level Python developer role open worldwide.",
        "location_raw": "Remote",
        "remote_restriction": "Worldwide",
        "is_remote": True,
        "is_unpaid": False,
        "detected_language": "english",
        "exclude_reason": None,
    }
    is_ok, result = check_eligibility(job)
    assert is_ok is True
    assert result.reason == FilterReason.PASS


def test_check_eligibility_senior_job():
    job = {
        "title": "Senior Staff Architect",
        "description_text": "Need 10+ years of enterprise experience.",
        "location_raw": "Remote",
        "remote_restriction": "Worldwide",
        "is_remote": True,
        "exclude_reason": None,
    }
    is_ok, result = check_eligibility(job)
    assert is_ok is False
    assert result.reason == FilterReason.TOO_SENIOR


def test_evaluate_batch():
    jobs = [
        {
            "title": "Junior Python Developer",
            "description_text": "Entry-level Python developer.",
            "location_raw": "Remote",
            "remote_restriction": "Worldwide",
            "is_remote": True,
            "exclude_reason": None,
        },
        {
            "title": "Director of Engineering",
            "description_text": "Leadership position.",
            "location_raw": "Remote",
            "remote_restriction": "Worldwide",
            "is_remote": True,
            "exclude_reason": None,
        },
        {
            "title": "Web Developer",
            "description_text": "Nice job",
            "location_raw": "Remote",
            "remote_restriction": "Worldwide",
            "is_remote": True,
            "exclude_reason": "board_not_junior_friendly",
        },
    ]
    res = evaluate_batch(jobs)
    assert res["total"] == 3
    assert len(res["passed"]) == 1
    assert len(res["failed"]) == 2
    assert len(res["excluded"]) == 1
