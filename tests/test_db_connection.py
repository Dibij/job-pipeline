"""Test PostgreSQL database connectivity and health."""
import pytest
from src.db.connection import get_connection, check_db_health


def test_db_connection():
    """Verify we can open a connection, run a basic query, and read results."""
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS num;")
            result = cur.fetchone()
            assert result["num"] == 1


def test_db_health():
    """Verify database health check reports correct database name and user."""
    health = check_db_health()
    assert health["status"] == "healthy"
    assert health["database"] == "job_pipeline"
    assert health["user"] == "jobseeker"
    assert "PostgreSQL" in health["version"]
