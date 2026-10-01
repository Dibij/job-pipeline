"""Tests for JobRepository and database deduplication pipeline."""
import pytest
from src.db.connection import get_connection
from src.db.migrate import run_migrations
from src.db.repository import JobRepository
from src.models.job import NormalizedJob


@pytest.fixture(scope="module", autouse=True)
def prepare_db():
    run_migrations()


def test_repository_upsert_and_deduplication():
    """Verify upsert_job inserts a new record and updates on matching fingerprint_hash."""
    repo = JobRepository()

    job1 = NormalizedJob(
        source="test_source",
        external_id="ext_001",
        title="Python Backend Engineer",
        company_name="Acme Corp",
        is_remote=True,
        description_text="Original description text for Python dev.",
        apply_url="https://example.com/apply1",
        tags=["Python", "Django"],
    )

    # Clean existing test jobs
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE source = 'test_source';")

    # 1. First insert
    job_id1 = repo.upsert_job(job1)
    assert job_id1 is not None

    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, description_text FROM jobs WHERE id = %s;", (job_id1,))
            row = cur.fetchone()
            assert row["title"] == "Python Backend Engineer"
            assert row["description_text"] == "Original description text for Python dev."

    # 2. Second insert with identical fingerprint (same title + company + remote) but updated description
    job2 = NormalizedJob(
        source="test_source_2",
        external_id="ext_002",
        title="Python Backend Engineer",
        company_name="Acme Corp",
        is_remote=True,
        description_text="UPDATED description text for Python dev.",
        apply_url="https://example.com/apply2",
        tags=["Python", "Django", "FastAPI"],
    )
    assert job2.fingerprint_hash == job1.fingerprint_hash

    job_id2 = repo.upsert_job(job2)
    assert job_id2 == job_id1  # Should update existing record, returning same UUID

    # Verify updated row
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT description_text, tags FROM jobs WHERE id = %s;", (job_id1,))
            row = cur.fetchone()
            assert row["description_text"] == "UPDATED description text for Python dev."
            assert "FastAPI" in row["tags"]

    # Clean up
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE source IN ('test_source', 'test_source_2');")
