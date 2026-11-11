"""Tests for the GitHub quality-gate verdict engine.

One pytest per fixture from the brief. Fields I had to guess are marked with
G U E S S comments; everything else uses the details supplied in the request.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.opportunities.bounty_verdict import (
    BountyVerdictEngine,
    RejectReason,
    Verdict,
    material_state_hash,
    should_resurface,
)


def _iso(days_ago: float = 0, seconds_ago: float = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, seconds=seconds_ago)
    return dt.isoformat().replace("+00:00", "Z")


def _issue(
    title,
    body="",
    *,
    state="open",
    labels=None,
    author="alice",
    assignee=None,
    comments=0,
    days_old=2,
    updated_days_ago=None,
    linked_pr=False,
    repo="owner/repo",
    url="https://github.com/owner/repo/issues/1",
    extra=None,
):
    created = _iso(days_ago=days_old)
    updated = _iso(days_ago=updated_days_ago if updated_days_ago is not None else days_old)
    payload = {
        "id": 1,
        "number": 1,
        "title": title,
        "body": body,
        "state": state,
        "labels": [{"name": l} for l in (labels or [])],
        "user": {"login": author},
        "assignee": {"login": assignee} if assignee else None,
        "comments": comments,
        "created_at": created,
        "updated_at": updated,
        "html_url": url,
        "_gh_repo": repo,
        "repository_url": f"https://api.github.com/repos/{repo}",
    }
    if linked_pr:
        payload["linked_pr"] = {"number": 42}
    if extra:
        payload.update(extra)
    return payload


@pytest.fixture(scope="module")
def engine():
    return BountyVerdictEngine()


# ---------------------------------------------------------------- fixture 1
def test_fixture_civitai_race_condition_proof_candidate(engine):
    body = (
        "There is a race condition in the bounty claim handler. Two requests can "
        "claim the same bounty.\n\nSteps to reproduce:\n1. Open two tabs\n"
        "2. Claim simultaneously\n\nExpected: one claim wins.\nActual: both win.\n\n"
        "Fix should be in src/bounty/claim.service.ts and add a unit test."
    )
    issue = _issue("[Bug] Race condition when claiming a bounty", body, days_old=5, labels=["T: Bug"])
    repo_meta = {"full_name": "civitai/civitai", "size": 900000, "owner": {"login": "civitai"}}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.UNCERTAIN, res.reject_evidence
    assert res.score < engine.config.confidence_accept
    assert "large codebase" in res.reject_evidence.lower() or "heavy setup" in res.notes.lower()


# ---------------------------------------------------------------- fixture 2
def test_fixture_alfrexo_bounty_bot_crypto(engine):
    body = (
        "Bounty bounty bounty bounty bounty bounty bounty alert.\n"
        "Earn $750 escrow! Send payment to:\n"
        "BTC: 1A1zP1eP5QGe6u9J2z3j4k5l6m7n8o9p0q\n"
        "ETH: 0x52908400098527886E0F7030069857D2E4169EE7\n"
        "LTC: LdP8Qox1VAhCzLJNqrr74YovaWYyNBUWvL\n"
    )
    issue = _issue(
        "Bounty Bounty Bounty Bounty $750",
        body,
        author="alfrexo95",
        repo="alfrexo95/bounty-bot",
    )
    repo_meta = {"full_name": "alfrexo95/bounty-bot", "size": 12}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    for reason in (
        RejectReason.CRYPTO_WALLET_IN_BODY,
        RejectReason.BOT_OR_FARM_REPO,
        RejectReason.REPEATED_TITLE,
        RejectReason.NO_TASK,
    ):
        assert reason in res.reject_reasons, (reason, res.reject_reasons)


# ---------------------------------------------------------------- fixture 3
@pytest.mark.parametrize("num", [1382, 1389])
def test_fixture_freedom_winds_bountyscout_digest(engine, num):
    issue = _issue(
        f"Bounty Alert: {num % 7} New Opportunities",
        "Here are the latest bounties...",
        author="github-actions[bot]",
        repo="freedom-winds/BountyScout",
    )
    issue["number"] = num
    repo_meta = {"full_name": "freedom-winds/BountyScout", "size": 900}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.AGGREGATOR_DIGEST in res.reject_reasons


# ---------------------------------------------------------------- fixture 4
def test_fixture_whole_trout_clone_farm(engine):
    body = "$450 USDC task. Implement the conformance relay endpoint as specified."
    issue = _issue(
        "Implement protocol conformance relay endpoint",
        body,
        repo="WholeTroutMedia/protocol-conformance-relay",
        days_old=1,
    )
    repo_meta = {"full_name": "WholeTroutMedia/protocol-conformance-relay", "size": 20}
    res = engine.evaluate(issue, similar_titles_count=4, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.CLONE_FARM in res.reject_reasons
    # USDC is a crypto payment: illegal to receive in Nepal.
    assert RejectReason.CRYPTO_PAYMENT in res.reject_reasons


def test_fixture_bounty_plaza_clone_farm_and_farm_repo(engine):
    body = "$600 USDC task. Implement the generated technical name endpoint."
    issue = _issue(
        "Implement generated technical name endpoint",
        body,
        repo="zhangjiayang6835-cyber/bounty-plaza",
        days_old=1,
    )
    repo_meta = {"full_name": "zhangjiayang6835-cyber/bounty-plaza", "size": 30}
    res = engine.evaluate(issue, similar_titles_count=6, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.CLONE_FARM in res.reject_reasons
    assert RejectReason.BOT_OR_FARM_REPO in res.reject_reasons


# ---------------------------------------------------------------- fixture 5
def test_fixture_misaka_linked_questions_same_second(engine):
    body = "Answer the 2 linked question(s) to complete this task."
    issue = _issue(
        "[Bounty] Answer the 2 linked question(s)",
        body,
        repo="Ikalus1988/MisakaNet",
        days_old=0,
    )
    res = engine.evaluate(issue, similar_titles_count=1)
    assert res.verdict == Verdict.REJECT
    assert (
        RejectReason.CLONE_FARM in res.reject_reasons
        or RejectReason.TEMPLATED_ISSUE in res.reject_reasons
    )


# ---------------------------------------------------------------- fixture 6
def test_fixture_devloot_unfunded_notice(engine):
    body = (
        "Design spec for the LootTown economy. This design spec does not fund a "
        "bounty. It is blocked on the inventory rework. Add the token sink design."
    )
    issue = _issue(
        "Design spec: token sinks",
        body,
        repo="devloot-xyz/LootTown",
        labels=["design"],
    )
    repo_meta = {"full_name": "devloot-xyz/LootTown", "size": 400}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.UNFUNDED_NOTICE in res.reject_reasons


# ---------------------------------------------------------------- fixture 7
def test_fixture_soroban_platform_feature_taken(engine):
    body = (
        "Feature request for the bounty platform website: add a wallet connect "
        "button to the escrow app dashboard."
    )
    issue = _issue(
        "Add wallet connect to bounty platform site",
        body,
        repo="Soroban-escrow/escrow-app",
        linked_pr=True,
        labels=["enhancement"],
    )
    repo_meta = {"full_name": "Soroban-escrow/escrow-app", "size": 300}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.TAKEN in res.reject_reasons
    assert RejectReason.PLATFORM_FEATURE in res.reject_reasons


# ---------------------------------------------------------------- fixture 8
def test_fixture_mrpeppers_intake_release_watch(engine):
    body = "Intake: OpenAI announced a bug bounty program. Track it."
    issue = _issue(
        "Intake (release-watch): OpenAI bug bounty announcement",
        body,
        author="github-actions[bot]",
        repo="MrPeppersDev/agent-infrastructure-landscape",
        labels=["intake", "intake-release-watch"],
    )
    repo_meta = {"full_name": "MrPeppersDev/agent-infrastructure-landscape", "size": 200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.AGGREGATOR_DIGEST in res.reject_reasons
    assert RejectReason.WORD_ONLY_MATCH in res.reject_reasons


# ---------------------------------------------------------------- fixture 9
def test_fixture_takt_drips_wave_but_taken(engine):
    body = "Implement the vesting schedule fix in contracts/vesting.rs and add tests."
    issue = _issue(
        "Fix vesting schedule",
        body,
        repo="takt-protocol/takt-contract",
        labels=["drips-wave", "good first issue", "difficulty: easy"],
        linked_pr=True,
    )
    repo_meta = {"full_name": "takt-protocol/takt-contract", "size": 500}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.TAKEN in res.reject_reasons


def test_drips_wave_label_scores_as_funding_signal(engine):
    body = "Implement the vesting schedule fix in contracts/vesting.rs. Reward is 500 USDC."
    issue = _issue(
        "Fix vesting schedule",
        body,
        repo="takt-protocol/takt-contract",
        labels=["drips-wave", "good first issue", "difficulty: easy"],
    )
    repo_meta = {"full_name": "takt-protocol/takt-contract", "size": 500}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.funding_evidence is not None
    assert res.funding_evidence.platform == "drips-wave"
    assert res.score_breakdown.get("funding_evidence", 0) > 0


# ---------------------------------------------------------------- fixture 10
def test_fixture_balatro_in_game_bounty(engine):
    body = (
        "Feature proposal: add an in-game bounty challenge mode where players "
        "compete. This needs alignment before implementation. Difficulty: Hard."
    )
    issue = _issue(
        "Add in-game bounty challenge mode",
        body,
        repo="Balatro-Multiplayer/BalatroMultiplayerServer",
        labels=["Needs alignment", "Difficulty: Hard"],
    )
    repo_meta = {"full_name": "Balatro-Multiplayer/BalatroMultiplayerServer", "size": 800}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.WORD_ONLY_MATCH in res.reject_reasons


# ---------------------------------------------------------------- fixture 11
@pytest.mark.parametrize("title,repo", [
    ("Poker bounty tournament payout is wrong", "page-pledge/app"),
    ("Add keeper bounty to the protocol", "page-pledge/app"),
    ("fpdb bounty display bug", "fpdb-3/fpdb"),
    ("Tournament bounty calculation", "spqtc-tournament-manager/app"),
    ("Trauma Station bounty rewards", "Trauma-Station/server"),
])
def test_fixture_game_and_protocol_bounty_terms(engine, title, repo):
    body = "The bounty display shows the wrong value on the leaderboard screen."
    issue = _issue(title, body, repo=repo, labels=["bug"])
    repo_meta = {"full_name": repo, "size": 600}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.WORD_ONLY_MATCH in res.reject_reasons


# ---------------------------------------------------------------- fixture 12
def test_fixture_tripsit_tripbot_accept(engine):
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
        repo="TripSit/TripBot",
        labels=["S0: Review Needed", "T: Bug", "P2: Medium", "E2: Low"],
        author="TripSit",
        days_old=2,
        extra={"_maintainer_authored": True},
    )
    repo_meta = {"full_name": "TripSit/TripBot", "size": 2000, "owner": {"login": "TripSit"}}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.ACCEPT, res.reject_evidence
    assert res.score >= 70
    assert "S0: Review Needed" in res.notes
    assert "ask the maintainers" in res.notes
    assert "#1298" in res.notes


# ---------------------------------------------------------------- fixture 13
def test_fixture_kana_dojo_trivial_templated_label_stuffing(engine):
    body = (
        "No coding required. Under 1 minute. Just paste this placeholder sentence "
        "into the JSON file: practice variation 15."
    )
    issue = _issue(
        "Practice variation 15",
        body,
        repo="lingdojo/kana-dojo",
        labels=[
            "good first issue", "beginner", "easy", "hacktoberfest", "documentation",
            "help wanted", "first-timers-only", "good-first-pr",
        ],
        days_old=1,
    )
    repo_meta = {"full_name": "lingdojo/kana-dojo", "size": 3000}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    for reason in (
        RejectReason.TRIVIAL_TASK,
        RejectReason.TEMPLATED_ISSUE,
        RejectReason.LABEL_STUFFING,
    ):
        assert reason in res.reject_reasons, (reason, res.reject_reasons)


# ---------------------------------------------------------- synthetic accepts
def _strong_body(feature="pagination"):
    return (
        f"Add {feature} support to the API client. The change belongs in "
        f"src/client/api.py and needs a unit test.\n\n"
        f"Acceptance criteria:\n- {feature} works for large result sets\n"
        f"- existing tests pass\n\nSteps to reproduce the missing behaviour are documented."
    )


def test_synthetic_accept_funded_platform_link(engine):
    body = (
        "This task is funded on Algora: https://algora.io/owner/repo/issues/1 "
        "for 800 USD. " + _strong_body()
    )
    issue = _issue("Add pagination to the API client", body, repo="acme/widgets", days_old=2)
    repo_meta = {"full_name": "acme/widgets", "size": 1500}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.ACCEPT
    assert res.funding_evidence.amount == 800
    assert res.funding_evidence.platform == "algora.io"


def test_synthetic_accept_funded_platform_label_euro(engine):
    body = "Reward is 450 EUR via Polar. " + _strong_body("retry logic")
    issue = _issue(
        "Add retry logic to the API client",
        body,
        repo="acme/widgets",
        labels=["polar.sh"],
        days_old=1,
    )
    repo_meta = {"full_name": "acme/widgets", "size": 900}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.ACCEPT
    assert res.funding_evidence.currency == "EUR"


def test_synthetic_accept_unfunded_good_first_issue(engine):
    issue = _issue(
        "Add pagination to the API client",
        _strong_body(),
        repo="acme/widgets",
        labels=["good first issue", "help wanted", "E2"],
        days_old=3,
        comments=1,
    )
    repo_meta = {"full_name": "acme/widgets", "size": 1200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.ACCEPT
    assert res.funding_evidence is None
    assert res.score >= 70


def test_synthetic_accept_maintainer_bug_report(engine):
    issue = _issue(
        "Crash when loading the settings page",
        "The settings page crashes on load. The bug is in src/pages/settings.tsx "
        "line 42. Steps to reproduce: open settings. Expected: page renders. "
        "Actual: TypeError. Suggested fix: guard the null user object and add a test.",
        repo="acme/widgets",
        labels=["bug", "P2: Medium"],
        author="acme",
        days_old=1,
        extra={"_maintainer_authored": True},
    )
    repo_meta = {"full_name": "acme/widgets", "size": 1500, "owner": {"login": "acme"}}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.ACCEPT
    assert res.score >= 70


# -------------------------------------------------------------- edge cases
def test_edge_missing_body_rejected(engine):
    issue = _issue("Fix the thing", "", repo="acme/widgets")
    repo_meta = {"full_name": "acme/widgets", "size": 1200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.NO_TASK in res.reject_reasons


def test_edge_stale_issue_rejected(engine):
    issue = _issue("Add pagination to the API client", _strong_body(), repo="acme/widgets", days_old=40)
    repo_meta = {"full_name": "acme/widgets", "size": 1200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.STALE in res.reject_reasons


def test_edge_closed_between_runs_rejected(engine):
    issue = _issue(
        "Add pagination to the API client",
        _strong_body(),
        repo="acme/widgets",
        state="closed",
        extra={"closed_at": _iso(days_ago=1)},
    )
    repo_meta = {"full_name": "acme/widgets", "size": 1200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.TAKEN in res.reject_reasons


def test_edge_linked_pr_closed_without_merge_resurfaces(engine):
    # A previously rejected item whose only blocker was a linked PR. When the PR
    # is closed without merging the state hash changes, so it must re-surface.
    base = _issue("Add pagination to the API client", _strong_body(), repo="acme/widgets")
    with_pr = dict(base, linked_pr={"number": 9, "merged": False})
    without_pr = dict(base)
    h_with = material_state_hash(with_pr)
    h_without = material_state_hash(without_pr)
    assert h_with != h_without
    assert should_resurface(h_with, h_without) is True

    # Unchanged state must not re-surface.
    assert should_resurface(h_without, h_without) is False


def test_edge_rate_limit_response_does_not_raise(monkeypatch):
    """A 403/429 from GitHub must be handled, not crash or block the extractor."""
    from src.extractors.github import GitHubIssuesExtractor

    ext = GitHubIssuesExtractor(
        token="", use_search=False, use_watchlist=False, run_verdict=False,
        secondary_backoff_seconds=0,
    )

    class FakeResp:
        status_code = 403
        headers = {"X-RateLimit-Reset": "0"}

    # No real network: the session returns the 403 and sleep is stubbed.
    monkeypatch.setattr(ext.session, "get", lambda *a, **k: FakeResp())
    monkeypatch.setattr("src.extractors.github.time.sleep", lambda s: None)

    assert ext._conditional_get("https://api.github.com/x") is None
    ext._handle_rate_limit(FakeResp())  # must not raise or hang


def test_edge_api_timeout_returns_none(monkeypatch):
    import requests

    from src.extractors.github import GitHubIssuesExtractor

    ext = GitHubIssuesExtractor(token="", use_search=False, use_watchlist=False, run_verdict=False)

    def boom(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(ext.session, "get", boom)
    assert ext._conditional_get("https://api.github.com/x") is None


# ------------------------------------------------- crypto legal gate (Nepal)
@pytest.mark.parametrize("body", [
    "Bounty is 450 USDC for this fix. " + _strong_body(),
    "We pay in ETH. " + _strong_body(),
    "Reward in BTC for the merged PR. " + _strong_body(),
    "Payout in Solana once merged. " + _strong_body(),
])
def test_crypto_paid_bounty_rejected_even_if_otherwise_good(engine, body):
    """Receiving crypto is illegal in Nepal, so crypto-paid bounties are rejected."""
    issue = _issue("Add pagination to the API client", body, repo="acme/widgets", days_old=1)
    repo_meta = {"full_name": "acme/widgets", "size": 1200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.CRYPTO_PAYMENT in res.reject_reasons
    assert "illegal in Nepal" in res.notes


def test_crypto_software_issue_without_crypto_payment_is_allowed(engine):
    """A normal bug report touching crypto software is fine if no crypto is paid."""
    body = (
        "The Ethereum JSON-RPC client times out on reconnect. Fix in "
        "src/rpc/client.ts and add a unit test.\n\nSteps to reproduce: open the "
        "client and disconnect the network. Expected: reconnect. Actual: timeout."
    )
    issue = _issue(
        "Fix reconnect timeout in RPC client",
        body,
        repo="acme/widgets",
        labels=["bug", "E2"],
        days_old=2,
    )
    repo_meta = {"full_name": "acme/widgets", "size": 1200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert RejectReason.CRYPTO_PAYMENT not in res.reject_reasons
    assert res.verdict in (Verdict.ACCEPT, Verdict.UNCERTAIN)


def test_word_boundaries_avoid_false_crypto_matches(engine):
    """Words like 'method'/'solution'/'author' must not look like ETH/SOL."""
    body = (
        "Use a different method to solve this. The solution should also handle "
        "the author field. Fix in src/utils.py and add a test."
    )
    issue = _issue("Improve method handling", body, repo="acme/widgets", days_old=2, labels=["E2"])
    repo_meta = {"full_name": "acme/widgets", "size": 1200}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert RejectReason.CRYPTO_PAYMENT not in res.reject_reasons


def test_secondary_rate_limit_defaults_to_60s(monkeypatch):
    """Secondary limits have high remaining and no Retry-After: use 60s, not 0."""
    from src.extractors.github import GitHubIssuesExtractor

    ext = GitHubIssuesExtractor(token="", use_search=False, use_watchlist=False, run_verdict=False)
    slept = {}
    monkeypatch.setattr("src.extractors.github.time.sleep", lambda s: slept.setdefault("s", s))

    class FakeResp:
        status_code = 403
        headers = {"X-RateLimit-Remaining": "27"}  # high remaining = secondary

    ext._handle_rate_limit(FakeResp())
    assert slept.get("s") == 60.0


def test_missing_repo_metadata_does_not_look_like_farm(engine):
    """A failed repo fetch (size=None) must not be treated as 'almost no code'."""
    issue = _issue(
        "Add pagination to the API client", _strong_body(), repo="acme/widgets", days_old=2
    )
    for meta in (None, {}, {"full_name": "acme/widgets"}, {"full_name": "acme/widgets", "size": None}):
        res = engine.evaluate(issue, repo_meta=meta)
        assert RejectReason.BOT_OR_FARM_REPO not in res.reject_reasons, meta


def test_genuinely_empty_repo_is_farm(engine):
    issue = _issue("Add pagination to the API client", _strong_body(), repo="x/y", days_old=2)
    res = engine.evaluate(issue, repo_meta={"full_name": "x/y", "size": 3})
    assert RejectReason.BOT_OR_FARM_REPO in res.reject_reasons


def test_normalize_title_strips_prefixes_and_numbers(engine):
    from src.extractors.github import GitHubIssuesExtractor

    f = GitHubIssuesExtractor.normalize_title
    assert f("[CSS 2024] Display (display)") == f("[CSS 2025] Display (display2)")
    assert f("feat(devx): add canary check 12") == f("feat(devx): add canary check 99")
    assert "0xdeadbeef" not in f("Fix deadbeef issue 0xdeadbeef")


# ------------------------------------------------- repo health budget/quota
def test_repo_health_most_of_rule_not_all():
    """A repo missing only CONTRIBUTING still passes: 6/7 criteria."""
    from src.opportunities.repo_health import RepoHealthChecker

    checker = RepoHealthChecker(token="", quota_reserve=0)

    class Resp:
        headers = {}
        def __init__(self, status, payload=None):
            self.status_code = status
            self._p = payload if payload is not None else {}
        def json(self):
            return self._p

    repo_payload = {
        "pushed_at": _iso(days_ago=3), "fork": False, "archived": False,
        "size": 2000, "language": "Python", "open_issues_count": 12,
    }
    pulls = [{"merged_at": _iso(days_ago=2)} for _ in range(4)]

    def fake_get(url, *a, **k):
        if "rate_limit" in url:
            return Resp(200, {"resources": {"core": {"remaining": 5000}}})
        if "CONTRIBUTING" in url:
            return Resp(404)              # 404 is a real answer, not an error
        if url.endswith("/pulls"):
            return Resp(200, pulls)
        return Resp(200, repo_payload)

    checker.session.get = fake_get
    health = checker._fetch_health("acme/widgets")
    assert health.checked is True
    assert health.has_contributing is False
    assert health.passed >= 5, health.reasons
    assert health.healthy is True, health.reasons


def test_repo_health_transient_failure_is_unchecked_not_blocklisted():
    """A 403/timeout must never be persisted as an unhealthy judgement."""
    from src.opportunities.repo_health import RepoHealthChecker

    checker = RepoHealthChecker(token="", quota_reserve=0)
    saved = {"n": 0}
    checker._save_health = lambda h: saved.__setitem__("n", saved["n"] + 1)
    checker._get_cached = lambda repo: None

    class RateLimited:
        status_code = 403
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"}

    checker.session.get = lambda *a, **k: RateLimited()
    health = checker.assess("acme/widgets")
    assert health.checked is False
    assert health.healthy is False
    assert saved["n"] == 0, "transient failure must not be persisted"


def test_repo_health_respects_quota_reserve():
    """No calls are made once remaining <= reserve."""
    from src.opportunities.repo_health import RepoHealthChecker

    checker = RepoHealthChecker(token="", quota_reserve=400)
    checker._get_cached = lambda repo: None
    checker.refresh_quota = lambda: 350

    called = {"n": 0}
    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not call the API below the reserve")
    checker.session.get = boom

    health = checker.assess("acme/widgets")
    assert called["n"] == 0
    assert health.checked is False
    assert "quota_reserve" in health.reasons


def test_repo_health_caps_repos_per_run():
    from src.opportunities.repo_health import RepoHealthChecker, RepoHealth

    checker = RepoHealthChecker(token="", quota_reserve=0, max_repos_per_run=1)
    checker._get_cached = lambda repo: None
    checker.refresh_quota = lambda: 5000
    checker._fetch_health = lambda repo: RepoHealth(repo=repo, healthy=True, checked=True)

    checker.assess("a/one")
    second = checker.assess("b/two")
    assert second.checked is False
    assert "run_budget_exhausted" in second.reasons


def test_extractor_does_not_auto_grow_watchlist(monkeypatch):
    """A search run must not add every accepted repo to the watchlist."""
    from src.extractors.github import GitHubIssuesExtractor

    ext = GitHubIssuesExtractor(token="", use_search=True, use_watchlist=False, run_verdict=False)
    added = []
    monkeypatch.setattr(ext, "_add_to_watchlist", lambda r, source="search": added.append(r))
    monkeypatch.setattr(ext, "_search_source", lambda mp: [
        {"id": i, "number": i, "title": f"t{i}",
         "repository_url": f"https://api.github.com/repos/o/r{i}"} for i in range(3)
    ])
    monkeypatch.setattr(ext, "_fetch_repo_meta", lambda repo: {"full_name": repo, "size": 900})
    ext.fetch_raw(max_pages=1)
    assert added == []


# ------------------------------------------- non-coding issue detection
def test_marketplace_submission_form_rejected(engine):
    issue = _issue(
        "[Server Submission]: Oxyo (oxyo-mcp) — Persistent Memory",
        "### GitHub Repository URL\nhttps://github.com/x/y\n### Logo Image\n![logo](x.png)\n"
        "### Description\nA memory server. Add it to the directory listing.",
        repo="cline/mcp-marketplace",
        days_old=2,
    )
    repo_meta = {"full_name": "cline/mcp-marketplace", "size": 128}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.NOT_A_CODING_TASK in res.reject_reasons


def test_software_download_spam_rejected(engine):
    issue = _issue(
        "MixDesk X 1.42.030 for Windows",
        "Boost your audio production: download MixDesk X latest version! "
        "Free download, full version with activation key included.",
        repo="samaansari04/All-Softwares",
        days_old=1,
    )
    repo_meta = {"full_name": "samaansari04/All-Softwares", "size": 0}
    res = engine.evaluate(issue, repo_meta=repo_meta)
    assert res.verdict == Verdict.REJECT
    assert RejectReason.NOT_A_CODING_TASK in res.reject_reasons


def test_talk_announcement_rejected(engine):
    issue = _issue(
        "AWARE-AI Winter Symposium midpoint talk",
        "I will present the midpoint results at the symposium in January.",
        repo="acme/talks",
        days_old=3,
    )
    res = engine.evaluate(issue, repo_meta={"full_name": "acme/talks", "size": 900})
    assert res.verdict == Verdict.REJECT
    assert RejectReason.NOT_A_CODING_TASK in res.reject_reasons


def test_normal_bug_report_not_flagged_as_non_coding(engine):
    issue = _issue(
        "Fix crash when loading settings",
        "Steps to reproduce: open settings. Expected: renders. Actual: TypeError. "
        "Fix in src/pages/settings.tsx and add a unit test.",
        repo="acme/widgets", labels=["bug"], days_old=2,
    )
    res = engine.evaluate(issue, repo_meta={"full_name": "acme/widgets", "size": 1200})
    assert RejectReason.NOT_A_CODING_TASK not in res.reject_reasons
