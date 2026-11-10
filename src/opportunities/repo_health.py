"""Repo health check for GitHub repos, cached per repo for 7 days.

Store results in the repo_health table. Failing repos go on an expiring
blocklist. Never crawl repos you have not vetted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

import requests

from src.db.connection import get_connection
from src.opportunities.bounty_config import load_github_config

logger = logging.getLogger(__name__)


@dataclass
class RepoHealth:
    repo: str
    healthy: bool
    reasons: list = field(default_factory=list)
    pushed_at: Optional[str] = None
    is_fork: bool = False
    is_archived: bool = False
    has_contributing: bool = False
    recent_merged_prs: int = 0
    maintainer_reply_days: Optional[float] = None
    repo_size_kb: int = 0
    language: Optional[str] = None
    open_prs: int = 0
    merged_prs_recent: int = 0
    blocklisted: bool = False
    blocklisted_until: Optional[str] = None


class RepoHealthChecker:
    """Assess repo health via the GitHub REST API, cached in repo_health."""

    def __init__(self, token: Optional[str] = None, config=None):
        self.config = config or load_github_config()
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/vnd.github+json"
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["User-Agent"] = "job-aggregation-pipeline"
        self._etag_cache: dict = {}

    def _get_conditional(self, url: str, params=None) -> Optional[requests.Response]:
        """GET with ETag/If-Modified-Since conditional headers + backoff."""
        headers = {}
        key = url + str(params or "")
        if key in self._etag_cache:
            etag, mtime = self._etag_cache[key]
            if etag:
                headers["If-None-Match"] = etag
            if mtime:
                headers["If-Modified-Since"] = mtime
        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=15)
        except requests.RequestException as exc:
            logger.warning("[repo_health] request failed for %s: %s", url, exc)
            return None

        if resp.status_code == 304:
            # Not modified: build a synthetic ok response from cache
            return None  # caller treats as cached
        if resp.status_code == 403:
            reset = resp.headers.get("X-RateLimit-Reset")
            logger.warning("[repo_health] rate limited on %s; reset=%s", url, reset)
            return None
        if resp.status_code != 200:
            logger.warning("[repo_health] %s returned HTTP %s", url, resp.status_code)
            return None

        # Update ETag cache
        if resp.headers.get("ETag"):
            self._etag_cache[key] = (resp.headers["ETag"], resp.headers.get("Last-Modified"))
        return resp

    def assess(self, repo: str) -> RepoHealth:
        """Return cached health if fresh (< ttl days), else re-assess."""
        now = datetime.now(timezone.utc)
        ttl_days = self.config.thresholds.repo_health_cache_ttl_days

        # Check cache + blocklist from DB
        cached = self._get_cached(repo)
        if cached:
            health = RepoHealth(**cached)
            age = (now - health.checked_at).days if health.checked_at else 999
            if health.blocklisted and health.blocklisted_until:
                try:
                    until = datetime.fromisoformat(health.blocklisted_until.replace("Z", "+00:00"))
                    if now < until:
                        return health  # still blocklisted
                except ValueError:
                    pass
            if age < ttl_days:
                return health

        health = self._fetch_health(repo)
        self._save_health(health)
        return health

    def _get_cached(self, repo: str) -> Optional[dict]:
        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT healthy, pushed_at, is_fork, is_archived, has_contributing, "
                        "recent_merged_prs, maintainer_reply_days, repo_size_kb, language, "
                        "open_prs, merged_prs_recent, checked_at, blocklisted, blocklisted_until "
                        "FROM repo_health WHERE repo = %s",
                        (repo,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    cols = [d.name for d in cur.description]
                    return dict(zip(cols, row))
        except Exception as exc:  # pragma: no cover - DB may not exist in tests
            logger.debug("[repo_health] cache read failed for %s: %s", repo, exc)
            return None

    def _save_health(self, health: RepoHealth) -> None:
        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO repo_health (
                            repo, healthy, pushed_at, is_fork, is_archived,
                            has_contributing, recent_merged_prs, maintainer_reply_days,
                            repo_size_kb, language, open_prs, merged_prs_recent,
                            checked_at, blocklisted, blocklisted_until
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
                        ON CONFLICT (repo) DO UPDATE SET
                            healthy = EXCLUDED.healthy,
                            pushed_at = EXCLUDED.pushed_at,
                            is_fork = EXCLUDED.is_fork,
                            is_archived = EXCLUDED.is_archived,
                            has_contributing = EXCLUDED.has_contributing,
                            recent_merged_prs = EXCLUDED.recent_merged_prs,
                            maintainer_reply_days = EXCLUDED.maintainer_reply_days,
                            repo_size_kb = EXCLUDED.repo_size_kb,
                            language = EXCLUDED.language,
                            open_prs = EXCLUDED.open_prs,
                            merged_prs_recent = EXCLUDED.merged_prs_recent,
                            checked_at = NOW(),
                            blocklisted = EXCLUDED.blocklisted,
                            blocklisted_until = EXCLUDED.blocklisted_until
                        """,
                        (
                            health.repo, health.healthy, health.pushed_at,
                            health.is_fork, health.is_archived, health.has_contributing,
                            health.recent_merged_prs, health.maintainer_reply_days,
                            health.repo_size_kb, health.language, health.open_prs,
                            health.merged_prs_recent, health.blocklisted,
                            health.blocklisted_until,
                        ),
                    )
        except Exception as exc:  # pragma: no cover - DB may not exist in tests
            logger.debug("[repo_health] cache write failed for %s: %s", health.repo, exc)

    def _fetch_health(self, repo: str) -> RepoHealth:
        """Fetch repo + PR/issue data and compute health."""
        health = RepoHealth(repo=repo)
        resp = self._get_conditional(f"https://api.github.com/repos/{repo}")
        if resp is None:
            health.reasons.append("rate_limited_or_error")
            return health

        data = resp.json()
        health.pushed_at = data.get("pushed_at")
        health.is_fork = bool(data.get("fork"))
        health.is_archived = bool(data.get("archived"))
        health.repo_size_kb = int(data.get("size") or 0)
        health.language = data.get("language")
        health.open_prs = int(data.get("open_issues_count") or 0)

        # Has CONTRIBUTING or similar
        contributing = self._get_conditional(f"https://api.github.com/repos/{repo}/contents/CONTRIBUTING.md")
        if contributing is not None and contributing.status_code == 200:
            health.has_contributing = True

        # Recent merged PRs (last 30 days) + maintainer reply time
        since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        prs = self._get_conditional(
            f"https://api.github.com/repos/{repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 50},
        )
        merged_recent = 0
        if prs is not None and prs.status_code == 200:
            for pr in prs.json() or []:
                if pr.get("merged_at"):
                    merged_at = pr.get("merged_at") or ""
                    if merged_at >= since:
                        merged_recent += 1
        health.merged_prs_recent = merged_recent

        # Health rules
        pushed = data.get("pushed_at")
        if pushed:
            try:
                pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - pushed_dt).days > self.config.thresholds.repo_pushed_within_days:
                    health.reasons.append("not_pushed_recently")
            except ValueError:
                pass
        if health.is_fork:
            health.reasons.append("fork")
        if health.is_archived:
            health.reasons.append("archived")
        if not health.has_contributing:
            health.reasons.append("no_contributing")
        if health.merged_prs_recent == 0:
            health.reasons.append("no_recent_merges")
        if health.repo_size_kb > self.config.thresholds.repo_size_warn_kb:
            health.reasons.append("large_codebase")

        health.healthy = (
            not health.is_fork
            and not health.is_archived
            and health.has_contributing
            and health.merged_prs_recent > 0
            and health.repo_size_kb <= self.config.thresholds.repo_size_warn_kb
        )
        if not health.healthy and health.reasons:
            # Blocklist failing repos for TTL hours
            health.blocklisted = True
            until = datetime.now(timezone.utc) + timedelta(hours=self.config.thresholds.blocklist_ttl_hours)
            health.blocklisted_until = until.isoformat()

        return health
