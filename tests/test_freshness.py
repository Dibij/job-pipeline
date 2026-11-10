"""Tests for the freshness manager."""

from datetime import datetime, timedelta, timezone

from src.opportunities.freshness import (
    DEFAULT_INTERVAL_SECONDS,
    FreshnessManager,
    SOURCE_POLLING_INTERVALS,
)


def _now():
    return datetime.now(timezone.utc)


def test_never_seen_is_fresh():
    fm = FreshnessManager()
    assert fm.is_fresh("reddit", None) is True


def test_recent_listing_is_fresh():
    fm = FreshnessManager()
    assert fm.is_fresh("reddit", _now() - timedelta(minutes=1), "freelance")


def test_stale_freelance_listing_is_not_fresh():
    fm = FreshnessManager()
    old = _now() - timedelta(seconds=SOURCE_POLLING_INTERVALS["reddit"] + 60)
    assert fm.is_fresh("reddit", old, "freelance") is False


def test_jobs_use_longer_window():
    fm = FreshnessManager()
    age = _now() - timedelta(hours=23)
    assert fm.is_fresh("reddit", age, "job") is True
    assert fm.is_fresh("reddit", age, "freelance") is False


def test_naive_datetime_treated_as_utc():
    fm = FreshnessManager()
    naive = datetime.now(timezone.utc).replace(tzinfo=None)
    assert fm.is_fresh("reddit", naive, "freelance") is True


def test_should_poll_when_never_polled():
    fm = FreshnessManager()
    assert fm.should_poll("github") is True


def test_should_poll_respects_interval():
    fm = FreshnessManager()
    now = _now()
    fm.update_freshness("github", now)
    assert fm.should_poll("github", now + timedelta(seconds=10)) is False
    later = now + timedelta(seconds=SOURCE_POLLING_INTERVALS["github"] + 1)
    assert fm.should_poll("github", later) is True


def test_custom_interval_override():
    fm = FreshnessManager(intervals={"reddit": 60})
    old = _now() - timedelta(seconds=120)
    assert fm.is_fresh("reddit", old, "freelance") is False


def test_freshness_window_default():
    fm = FreshnessManager()
    window = fm.freshness_window("unknown_source", "freelance")
    assert window == timedelta(seconds=DEFAULT_INTERVAL_SECONDS)
