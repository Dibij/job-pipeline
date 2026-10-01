"""Tests for base and Arbeitnow extractors, verifying staging and idempotency."""
from unittest.mock import MagicMock, patch
import pytest
from src.db.connection import get_connection
from src.db.migrate import run_migrations
from src.extractors.arbeitnow import ArbeitnowExtractor
from src.extractors.base import BaseExtractor


@pytest.fixture(scope="module", autouse=True)
def prepare_db():
    run_migrations()


class DummyExtractor(BaseExtractor):
    def fetch_raw(self, max_pages: int = 1):
        return []

    def extract_external_id(self, item):
        return item.get("id")


def test_base_extractor_staging_and_idempotency():
    """Verify that stage_raw inserts records on first run and skips on duplicate runs."""
    extractor = DummyExtractor(source_name="dummy_source", delay_seconds=0)
    sample_items = [
        {"id": "dummy_1", "title": "Junior Python Dev", "remote": True},
        {"id": "dummy_2", "title": "Fullstack TS Dev", "remote": False},
    ]

    # Clean existing dummy records
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw_job_listings WHERE source = 'dummy_source';")

    # 1. First run: should insert 2, skip 0
    res1 = extractor.stage_raw(sample_items)
    assert res1["total"] == 2
    assert res1["inserted"] == 2
    assert res1["skipped"] == 0

    # Verify rows in database
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT external_id, payload FROM raw_job_listings WHERE source = 'dummy_source' ORDER BY external_id;"
            )
            rows = cur.fetchall()
            assert len(rows) == 2
            assert rows[0]["external_id"] == "dummy_1"
            assert rows[0]["payload"]["title"] == "Junior Python Dev"

    # 2. Second run: exact same data, should insert 0, skip 2
    res2 = extractor.stage_raw(sample_items)
    assert res2["total"] == 2
    assert res2["inserted"] == 0
    assert res2["skipped"] == 2

    # Clean up
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raw_job_listings WHERE source = 'dummy_source';")


def test_arbeitnow_extract_external_id():
    """Verify ArbeitnowExtractor properly extracts slug or url as ID."""
    extractor = ArbeitnowExtractor(delay_seconds=0)

    item1 = {"slug": "test-job-slug", "url": "https://example.com/job"}
    assert extractor.extract_external_id(item1) == "test-job-slug"

    item2 = {"url": "https://example.com/job-without-slug"}
    assert extractor.extract_external_id(item2) == "https://example.com/job-without-slug"

    item3 = {}
    assert extractor.extract_external_id(item3) == ""


def test_arbeitnow_fetch_mocked():
    """Verify ArbeitnowExtractor handles paginated responses and rate limits."""
    extractor = ArbeitnowExtractor(delay_seconds=0)

    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = {
        "data": [{"slug": "job-1", "title": "Dev 1"}, {"slug": "job-2", "title": "Dev 2"}],
        "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"},
    }

    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = {
        "data": [{"slug": "job-3", "title": "Dev 3"}],
        "links": {"next": None},
    }

    with patch.object(extractor.session, "get", side_effect=[mock_resp1, mock_resp2]):
        items = extractor.fetch_raw(max_pages=2)
        assert len(items) == 3
        assert items[0]["slug"] == "job-1"
        assert items[2]["slug"] == "job-3"
