"""Unit tests for scripts/make_labeling_batch.py."""
import csv
from pathlib import Path
import pytest

from scripts.make_labeling_batch import score_title_rule, make_labeling_batch
import scripts.make_labeling_batch as mlb


def test_score_title_rule():
    # Boost words
    tech_title = "Junior Full-Stack Python Engineer"
    score_tech = score_title_rule(tech_title)
    assert score_tech >= 3.0  # junior, full-stack, python, engineer

    # Penalty words
    senior_title = "Senior Sales Manager"
    score_senior = score_title_rule(senior_title)
    assert score_senior < 0.0

    # Mixed
    mixed_title = "Lead Software Engineer"
    # lead (-2), software (+1), engineer (+1) = 0
    assert score_title_rule(mixed_title) == 0.0


def test_make_labeling_batch_mocked(tmp_path, monkeypatch):
    # Mock historical counts: CompanyA has 5 (blocked), CompanyB has 2, CompanyC has 0
    monkeypatch.setattr(
        mlb,
        "get_historical_company_counts",
        lambda: {"companya": 5, "companyb": 2, "elevenlabs": 53},
    )

    mock_pool = [
        {"id": "1", "title": "Software Engineer", "company_name": "CompanyA"},  # should be dropped (hist >= 5)
        {"id": "2", "title": "Python Developer", "company_name": "CompanyB"},   # hist 2, allowed
        {"id": "3", "title": "Data Engineer", "company_name": "CompanyB"},      # hist 2, allowed
        {"id": "4", "title": "Backend Engineer", "company_name": "CompanyB"},   # hist 2, allowed (batch count=3, total=5)
        {"id": "5", "title": "AI Engineer", "company_name": "CompanyB"},        # should be dropped (batch count would exceed 3)
        {"id": "6", "title": "Junior Developer", "company_name": "CompanyC"},   # allowed
        {"id": "7", "title": "Frontend Developer", "company_name": "CompanyC"}, # allowed
        {"id": "8", "title": "Web Developer", "company_name": "CompanyC"},      # allowed
        {"id": "9", "title": "Fullstack Engineer", "company_name": "CompanyC"}, # dropped (batch cap 3)
    ]
    for r in mock_pool:
        r["location_raw"] = "Remote"
        r["source"] = "test"
        r["apply_url"] = "https://example.com"
        r["company_url"] = ""
        r["title_score"] = score_title_rule(r["title"])

    monkeypatch.setattr(mlb, "fetch_candidate_pool", lambda: mock_pool)
    monkeypatch.setattr(mlb, "execute_query", lambda sql, params=None: [{"cnt": 5}])

    out_file = tmp_path / "test_batch.csv"
    res = make_labeling_batch(target_count=10, output_file=out_file, seed=42)

    assert res == out_file
    with open(out_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Verify CompanyA was dropped
    assert not any(r["company"].lower() == "companya" for r in rows)
    # Verify CompanyB has at most 3 rows
    comp_b_rows = [r for r in rows if r["company"].lower() == "companyb"]
    assert len(comp_b_rows) <= 3
    # Verify CompanyC has at most 3 rows
    comp_c_rows = [r for r in rows if r["company"].lower() == "companyc"]
    assert len(comp_c_rows) <= 3

    # Check field formatting
    for r in rows:
        assert r["label_guideline_version"] == "v2_role_fit_only"
        assert r["my_label"] == ""
        assert r["sampling_stratum"] in ("top_title_rule", "random")
