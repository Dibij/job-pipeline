"""End-to-end Reddit extractor -> normalisation path with mocked HTTP."""

from unittest.mock import MagicMock

import pytest

from src.extractors.reddit import RedditExtractor
from src.models.transformers import transform_raw_listing


def _fake_response(posts):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "data": {"children": [{"data": p} for p in posts]}
    }
    return resp


POSTS = [
    {
        "id": "post1",
        "title": "[HIRING] Django developer for MVP",
        "selftext": (
            "We need a Django developer to build an MVP with PostgreSQL tests and "
            "Docker. Budget: $1,500 fixed price. Remote work. No upfront payment."
        ),
        "created_utc": 1700000000,
        "permalink": "/r/forhire/comments/post1/mvp/",
        "url": "",
    },
    {
        "id": "post2",
        "title": "Bounty: fix async bug in our SDK",
        "selftext": "Bounty of $300 for fixing an async bug. Python SDK, pytest suite included.",
        "created_utc": 1700000100,
        "permalink": "/r/forhire/comments/post2/bounty/",
        "url": "",
    },
    {
        "id": "post3",
        "title": "Weekly thread: hiring megathread",
        "selftext": "Post your jobs here.",
        "created_utc": 1700000200,
        "permalink": "/r/forhire/comments/post3/weekly/",
        "url": "",
    },
]


@pytest.fixture
def extractor(monkeypatch):
    ext = RedditExtractor(delay_seconds=0)
    monkeypatch.setattr(ext, "polite_sleep", lambda: None)
    ext._access_token = "fake-token"

    calls = {"n": 0}
    def fake_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            return _fake_response([])
        return _fake_response(POSTS)

    ext.session.get = fake_get
    return ext


def test_fetch_filters_non_job_posts(extractor):
    posts = extractor.fetch_raw()
    ids = {p["id"] for p in posts}
    assert ids == {"post1", "post2"}  # weekly thread filtered


def test_full_flow_produces_normalizable_jobs(extractor):
    posts = extractor.fetch_raw()
    jobs = extractor._to_jobs(posts)
    assert len(jobs) == 2

    hiring = next(j for j in jobs if j.external_id == "post1")
    assert hiring.opportunity_type == "job"
    assert hiring.budget_min == 1500
    assert hiring.budget_currency == "USD"
    assert hiring.is_remote is True
    assert hiring.apply_url.startswith("https://www.reddit.com/r/forhire")

    bounty = next(j for j in jobs if j.external_id == "post2")
    assert bounty.opportunity_type == "bounty"
    assert bounty.budget_min == 300

    for job in jobs:
        payload = job.model_dump(mode="json")
        roundtripped = transform_raw_listing("reddit", payload)
        assert roundtripped is not None
        assert roundtripped.opportunity_type == job.opportunity_type
        assert roundtripped.external_id == job.external_id


def test_fetch_uses_oauth_endpoint(extractor):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        return _fake_response([])

    extractor.session.get = fake_get
    extractor.fetch_raw()
    assert "oauth.reddit.com" in seen["url"]
