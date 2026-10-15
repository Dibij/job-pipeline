"""Tests for tools/app.py in-browser labeling and rating backend API."""
import json
import uuid
import pytest

from src.db.connection import get_connection
from src.db.migrate import run_migrations
from tools.app import JobServerHandler


@pytest.fixture(scope="module", autouse=True)
def prepare_db():
    run_migrations()


def test_handle_label_job_success():
    """Verify labeling a job via backend handler stores record in laya_labels."""
    # Find an existing job id
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM jobs LIMIT 1;")
            row = cur.fetchone()
            assert row is not None, "Jobs table must not be empty for this test."
            job_id = str(row["id"])

    handler = JobServerHandler.__new__(JobServerHandler)

    # 1. Label as good_fit with rating 5 and notes
    res, code = handler._handle_label_job({
        "job_id": job_id,
        "label": "good_fit",
        "rating": 5,
        "notes": "Excellent role for local candidate"
    })
    assert code == 200
    assert res["success"] is True
    assert res["label"] == "good_fit"
    assert res["rating"] == 5
    assert res["notes"] == "Excellent role for local candidate"

    # Verify directly in DB
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT label, notes, metadata, sampling_stratum, label_guideline_version
                FROM laya_labels
                WHERE job_id = %s
                ORDER BY labeled_at DESC
                LIMIT 1;
            """, (job_id,))
            lbl = cur.fetchone()
            assert lbl is not None
            assert lbl["label"] == "good_fit"
            assert lbl["notes"] == "Excellent role for local candidate"
            assert lbl["metadata"]["rating"] == 5
            assert lbl["sampling_stratum"] == "web_ui"
            assert lbl["label_guideline_version"] == "v1"

    # 2. Update to maybe with rating 3
    res2, code2 = handler._handle_label_job({
        "job_id": job_id,
        "label": "maybe",
        "rating": 3,
        "notes": "Need to check salary range"
    })
    assert code2 == 200
    assert res2["label"] == "maybe"
    assert res2["rating"] == 3

    # 3. Test clear label
    res3, code3 = handler._handle_label_job({
        "job_id": job_id,
        "label": "clear",
    })
    assert code3 == 200
    assert res3["label"] is None

    # Check deleted from DB
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) as cnt FROM laya_labels WHERE job_id = %s;", (job_id,))
            assert cur.fetchone()["cnt"] == 0


def test_handle_label_job_validation():
    """Verify validation errors for bad input."""
    handler = JobServerHandler.__new__(JobServerHandler)

    # Missing job_id
    res1, code1 = handler._handle_label_job({"label": "good_fit"})
    assert code1 == 400
    assert "Missing job_id" in res1["error"]

    # Invalid UUID
    res2, code2 = handler._handle_label_job({"job_id": "not-a-uuid", "label": "good_fit"})
    assert code2 == 400
    assert "Invalid UUID" in res2["error"]

    # Invalid label
    res3, code3 = handler._handle_label_job({"job_id": str(uuid.uuid4()), "label": "super_awesome"})
    assert code3 == 400
    assert "Invalid label" in res3["error"]


def test_fetch_jobs_includes_label_and_reachability():
    """Verify _fetch_jobs includes user_label, user_notes, user_rating, and reachability."""
    handler = JobServerHandler.__new__(JobServerHandler)
    jobs = handler._fetch_jobs()
    assert len(jobs) > 0

    first = jobs[0]
    assert "id" in first
    assert "user_label" in first
    assert "user_notes" in first
    assert "user_rating" in first
    assert "reachable_from_nepal" in first
    assert "reachable_reason" in first
