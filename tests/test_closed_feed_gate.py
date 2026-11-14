"""Closed-feed gate tests (Step 1-6 of the closed-issue fix).

One test per fixture in the brief. Fields I had to guess are marked with
``# G U E S S``. Language detection was removed at the user's request, so the
Korean fixture asserts CLOSED + OWNER_BACKLOG (no NON_ENGLISH).

Run with: .venv/bin/python -m pytest tests/test_closed_feed_gate.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.opportunities.bounty_verdict import (
    FILTER_STAGE_ORDER,
    BountyVerdictEngine,
    Lane,
    RejectReason,
    Verdict,
    reason_stage,
)
from src.opportunities.recheck import FreshRechecker
from src.opportunities.repo_health import RepoHealthChecker


def _iso(*, minutes=0, hours=0, days=0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(
        minutes=minutes, hours=hours, days=days
    )
    return dt.isoformat().replace("+00:00", "Z")


def _issue(
    title,
    body="",
    *,
    state="open",
    labels=None,
    author="alice",
    assignees=None,
    author_association=None,
    days_old=None,
    minutes_old=0,
    hours_old=0,
    repo="owner/repo",
    number=1,
    linked_prs=None,
    state_reason=None,
    closed_at=None,
    parent_issue_url=None,
    parent_issue_title=None,
    extra=None,
):
    if minutes_old or hours_old or days_old:
        created = _iso(minutes=minutes_old, hours=hours_old, days=days_old or 0)
    else:
        created = _iso(days=2)
    payload = {
        "id": number,
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "state_reason": state_reason,
        "closed_at": closed_at,
        "labels": [{"name": l} for l in (labels or [])],
        "user": {"login": author},
        "author_association": author_association,
        "assignees": [{"login": a} for a in (assignees or [])],
        "assignee": {"login": assignees[0]} if assignees else None,
        "comments": 0,
        "created_at": created,
        "updated_at": _iso(days=0, hours=1),
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "_gh_repo": repo,
        "repository_url": f"https://api.github.com/repos/{repo}",
        "parent_issue_url": parent_issue_url,
        "_parent_issue_title": parent_issue_title,
    }
    if linked_prs:
        payload["_linked_prs"] = linked_prs
        payload["linked_pr"] = {"number": linked_prs[0].get("number")}
    if extra:
        payload.update(extra)
    return payload


@pytest.fixture(scope="module")
def engine():
    return BountyVerdictEngine()


# ============================================================ fixture 1
def test_fixture_math_concept_checker_closed_owner_plan(engine):
    """93minki/math-concept-checker#23: closed as completed via PR #24."""
    body = "[PLAN] 오늘의 할 일 정리\n\n이 문제를 수정합니다. PR #24 로 완료되었습니다."
    issue = _issue(
        "[PLAN] 오늘의 할 일",
        body,
        state="closed",
        state_reason="completed",
        closed_at=_iso(hours=9),
        author="93minki",
        author_association="OWNER",
        labels=["plan"],
        repo="93minki/math-concept-checker",
        number=23,
    )
    repo_meta = {
        "full_name": "93minki/math-concept-checker",
        "owner": {"login": "93minki", "type": "User"},
        "size": 40,
    }
    repo_health = {
        "contributor_count": 1,
        "outside_merged_prs_recent": 0,
        "owner_issue_share": 1.0,
    }
    res = engine.evaluate(issue, repo_meta=repo_meta, repo_health=repo_health)
    assert res.verdict == Verdict.REJECT
    # NON_ENGLISH removed at user's request.
    assert RejectReason.CLOSED in res.reject_reasons
    assert RejectReason.OWNER_BACKLOG in res.reject_reasons
    # CLOSED is stage 1 and must be first.
    assert res.reject_reasons[0] == RejectReason.CLOSED


