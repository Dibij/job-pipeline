"""Tests for the GitHub Issues extractor and transformer (mocked, no network)."""
from unittest.mock import MagicMock, patch

from src.extractors.github import GitHubIssuesExtractor
from src.models.transformers import transform_github_issue


def test_github_extract_external_id():
    ext = GitHubIssuesExtractor(delay_seconds=0)
    assert ext.extract_external_id({"id": 123, "html_url": "https://x/1"}) == "123"
    assert ext.extract_external_id({"html_url": "https://x/1"}) == "https://x/1"
    assert ext.extract_external_id({}) == ""


def test_github_repo_from_url():
    ext = GitHubIssuesExtractor(delay_seconds=0)
    assert ext.repo_from_url("https://api.github.com/repos/org/repo") == "org/repo"
    assert ext.repo_from_url("https://api.github.com/repos/org/repo/") == "org/repo"


def test_github_fetch_mocked_single_page():
    ext = GitHubIssuesExtractor(delay_seconds=0, per_query=2)

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "items": [
            {"id": 1, "title": "Fix bug", "repository_url": "https://api.github.com/repos/a/b"},
            {"id": 2, "title": "Add feature", "repository_url": "https://api.github.com/repos/c/d"},
        ]
    }

    with patch.object(ext.session, "get", return_value=resp) as get:
        items = ext.fetch_raw(max_pages=1)

    assert get.call_count == len(ext.queries)
    # Same two issues returned by every query are deduplicated by external id.
    assert len(items) == 2
    assert all("_gh_repo" in it for it in items)


def test_github_fetch_respects_rate_limit():
    ext = GitHubIssuesExtractor(delay_seconds=0, per_query=2)

    resp = MagicMock()
    resp.status_code = 403
    resp.headers = {"X-RateLimit-Reset": "1700000000"}

    with patch.object(ext.session, "get", return_value=resp):
        items = ext.fetch_raw(max_pages=1)

    assert items == []


def test_transform_github_bounty_issue():
    payload = {
        "id": 123,
        "title": "Fix Django admin crash",
        "body": "We will pay a $500 bounty for fixing this bug.",
        "state": "open",
        "created_at": "2026-11-01T10:00:00Z",
        "html_url": "https://github.com/org/repo/issues/123",
        "labels": [{"name": "bounty"}, {"name": "good first issue"}],
        "_gh_repo": "org/repo",
    }
    job = transform_github_issue(payload)
    assert job.opportunity_type == "bounty"
    assert job.compensation_type == "bounty"
    assert job.payment_verification_status == "unverified"
    assert job.budget_min is not None and float(job.budget_min) == 500.0
    assert job.source_url == "https://github.com/org/repo/issues/123"
    assert job.company_name == "org/repo"
    assert "unverified_payment_claim" in job.risk_flags


def test_transform_github_unpaid_open_source_issue():
    payload = {
        "id": 456,
        "title": "Improve docs",
        "body": "Looking for contributors to improve the README.",
        "state": "open",
        "created_at": "2026-11-01T10:00:00Z",
        "html_url": "https://github.com/org/repo/issues/456",
        "labels": [{"name": "help wanted"}],
        "_gh_repo": "org/repo",
    }
    job = transform_github_issue(payload)
    assert job.opportunity_type == "open_source"
    assert job.compensation_type == "unknown"
    assert job.payment_verification_status == "unknown"
    assert job.status == "open"
    assert job.risk_flags == []
