"""Unit tests for Phase 2: Ollama LLM integration, schemas, few-shot isolation, and reachability.

Pure in-memory unit tests (no active Ollama daemon or database required).
"""
import pytest
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from src.llm.schemas import (
    JDExtraction,
    TriageResult,
    JobExplanation,
    StringFieldWithQuote,
    FloatFieldWithQuote,
    ListStringFieldWithQuote,
)
from src.llm.few_shot import select_few_shot_examples
from src.llm.reachability import suggest_qualification_and_reachability
from src.llm.caching import compute_job_content_hash
from src.llm.client import (
    call_structured_ollama,
    OllamaUnavailableError,
    OllamaGenerationError,
)


def test_jd_extraction_schema_valid():
    data = {
        "required_stack": {"value": ["Python", "FastAPI"], "evidence_quote": "FastAPI expert"},
        "seniority": {"value": "junior", "evidence_quote": "Junior developer wanted"},
        "years_experience_min": {"value": 1.5, "evidence_quote": "1+ years"},
        "degree_required": {"value": False, "evidence_quote": "Degree not required"},
        "remote_policy": {"value": "remote", "evidence_quote": "100% remote"},
        "region_restrictions": {"value": [], "evidence_quote": ""},
        "work_authorization": {"value": None, "evidence_quote": ""},
        "salary_if_stated": {"value": "$60k-$80k", "evidence_quote": "$60k-$80k"},
        "extraction_status": "success",
    }
    extraction = JDExtraction.model_validate(data)
    assert extraction.required_stack.value == ["Python", "FastAPI"]
    assert extraction.seniority.value == "junior"
    assert extraction.years_experience_min.value == 1.5
    assert extraction.remote_policy.value == "remote"
    assert extraction.extraction_status == "success"


def test_triage_result_schema_constraints():
    # Valid
    tr = TriageResult(
        label="good_fit",
        confidence=0.88,
        reason="Matches Python and FastAPI backend experience",
        evidence_quote="Python developer",
    )
    assert tr.label == "good_fit"
    assert tr.confidence == 0.88

    # Invalid confidence (> 1.0)
    with pytest.raises(ValidationError):
        TriageResult(label="good_fit", confidence=1.5, reason="too high")

    # Invalid label
    with pytest.raises(ValidationError):
        TriageResult(label="super_fit", confidence=0.9, reason="invalid label")


def test_job_explanation_schema():
    exp = JobExplanation(
        why_fits="Strong alignment with Python and Postgres.",
        what_missing="Requires 3+ years experience which is a mild stretch.",
    )
    assert len(exp.why_fits) > 10
    assert len(exp.what_missing) > 10


def test_few_shot_examples_strictly_excludes_target_and_fold():
    sample_pool = [
        {"job_id": "j_target", "title": "Target Role", "company": "Co1", "label": "good_fit", "guideline_version": "v2_role_fit_only"},
        {"job_id": "j_test_fold_1", "title": "Fold Role", "company": "Co2", "label": "good_fit", "guideline_version": "v2_role_fit_only"},
        {"job_id": "j_train_1", "title": "Good Job", "company": "Co3", "label": "good_fit", "guideline_version": "v2_role_fit_only"},
        {"job_id": "j_train_2", "title": "Maybe Job", "company": "Co4", "label": "maybe", "guideline_version": "v2_role_fit_only"},
        {"job_id": "j_train_3", "title": "Bad Job", "company": "Co5", "label": "bad_fit", "guideline_version": "v2_role_fit_only"},
    ]

    examples = select_few_shot_examples(
        target_job_id="j_target",
        excluded_job_ids={"j_test_fold_1"},
        n_per_class=1,
        gold_pool=sample_pool,
    )

    ids = [e["job_id"] for e in examples]
    assert "j_target" not in ids, "Target job leaked into few-shot prompt!"
    assert "j_test_fold_1" not in ids, "Test fold job leaked into few-shot prompt!"
    assert len(ids) == 3
    assert set(e["label"] for e in examples) == {"good_fit", "maybe", "bad_fit"}


def test_reachability_and_qualification_suggestions():
    # 1. Onsite job with US restriction -> should suggest NOT_REMOTE and REGION_LOCKED
    ext_blocked = JDExtraction(
        remote_policy=StringFieldWithQuote(value="onsite"),
        region_restrictions=ListStringFieldWithQuote(value=["US Only"]),
        seniority=StringFieldWithQuote(value="senior"),
        years_experience_min=FloatFieldWithQuote(value=5.0),
    )
    sugg_blocked = suggest_qualification_and_reachability(ext_blocked)
    assert sugg_blocked["reachability"]["suggested_accessible"] is False
    assert "NOT_REMOTE" in sugg_blocked["advisory_hard_filter_codes"]
    assert "REGION_LOCKED" in sugg_blocked["advisory_hard_filter_codes"]
    assert "TOO_SENIOR" in sugg_blocked["advisory_hard_filter_codes"]
    assert "DEGREE_OR_EXP" in sugg_blocked["advisory_hard_filter_codes"]

    # 2. Remote Worldwide Junior role -> accessible & junior_friendly
    ext_open = JDExtraction(
        remote_policy=StringFieldWithQuote(value="remote"),
        region_restrictions=ListStringFieldWithQuote(value=[]),
        seniority=StringFieldWithQuote(value="junior"),
        years_experience_min=FloatFieldWithQuote(value=1.0),
    )
    sugg_open = suggest_qualification_and_reachability(ext_open)
    assert sugg_open["reachability"]["suggested_accessible"] is True
    assert sugg_open["qualification"]["seniority_fit"] == "junior_friendly"
    assert sugg_open["qualification"]["experience_fit"] == "well_matched"
    assert len(sugg_open["advisory_hard_filter_codes"]) == 0


def test_content_hash_invariance_and_sensitivity():
    job1 = {"title": "Python Dev", "company_name": "Acme", "description_text": "Write code", "irrelevant": 123}
    job2 = {"title": "Python Dev", "company_name": "Acme", "description_text": "Write code", "irrelevant": 999}
    job3 = {"title": "Python Dev", "company_name": "Acme", "description_text": "Write DIFFERENT code"}

    assert compute_job_content_hash(job1) == compute_job_content_hash(job2)
    assert compute_job_content_hash(job1) != compute_job_content_hash(job3)


@patch("src.llm.client.is_ollama_available", return_value=False)
def test_client_offline_graceful_error(mock_avail):
    with pytest.raises(OllamaUnavailableError, match="Ollama server not reachable"):
        call_structured_ollama(
            messages=[{"role": "user", "content": "hi"}],
            response_model=TriageResult,
        )


@patch("src.llm.client.is_ollama_available", return_value=True)
@patch("src.llm.client.requests.post")
def test_client_retry_on_invalid_json(mock_post, mock_avail):
    # First response is bad JSON, second response is valid JSON
    bad_resp = MagicMock()
    bad_resp.status_code = 200
    bad_resp.json.return_value = {"message": {"content": "not json"}}

    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.json.return_value = {
        "message": {
            "content": '{"label": "good_fit", "confidence": 0.95, "reason": "matches", "evidence_quote": ""}'
        }
    }

    mock_post.side_effect = [bad_resp, good_resp]

    res = call_structured_ollama(
        messages=[{"role": "user", "content": "test"}],
        response_model=TriageResult,
        max_retries=1,
    )
    assert res.label == "good_fit"
    assert res.confidence == 0.95
    assert mock_post.call_count == 2
