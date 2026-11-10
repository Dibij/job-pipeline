"""Deterministic compensation & reward extraction for freelance/bounty text.

Key rule: unknown compensation stays unknown. We never fabricate a budget from
a mention that is not actually about money.

Distinctions the rest of the system relies on:
  - salary  != project budget  (salary_min/max on jobs, budget_min/max on gigs)
  - hourly  != fixed_price
  - bounty  != normal freelance contract
  - unpaid contribution != paid work
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Currency symbols -> ISO code
_CURRENCY_SYMBOLS = {"$": "USD", "\u20ac": "EUR", "\u00a3": "GBP", "\u20b9": "INR"}
_CURRENCY_CODES = {"USD", "EUR", "GBP", "INR"}

# "US$500", "$500", "$1,200", "€350", "₹5,000" and "$80k" (k is handled below).
_MONEY_RE = re.compile(
    r"(?:"
    r"(?P<sym>[\$\u20ac\u00a3\u20b9])\s*(?P<amt>\d[\d,]*(?:\.\d{1,2})?)"
    r"|"
    r"(?P<amt2>\d[\d,]*(?:\.\d{1,2})?)\s*(?:[kK])?\s*(?P<code>USD|EUR|GBP|INR)"
    r")",
    re.IGNORECASE,
)

_REWARD_SIGNAL_RE = re.compile(
    r"\b(bounty|bounties|reward|rewards|bounty\s+program)\b", re.IGNORECASE
)
_PAID_SIGNAL_RE = re.compile(
    r"\b(paid|payment|compensation|sponsor(?:ed|ship)?|fund(?:ed|ing)?|stipend|honorarium)\b",
    re.IGNORECASE,
)
_UNPAID_SIGNAL_RE = re.compile(
    r"\b(unpaid|not\s+paid|no\s+(?:payment|compensation|pay|budget|monetary\s+reward)"
    r"|for\s+free|volunteer|pro\s*bono)\b",
    re.IGNORECASE,
)

# "no bounty" / "without reward" negates a reward claim WITHOUT implying unpaid labor.
_NO_REWARD_RE = re.compile(
    r"\b(?:no|without)\s+(?:bounty|bounties|reward|rewards|monetary\s+reward)\b",
    re.IGNORECASE,
)


@dataclass
class Compensation:
    compensation_type: str = "unknown"          # salary|hourly|fixed_price|bounty|equity|unpaid|unknown
    payment_verification_status: str = "unknown"  # verified|unverified|none|unknown
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    budget_currency: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "compensation_type": self.compensation_type,
            "payment_verification_status": self.payment_verification_status,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "budget_currency": self.budget_currency,
        }


def _parse_num(s: str) -> Optional[float]:
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract_money(text: str) -> List[Tuple[float, str]]:
    """Return a list of (amount, ISO currency) found in text."""
    out: List[Tuple[float, str]] = []
    for m in _MONEY_RE.finditer(text or ""):
        if m.group("sym"):
            amt = _parse_num(m.group("amt"))
            cur = _CURRENCY_SYMBOLS.get(m.group("sym"), "USD")
        else:
            amt = _parse_num(m.group("amt2"))
            code = (m.group("code") or "USD").upper()
            cur = code if code in _CURRENCY_CODES else "USD"
        if amt is not None:
            out.append((amt, cur))
    return out


def detect_compensation(
    text: str,
    *,
    kind: str = "freelance",
    platform_verified: bool = False,
) -> Compensation:
    """Classify compensation intent from free text.

    Args:
        text: body/description text to inspect.
        kind: 'freelance' | 'bounty' — biases the default compensation_type.
        platform_verified: True when the source escrows/confirms the reward
            (e.g. Algora/Polar), making a listed amount 'verified'.
    """
    t = text or ""
    amounts = extract_money(t)
    has_money = bool(amounts)
    negated = bool(_UNPAID_SIGNAL_RE.search(t))
    reward = bool(_REWARD_SIGNAL_RE.search(t)) and not bool(_NO_REWARD_RE.search(t))
    paid = bool(_PAID_SIGNAL_RE.search(t))

    c = Compensation()
    if amounts:
        vals = [a for a, _ in amounts]
        c.budget_min = min(vals)
        c.budget_max = max(vals)
        c.budget_currency = amounts[0][1]

    positive_reward = reward and not negated

    if has_money or positive_reward:
        # A concrete amount or an explicit, non-negated bounty/reward signal.
        c.compensation_type = "bounty" if (kind == "bounty" or positive_reward) else "fixed_price"
        c.payment_verification_status = "verified" if platform_verified else "unverified"
    elif negated:
        # Explicitly unpaid / no-bounty / no-compensation.
        c.compensation_type = "unpaid"
        c.payment_verification_status = "none"
    elif paid:
        # Payment/funding mentioned without a concrete amount or bounty label.
        c.compensation_type = "bounty" if kind == "bounty" else "fixed_price"
        c.payment_verification_status = "unverified"
    else:
        c.compensation_type = "unknown"
        c.payment_verification_status = "unknown"

    return c
