"""Repo health check for GitHub repos, cached per repo for 7 days.

Design goals (learned from a real run that burned 5000 API calls in 40s):
  * Cheap: cache-first, hard per-run budget, and a quota guard that stops before
    exhausting the token's core limit.
  * Honest: a transient failure (rate limit, 5xx, timeout) is recorded as
    UNCHECKED and is never persisted as "unhealthy" or blocklisted.
  * Fair: "pass" requires MOST criteria, not all. A great repo without a
    CONTRIBUTING.md is still a great repo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

from src.db.connection import get_connection
from src.opportunities.bounty_config import load_github_config

logger = logging.getLogger(__name__)

# Criteria that make up the "most of" health score.
CRITERIA = (
    "pushed_recently",
    "not_fork",
    "not_archived",
    "has_contributing",
    "has_recent_merges",
    "reasonable_size",
    "pr_backlog_ok",
)


@dataclass
class RepoHealth:
    repo: str = ""
    healthy: bool = False
    reasons: List[str] = field(default_factory=list)
    checked: bool = True          # False = transient failure, not a judgement
    passed: int = 0
    total: int = 0
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
    checked_at: Optional[datetime] = None


class RepoHealthChecker:
    """Assess repo health via the GitHub REST API, cached in repo_health."""

    def __init__(
        self,
        token: Optional[str] = None,
        config=None,
        max_repos_per_run: int = 8,
        quota_reserve: int = 400,
    ):
        self.config = config or load_github_config()
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["User-Agent"] = "job-aggregation-pipeline"
        self._etag_cache: dict = {}
        self.max_repos_per_run = max_repos_per_run
        self.quota_reserve = quota_reserve
        self._assessed_this_run = 0
        self._quota_exhausted = False
        self._remaining: Optional[int] = None

    # ------------------------------------------------------------------ quota
    def refresh_quota(self) -> Optional[int]:
        """Read remaining core quota. Returns None if unknown."""
        try:
            resp = self.session.get("https://api.github.com/rate_limit", timeout=10)
            if resp.status_code == 200:
                core = resp.json()["resources"]["core"]
                self._remaining = int(core.get("remaining", 0))
                return self._remaining
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.debug("[repo_health] quota probe failed: %s", exc)
        return None

    def _budget_left(self) -> bool:
        """True if we may make more calls without breaching the reserve."""
        if self._quota_exhausted:
            return False
        if self._remaining is None:
            # Use the probe's return value; it may not mutate self._remaining.
            probed = self.refresh_quota()
            if probed is not None:
                self._remaining = probed
        if self._remaining is None:
            # Quota genuinely unknown (probe failed): stay conservative but
            # allow the attempt so a single offline run is not fully blocked.
            return True
        if self._remaining <= self.quota_reserve:
            if not self._quota_exhausted:
                logger.warning(
                    "[repo_health] only %s API calls left (reserve %s); "
                    "stopping health checks for this run",
                    self._remaining, self.quota_reserve,
                )
            self._quota_exhausted = True
            return False
        return True

    def _consume(self, n: int = 1) -> None:
        if self._remaining is not None:
            self._remaining -= n

    # ------------------------------------------------------------------ http
    def _get(self, url: str, params=None) -> Optional[requests.Response]:
        """GET with ETag caching. Returns None on 304/transient error.

        Sets self.last_error to a reason string when the response was transient
        so callers can mark the repo UNCHECKED instead of unhealthy.
        """
        self.last_error: Optional[str] = None
        if not self._budget_left():
            self.last_error = "quota_reserve"
            return None

        headers = {}
        key = url + repr(sorted((params or {}).items()))
        cached = self._etag_cache.get(key)
        if cached:
            etag, mtime = cached
            if etag:
                headers["If-None-Match"] = etag
            if mtime:
                headers["If-Modified-Since"] = mtime

        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=15)
        except requests.RequestException as exc:
            logger.warning("[repo_health] request failed %s: %s", url, exc)
            self.last_error = "network"
            return None

        self._consume()
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                self._remaining = int(remaining)
            except ValueError:
                pass

        if resp.status_code == 304:
            return None
        if resp.status_code in (401, 403, 429):
            self.last_error = "rate_limited"
            reset = resp.headers.get("X-RateLimit-Reset")
            logger.warning("[repo_health] rate limited on %s (reset=%s)", url, reset)
            if self._remaining is not None and self._remaining <= self.quota_reserve:
                self._quota_exhausted = True
            return None
        if resp.status_code >= 500:
            self.last_error = "server_error"
            logger.warning("[repo_health] %s returned HTTP %s", url, resp.status_code)
            return None
        if resp.status_code != 200:
            # 404 etc. are a real answer, not a transient failure.
            return resp

        if resp.headers.get("ETag"):
            self._etag_cache[key] = (
                resp.headers["ETag"],
                resp.headers.get("Last-Modified"),
            )
        return resp

    # ------------------------------------------------------------------ public
    def assess(self, repo: str) -> RepoHealth:
        """Return cached health if fresh, else re-assess within the run budget."""
        now = datetime.now(timezone.utc)

        cached = self._get_cached(repo)
        if cached:
            if cached.blocklisted and cached.blocklisted_until:
                try:
                    until = datetime.fromisoformat(
                        str(cached.blocklisted_until).replace("Z", "+00:00")
                    )
                    if now < until:
                        return cached
                except ValueError:
                    pass
            age = (now - cached.checked_at).days if cached.checked_at else 999
            if age < self.config.thresholds.repo_health_cache_ttl_days:
                return cached

        # Not cached (or stale): only spend calls if budget allows.
        if self._assessed_this_run >= self.max_repos_per_run:
            return RepoHealth(
                repo=repo, healthy=False, checked=False,
                reasons=["run_budget_exhausted"],
            )
        if not self._budget_left():
            return RepoHealth(
                repo=repo, healthy=False, checked=False, reasons=["quota_reserve"],
            )

        self._assessed_this_run += 1
        health = self._fetch_health(repo)
        # Only persist a real judgement. Transient failures must not poison the
        # cache or the blocklist.
        if health.checked:
            self._save_health(health)
        return health

    def _get_cached(self, repo: str) -> Optional[RepoHealth]:
        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT repo, healthy, pushed_at, is_fork, is_archived, "
                        "has_contributing, recent_merged_prs, maintainer_reply_days, "
                        "repo_size_kb, language, open_prs, merged_prs_recent, checked_at, "
                        "blocklisted, blocklisted_until "
                        "FROM repo_health WHERE repo = %s",
                        (repo,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
        except Exception as exc:  # pragma: no cover
            logger.debug("[repo_health] cache read failed for %s: %s", repo, exc)
            return None

        allowed = {
            "repo", "healthy", "pushed_at", "is_fork", "is_archived",
            "has_contributing", "recent_merged_prs", "maintainer_reply_days",
            "repo_size_kb", "language", "open_prs", "merged_prs_recent",
            "checked_at", "blocklisted", "blocklisted_until",
        }
        data = {k: v for k, v in dict(row).items() if k in allowed}
        data["reasons"] = []
        return RepoHealth(**data)

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
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s,%s)
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
        except Exception as exc:  # pragma: no cover
            logger.debug("[repo_health] cache write failed for %s: %s", health.repo, exc)

    # ------------------------------------------------------------------ assess
    def _fetch_health(self, repo: str) -> RepoHealth:
        """Fetch repo data (2 calls max) and apply the "most of" rule."""
        health = RepoHealth(repo=repo)
        resp = self._get(f"https://api.github.com/repos/{repo}")
        if resp is None or resp.status_code != 200:
            # Transient or missing repo: do not judge, do not persist.
            health.checked = False
            health.reasons.append(self.last_error or "unavailable")
            return health

        data = resp.json()
        health.pushed_at = data.get("pushed_at")
        health.is_fork = bool(data.get("fork"))
        health.is_archived = bool(data.get("archived"))
        health.repo_size_kb = int(data.get("size") or 0)
        health.language = data.get("language")
        health.open_prs = int(data.get("open_issues_count") or 0)

        # Merged-PR recency, one call (search API would be a second; this is cheaper).
        since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        prs = self._get(
            f"https://api.github.com/repos/{repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 30},
        )
        if prs is not None and prs.status_code == 200:
            for pr in prs.json() or []:
                merged_at = pr.get("merged_at")
                if merged_at and merged_at[:10] >= since:
                    health.merged_prs_recent += 1

        # CONTRIBUTING is optional: a 404 is normal, not a warning.
        contributing = self._get(
            f"https://api.github.com/repos/{repo}/contents/CONTRIBUTING.md"
        )
        health.has_contributing = bool(contributing is not None and contributing.status_code == 200)

        # ---- "Most of" scoring ------------------------------------------
        checks: Dict[str, bool] = {}

        pushed_ok = False
        if health.pushed_at:
            try:
                pushed_dt = datetime.fromisoformat(health.pushed_at.replace("Z", "+00:00"))
                pushed_ok = (
                    datetime.now(timezone.utc) - pushed_dt
                ).days <= self.config.thresholds.repo_pushed_within_days
            except ValueError:
                pushed_ok = True
        checks["pushed_recently"] = pushed_ok
        checks["not_fork"] = not health.is_fork
        checks["not_archived"] = not health.is_archived
        checks["has_contributing"] = health.has_contributing
        checks["has_recent_merges"] = health.merged_prs_recent > 0
        checks["reasonable_size"] = (
            health.repo_size_kb <= self.config.thresholds.repo_size_warn_kb
        )
        # Hundreds open with almost nothing merged is a warning.
        checks["pr_backlog_ok"] = not (
            health.open_prs >= 200 and health.merged_prs_recent < 5
        )

        health.passed = sum(1 for v in checks.values() if v)
        health.total = len(checks)
        health.reasons = [name for name, ok in checks.items() if not ok]

        # Hard vetoes: a fork or archived repo can never pass.
        hard_veto = health.is_fork or health.is_archived
        # "Most of": at least 5 of 7 criteria.
        health.healthy = (not hard_veto) and health.passed >= 5

        if not health.healthy:
            until = datetime.now(timezone.utc) + timedelta(
                hours=self.config.thresholds.blocklist_ttl_hours
            )
            health.blocklisted = True
            health.blocklisted_until = until.isoformat()

        return health