# ============================================================ fixture 2
def test_fixture_helios_owner_kernel_parent_review(engine):
    """lexoliu/helios#670: 8 min old, owner-authored, parent review issue."""
    body = (
        "Whole-tree read found defects in the x86 kernel assembly paths.\n"
        "Fix the boot stub in arch/x86/boot.S and add a test."
    )
    issue = _issue(
        "defects found in whole-tree read",
        body,
        author="lexoliu",
        author_association="OWNER",
        labels=["bug", "security"],
        minutes_old=8,
        repo="lexoliu/helios",
        number=670,
        parent_issue_url="https://github.com/lexoliu/helios/issues/640",
        parent_issue_title="review: defects found in a whole-tree read",
    )
    repo_meta = {
        "full_name": "lexoliu/helios",
        "owner": {"login": "lexoliu", "type": "User"},
        "size": 900,
    }
    repo_health = {
        "contributor_count": 1,
        "outside_merged_prs_recent": 0,
        "owner_issue_share": 1.0,
    }
    res = engine.evaluate(issue, repo_meta=repo_meta, repo_health=repo_health)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.OWNER_BACKLOG in res.reject_reasons
    assert RejectReason.DOMAIN_PENALTY in res.reject_reasons
    assert RejectReason.NEW_ISSUE_HOLD in res.reject_reasons
    assert res.hold is True


# ============================================================ fixture 3
def test_fixture_dokimi_self_assigned_follow_up(engine):
    """intel/dokimi#598: self-assigned maintainer follow-up, 6 min old."""
    body = "Follow-up from the review of #572. Clean up the leftover checks."
    issue = _issue(
        "Follow-up from the review of #572",
        body,
        author="dokimi-dev",
        author_association="COLLABORATOR",
        assignees=["dokimi-dev"],
        minutes_old=6,
        repo="intel/dokimi",
        number=598,
    )
    repo_meta = {
        "full_name": "intel/dokimi",
        "owner": {"login": "intel", "type": "Organization"},
        "size": 5000,
    }
    repo_health = {
        "contributor_count": 18,
        "outside_merged_prs_recent": 11,
        "owner_issue_share": 0.2,
    }
    res = engine.evaluate(issue, repo_meta=repo_meta, repo_health=repo_health)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.SELF_ASSIGNED in res.reject_reasons
    assert RejectReason.FOLLOW_UP_INTERNAL in res.reject_reasons
    assert RejectReason.NEW_ISSUE_HOLD in res.reject_reasons

    # The repo itself is healthy and worth watching.
    health = _fake_health(
        repo="intel/dokimi",
        contributors=18,
        outside_merges=11,
        has_contributing=True,
        owner_issue_share=0.2,
    )
    assert health.checked is True
    assert health.healthy is True
    assert health.suggests_watchlist is True


# ============================================================ fixture 4
def test_fixture_campus_saathi_internal_team_owner(engine):
    """pryanz/campus-saathi-agents#32: owner, teammates, one campus's docs."""
    # G U E S S: "just paste" is included to satisfy the brief's TRIVIAL_TASK
    # expectation; the exact original body is not in the request.
    body = (
        "Teammates can split by category. We need one campus's official documents "
        "for the curriculum. Just paste the Hinglish aliases into data/aliases.json."
    )
    issue = _issue(
        "Add campus document aliases",
        body,
        author="pryanz",
        author_association="OWNER",
        labels=[],
        minutes_old=5,
        repo="pryanz/campus-saathi-agents",
        number=32,
    )
    repo_meta = {
        "full_name": "pryanz/campus-saathi-agents",
        "owner": {"login": "pryanz", "type": "User"},
        "size": 120,
    }
    repo_health = {
        "contributor_count": 1,
        "outside_merged_prs_recent": 0,
        "owner_issue_share": 1.0,
    }
    res = engine.evaluate(issue, repo_meta=repo_meta, repo_health=repo_health)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.INTERNAL_TEAM_TASK in res.reject_reasons
    assert RejectReason.OWNER_BACKLOG in res.reject_reasons
    assert RejectReason.LOCAL_KNOWLEDGE_REQUIRED in res.reject_reasons
    assert RejectReason.TRIVIAL_TASK in res.reject_reasons


