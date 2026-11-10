"""Tests for the Reddit extractor (offline; no network or OAuth required)."""

from datetime import datetime, timezone

import pytest

from src.extractors.reddit import RedditExtractor


def _extractor():
    return RedditExtractor(client_id=None, client_secret=None, delay_seconds=0)


class TestJobPostDetection:
    def test_hiring_tag_is_job(self):
        assert _extractor()._is_job_post("[HIRING] Django dev", "")

    def test_for_hire_tag_is_job(self):
        assert _extractor()._is_job_post("[FOR HIRE] Python dev", "")

    def test_budget_in_body_is_job(self):
        assert _extractor()._is_job_post("Need help", "We have a budget of 500 USD")

    def test_moderator_post_is_not_job(self):
        assert not _extractor()._is_job_post("Moderator announcement", "")

    def test_weekly_thread_is_not_job(self):
        assert not _extractor()._is_job_post("Weekly thread: hiring", "")


class TestOpportunityClassification:
    def test_freelance(self):
        e = _extractor()
        assert e._determine_opportunity_type("Freelance Django dev", "") == "freelance"

    def test_bounty(self):
        e = _extractor()
        assert e._determine_opportunity_type("Bounty for bug fix", "") == "bounty"

    def test_default_job(self):
        e = _extractor()
        assert e._determine_opportunity_type("Senior engineer needed", "") == "job"


class TestBudgetExtraction:
    def test_budget_label(self):
        e = _extractor()
        assert e._extract_budget("Budget: $1,500 for this") == (1500.0, "USD")

    def test_hourly_rate(self):
        e = _extractor()
        assert e._extract_budget("Rate: 75 per hr") == (75.0, "USD")

    def test_no_budget(self):
        e = _extractor()
        assert e._extract_budget("No numbers here") is None


class TestNormalization:
    def test_builds_normalized_job(self):
        e = _extractor()
        item = {
            "id": "abc123",
            "title": "[HIRING] Python developer for Django project",
            "selftext": "Freelance gig. Budget: $2,000. Remote work.",
            "subreddit": "forhire",
            "created_utc": 1700000000,
            "permalink": "/r/forhire/comments/abc123/x/",
        }
        jobs = e._to_jobs([item])
        assert len(jobs) == 1
        job = jobs[0]
        assert job.source == "reddit"
        assert job.external_id == "abc123"
        assert job.opportunity_type == "freelance"
        assert job.budget_min == 2000
        assert job.budget_currency == "USD"
        assert job.is_remote is True
        assert job.apply_url == "https://www.reddit.com/r/forhire/comments/abc123/x/"
        assert "reddit" in job.tags and "forhire" in job.tags
        assert job.fingerprint_hash

    def test_skips_blank_title(self):
        e = _extractor()
        assert e._to_jobs([{"id": "x", "title": "  "}]) == []

    def test_fingerprint_includes_type(self):
        e = _extractor()
        base = {
            "id": "1",
            "selftext": "freelance contract work",
            "subreddit": "forhire",
            "created_utc": 1700000000,
            "permalink": "/r/x/1",
        }
        freelance = e._to_jobs([{**base, "title": "Python dev"}])[0]
        job = e._to_jobs([{**base, "title": "Python dev", "selftext": ""}])[0]
        assert freelance.opportunity_type == "freelance"
        assert job.opportunity_type == "job"
        assert freelance.fingerprint_hash != job.fingerprint_hash


class TestNoCredentials:
    def test_fetch_returns_empty_without_oauth(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        e = RedditExtractor(client_id=None, client_secret=None, delay_seconds=0)
        assert e.fetch_raw() == []

    def test_stage_returns_zero_without_oauth(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        e = RedditExtractor(client_id=None, client_secret=None, delay_seconds=0)
        assert e.stage_raw() == {"total": 0, "inserted": 0, "skipped": 0}
