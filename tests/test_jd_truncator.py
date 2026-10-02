"""Unit tests for src/matching/jd_truncator.py — Task 7.3.

Covers:
- Empty sections input
- Very short input
- Very long input that exceeds budget (verifies truncation and marker)
- Priority preservation (requirements kept over company blurb)
- Benefits and legal/EEO are dropped
- Real JDs sampled from local PostgreSQL database
- Assert total token count never exceeds the model/budget limit
"""
import pytest
from src.matching.jd_extractor import JDSections, extract_sections
from src.matching.jd_truncator import (
    build_truncated_laya_state,
    count_tokens,
    get_compact_cv_summary,
    get_tokenizer,
    load_token_budget_config,
    truncate_text_to_tokens,
)


@pytest.fixture(scope="module")
def tokenizer():
    return get_tokenizer()


def test_cv_summary_non_empty():
    summary = get_compact_cv_summary()
    assert "candidate:" in summary.lower()
    assert "python" in summary.lower()
    assert "0 years" in summary.lower()


def test_empty_sections_truncation(tokenizer):
    empty = JDSections()
    state = build_truncated_laya_state(empty, max_jd_tokens=300, tokenizer=tokenizer)
    assert state["title"] == ""
    assert state["requirements"] == ""
    assert state["responsibilities"] == ""
    assert state["candidate_summary"] != ""


def test_very_short_input_preserved(tokenizer):
    sec = JDSections(
        title="Junior Developer",
        company="TechCorp",
        location="Remote",
        requirements="Python 3.10 and Git.",
        responsibilities="Build APIs."
    )
    state = build_truncated_laya_state(sec, max_jd_tokens=400, tokenizer=tokenizer)
    assert state["requirements"] == "Python 3.10 and Git."
    assert state["responsibilities"] == "Build APIs."
    assert "[...]" not in state["requirements"]


def test_very_long_input_truncated_within_budget(tokenizer):
    long_requirements = "Must have extensive Python and Django expertise. " * 80
    long_responsibilities = "Develop high-scale cloud backend microservices. " * 80
    sec = JDSections(
        title="Python Engineer",
        company="BigScale",
        location="Remote",
        requirements=long_requirements,
        responsibilities=long_responsibilities,
        benefits="Free lunch, health insurance, equity options.",
        legal_eeo="We are an equal opportunity employer."
    )

    budget = 200
    state = build_truncated_laya_state(sec, max_jd_tokens=budget, tokenizer=tokenizer)

    # Check that benefits and legal were dropped
    assert "benefits" not in state
    assert "legal_eeo" not in state

    # Check that requirements was truncated with marker
    assert "[...]" in state["requirements"]

    # Calculate token count of the JD content in state
    jd_content = " ".join([
        state["requirements"],
        state["responsibilities"],
        state["nice_to_have"],
        state["company_blurb"]
    ]).strip()
    actual_tokens = count_tokens(jd_content, tokenizer=tokenizer)
    assert actual_tokens <= budget + 5  # Allow minor margin for marker decoding


def test_priority_order_drops_blurb_before_requirements(tokenizer):
    sec = JDSections(
        title="Backend Developer",
        requirements="Requirements: Python, Django, PostgreSQL. Need 0-1 years.",
        company_blurb="Company blurb: " + "We are the best global company with thousands of staff. " * 30
    )
    # Give budget enough for requirements but not full blurb
    req_tokens = count_tokens(sec.requirements, tokenizer=tokenizer)
    budget = req_tokens + 25

    state = build_truncated_laya_state(sec, max_jd_tokens=budget, tokenizer=tokenizer)
    assert state["requirements"] == sec.requirements
    # Blurb must be truncated or empty
    assert len(state["company_blurb"]) < len(sec.company_blurb)


def test_real_jds_from_database(tokenizer):
    """Test truncation on real listings stored in the local database."""
    try:
        from src.db.connection import execute_query
        rows = execute_query("""
            SELECT title, company_name, location_raw, description_text
            FROM jobs
            WHERE detected_language = 'english'
            LIMIT 5;
        """)
    except Exception as e:
        pytest.skip(f"Database unavailable: {e}")

    if not rows:
        pytest.skip("No jobs found in database")

    config = load_token_budget_config()
    max_budget = config.get("laya_input_token_budget", 566)

    for r in rows:
        sections = extract_sections(
            description_text=r["description_text"] or "",
            title=r["title"] or "",
            company=r["company_name"] or "",
            location=r["location_raw"] or ""
        )
        state = build_truncated_laya_state(
            sections, max_jd_tokens=max_budget, tokenizer=tokenizer
        )

        jd_text = " ".join([
            state["requirements"],
            state["responsibilities"],
            state["nice_to_have"],
            state["company_blurb"]
        ]).strip()
        tokens = count_tokens(jd_text, tokenizer=tokenizer)
        assert tokens <= max_budget + 5, f"Exceeded budget: {tokens} > {max_budget}"
