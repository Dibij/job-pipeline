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


def test_remotive_extract_external_id():
    """Verify RemotiveExtractor properly extracts id or url as external ID."""
    from src.extractors.remotive import RemotiveExtractor

    extractor = RemotiveExtractor(delay_seconds=0)

    item1 = {"id": 12345, "url": "https://remotive.com/job/12345"}
    assert extractor.extract_external_id(item1) == "12345"

    item2 = {"url": "https://remotive.com/job/without-id"}
    assert extractor.extract_external_id(item2) == "https://remotive.com/job/without-id"

    item3 = {}
    assert extractor.extract_external_id(item3) == ""


def test_remotive_fetch_mocked():
    """Verify RemotiveExtractor correctly parses job list from response."""
    from src.extractors.remotive import RemotiveExtractor

    extractor = RemotiveExtractor(delay_seconds=0)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {"id": 101, "title": "Python Engineer", "candidate_required_location": "Worldwide"},
            {"id": 102, "title": "React Frontend", "candidate_required_location": "Anywhere"},
        ]
    }

    with patch.object(extractor.session, "get", return_value=mock_resp):
        jobs = extractor.fetch_raw(category="software-dev")
        assert len(jobs) == 2
        assert jobs[0]["id"] == 101
        assert jobs[1]["title"] == "React Frontend"


def test_himalayas_extract_external_id():
    """Verify HimalayasExtractor properly extracts guid or applicationLink."""
    from src.extractors.himalayas import HimalayasExtractor

    extractor = HimalayasExtractor(delay_seconds=0)

    item1 = {"guid": "https://himalayas.app/jobs/123", "applicationLink": "https://example.com/apply"}
    assert extractor.extract_external_id(item1) == "https://himalayas.app/jobs/123"

    item2 = {"applicationLink": "https://example.com/apply-only"}
    assert extractor.extract_external_id(item2) == "https://example.com/apply-only"

    item3 = {}
    assert extractor.extract_external_id(item3) == ""


def test_himalayas_fetch_mocked():
    """Verify HimalayasExtractor correctly parses jobs with pagination."""
    from src.extractors.himalayas import HimalayasExtractor

    extractor = HimalayasExtractor(delay_seconds=0)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jobs": [
            {"guid": "g1", "title": "Backend Python", "companyName": "Acme"},
            {"guid": "g2", "title": "DevOps Engineer", "companyName": "Beta"},
        ]
    }

    with patch.object(extractor.session, "get", return_value=mock_resp):
        jobs = extractor.fetch_raw(limit=2, max_pages=1)
        assert len(jobs) == 2
        assert jobs[0]["guid"] == "g1"
        assert jobs[1]["companyName"] == "Beta"


def test_wwr_extract_external_id():
    """Verify WWRExtractor properly extracts guid or link."""
    from src.extractors.weworkremotely import WWRExtractor

    extractor = WWRExtractor(delay_seconds=0)

    item1 = {"guid": "https://weworkremotely.com/jobs/123", "link": "https://weworkremotely.com/jobs/123"}
    assert extractor.extract_external_id(item1) == "https://weworkremotely.com/jobs/123"

    item2 = {"link": "https://weworkremotely.com/jobs/456"}
    assert extractor.extract_external_id(item2) == "https://weworkremotely.com/jobs/456"

    item3 = {}
    assert extractor.extract_external_id(item3) == ""


def test_wwr_fetch_mocked():
    """Verify WWRExtractor correctly parses RSS XML response."""
    from src.extractors.weworkremotely import WWRExtractor

    extractor = WWRExtractor(delay_seconds=0)

    rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Acme Corp: Backend Engineer</title>
          <region>Anywhere in the World</region>
          <category>Programming</category>
          <type>Full-Time</type>
          <pubDate>Mon, 13 Oct 2026 12:00:00 +0000</pubDate>
          <guid>https://weworkremotely.com/remote-jobs/acme-backend</guid>
          <link>https://weworkremotely.com/remote-jobs/acme-backend</link>
          <description>&lt;p&gt;Build things.&lt;/p&gt;</description>
        </item>
        <item>
          <title>Beta Inc: Frontend Dev</title>
          <region>USA Only</region>
          <category>Programming</category>
          <type>Full-Time</type>
          <pubDate>Sun, 12 Oct 2026 10:00:00 +0000</pubDate>
          <guid>https://weworkremotely.com/remote-jobs/beta-frontend</guid>
          <link>https://weworkremotely.com/remote-jobs/beta-frontend</link>
          <description>&lt;p&gt;React stuff.&lt;/p&gt;</description>
        </item>
      </channel>
    </rss>"""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = rss_xml

    with patch.object(extractor.session, "get", return_value=mock_resp):
        jobs = extractor.fetch_raw()
        assert len(jobs) == 2
        assert jobs[0]["title"] == "Acme Corp: Backend Engineer"
        assert jobs[0]["region"] == "Anywhere in the World"
        assert jobs[1]["region"] == "USA Only"



def test_remoteok_extract_external_id():
    """Verify RemoteOKExtractor properly extracts id or slug."""
    from src.extractors.remoteok import RemoteOKExtractor

    extractor = RemoteOKExtractor(delay_seconds=0)

    item1 = {"id": "123456", "slug": "remote-dev-acme-123456"}
    assert extractor.extract_external_id(item1) == "123456"

    item2 = {"slug": "remote-dev-beta-789"}
    assert extractor.extract_external_id(item2) == "remote-dev-beta-789"

    item3 = {}
    assert extractor.extract_external_id(item3) == ""


def test_remoteok_fetch_mocked():
    """Verify RemoteOKExtractor skips legal notice and returns jobs."""
    from src.extractors.remoteok import RemoteOKExtractor

    extractor = RemoteOKExtractor(delay_seconds=0)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"last_updated": "2026-10-13", "legal": "See terms"},
        {"id": "101", "position": "Python Dev", "company": "Acme", "location": "Remote"},
        {"id": "102", "position": "React Dev", "company": "Beta", "location": "Worldwide"},
    ]

    with patch.object(extractor.session, "get", return_value=mock_resp):
        jobs = extractor.fetch_raw()
        assert len(jobs) == 2
        assert jobs[0]["id"] == "101"
        assert jobs[1]["position"] == "React Dev"