# ============================================================ fixture 5
def test_fixture_ovh_ttyrec_self_fixed(engine):
    """ovh/ovh-ttyrec#61: author already linked closing PR #62."""
    body = "Fix the resize crash in src/ttyrec.c and add a regression test."
    issue = _issue(
        "Fix resize crash",
        body,
        author="sylvain",
        minutes_old=3,
        repo="ovh/ovh-ttyrec",
        number=61,
        linked_prs=[{
            "number": 62,
            "author_login": "sylvain",
            "created_at": _iso(minutes=2),
            "state": "open",
            "merged": False,
            "is_self": True,
        }],
    )
    repo_meta = {
        "full_name": "ovh/ovh-ttyrec",
        "owner": {"login": "ovh", "type": "Organization"},
        "size": 800,
    }
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.SELF_FIXED in res.reject_reasons
    assert RejectReason.TAKEN in res.reject_reasons


# ============================================================ fixture 6
@pytest.mark.parametrize("repo,title,label,number", [
    ("abdulsalam-create/bounty-watch", "Scope digest: 2026-11-09", "bounty-watch", 207),
    ("ariahendrawan-sudo/project-a", "Bounty Scout — 2026-11-09", "bounty-scout", 24),
])
def test_fixture_aggregator_digests(engine, repo, title, label, number):
    issue = _issue(
        title,
        "Here are the latest bounties across GitHub. Track them.",
        author="github-actions[bot]",
        labels=[label],
        repo=repo,
        number=number,
    )
    repo_meta = {"full_name": repo, "size": 300}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.AGGREGATOR_DIGEST in res.reject_reasons


# ============================================================ fixture 7
def test_fixture_kana_dojo_trivial_templated_stuffed(engine):
    body = (
        "No coding required. Under 1 minute. Just paste this placeholder sentence "
        "into the JSON file: practice variation 15."
    )
    issue = _issue(
        "Practice variation 15",
        body,
        author="kana-bot",
        labels=[
            "good first issue", "beginner", "easy", "hacktoberfest",
            "documentation", "help wanted", "first-timers-only", "good-first-pr",
        ],
        days_old=1,
        repo="lingdojo/kana-dojo",
        number=33861,
    )
    repo_meta = {"full_name": "lingdojo/kana-dojo", "size": 3000}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.TRIVIAL_TASK in res.reject_reasons
    assert RejectReason.TEMPLATED_ISSUE in res.reject_reasons
    assert RejectReason.LABEL_STUFFING in res.reject_reasons


# ============================================================ fixture 8
def test_fixture_tripsit_tripbot_still_accept_proof(engine):
    """TripSit/TripBot#1309 must stay ACCEPT in the PROOF lane."""
    body = (
        "The BountyAwards.yml workflow fails when it runs on a fork. The problem is "
        "in .github/workflows/BountyAwards.yml at the checkout step.\n\n"
        "Steps to reproduce:\n1. Fork the repo\n2. Run the workflow\n\n"
        "Expected: workflow passes. Actual: it errors.\n\n"
        "Suggested fix: set the correct token scope in the workflow file. "
        "This may depend on issue #1298."
    )
    issue = _issue(
        "BountyAwards.yml workflow fails on forks",
        body,
        author="TripSit",
        author_association="OWNER",
        labels=["S0: Review Needed", "T: Bug", "P2: Medium", "E2: Low"],
        days_old=2,
        repo="TripSit/TripBot",
        number=1309,
        extra={"_maintainer_authored": True},
    )
    repo_meta = {
        "full_name": "TripSit/TripBot",
        "size": 2000,
        "owner": {"login": "TripSit", "type": "Organization"},
    }
    repo_health = {
        "contributor_count": 42,
        "outside_merged_prs_recent": 17,
        "owner_issue_share": 0.15,
    }
    res = engine.evaluate(issue, repo_meta=repo_meta, repo_health=repo_health)
    assert res.verdict == Verdict.ACCEPT, res.reject_evidence
    assert res.lane == Lane.PROOF
    assert res.hold is False
    assert "S0: Review Needed" in res.notes
    assert "ask the maintainers" in res.notes


