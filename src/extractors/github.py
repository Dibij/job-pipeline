"""GitHub Issues opportunity extractor (bounties, help-wanted, good-first-issue).

Uses the official GitHub Search REST API (https://api.github.com/search/issues):
  - Unauthenticated: 60 requests/hour.
  - With GITHUB_TOKEN (env var): 5,000 requests/hour.

Do NOT scrape github.com HTML. Search results are issue metadata only; the
extractor does not fetch individual issues or repos, keeping usage far inside
the rate budget. Reward/paid-ness is detected from labels + issue body text by
src.opportunities.compensation, and is NEVER assumed to be verified.

Bounty verdict: each collected issue is run through
src.opportunities.bounty_verdict.BountyVerdictEngine and the resulting verdict
is stored on the payload under "_bounty_verdict" so the transformer can map it
to the jobs table bounty_verdict columns. Never auto-accept or auto-message;
humans decide via triage.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from src import config
from src.extractors.base import BaseExtractor
from src.opportunities.bounty_verdict import BountyVerdictEngine

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.github.com/search/issues"

# Targeted queries: paid/bounty signals first, then community signals.
SEARCH_QUERIES = [
    'label:bounty is:issue is:open',
    '"bounty" in:body is:issue is:open',
    'label:"good first issue" is:issue is:open',
    'label:"help wanted" is:issue is:open',
]


class GitHubIssuesExtractor(BaseExtractor):
    """Extractor for paid and unpaid open-source issues via GitHub Search API."""

    def __init__(
        self,
        delay_seconds: float = 1.0,
        token: str | None = None,
        per_query: int = 50,
        queries: List[str] | None = None,
        run_verdict: bool = True,
    ):
        super().__init__(source_name="github", delay_seconds=delay_seconds)
        self.token = token if token is not None else config.GITHUB_TOKEN
        self.per_query = per_query
        self.queries = queries if queries is not None else SEARCH_QUERIES
        self.run_verdict = run_verdict
        self._verdict_engine = BountyVerdictEngine() if run_verdict else None
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers["Accept"] = "application/vnd.github+json"

    def extract_external_id(self, item: Dict[str, Any]) -> str:
        """Use the issue id (stable) with a fallback to the html_url."""
        return str(item.get("id") or item.get("html_url") or "").strip()

    @staticmethod
    def repo_from_url(repo_url: str) -> str:
        """Parse 'owner/name' from an api.github.com/repos/{owner}/{name} URL."""
        parts = (repo_url or "").rstrip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return ""

    def _run_verdict(
        self, issue: Dict[str, Any], repo_meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Run the bounty verdict engine on a single issue.

        Returns a dict suitable for storing under payload["_bounty_verdict"].
        """
        if not self._verdict_engine:
            return {}
        try:
            result = self._verdict_engine.evaluate(
                issue=issue,
                repo_meta=repo_meta,
            )
            from src.opportunities.bounty_verdict import BountyVerdictEngine as _E

            return _E.verdict_to_db_fields(result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[github] verdict failed for issue %s: %s",
                           issue.get("id"), exc)
            return {
                "bounty_verdict": "uncertain",
                "reject_reasons": [],
                "funding_evidence": None,
                "bounty_confidence": 0,
                "reject_evidence": "verdict error: " + str(exc),
            }

    def fetch_raw(self, max_pages: int = 1) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        seen: set = set()

        for query in self.queries:
            page = 1
            while page <= max_pages:
                params = {"q": query, "per_page": self.per_query, "page": page}
                try:
                    resp = self.session.get(
                        SEARCH_URL, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS
                    )
                except requests.RequestException as exc:
                    logger.warning("[github] request failed for %r: %s", query, exc)
                    break

                if resp.status_code == 403:
                    reset = resp.headers.get("X-RateLimit-Reset", "?")
                    logger.warning(
                        "[github] rate limited (403) on %r. Set GITHUB_TOKEN to raise the budget. reset=%s",
                        query, reset,
                    )
                    break
                if resp.status_code != 200:
                    logger.warning("[github] search returned HTTP %s for %r", resp.status_code, query)
                    break

                try:
                    data = resp.json()
                except ValueError:
                    logger.warning("[github] non-JSON response for %r", query)
                    break

                items = data.get("items") or []
                if not items:
                    break

                for it in items:
                    eid = self.extract_external_id(it)
                    if eid in seen:
                        continue
                    seen.add(eid)
                    it["_gh_repo"] = self.repo_from_url(it.get("repository_url") or "")
                    # Run bounty verdict so the transformer can map verdict fields.
                    if self.run_verdict:
                        it["_bounty_verdict"] = self._run_verdict(it)
                    collected.append(it)

                if len(items) < self.per_query:
                    break
                page += 1
                self.polite_sleep()

        logger.info("[github] collected %d unique issues.", len(collected))
        return collected
