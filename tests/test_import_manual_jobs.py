"""Tests for scripts/import_manual_jobs.py (Brief §0)."""
import json
import pytest
from pathlib import Path
from scripts.import_manual_jobs import load_jobs_from_file, import_manual_jobs


def test_load_jobs_from_json(tmp_path: Path):
    sample = [
        {
            "title": "Junior Python Developer",
            "company_name": "Kathmandu Tech",
            "location_raw": "Kathmandu, Nepal",
            "is_remote": False,
            "description_text": "Join our team in Kathmandu. Python, Django, PostgreSQL.",
        }
    ]
    json_file = tmp_path / "test_jobs.json"
    json_file.write_text(json.dumps(sample), encoding="utf-8")

    loaded = load_jobs_from_file(json_file)
    assert len(loaded) == 1
    assert loaded[0]["title"] == "Junior Python Developer"


def test_load_jobs_from_csv(tmp_path: Path):
    csv_file = tmp_path / "test_jobs.csv"
    csv_file.write_text(
        "title,company_name,location_raw,is_remote,description_text\n"
        "AI Intern,Nepal AI Lab,Lalitpur Nepal,False,Internship in PyTorch and machine learning.\n",
        encoding="utf-8",
    )

    loaded = load_jobs_from_file(csv_file)
    assert len(loaded) == 1
    assert loaded[0]["title"] == "AI Intern"
    assert loaded[0]["is_remote"] is False


def test_import_manual_jobs_pipeline():
    """Verify manual import runs through normalization, enrichment, and filtering."""
    sample = [
        {
            "title": "Junior React Developer",
            "company_name": "Everest Labs",
            "location_raw": "Kathmandu, Nepal",
            "is_remote": False,
            "description_text": "Looking for a junior React/Next.js frontend engineer in Kathmandu. Python backend.",
        },
        {
            "title": "Senior Staff Architect",
            "company_name": "Foreign Corp",
            "location_raw": "San Francisco, CA",
            "is_remote": False,
            "description_text": "10+ years experience required.",
        }
    ]

    stats = import_manual_jobs(sample, source="manual:nepal")
    assert stats["total_read"] == 2
    assert stats["raw_staged"] == 2
    assert stats["jobs_upserted"] == 2
    # The junior Kathmandu job should pass, while senior SF job is disqualified
    assert stats["hard_filter_passed"] >= 1
    assert stats["hard_filter_disqualified"] >= 1