# ============================================================ fixture 9
class _FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = {}

    def json(self):
        return self._payload


class _FakeSession:
    """Routes GitHub URLs to canned payloads for the re-check tests."""

    def __init__(self, issue, timeline=None, repo=None):
        self.headers = {}
        self._issue = issue
        self._timeline = timeline or []
        self._repo = repo or {"archived": False}

    def get(self, url, params=None, timeout=None):
        if url.endswith("/timeline"):
            return _FakeResp(200, self._timeline)
        if "/issues/" in url:
            return _FakeResp(200, self._issue)
        return _FakeResp(200, self._repo)


def test_fixture_stale_state_closed_before_recheck():
    issue = _issue(
        "Add pagination to the API client",
        "Add pagination in src/client/api.py and a unit test.",
        author="alice",
        repo="acme/widgets",
        number=9,
    )
    closed = dict(issue)
    closed.update({"state": "closed", "state_reason": "completed",
                   "closed_at": _iso(hours=1)})
    checker = FreshRechecker(token="", session=_FakeSession(closed))
    result = checker.verify("acme/widgets", 9)
    decision = checker.decide(issue, result)
    assert result.ok is True
    assert decision.keep is False
    assert RejectReason.CLOSED in decision.reasons
    # Not in feed: decision.keep False means the extractor drops it.
    assert "CLOSED" in decision.reasons


# ============================================================ fixture 10
def test_fixture_recheck_timeout_marks_unverified():
    import requests

    class _TimeoutSession:
        headers = {}

        def get(self, *a, **k):
            raise requests.Timeout("timed out")

    issue = _issue(
        "Add pagination to the API client",
        "Add pagination in src/client/api.py and a unit test.",
        author="alice",
        repo="acme/widgets",
        number=10,
    )
    checker = FreshRechecker(token="", session=_TimeoutSession())
    result = checker.verify("acme/widgets", 10)
    decision = checker.decide(issue, result)
    assert result.ok is False
    assert decision.keep is False
    assert decision.reasons == ["UNVERIFIED"]
    assert decision.verified_at is None


# ============================================================ fixture 11
def _fake_health(repo, *, contributors, outside_merges, has_contributing,
                 owner_issue_share, owner="owner", archived=False):
    checker = RepoHealthChecker(token="", quota_reserve=0)

    repo_payload = {
        "pushed_at": _iso(days=2),
        "fork": False,
        "archived": archived,
        "size": 2000,
        "language": "Python",
        "open_issues_count": 10,
        "owner": {"login": owner, "type": "User"},
    }
    pulls = [
        {"merged_at": _iso(days=3), "user": {"login": f"dev{i}"}}
        for i in range(outside_merges)
    ]
    contributors_payload = [{"login": f"dev{i}"} for i in range(contributors)]
    issues_payload = [
        {"user": {"login": owner}} for _ in range(10)
    ]

    def fake_get(url, *a, **k):
        if "rate_limit" in url:
            return _FakeResp(200, {"resources": {"core": {"remaining": 5000}}})
        if url.endswith("/community/profile"):
            return _FakeResp(200, {
                "files": {"contributing": {"url": "x"} if has_contributing else None}
            })
        if url.endswith("/contributors"):
            return _FakeResp(200, contributors_payload)
        if url.endswith("/pulls"):
            return _FakeResp(200, pulls)
        if url.endswith("/issues"):
            return _FakeResp(200, issues_payload)
        return _FakeResp(200, repo_payload)

    checker.session.get = fake_get
    return checker._fetch_health(repo)


def test_fixture_repo_health_watchlist_rule():
    solo = _fake_health(
        "solo/dev", contributors=1, outside_merges=0,
        has_contributing=True, owner_issue_share=1.0, owner="solo",
    )
    assert solo.suggests_watchlist is False

    active = _fake_health(
        "org/active", contributors=12, outside_merges=6,
        has_contributing=True, owner_issue_share=0.2, owner="org",
    )
    assert active.suggests_watchlist is True
    assert active.outside_merged_prs_recent == 6
    assert active.has_contributing is True


