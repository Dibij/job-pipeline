"""Configuration for the GitHub bounty verdict engine and lane scoring."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

BOUNTY_PLATFORMS: List[str] = ["algora.io", "issuehunt.io", "polar.sh", "bountysource.com", "gitcoin.co"]
BOUNTY_PLATFORM_BOTS: List[str] = ["algora", "issuehunt", "polar-bot", "bountysource", "gitcoin"]
BOUNTY_LABELS: List[str] = ["bounty", "bounties", "reward", "paid", "funded"]
MIN_BOUNTY_AMOUNT_USD = 50.0
MAX_BOUNTY_AMOUNT_USD = 1000000.0
MAX_AGE_DAYS = 14
MIN_BODY_LENGTH = 80
MIN_TASK_SENTENCES = 1
FARM_REPO_PATTERNS: List[str] = ["bounty-bot", "bountybot", "bounty-plaza", "bountyplaza", "bountyscout", "bounty-scout", "scout", "aggregator"]
BOT_AUTHOR_PATTERNS: List[str] = ["github-actions[bot]", "dependabot[bot]", "renovate[bot]", "actions-user"]
DIGEST_TITLE_PATTERNS: List[str] = ["bounty alert", "new opportunities", "scan results", "bounty digest", "opportunity scan", "intake", "release-watch", "bounty-alert"]
CLONE_FARM_MIN_REPOS = 3
CLONE_FARM_DAYS_WINDOW = 30
CLONE_FARM_AUTHOR_MAX_ISSUES = 3
LOW_STAR_THRESHOLD = 5
BLOCKLIST_TTL_HOURS = 24
REPO_HEALTH_CACHE_TTL_DAYS = 7
REPO_PUSHED_WITHIN_DAYS = 30
LABEL_STUFFING_THRESHOLD = 6
REPO_SIZE_WARN_KB = 50000
MIN_REPO_SIZE_KB = 50
MAX_WATCHLIST_REPOS = 8
MAX_REPO_META_FETCHES = 25
API_QUOTA_RESERVE = 400
CONFIDENCE_ACCEPT = 70
CONFIDENCE_REJECT = 40
PLATFORM_FEATURE_KEYWORDS: List[str] = ["bounty platform", "bounty website", "bounty app", "escrow app", "reward platform"]
UNFUNDED_PHRASES: List[str] = ["does not fund a bounty", "no reward", "not funded", "unpaid", "publishing this issue does not fund", "this issue does not fund"]
CRYPTO_ADDRESS_RE = re.compile(r"\b([13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-z0-9]{39,59}|0x[a-fA-F0-9]{40}|L[a-km-zA-HJ-NP-Z1-9]{26,33}|tb1[a-z0-9]{39,59})\b")

# Crypto payments/rewards are illegal in Nepal. Any bounty paid in crypto is a
# hard reject, even when the funding evidence is otherwise real. Word-bounded so
# "method" does not match "eth" and "solution" does not match "sol".
CRYPTO_PAYMENT_TOKENS: List[str] = [
    "btc", "bitcoin", "eth", "ethereum", "ltc", "litecoin", "sol", "solana",
    "xlm", "stellar", "usdc", "usdt", "dai", "usd coin", "stablecoin",
    "lightning network", "lightning", "sats", "satoshi", "satoshis", "on-chain",
    "onchain", "web3", "defi", "crypto", "cryptocurrency", "memecoin",
]
CRYPTO_PAYMENT_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in CRYPTO_PAYMENT_TOKENS) + r")\b",
    re.IGNORECASE,
)

GITHUB_CONFIG_PATH = os.getenv("GITHUB_ISSUES_CONFIG", str(Path(__file__).resolve().parents[2] / "config" / "github_issues.yml"))


@dataclass
class SearchQuery:
    source: str
    q: str
    label_filter: List[str] = field(default_factory=list)
    language: List[str] = field(default_factory=list)
    updated_within_days: int = 7
    max_comments: int = 20
    per_page: int = 50


@dataclass
class FundingConfig:
    platforms: List[str] = field(default_factory=list)
    platform_labels: List[str] = field(default_factory=list)
    platform_bots: List[str] = field(default_factory=list)
    min_amount_usd: float = MIN_BOUNTY_AMOUNT_USD
    max_amount_usd: float = MAX_BOUNTY_AMOUNT_USD


@dataclass
class ThresholdConfig:
    max_age_days: int = MAX_AGE_DAYS
    min_body_length: int = MIN_BODY_LENGTH
    min_task_sentences: int = MIN_TASK_SENTENCES
    clone_farm_min_repos: int = CLONE_FARM_MIN_REPOS
    clone_farm_days_window: int = CLONE_FARM_DAYS_WINDOW
    clone_farm_author_max_issues: int = CLONE_FARM_AUTHOR_MAX_ISSUES
    low_star_threshold: int = LOW_STAR_THRESHOLD
    blocklist_ttl_hours: int = BLOCKLIST_TTL_HOURS
    repo_health_cache_ttl_days: int = REPO_HEALTH_CACHE_TTL_DAYS
    repo_pushed_within_days: int = REPO_PUSHED_WITHIN_DAYS
    label_stuffing_threshold: int = LABEL_STUFFING_THRESHOLD
    repo_size_warn_kb: int = REPO_SIZE_WARN_KB
    min_repo_size_kb: int = MIN_REPO_SIZE_KB
    max_watchlist_repos: int = MAX_WATCHLIST_REPOS
    max_repo_meta_fetches: int = MAX_REPO_META_FETCHES
    api_quota_reserve: int = API_QUOTA_RESERVE
    confidence_accept: int = CONFIDENCE_ACCEPT
    confidence_reject: int = CONFIDENCE_REJECT


@dataclass
class StackConfig:
    strong: List[str] = field(default_factory=list)
    weak: List[str] = field(default_factory=list)


@dataclass
class GithubConfig:
    platforms: List[str]
    platform_bots: List[str]
    bounty_labels: List[str]
    farm_repo_patterns: List[str]
    bot_author_patterns: List[str]
    digest_title_patterns: List[str]
    unfunded_phrases: List[str]
    platform_feature_keywords: List[str]
    min_amount_usd: float
    max_amount_usd: float
    max_age_days: int
    min_body_length: int
    min_task_sentences: int
    clone_farm_min_repos: int
    clone_farm_days_window: int
    clone_farm_author_max_issues: int
    low_star_threshold: int
    blocklist_ttl_hours: int
    confidence_accept: int
    confidence_reject: int
    crypto_address_re: object
    funding: FundingConfig = field(default_factory=FundingConfig)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    stack: StackConfig = field(default_factory=StackConfig)
    avoid_domains: List[str] = field(default_factory=list)
    search_queries: List[SearchQuery] = field(default_factory=list)
    watchlist_seeds: List[str] = field(default_factory=list)
    crypto_payment_tokens: List[str] = field(default_factory=lambda: list(CRYPTO_PAYMENT_TOKENS))
    crypto_payment_re: object = field(default_factory=lambda: CRYPTO_PAYMENT_RE)

    def __getattr__(self, name: str):
        if "thresholds" in self.__dict__ and hasattr(self.thresholds, name):
            return getattr(self.thresholds, name)
        if "funding" in self.__dict__ and hasattr(self.funding, name):
            return getattr(self.funding, name)
        raise AttributeError(f"'LaneConfig' object has no attribute '{name}'")


@dataclass
class BountyConfig:
    platforms: List[str] = field(default_factory=lambda: list(BOUNTY_PLATFORMS))
    platform_bots: List[str] = field(default_factory=lambda: list(BOUNTY_PLATFORM_BOTS))
    bounty_labels: List[str] = field(default_factory=lambda: list(BOUNTY_LABELS))
    farm_repo_patterns: List[str] = field(default_factory=lambda: list(FARM_REPO_PATTERNS))
    bot_author_patterns: List[str] = field(default_factory=lambda: list(BOT_AUTHOR_PATTERNS))
    digest_title_patterns: List[str] = field(default_factory=lambda: list(DIGEST_TITLE_PATTERNS))
    unfunded_phrases: List[str] = field(default_factory=lambda: list(UNFUNDED_PHRASES))
    platform_feature_keywords: List[str] = field(default_factory=lambda: list(PLATFORM_FEATURE_KEYWORDS))
    min_amount_usd: float = MIN_BOUNTY_AMOUNT_USD
    max_amount_usd: float = MAX_BOUNTY_AMOUNT_USD
    max_age_days: int = MAX_AGE_DAYS
    min_body_length: int = MIN_BODY_LENGTH
    min_task_sentences: int = MIN_TASK_SENTENCES
    clone_farm_min_repos: int = CLONE_FARM_MIN_REPOS
    clone_farm_days_window: int = CLONE_FARM_DAYS_WINDOW
    clone_farm_author_max_issues: int = CLONE_FARM_AUTHOR_MAX_ISSUES
    low_star_threshold: int = LOW_STAR_THRESHOLD
    label_stuffing_threshold: int = LABEL_STUFFING_THRESHOLD
    repo_size_warn_kb: int = REPO_SIZE_WARN_KB
    blocklist_ttl_hours: int = BLOCKLIST_TTL_HOURS
    confidence_accept: int = CONFIDENCE_ACCEPT
    confidence_reject: int = CONFIDENCE_REJECT
    crypto_address_re: object = field(default_factory=lambda: CRYPTO_ADDRESS_RE)
    crypto_payment_tokens: List[str] = field(default_factory=lambda: list(CRYPTO_PAYMENT_TOKENS))
    crypto_payment_re: object = field(default_factory=lambda: CRYPTO_PAYMENT_RE)
    funding: FundingConfig = field(default_factory=FundingConfig)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    stack: StackConfig = field(default_factory=StackConfig)
    avoid_domains: List[str] = field(default_factory=list)
    search_queries: List[SearchQuery] = field(default_factory=list)
    watchlist_seeds: List[str] = field(default_factory=list)

    def __getattr__(self, name: str):
        if "thresholds" in self.__dict__ and hasattr(self.thresholds, name):
            return getattr(self.thresholds, name)
        if "funding" in self.__dict__ and hasattr(self.funding, name):
            return getattr(self.funding, name)
        raise AttributeError(f"'BountyConfig' object has no attribute '{name}'")



def load_config() -> BountyConfig:
    """Backward-compatible config loader (env-based, no YAML)."""
    def _csv(env: str, default: List[str]) -> List[str]:
        raw = os.getenv(env, "").strip()
        if not raw:
            return default
        return [s.strip() for s in raw.split(",") if s.strip()]

    return BountyConfig(
        platforms=_csv("BOUNTY_PLATFORMS", list(BOUNTY_PLATFORMS)),
        platform_bots=_csv("BOUNTY_PLATFORM_BOTS", list(BOUNTY_PLATFORM_BOTS)),
        bounty_labels=_csv("BOUNTY_LABELS", list(BOUNTY_LABELS)),
        farm_repo_patterns=_csv("BOUNTY_FARM_REPO_PATTERNS", list(FARM_REPO_PATTERNS)),
        bot_author_patterns=_csv("BOUNTY_BOT_AUTHOR_PATTERNS", list(BOT_AUTHOR_PATTERNS)),
        digest_title_patterns=_csv("BOUNTY_DIGEST_TITLE_PATTERNS", list(DIGEST_TITLE_PATTERNS)),
        unfunded_phrases=_csv("BOUNTY_UNFUNDED_PHRASES", list(UNFUNDED_PHRASES)),
        platform_feature_keywords=_csv("BOUNTY_PLATFORM_FEATURE_KEYWORDS", list(PLATFORM_FEATURE_KEYWORDS)),
        min_amount_usd=float(os.getenv("BOUNTY_MIN_AMOUNT_USD", str(MIN_BOUNTY_AMOUNT_USD))),
        max_amount_usd=float(os.getenv("BOUNTY_MAX_AMOUNT_USD", str(MAX_BOUNTY_AMOUNT_USD))),
        max_age_days=int(os.getenv("BOUNTY_MAX_AGE_DAYS", str(MAX_AGE_DAYS))),
        min_body_length=int(os.getenv("BOUNTY_MIN_BODY_LENGTH", str(MIN_BODY_LENGTH))),
        min_task_sentences=int(os.getenv("BOUNTY_MIN_TASK_SENTENCES", str(MIN_TASK_SENTENCES))),
        clone_farm_min_repos=int(os.getenv("BOUNTY_CLONE_FARM_MIN_REPOS", str(CLONE_FARM_MIN_REPOS))),
        clone_farm_days_window=int(os.getenv("BOUNTY_CLONE_FARM_DAYS_WINDOW", str(CLONE_FARM_DAYS_WINDOW))),
        low_star_threshold=int(os.getenv("BOUNTY_LOW_STAR_THRESHOLD", str(LOW_STAR_THRESHOLD))),
        blocklist_ttl_hours=int(os.getenv("BOUNTY_BLOCKLIST_TTL_HOURS", str(BLOCKLIST_TTL_HOURS))),
        confidence_accept=int(os.getenv("BOUNTY_CONFIDENCE_ACCEPT", str(CONFIDENCE_ACCEPT))),
        confidence_reject=int(os.getenv("BOUNTY_CONFIDENCE_REJECT", str(CONFIDENCE_REJECT))),
        crypto_address_re=re.compile(os.getenv("BOUNTY_CRYPTO_ADDRESS_RE", CRYPTO_ADDRESS_RE.pattern)),
    )


def load_github_config(path: str = GITHUB_CONFIG_PATH) -> GithubConfig:
    """Load the GitHub lane config from config/github_issues.yml (YAML)."""
    data: Dict[str, Any] = {}
    p = Path(path)
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except Exception:
            data = {}

    funding = data.get("funding", {}) or {}
    crypto = data.get("crypto", {}) or {}
    thresholds = data.get("thresholds", {}) or {}
    stack = data.get("stack", {}) or {}
    search = data.get("search", {}) or {}
    watchlist = data.get("watchlist", {}) or {}

    search_queries: List[SearchQuery] = []
    for q in search.get("queries", []) or []:
        search_queries.append(SearchQuery(
            source=q.get("source", "search"),
            q=q.get("q", ""),
            label_filter=q.get("label_filter", []) or [],
            language=q.get("language", []) or [],
            updated_within_days=int(q.get("updated_within_days", 7)),
            max_comments=int(q.get("max_comments", 20)),
            per_page=int(q.get("per_page", 50)),
        ))

    return GithubConfig(
        platforms=funding.get("platforms", list(BOUNTY_PLATFORMS)),
        platform_bots=funding.get("platform_bots", list(BOUNTY_PLATFORM_BOTS)),
        bounty_labels=funding.get("platform_labels", list(BOUNTY_LABELS)),
        farm_repo_patterns=data.get("farm_repo_patterns", list(FARM_REPO_PATTERNS)),
        bot_author_patterns=data.get("bot_author_patterns", list(BOT_AUTHOR_PATTERNS)),
        digest_title_patterns=data.get("digest_title_patterns", list(DIGEST_TITLE_PATTERNS)),
        unfunded_phrases=data.get("unfunded_phrases", list(UNFUNDED_PHRASES)),
        platform_feature_keywords=data.get("platform_feature_keywords", list(PLATFORM_FEATURE_KEYWORDS)),
        min_amount_usd=float(funding.get("min_amount_usd", MIN_BOUNTY_AMOUNT_USD)),
        max_amount_usd=float(funding.get("max_amount_usd", MAX_BOUNTY_AMOUNT_USD)),
        max_age_days=int(thresholds.get("max_age_days", MAX_AGE_DAYS)),
        min_body_length=int(thresholds.get("min_body_length", MIN_BODY_LENGTH)),
        min_task_sentences=int(thresholds.get("min_task_sentences", MIN_TASK_SENTENCES)),
        clone_farm_min_repos=int(thresholds.get("clone_farm_min_repos", CLONE_FARM_MIN_REPOS)),
        clone_farm_days_window=int(thresholds.get("clone_farm_days_window", CLONE_FARM_DAYS_WINDOW)),
        clone_farm_author_max_issues=int(thresholds.get("clone_farm_author_max_issues", CLONE_FARM_AUTHOR_MAX_ISSUES)),
        low_star_threshold=int(thresholds.get("low_star_threshold", LOW_STAR_THRESHOLD)),
        blocklist_ttl_hours=int(thresholds.get("blocklist_ttl_hours", BLOCKLIST_TTL_HOURS)),
        confidence_accept=int(thresholds.get("confidence_accept", CONFIDENCE_ACCEPT)),
        confidence_reject=int(thresholds.get("confidence_reject", CONFIDENCE_REJECT)),
        crypto_address_re=re.compile(data.get("crypto_address_re", CRYPTO_ADDRESS_RE.pattern)),
        funding=FundingConfig(
            platforms=funding.get("platforms", list(BOUNTY_PLATFORMS)),
            platform_labels=funding.get("platform_labels", list(BOUNTY_LABELS)),
            platform_bots=funding.get("platform_bots", list(BOUNTY_PLATFORM_BOTS)),
            min_amount_usd=float(funding.get("min_amount_usd", MIN_BOUNTY_AMOUNT_USD)),
            max_amount_usd=float(funding.get("max_amount_usd", MAX_BOUNTY_AMOUNT_USD)),
        ),
        thresholds=ThresholdConfig(
            max_age_days=int(thresholds.get("max_age_days", MAX_AGE_DAYS)),
            min_body_length=int(thresholds.get("min_body_length", MIN_BODY_LENGTH)),
            min_task_sentences=int(thresholds.get("min_task_sentences", MIN_TASK_SENTENCES)),
            clone_farm_min_repos=int(thresholds.get("clone_farm_min_repos", CLONE_FARM_MIN_REPOS)),
            clone_farm_days_window=int(thresholds.get("clone_farm_days_window", CLONE_FARM_DAYS_WINDOW)),
            clone_farm_author_max_issues=int(thresholds.get("clone_farm_author_max_issues", CLONE_FARM_AUTHOR_MAX_ISSUES)),
            low_star_threshold=int(thresholds.get("low_star_threshold", LOW_STAR_THRESHOLD)),
            blocklist_ttl_hours=int(thresholds.get("blocklist_ttl_hours", BLOCKLIST_TTL_HOURS)),
            repo_health_cache_ttl_days=int(thresholds.get("repo_health_cache_ttl_days", REPO_HEALTH_CACHE_TTL_DAYS)),
            repo_pushed_within_days=int(thresholds.get("repo_pushed_within_days", REPO_PUSHED_WITHIN_DAYS)),
            label_stuffing_threshold=int(thresholds.get("label_stuffing_threshold", LABEL_STUFFING_THRESHOLD)),
            repo_size_warn_kb=int(thresholds.get("repo_size_warn_kb", REPO_SIZE_WARN_KB)),
            min_repo_size_kb=int(thresholds.get("min_repo_size_kb", MIN_REPO_SIZE_KB)),
            max_watchlist_repos=int(thresholds.get("max_watchlist_repos", MAX_WATCHLIST_REPOS)),
            max_repo_meta_fetches=int(thresholds.get("max_repo_meta_fetches", MAX_REPO_META_FETCHES)),
            api_quota_reserve=int(thresholds.get("api_quota_reserve", API_QUOTA_RESERVE)),
            confidence_accept=int(thresholds.get("confidence_accept", CONFIDENCE_ACCEPT)),
            confidence_reject=int(thresholds.get("confidence_reject", CONFIDENCE_REJECT)),
        ),
        stack=StackConfig(
            strong=stack.get("strong", []),
            weak=stack.get("weak", []),
        ),
        avoid_domains=data.get("avoid_domains", []),
        search_queries=search_queries,
        watchlist_seeds=watchlist.get("seeds", []),
        crypto_payment_tokens=crypto.get("payment_tokens", list(CRYPTO_PAYMENT_TOKENS)) or list(CRYPTO_PAYMENT_TOKENS),
        crypto_payment_re=CRYPTO_PAYMENT_RE,
    )


# Backward-compatible alias
LaneConfig = GithubConfig
