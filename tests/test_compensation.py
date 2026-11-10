"""Unit tests for compensation/reward extraction (deterministic, no network)."""
from src.opportunities.compensation import detect_compensation, extract_money


def test_extract_money_dollar_symbol():
    assert extract_money("We pay $500 for this fix") == [(500.0, "USD")]


def test_extract_money_comma_and_currency():
    assert extract_money("$1,200 budget") == [(1200.0, "USD")]
    assert extract_money("500 USD") == [(500.0, "USD")]
    assert extract_money("\u20ac350") == [(350.0, "EUR")]


def test_extract_money_range():
    assert extract_money("Budget $200 - $500 USD") == [(200.0, "USD"), (500.0, "USD")]


def test_detect_bounty_is_unverified_on_github():
    c = detect_compensation("$500 bounty for fixing this bug", kind="bounty")
    assert c.compensation_type == "bounty"
    assert c.payment_verification_status == "unverified"
    assert c.budget_min == 500.0


def test_detect_platform_verified():
    c = detect_compensation("$300 bounty", kind="bounty", platform_verified=True)
    assert c.payment_verification_status == "verified"


def test_detect_explicit_unpaid():
    c = detect_compensation("This is unpaid volunteer work, no compensation", kind="bounty")
    assert c.compensation_type == "unpaid"
    assert c.payment_verification_status == "none"


def test_no_bounty_not_treated_as_reward():
    # "no bounty" must not be read as a positive reward signal.
    c = detect_compensation("We have no bounty for this issue", kind="bounty")
    assert c.compensation_type == "unknown"
    assert c.payment_verification_status == "unknown"


def test_detect_unknown_when_silent():
    c = detect_compensation("Looking for help with a Django app", kind="freelance")
    assert c.compensation_type == "unknown"
    assert c.payment_verification_status == "unknown"


def test_fixed_price_for_plain_freelance_amount():
    c = detect_compensation("Fixed project at $800", kind="freelance")
    assert c.compensation_type == "fixed_price"
    assert c.payment_verification_status == "unverified"
