"""Fresh re-check right before a GitHub issue can enter the feed.

An issue can be open when fetched and closed, assigned, or fixed minutes later.
This module re-reads the issue, its timeline (linked/closing PRs, comments,
assignee changes) and the repo's archived flag, then decides whether the item is
still clean. Results are cached for a few minutes only.

Official REST endpoints used (verify against
https://docs.github.com/en/rest/issues and .../rest/issues/timeline):
  GET /repos/{owner}/{repo}/issues/{issue_number}
  GET /repos/{owner}/{repo}/issues/{issue_number}/timeline?per_page=100
  GET /repos/{owner}/{repo}                    (archived flag)

If any call fails (timeout, 403/429, 5xx) the item is UNVERIFIED and must be
kept out of the feed, never shown as clean.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

from src import config
from src.opportunities.bounty_config import load_github_config

logger = logging.getLogger(__name__)

API = "https://api.github.com"
MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}

# A maintainer comment that says the issue is claimed or already fixed.
CLAIM_PHRASES = (
    "i'm working on this", "i am working on this", "working on this now",
    "already fixed", "fixed in", "fixed by", "this is fixed", "will fix",
    "taken", "claimed", "in progress", "i'll take", "i will take",
    "resolved by", "duplicate of",
)


@dataclass
class RecheckResult:
    ok: bool = False
    state: Optional[str] = None
    state_reason: Optional[str] = None
    closed_at: Optional[str] = None
    assignees: List[str] = field(default_factory=list)
    linked_prs: List[Dict[str, Any]] = field(default_factory=list)
    maintainer_claimed: bool = False
    maintainer_claim_evidence: str = ""
    repo_archived: bool = False
    labels_with_actor: List[Dict[str, Any]] = field(default_factory=list)
    parent_issue_url: Optional[str] = None
    sub_issue_urls: List[str] = field(default_factory=list)
    fetched_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    unverified_reason: Optional[str] = None
    http_calls: int = 0


@dataclass
class RecheckDecision:
    keep: bool
    reasons: List[str] = field(default_factory=list)
    evidence: str = ""
    verified_at: Optional[str] = None
    fetched_at: Optional[str] = None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class FreshRechecker:
    """Re-verify issues against the GitHub REST API with a short cache."""

    def __init__(
        self,
        token: Optional[str] = None,
        config_obj=None,
        cache_seconds: Optional[int] = None,
        session: Optional[requests.Session] = None,
        timeout: Optional[int] = None,
    ):
        self.cfg = config_obj or load_github_config()
        self.cache_seconds = (
            cache_seconds
            if cache_seconds is not None
            else self.cfg.thresholds.reverify_cache_seconds
        )
        self.timeout = timeout or config.REQUEST_TIMEOUT_SECONDS
        self.session = session or requests.Session()
        self.session.headers["Accept"] = "application/vnd.github+json"
        self.session.headers["X-GitHub-Api-Version"] = "2022-11-28"
        self.session.headers["User-Agent"] = "job-aggregation-pipeline"
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self._cache: Dict[str, tuple] = {}

    # ------------------------------------------------------------------ cache
    def _cache_key(self, repo: str, number: int) -> str:
        return f"{repo.lower()}#{int(number)}"

    def clear_cache(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------- http
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None):
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("[recheck] request failed %s: %s", url, exc)
            return None, "network"
        if resp.status_code == 403 or resp.status_code == 429:
            logger.warning("[recheck] rate limited on %s", url)
            return None, "rate_limited"
        if resp.status_code >= 500:
            return None, "server_error"
        if resp.status_code != 200:
            return None, f"http_{resp.status_code}"
        try:
            return resp.json(), None
        except ValueError:
            return None, "bad_json"

    # ----------------------------------------------------------------- verify
    def verify(
        self,
        repo: str,
        number: int,
        repo_meta: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> RecheckResult:
        now = now or datetime.now(timezone.utc)
        key = self._cache_key(repo, number)
        cached = self._cache.get(key)
        if cached:
            cached_at, result = cached
            if (now - cached_at).total_seconds() <= self.cache_seconds:
                return result

        result = RecheckResult(fetched_at=now)
        issue, err = self._get(f"{API}/repos/{repo}/issues/{int(number)}")
        result.http_calls += 1
        if err:
            result.unverified_reason = err
            self._cache[key] = (now, result)
            return result

        result.state = (issue.get("state") or "").lower() or None
        result.state_reason = issue.get("state_reason")
        result.closed_at = issue.get("closed_at")
        result.assignees = [
            (a or {}).get("login")
            for a in (issue.get("assignees") or [])
            if (a or {}).get("login")
        ]
        if not result.assignees and isinstance(issue.get("assignee"), dict):
            login = issue["assignee"].get("login")
            if login:
                result.assignees = [login]
        result.parent_issue_url = issue.get("parent_issue_url")
        sub = issue.get("sub_issues_summary") or {}
        if isinstance(sub, dict) and sub.get("total"):
            # The summary only carries counts; URLs require the sub_issues
            # endpoint. We record the summary in details, not fake URLs.
            result.sub_issue_urls = []

        timeline, terr = self._get(
            f"{API}/repos/{repo}/issues/{int(number)}/timeline",
            {"per_page": 100},
        )
        result.http_calls += 1
        if terr:
            result.unverified_reason = f"timeline_{terr}"
            self._cache[key] = (now, result)
            return result

        author = ((issue.get("user") or {}).get("login") or "").lower()
        for event in timeline or []:
            if not isinstance(event, dict):
                continue
            etype = event.get("event")
            if etype == "cross-referenced":
                src = (event.get("source") or {}).get("issue") or {}
                if not src.get("pull_request"):
                    continue
                pr_author = ((src.get("user") or {}).get("login") or "").lower()
                result.linked_prs.append({
                    "number": src.get("number"),
                    "author_login": pr_author,
                    "created_at": src.get("created_at"),
                    "state": (src.get("state") or "").lower() or None,
                    "merged": bool((src.get("pull_request") or {}).get("merged_at")),
                    "is_self": bool(author and pr_author == author),
                })
            elif etype == "connected":
                result.linked_prs.append({
                    "number": None,
                    "author_login": ((event.get("actor") or {}).get("login") or "").lower(),
                    "created_at": event.get("created_at"),
                    "state": None,
                    "merged": False,
                    "is_self": False,
                })
            elif etype == "commented":
                assoc = (event.get("author_association") or "").upper()
                body = (event.get("body") or "").lower()
                if assoc in MAINTAINER_ASSOCIATIONS and any(p in body for p in CLAIM_PHRASES):
                    result.maintainer_claimed = True
                    result.maintainer_claim_evidence = (
                        f"maintainer comment by "
                        f"{((event.get('user') or {}).get('login') or '?')}"
                    )
            elif etype == "labeled":
                label = (event.get("label") or {}).get("name")
                actor = ((event.get("actor") or {}).get("login") or "")
                assoc = (event.get("author_association") or "").upper()
                if label:
                    result.labels_with_actor.append({
                        "name": label,
                        "actor_login": actor,
                        "actor_association": assoc or None,
                        "maintainer_applied": assoc in MAINTAINER_ASSOCIATIONS,
                    })

        if repo_meta is not None:
            result.repo_archived = bool(
                repo_meta.get("archived") or repo_meta.get("is_archived")
            )
        else:
            repo_data, rerr = self._get(f"{API}/repos/{repo}")
            result.http_calls += 1
            if rerr:
                result.unverified_reason = f"repo_{rerr}"
                self._cache[key] = (now, result)
                return result
            result.repo_archived = bool((repo_data or {}).get("archived"))

        result.ok = True
        result.verified_at = now
        self._cache[key] = (now, result)
        return result

    # ---------------------------------------------------------------- decision
    def decide(
        self,
        issue: Dict[str, Any],
        result: RecheckResult,
        link_window_minutes: Optional[int] = None,
    ) -> RecheckDecision:
        """Apply the re-check to one issue. Pure: no network, no DB."""
        fetched = issue.get("_fetched_at") or issue.get("fetched_at")
        fetched_s = fetched.isoformat() if isinstance(fetched, datetime) else fetched
        verified_s = (
            result.verified_at.isoformat()
            if isinstance(result.verified_at, datetime)
            else result.verified_at
        )
        if not result.ok:
            return RecheckDecision(
                keep=False,
                reasons=["UNVERIFIED"],
                evidence=f"re-check failed: {result.unverified_reason or 'unknown'}",
                verified_at=None,
                fetched_at=fetched_s,
            )

        author = ((issue.get("user") or {}).get("login") or "").lower()
        reasons: List[str] = []
        evidence: List[str] = []

        if result.state == "closed" or result.closed_at:
            reasons.append("CLOSED")
            evidence.append(
                f"state={result.state or '?'} state_reason={result.state_reason or '?'}"
            )
        if result.repo_archived:
            reasons.append("CLOSED_OR_ARCHIVED_REPO")
            evidence.append("repo archived at re-check")

        if result.assignees:
            if author and author in {a.lower() for a in result.assignees}:
                reasons.append("SELF_ASSIGNED")
                evidence.append(f"self-assigned to {author}")
            else:
                reasons.append("TAKEN")
                evidence.append("assignees: " + ", ".join(result.assignees))

        if result.linked_prs:
            reasons.append("TAKEN")
            evidence.append(
                "linked PR(s): "
                + ", ".join(
                    f"#{p.get('number')}" for p in result.linked_prs if p.get("number")
                )
            )
            window = (
                link_window_minutes
                if link_window_minutes is not None
                else self.cfg.thresholds.self_fixed_link_window_minutes
            )
            issue_created = _parse_dt(issue.get("created_at"))
            for pr in result.linked_prs:
                if pr.get("is_self") or (author and pr.get("author_login") == author):
                    reasons.append("SELF_FIXED")
                    evidence.append("author also authored the linked PR")
                    break
                pr_created = _parse_dt(pr.get("created_at"))
                if issue_created and pr_created:
                    delta = abs((pr_created - issue_created).total_seconds()) / 60.0
                    if delta <= window:
                        reasons.append("SELF_FIXED")
                        evidence.append(
                            f"PR linked {int(delta)} min after issue opened"
                        )
                        break

        if result.maintainer_claimed:
            reasons.append("TAKEN")
            evidence.append(result.maintainer_claim_evidence or "maintainer says claimed")

        return RecheckDecision(
            keep=not reasons,
            reasons=list(dict.fromkeys(reasons)),
            evidence="; ".join(evidence),
            verified_at=verified_s,
            fetched_at=fetched_s,
        )