# ============================================================ fixture 12
def _clean_issue(*, minutes_old=0, hours_old=0):
    body = (
        "Add pagination support to the API client. The change belongs in "
        "src/client/api.py and needs a unit test.\n\n"
        "Acceptance criteria:\n- pagination works for large result sets\n"
        "- existing tests pass\n\nSteps to reproduce the missing behaviour."
    )
    return _issue(
        "Add pagination to the API client",
        body,
        author="alice",
        labels=["E2"],
        minutes_old=minutes_old,
        hours_old=hours_old,
        repo="acme/widgets",
        number=12,
    )


def test_fixture_new_issue_hold_then_released(engine):
    young = _clean_issue(minutes_old=20)
    res_young = engine.evaluate(young, repo_meta={"full_name": "acme/widgets", "size": 1200})
    assert RejectReason.NEW_ISSUE_HOLD in res_young.reject_reasons
    assert res_young.hold is True

    old = _clean_issue(hours_old=25)
    res_old = engine.evaluate(old, repo_meta={"full_name": "acme/widgets", "size": 1200})
    assert RejectReason.NEW_ISSUE_HOLD not in res_old.reject_reasons
    assert res_old.hold is False

    # After the re-check, the 25h issue is shown (verified, open, unassigned).
    checker = FreshRechecker(token="", session=_FakeSession(old))
    result = checker.verify("acme/widgets", 12)
    decision = checker.decide(old, result)
    assert decision.keep is True
    assert decision.verified_at is not None


# ============================================================ fixture 13
def test_filter_order():
    """Fails if the ordered pipeline in Step 5 changes order."""
    assert FILTER_STAGE_ORDER == [
        "state_and_repo",
        "aggregator_and_farm",
        "taken_and_self",
        "owner_and_quality",
        "new_issue_hold",
    ]
    # Every reject reason maps to exactly one stage.
    from src.opportunities.bounty_verdict import FILTER_STAGES

    seen = set()
    for _name, reasons in FILTER_STAGES:
        for reason in reasons:
            assert reason not in seen, f"{reason} listed in two stages"
            seen.add(reason)

    # CLOSED is stage 1; SELF_ASSIGNED is stage 3; OWNER_BACKLOG is stage 4.
    assert reason_stage(RejectReason.CLOSED) == "state_and_repo"
    assert reason_stage(RejectReason.SELF_ASSIGNED) == "taken_and_self"
    assert reason_stage(RejectReason.OWNER_BACKLOG) == "owner_and_quality"
    assert reason_stage(RejectReason.NEW_ISSUE_HOLD) == "new_issue_hold"

    # And the reasons emitted by evaluate follow stage order.
    issue = _issue(
        "defects found in whole-tree read",
        "Fix the x86 kernel assembly in arch/x86/boot.S and add a test.",
        state="closed",
        state_reason="completed",
        closed_at=_iso(hours=1),
        author="lexoliu",
        author_association="OWNER",
        assignees=["lexoliu"],
        labels=["bug"],
        minutes_old=5,
        repo="lexoliu/helios",
        number=670,
        parent_issue_title="review: defects found in a whole-tree read",
        parent_issue_url="https://github.com/lexoliu/helios/issues/640",
    )
    engine = BountyVerdictEngine()
    res = engine.evaluate(
        issue,
        repo_meta={"full_name": "lexoliu/helios", "owner": {"login": "lexoliu"}, "size": 900},
        repo_health={"contributor_count": 1, "outside_merged_prs_recent": 0,
                     "owner_issue_share": 1.0},
    )
    stages = [reason_stage(r) for r in res.reject_reasons]
    order = {name: i for i, name in enumerate(FILTER_STAGE_ORDER)}
    indices = [order[s] for s in stages if s in order]
    assert indices == sorted(indices), f"reasons out of stage order: {stages}"
