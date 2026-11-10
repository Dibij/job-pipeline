"""Tests for the GitHub bounty verdict engine.

Covers the 6 rejection fixtures plus synthetic positive cases and edge cases.
All tests are deterministic and require no network access.
"""
from src.opportunities.bounty_verdict import (
    BountyVerdictEngine,
    RejectReason,
    Verdict,
    BountyVerdictResult,
    FundingEvidence,
)


def _engine() -> BountyVerdictEngine:
    return BountyVerdictEngine()


def _issue(title="", body="", state="open", labels=None, user=None,
           updated_at="2026-11-09T10:00:00Z", html_url="https://github.com/o/r/issues/1",
           repository_url="https://api.github.com/repos/o/r", _gh_repo="o/r", **kw):
    d = {
        "title": title,
        "body": body,
        "state": state,
        "labels": labels or [],
        "user": user or {"login": "contributor"},
        "updated_at": updated_at,
        "html_url": html_url,
        "repository_url": repository_url,
        "_gh_repo": _gh_repo,
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# Fixture rejections (from real GitHub issues)
# ---------------------------------------------------------------------------

def test_fixture_civitai_word_only_match():
    """civitai/civitai#7813: title/body contains 'bounty' but no funding evidence."""
    issue = _issue(
        title="Add a bounty for this feature",
        body="Someone should add a bounty for implementing this feature. No monetary compensation is currently offered. Please volunteer.",
        labels=[{"name": "enhancement"}],
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.REJECT
    assert RejectReason.WORD_ONLY_MATCH in result.reject_reasons


def test_fixture_alfrexo_bounty_bot_crypto_and_bot():
    """alfrexo95/bounty-bot#75: crypto wallet in body + bot/farm repo."""
    issue = _issue(
        title="Bounty: fix login flow",
        body="Send payment to 0xAbcDEF1234567890abcdef1234567890abcdef12 once the login flow is fixed and tests pass.",
        labels=[{"name": "bounty"}],
        user={"login": "github-actions[bot]"},
        _gh_repo="alfrexo95/bounty-bot",
    )
    result = _engine().evaluate(issue, repo_meta={"stargazers_count": 1})
    assert result.verdict == Verdict.REJECT
    assert RejectReason.CRYPTO_WALLET_IN_BODY in result.reject_reasons
    assert RejectReason.BOT_OR_FARM_REPO in result.reject_reasons


def test_fixture_freedom_winds_bountyscout_aggregator_digest():
    """freedom-winds/BountyScout#1382: aggregator/digest scan issue."""
    issue = _issue(
        title="Bounty digest: new opportunities this week",
        body="See github.com/a/b, github.com/c/d, github.com/e/f, github.com/g/h for open bounties. Please review each.",
        labels=[{"name": "bounty"}],
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.REJECT
    assert RejectReason.AGGREGATOR_DIGEST in result.reject_reasons


def test_fixture_whole_trout_media_clone_farm():
    """WholeTroutMedia/zhangjiayang repos: clone farm via similar_titles_count."""
    issue = _issue(
        title="Implement dark mode toggle",
        body="Please implement a dark mode toggle for the app and ensure it persists across sessions.",
        labels=[{"name": "bounty"}],
    )
    result = _engine().evaluate(issue, similar_titles_count=3)
    assert result.verdict == Verdict.REJECT
    assert RejectReason.CLONE_FARM in result.reject_reasons


def test_fixture_devloot_loot_town_unfunded_notice():
    """devloot-xyz/LootTown#19: explicit unfunded notice."""
    issue = _issue(
        title="Bug bounty program",
        body="This issue does not fund a bounty. It is just a tracking issue for the reported bug. No reward is offered.",
        labels=[{"name": "bounty"}],
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.REJECT
    assert RejectReason.UNFUNDED_NOTICE in result.reject_reasons


def test_fixture_soroban_escrow_taken():
    """Soroban-escrow/escrow-app#20: bounty already taken/closed."""
    issue = _issue(
        title="$500 bounty for escrow contract",
        body="Implement the escrow contract for $500. This has been claimed already.",
        labels=[{"name": "bounty"}],
        state="closed",
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.REJECT
    assert RejectReason.TAKEN in result.reject_reasons


# ---------------------------------------------------------------------------
# Synthetic positive cases (real, unclaimed bounties)
# ---------------------------------------------------------------------------

def test_positive_platform_label_and_body_amount():
    """Real bounty: platform label + valid amount in body -> accept."""
    issue = _issue(
        title="$500 bounty: fix navigation crash",
        body="Pay $500 on Algora once this is resolved. Fix the nav crash on mobile and add regression tests.",
        labels=[{"name": "bounty"}, {"name": "algora.io"}],
        user={"login": "maintainer"},
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.ACCEPT
    assert result.funding_evidence is not None
    assert result.funding_evidence.amount == 500.0


def test_positive_platform_link_and_body_amount():
    """Real bounty: platform link (polar.sh) + valid amount in body -> accept."""
    issue = _issue(
        title="Add dark mode - $750 bounty",
        body="Claim $750 at https://polar.sh/org/repo/issues/42. Implement dark mode and add tests.",
        labels=[{"name": "enhancement"}],
        user={"login": "maintainer"},
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.ACCEPT
    assert result.funding_evidence is not None
    assert result.funding_evidence.amount == 750.0


def test_positive_euro_amount_platform_label():
    """Real bounty with EUR amount and platform label -> accept."""
    issue = _issue(
        title="€1,200 bounty for API integration",
        body="Reward €1,200 for completing the API integration. See https://bountysource.com/issues/123. Implement the endpoint.",
        labels=[{"name": "bounties"}, {"name": "paid"}],
        user={"login": "maintainer"},
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.ACCEPT
    assert result.funding_evidence is not None
    assert result.funding_evidence.amount == 1200.0
    assert result.funding_evidence.currency == "EUR"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_edge_title_only_amount_not_enough():
    """Amount only in title, no platform signal + body amount -> reject (no funding evidence)."""
    issue = _issue(
        title="$300 bounty for typo fix",
        body="Just fix the typo in the README file. No platform link or label and no body amount is mentioned anywhere in this issue text.",
        labels=[{"name": "good first issue"}],
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.REJECT
    assert RejectReason.WORD_ONLY_MATCH in result.reject_reasons
    assert result.funding_evidence is None


def test_edge_stale_issue_rejected():
    """Issue updated more than max_age_days ago -> STALE reject."""
    issue = _issue(
        title="$500 bounty fix",
        body="Pay $500 via https://polar.sh/org/r/issues/1. Fix the bug and add tests please.",
        labels=[{"name": "bounty"}],
        updated_at="2020-01-01T00:00:00Z",
    )
    result = _engine().evaluate(issue)
    assert RejectReason.STALE in result.reject_reasons


def test_edge_no_task_rejected():
    """Body with no actionable task verb -> NO_TASK reject."""
    issue = _issue(
        title="Bounty discussion",
        body="This is just a general discussion about bounties. No specific task to perform here at all.",
        labels=[{"name": "bounty"}],
    )
    result = _engine().evaluate(issue)
    assert RejectReason.NO_TASK in result.reject_reasons


def test_edge_amount_below_min_threshold():
    """Amount below min_amount_usd does not count as valid funding evidence."""
    issue = _issue(
        title="$20 bounty for tiny fix",
        body="Pay $20 via https://algora.io/org/r/issues/1 once the tiny typo is fixed in the README.",
        labels=[{"name": "bounty"}],
    )
    result = _engine().evaluate(issue)
    # $20 is below min_amount_usd (50) so no valid funding evidence -> reject
    assert result.verdict == Verdict.REJECT
    assert RejectReason.WORD_ONLY_MATCH in result.reject_reasons


def test_edge_verdict_to_db_fields():
    """verdict_to_db_fields maps result to DB column values."""
    result = BountyVerdictResult(
        verdict=Verdict.REJECT,
        confidence=40,
        reject_reasons=[RejectReason.WORD_ONLY_MATCH],
        reject_evidence="word only",
        funding_evidence=None,
    )
    fields = BountyVerdictEngine.verdict_to_db_fields(result)
    assert fields["bounty_verdict"] == Verdict.REJECT
    assert fields["reject_reasons"] == [RejectReason.WORD_ONLY_MATCH]
    assert fields["funding_evidence"] is None
    assert fields["bounty_confidence"] == 40
    assert fields["reject_evidence"] == "word only"


def test_edge_verdict_to_db_fields_with_funding():
    """verdict_to_db_fields includes funding_evidence dict when present."""
    result = BountyVerdictResult(
        verdict=Verdict.ACCEPT,
        confidence=80,
        reject_reasons=[],
        reject_evidence="",
        funding_evidence=FundingEvidence(
            platform="algora.io", amount=500.0, currency="USD",
            source_url="https://algora.io/x", source_type="platform_label",
        ),
    )
    fields = BountyVerdictEngine.verdict_to_db_fields(result)
    assert fields["funding_evidence"] == {
        "platform": "algora.io",
        "amount": 500.0,
        "currency": "USD",
        "source_url": "https://algora.io/x",
        "source_type": "platform_label",
    }


def test_edge_no_funding_evidence_reason():
    """Issue mentions bounty word but no platform + no amount -> NO_FUNDING_EVIDENCE."""
    issue = _issue(
        title="Looking for contributors",
        body="We welcome help with this issue. Please contribute documentation and triage incoming reports as needed by the team.",
        labels=[{"name": "help wanted"}],
    )
    result = _engine().evaluate(issue)
    assert RejectReason.NO_FUNDING_EVIDENCE in result.reject_reasons


def test_edge_low_trust_new_author_reduces_confidence():
    """New author (<30 days) reduces confidence but does not alone reject."""
    issue = _issue(
        title="$500 bounty fix login",
        body="Pay $500 via https://algora.io/org/r/issues/1 once login is fixed and tests pass.",
        labels=[{"name": "bounty"}],
        user={"login": "newbie"},
    )
    result = _engine().evaluate(issue, author_age_days=5)
    assert result.confidence < 80  # new-author penalty applied


def test_edge_crypto_wallet_rejects_even_with_funding():
    """Crypto wallet in body overrides accept -> CRYPTO_WALLET_IN_BODY reject."""
    issue = _issue(
        title="$500 bounty fix",
        body="Pay $500 via https://polar.sh/org/r/issues/1 once login is fixed. Wallet: 0xAbcDEF1234567890abcdef1234567890abcdef12",
        labels=[{"name": "bounty"}],
    )
    result = _engine().evaluate(issue)
    assert result.verdict == Verdict.REJECT
    assert RejectReason.CRYPTO_WALLET_IN_BODY in result.reject_reasons


def test_edge_platform_feature_rejected():
    """Issue about the bounty platform itself -> PLATFORM_FEATURE reject."""
    issue = _issue(
        title="Build a bounty website for the community",
        body="We need to build a bounty platform where users can post rewards and track them.",
        labels=[{"name": "enhancement"}],
    )
    result = _engine().evaluate(issue)
    assert RejectReason.PLATFORM_FEATURE in result.reject_reasons
