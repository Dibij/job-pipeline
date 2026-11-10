"""Freshness tracking for opportunities.

Handles source-specific polling intervals and decides whether a listing should
be re-extracted or considered stale.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

# Source-specific polling intervals in seconds.
SOURCE_POLLING_INTERVALS: Dict[str, int] = {
    "python_org": 1800,  # 30 minutes
    "reddit": 600,       # 10 minutes
    "github": 300,       # 5 minutes
    "hackernews": 900,   # 15 minutes
    "remotive": 900,
    "jobicy": 900,
    "arbeitnow": 900,
    "weworkremotely": 900,
    "remoteok": 900,
    "workingnomads": 900,
    "himalayas": 900,
}

DEFAULT_INTERVAL_SECONDS = 900
# Traditional jobs are slow-moving; keep them visible for a day.
JOB_FRESHNESS_WINDOW = timedelta(days=1)


def _as_utc(value: datetime) -> datetime:
    """Normalise a datetime to an aware UTC value."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FreshnessManager:
    """Tracks per-source last-seen timestamps and freshness windows."""

    def __init__(self, intervals: Optional[Dict[str, int]] = None):
        self.last_seen: Dict[str, datetime] = {}
        self.intervals: Dict[str, int] = dict(SOURCE_POLLING_INTERVALS)
        if intervals:
            self.intervals.update(intervals)

    def freshness_window(
        self, source: str, opportunity_type: str = "job"
    ) -> timedelta:
        """Return how long a listing from this source stays fresh."""
        if opportunity_type == "job":
            return JOB_FRESHNESS_WINDOW
        return timedelta(
            seconds=self.intervals.get(source, DEFAULT_INTERVAL_SECONDS)
        )

    def is_fresh(
        self,
        source: str,
        last_seen_at: Optional[datetime],
        opportunity_type: str = "job",
    ) -> bool:
        """A listing is fresh if seen within its window (never seen => fresh)."""
        if last_seen_at is None:
            return True
        window = self.freshness_window(source, opportunity_type)
        return _as_utc(last_seen_at) >= datetime.now(timezone.utc) - window

    def should_poll(self, source: str, now: Optional[datetime] = None) -> bool:
        """Whether the source is due for another extraction pass."""
        last = self.last_seen.get(source)
        if last is None:
            return True
        current = _as_utc(now) if now else datetime.now(timezone.utc)
        interval = self.intervals.get(source, DEFAULT_INTERVAL_SECONDS)
        return current - _as_utc(last) >= timedelta(seconds=interval)

    def update_freshness(self, source: str, last_seen_at: datetime) -> None:
        """Record the most recent successful poll for a source."""
        self.last_seen[source] = _as_utc(last_seen_at)


freshness_manager = FreshnessManager()
