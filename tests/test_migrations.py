"""Tests verifying database schema migrations, constraints, and data integrity."""
import json
import psycopg
import pytest
from src.db.connection import get_connection
from src.db.migrate import run_migrations


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Ensure migrations have been run before executing tests."""
    run_migrations()


def test_tables_exist():
    """Verify that all expected tables are created in PostgreSQL."""
    expected_tables = {"raw_job_listings", "jobs", "job_matches", "schema_migrations"}
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public';
            """)
            tables = {row["table_name"] for row in cur.fetchall()}
            assert expected_tables.issubset(tables)


def test_raw_job_listings_unique_constraint():
    """Verify raw_job_listings enforces (source, external_id) uniqueness."""
    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            # Clean test records
            cur.execute("DELETE FROM raw_job_listings WHERE source = 'test_source';")
            
            # First insert succeeds
            cur.execute(
                """
                INSERT INTO raw_job_listings (source, external_id, payload)
                VALUES (%s, %s, %s);
                """,
                ("test_source", "ext_100", json.dumps({"title": "Test Engineer"})),
            )
            
            # Duplicate insert fails
            with pytest.raises(psycopg.errors.UniqueViolation):
                cur.execute(
                    """
                    INSERT INTO raw_job_listings (source, external_id, payload)
                    VALUES (%s, %s, %s);
                    """,
                    ("test_source", "ext_100", json.dumps({"title": "Duplicate"})),
                )
        conn.rollback()


def test_jobs_and_matches_lifecycle_and_cascade():
    """Verify job insertion, match ranking linkage, and ON DELETE CASCADE behavior."""
    test_hash = "a" * 64
    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            # Clean test job
            cur.execute("DELETE FROM jobs WHERE fingerprint_hash = %s;", (test_hash,))

            # 1. Insert Job
            cur.execute(
                """
                INSERT INTO jobs (
                    source, external_id, title, company_name, is_remote,
                    description_text, apply_url, tags, fingerprint_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id;
                """,
                (
                    "remotive",
                    "remotive_999",
                    "Junior Python Developer",
                    "Acme Corp",
                    True,
                    "Looking for a Python dev with Django experience.",
                    "https://example.com/apply",
                    ["Python", "Django", "PostgreSQL"],
                    test_hash,
                ),
            )
            job_id = cur.fetchone()["id"]

            # 2. Insert Match
            cur.execute(
                """
                INSERT INTO job_matches (
                    job_id, match_score, matched_skills, missing_skills, score_breakdown
                ) VALUES (
                    %s, %s, %s, %s, %s
                );
                """,
                (
                    job_id,
                    88.50,
                    ["Python", "Django"],
                    ["FastAPI"],
                    json.dumps({"skill_match": 80, "remote_bonus": 10}),
                ),
            )

            # Verify match exists
            cur.execute("SELECT match_score FROM job_matches WHERE job_id = %s;", (job_id,))
            match_row = cur.fetchone()
            assert float(match_row["match_score"]) == 88.50

            # 3. Delete Job and verify CASCADE deletes the match
            cur.execute("DELETE FROM jobs WHERE id = %s;", (job_id,))
            cur.execute("SELECT * FROM job_matches WHERE job_id = %s;", (job_id,))
            assert cur.fetchone() is None
        conn.rollback()
