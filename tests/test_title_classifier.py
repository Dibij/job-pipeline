"""Unit tests for learned title classifier (Step 3)."""
import pytest
from src.matching.title_classifier import (
    predict_tech_probability,
    get_title_role_penalty,
    create_pipeline,
)


def test_tech_vs_non_tech_predictions():
    """Verify technical titles score high and non-technical titles score low."""
    tech_titles = [
        "Junior Software Engineer",
        "Python Backend Developer",
        "Full-Stack Web Developer",
        "Machine Learning Engineer",
        "Data Engineer",
    ]
    for title in tech_titles:
        p = predict_tech_probability(title)
        assert p >= 0.70, f"Expected high tech probability for {title!r}, got {p}"
        assert get_title_role_penalty(title) == 0.0

    non_tech_titles = [
        "Senior Sales Representative",
        "Account Executive, Mid-Market",
        "Group Fitness Instructor",
        "Payroll Specialist",
        "Customer Success Associate",
    ]
    for title in non_tech_titles:
        p = predict_tech_probability(title)
        assert p < 0.50, f"Expected low tech probability (<0.50) for {title!r}, got {p}"
        assert get_title_role_penalty(title) > 0.0


def test_typo_tolerance():
    """Verify char n-grams handle minor typos gracefully."""
    p_typo = predict_tech_probability("Pythn Backnd Enginer")
    assert p_typo >= 0.70, f"Char n-grams should tolerate typos, got {p_typo}"


def test_no_false_positives_on_good_fit_titles():
    """Verify known user good_fit titles never receive high non-tech penalty."""
    sample_good_titles = [
        "Junior React Developer",
        "Associate Data Engineer",
        "AI Experience Engineer (Conversational AI)",
        "Software Engineer AI Coding Tasks",
        "Web Developer (Fresh graduate welcome, WFH policy, on-job-training)",
        "Content Reviewer - United States",  # Title that blocklist falsely killed!
    ]
    for title in sample_good_titles:
        p = predict_tech_probability(title)
        # Even Content Reviewer should not be severely penalized
        penalty = get_title_role_penalty(title)
        assert penalty < 15.0, f"False positive penalty too high for good_fit title {title!r}: {penalty}"
