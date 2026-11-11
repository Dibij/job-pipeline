"""Tests for the GitHub Issues extractor and transformer (mocked, no network)."""
from unittest.mock import MagicMock, patch

from src.extractors.github import GitHubIssuesExtractor
from src.models.transformers import transform_github_issue


def _ext(**kw):
    """Extractor wired for deterministic offline tests (no DB, no network)."""
    kw.setdefault("delay_seconds", 0)
    kw.setdefault("use_search", True)
    kw.setdefault("use_watchlist", False)
    kw.setdefault("run_verdict", False)
    return GitHubIssuesExtractor(**kw)


def test_github_extract_external_id():
    ext = _ext()
    assert ext.extract_external_id({"id": 123, "html_url": "https://x/1"}) == "123"
    assert ext.extract_external_id({"html_url": "https://x/1"}) == "https://x/1"
    assert ext.extract_external_id({}) == ""


def test_github_repo_from_url():
    ext = _ext()
    assert ext.repo_from_url("https://api.github.com/repos/org/repo") == "org/repo"
    assert ext.repo_from_url("https://api.github.com/repos/org/repo/") == "org/repo"


def test_github_fetch_mocked_single_page():
    ext = _ext(per_query=2)

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"ETag": "abc"}
    resp.json.return_value = {
        "items": [
            {"id": 1, "number": 1, "title": "Fix bug",
             "repository_url": "https://api.github.com/repos/a/b"},
            {"id": 2, "number": 2, "title": "Add feature",
             "repository_url": "https://api.github.com/repos/c/d"},
        ]
    }
    repo_resp = MagicMock(status_code=200)
    repo_resp.json.return_value = {"full_name": "a/b", "size": 900}

    def fake_get(url, *a, **k):
        return repo_resp if "/repos/" in url else resp

    with patch.object(ext.session, "get", side_effect=fake_get) as get:
        items = ext.fetch_raw(max_pages=1)

    assert get.call_count >= 1
    # Deduplicated by repo + issue number.
    assert len(items) == 2
    assert all("_gh_repo" in it for it in items)


def test_github_fetch_respects_rate_limit():
    ext = _ext(per_query=2)

    resp = MagicMock()
    resp.status_code = 403
    resp.headers = {"X-RateLimit-Reset": "0"}

    with patch.object(ext.session, "get", return_value=resp),          patch.object(ext, "_handle_rate_limit", return_value=None):
        items = ext.fetch_raw(max_pages=1)

    assert items == []


def test_github_dedupes_by_repo_and_number():
    ext = _ext(per_query=10)
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"ETag": "x"}
    # Same issue number repeated across two queries must collapse to one.
    resp.json.return_value = {"items": [
        {"id": 1, "number": 7, "title": "Same issue",
         "repository_url": "https://api.github.com/repos/a/b"},
    ]}
    repo_resp = MagicMock(status_code=200)
    repo_resp.json.return_value = {"full_name": "a/b", "size": 900}

    def fake_get(url, *a, **k):
        return repo_resp if "/repos/" in url else resp

    with patch.object(ext.session, "get", side_effect=fake_get):
        items = ext.fetch_raw(max_pages=1)
    assert len(items) == 1


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
        "_bounty_verdict": {
            "bounty_verdict": "accept",
            "reject_reasons": [],
            "funding_evidence": {
                "platform": "bounty", "amount": 500.0, "currency": "USD",
                "source_url": "https://github.com/org/repo/issues/123",
                "source_type": "label",
            },
            "bounty_confidence": 85,
            "reject_evidence": "",
            "score": 85,
            "score_breakdown": {"funding_evidence": 40},
            "why": "Funded",
            "notes": "",
        },
    }
    job = transform_github_issue(payload)
    assert job.opportunity_type == "bounty"
    assert job.payment_verification_status == "unverified"
    assert job.budget_min is not None and float(job.budget_min) == 500.0
    assert job.source_url == "https://github.com/org/repo/issues/123"
    assert job.company_name == "org/repo"
    assert "unverified_payment_claim" in job.risk_flags
    assert job.score == 85


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


def test_transformer_maps_bounty_verdict_key():
    """Regression: transform must read 'bounty_verdict', not the old 'verdict'."""
    from src.opportunities.bounty_verdict import BountyVerdictEngine, Verdict

    engine = BountyVerdictEngine()
    issue = {
        "id": 1, "number": 7, "title": "Add pagination to the API client",
        "body": "Add pagination in src/client/api.py and a unit test. "
                "Acceptance criteria: large result sets work.",
        "state": "open", "created_at": "2026-11-09T10:00:00Z",
        "updated_at": "2026-11-10T10:00:00Z",
        "html_url": "https://github.com/acme/widgets/issues/7",
        "labels": [{"name": "good first issue"}],
        "user": {"login": "alice"}, "comments": 1,
        "repository_url": "https://api.github.com/repos/acme/widgets",
        "_gh_repo": "acme/widgets",
    }
    fields = BountyVerdictEngine.verdict_to_db_fields(
        engine.evaluate(issue, repo_meta={"full_name": "acme/widgets", "size": 1200})
    )
    assert "bounty_verdict" in fields and "verdict" not in fields

    payload = dict(issue)
    payload["_bounty_verdict"] = fields
    job = transform_github_issue(payload)
    assert job.bounty_verdict == fields["bounty_verdict"]
    assert job.score == fields["score"]


def test_stage_raw_refreshes_payload_on_conflict(monkeypatch):
    """A re-fetched issue must update its payload, not be frozen forever."""
    import src.extractors.base as base_mod

    captured = {}

    class Cur:
        def __init__(self):
            self.rows = [{"inserted": False}]
        def execute(self, sql, params=None):
            captured["sql"] = sql
        def fetchone(self):
            return self.rows.pop(0) if self.rows else None
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Conn:
        def __init__(self): self.cur = Cur()
        def cursor(self): return self.cur
        def commit(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(base_mod, "get_connection", lambda **k: Conn())

    class Ext(base_mod.BaseExtractor):
        def fetch_raw(self, max_pages=1): return []
        def extract_external_id(self, item): return str(item["id"])

    Ext("test").stage_raw([{"id": 1}])
    sql = " ".join(captured["sql"].split())
    assert "ON CONFLICT" in sql
    assert "DO UPDATE SET" in sql, "payload must refresh on re-fetch"
    assert "processed = FALSE" in sql, "re-fetched rows must be re-processed"
