"""Quality verdict engine for GitHub issues.

One pool, one gate: surface only real, workable issues, ranked by quality.
Funding evidence is a strong positive signal but is not required; an unfunded
issue still passes if it is a well-scoped task in a healthy repo.

Nothing is auto-accepted, auto-messaged or auto-contacted. Humans decide via
triage; uncertain items are routed there and never dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.opportunities.bounty_config import LaneConfig, load_github_config
from src.opportunities.compensation import extract_money


class RejectReason:
    WORD_ONLY_MATCH = "WORD_ONLY_MATCH"
    AGGREGATOR_DIGEST = "AGGREGATOR_DIGEST"
    TAKEN = "TAKEN"
    CRYPTO_WALLET_IN_BODY = "CRYPTO_WALLET_IN_BODY"
    CRYPTO_PAYMENT = "CRYPTO_PAYMENT"
    BOT_OR_FARM_REPO = "BOT_OR_FARM_REPO"
    CLONE_FARM = "CLONE_FARM"
    REPEATED_TITLE = "REPEATED_TITLE"
    NO_TASK = "NO_TASK"
    UNFUNDED_NOTICE = "UNFUNDED_NOTICE"
    PLATFORM_FEATURE = "PLATFORM_FEATURE"
    TRIVIAL_TASK = "TRIVIAL_TASK"
    TEMPLATED_ISSUE = "TEMPLATED_ISSUE"
    LABEL_STUFFING = "LABEL_STUFFING"
    STALE = "STALE"
    CLOSED_OR_ARCHIVED_REPO = "CLOSED_OR_ARCHIVED_REPO"
    LOW_TRUST_POSTER = "LOW_TRUST_POSTER"
    NOT_A_CODING_TASK = "NOT_A_CODING_TASK"


class Verdict:
    ACCEPT = "accept"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


# Flag-but-do-not-force-rejection reasons.
SOFT_REASONS = {
    RejectReason.PLATFORM_FEATURE,
    RejectReason.LOW_TRUST_POSTER,
}


@dataclass
class FundingEvidence:
    platform: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None  # 'link' | 'label' | 'bot'


@dataclass
class BountyVerdictResult:
    verdict: str = Verdict.REJECT
    confidence: int = 0
    reject_reasons: List[str] = field(default_factory=list)
    reject_evidence: str = ""
    funding_evidence: Optional[FundingEvidence] = None
    score: int = 0
    score_breakdown: Dict[str, int] = field(default_factory=dict)
    why: str = ""
    notes: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class BountyVerdictEngine:
    def __init__(self, config: Optional[LaneConfig] = None):
        self.config = config or load_github_config()
        self._crypto_re = self.config.crypto_address_re

    # ------------------------------------------------------------------ entry
    def evaluate(
        self,
        issue: Dict[str, Any],
        repo_meta: Optional[Dict[str, Any]] = None,
        author_age_days: Optional[int] = None,
        similar_titles_count: int = 0,
        author_recent_issues: int = 0,
        template_group_size: int = 0,
    ) -> BountyVerdictResult:
        title = issue.get("title") or ""
        body = issue.get("body") or ""
        state = (issue.get("state") or "open").lower()
        labels = self._extract_labels(issue)
        author = (issue.get("user") or {}).get("login", "")
        updated_at = issue.get("updated_at") or ""
        created_at = issue.get("created_at") or ""
        closed_at = issue.get("closed_at")

        result = BountyVerdictResult()
        breakdown: Dict[str, int] = {}
        reasons: List[str] = []
        evidence_parts: List[str] = []
        score = 50  # neutral start

        label_text = " ".join(labels)
        text_low = f"{title} {body} {label_text}".lower()
        has_substance = self._has_substance(body)
        alignment_blocker = ("needs alignment" in text_low) or ("needs triage" in text_low)
        review_needed = "s0: review needed" in text_low
        difficulty_hard = ("difficulty: hard" in text_low) or ("difficulty:hard" in text_low)

        # ---- Hard rejects ----------------------------------------------------
        if self._is_stale(updated_at):
            reasons.append(RejectReason.STALE)
            evidence_parts.append("not updated within threshold days")
            breakdown["stale_penalty"] = -30
            score -= 30

        taken, taken_ev = self._is_taken(issue)
        if taken:
            reasons.append(RejectReason.TAKEN)
            evidence_parts.append(taken_ev)
            breakdown["taken_penalty"] = -40
            score -= 40

        # Crypto payments are illegal in Nepal, so any crypto-paid bounty is
        # legally unworkable regardless of how good the issue is.
        if self._crypto_re.findall(body or ""):
            reasons.append(RejectReason.CRYPTO_WALLET_IN_BODY)
            evidence_parts.append("crypto wallet address in body")
            breakdown["crypto_penalty"] = -50
            score -= 50

        crypto_paid, crypto_ev = self._detect_crypto_payment(title, body)
        if crypto_paid:
            reasons.append(RejectReason.CRYPTO_PAYMENT)
            evidence_parts.append(crypto_ev)
            breakdown["crypto_payment_penalty"] = -50
            score -= 50

        digest, digest_ev = self._is_aggregator_digest(issue)
        if digest:
            reasons.append(RejectReason.AGGREGATOR_DIGEST)
            evidence_parts.append(digest_ev)
            breakdown["digest_penalty"] = -40
            score -= 40

        farm, farm_ev = self._is_farm_repo(issue, repo_meta)
        if farm:
            reasons.append(RejectReason.BOT_OR_FARM_REPO)
            evidence_parts.append(farm_ev)
            breakdown["farm_penalty"] = -30
            score -= 30

        if similar_titles_count >= self.config.clone_farm_min_repos:
            reasons.append(RejectReason.CLONE_FARM)
            evidence_parts.append(f"same title in {similar_titles_count}+ repos")
            breakdown["clonefarm_penalty"] = -30
            score -= 30

        if self._has_repeated_title_phrase(title):
            reasons.append(RejectReason.REPEATED_TITLE)
            breakdown["repeated_title_penalty"] = -15
            score -= 15

        # Meta/tracking/roadmap issues coordinate work; they are not a task.
        tracking = bool(re.search(
            r"\[(?:system )?roadmap\]|\b(?:tracking issue|meta issue|epic:)\b|"
            r"^\s*track (?:all|every)\b",
            text_low,
        ))
        if tracking:
            reasons.append(RejectReason.NO_TASK)
            evidence_parts.append("tracking/roadmap issue, not a concrete task")
            breakdown["tracking_penalty"] = -30
            score -= 30

        # Submission forms, listings, announcements and download pages are not
        # coding tasks, even when the body is long and structured.
        not_task, not_task_ev = self._is_not_a_coding_task(title, body)
        if not_task:
            reasons.append(RejectReason.NOT_A_CODING_TASK)
            evidence_parts.append(not_task_ev)
            breakdown["not_coding_task_penalty"] = -40
            score -= 40

        no_task, no_task_ev = self._has_no_task(body)
        if no_task:
            reasons.append(RejectReason.NO_TASK)
            evidence_parts.append(no_task_ev)
            breakdown["notask_penalty"] = -25
            score -= 25

        trivial, trivial_ev = self._is_trivial_task(body)
        if trivial:
            reasons.append(RejectReason.TRIVIAL_TASK)
            evidence_parts.append(trivial_ev)
            breakdown["trivial_penalty"] = -30
            score -= 30

        templated, templated_ev = self._is_templated_issue(
            title, body, author, author_recent_issues, template_group_size
        )
        if templated:
            reasons.append(RejectReason.TEMPLATED_ISSUE)
            evidence_parts.append(templated_ev)
            breakdown["templated_penalty"] = -20
            score -= 20

        if len(labels) >= self.config.label_stuffing_threshold:
            reasons.append(RejectReason.LABEL_STUFFING)
            evidence_parts.append(f"{len(labels)} labels on one issue")
            breakdown["labelstuffing_penalty"] = -20
            score -= 20

        if repo_meta and (repo_meta.get("archived") or repo_meta.get("is_archived")):
            reasons.append(RejectReason.CLOSED_OR_ARCHIVED_REPO)
            breakdown["archived_penalty"] = -50
            score -= 50

        if state == "closed" or closed_at:
            if RejectReason.TAKEN not in reasons:
                reasons.append(RejectReason.TAKEN)
                evidence_parts.append("issue closed")
                breakdown["closed_penalty"] = -40
                score -= 40

        # ---- Funding evidence (strong positive, not required) ----------------
        funding_ok, funding_evidence, funding_src = self._detect_funding_evidence(
            title, body, issue
        )
        funding = funding_evidence if funding_ok else None
        if funding_ok:
            breakdown["funding_evidence"] = 40
            score += 40
            evidence_parts.append(f"funding: {funding_src}")

        if not funding_ok and self._is_unfunded_notice(body):
            reasons.append(RejectReason.UNFUNDED_NOTICE)
            evidence_parts.append("explicit unfunded notice")
            breakdown["unfunded_penalty"] = -40
            score -= 40

        # "bounty" as a game/product/protocol term with no funding evidence.
        # A real, well-scoped bug report about the product's own "bounty"
        # feature still survives (flag only). We hard-reject when there is no
        # task substance, or when maintainers have not agreed on the approach.
        word_only = (not funding_ok) and self._is_word_only_match(title, body)
        if word_only:
            if has_substance and not alignment_blocker:
                # Real bug report about the product's own "bounty" feature: flag only.
                breakdown["wordonly_flag"] = -10
                score -= 10
                evidence_parts.append("'bounty' used as a product/game term")
            else:
                reasons.append(RejectReason.WORD_ONLY_MATCH)
                breakdown["wordonly_penalty"] = -25
                score -= 25
                evidence_parts.append("'bounty' word only, no funding and no task")

        platform_feat, pf_ev = self._is_platform_feature(title, body)
        if platform_feat:
            reasons.append(RejectReason.PLATFORM_FEATURE)
            breakdown["platform_feature_penalty"] = -10
            score -= 10
            evidence_parts.append(pf_ev)

        if author_age_days is not None and author_age_days < 30:
            reasons.append(RejectReason.LOW_TRUST_POSTER)
            breakdown["lowtrust_penalty"] = -15
            score -= 15

        # ---- Positive signals ------------------------------------------------
        effort_labels = {"e1", "e2", "easy", "small", "good first issue", "help wanted"}
        if any(l in effort_labels for l in labels):
            breakdown["effort_label"] = 10
            score += 10

        gfi_hw = any(l in ("good first issue", "help wanted") for l in labels)
        if gfi_hw and has_substance:
            breakdown["gfi_with_substance"] = 10
            score += 10
        elif gfi_hw and not has_substance:
            breakdown["gfi_no_substance"] = -10
            score -= 10

        if self._is_maintainer_authored(issue, repo_meta):
            breakdown["maintainer_authored"] = 10
            score += 10

        if self._is_fresh(created_at):
            breakdown["fresh"] = 8
            score += 8

        comments = int(issue.get("comments") or 0)
        if comments <= 5:
            breakdown["few_comments"] = 5
            score += 5

        stack_match = self._stack_match(title, body, labels)
        if stack_match == "strong":
            breakdown["stack_strong"] = 12
            score += 12
        elif stack_match == "weak":
            breakdown["stack_weak"] = 4
            score += 4

        if self._avoid_domain(title, body):
            breakdown["avoid_domain_penalty"] = -20
            score -= 20
            evidence_parts.append("hard domain outside my stack")

        _size = repo_meta.get("size") if isinstance(repo_meta, dict) else None
        large_codebase = bool(
            isinstance(_size, (int, float))
            and not isinstance(_size, bool)
            and _size > self.config.repo_size_warn_kb
        )
        if large_codebase:
            breakdown["large_codebase_penalty"] = -20
            score -= 20
            evidence_parts.append("very large codebase with heavy setup")

        if alignment_blocker:
            breakdown["needs_alignment_penalty"] = -15
            score -= 15
            evidence_parts.append("needs alignment: maintainers have not decided the approach")
        if review_needed:
            breakdown["review_needed_penalty"] = -5
            score -= 5
            evidence_parts.append("S0: Review Needed")

        if difficulty_hard:
            breakdown["difficulty_hard_penalty"] = -15
            score -= 15
            evidence_parts.append("difficulty: hard")

        score = max(0, min(100, score))

        # ---- Verdict ---------------------------------------------------------
        hard_reasons = [r for r in reasons if r not in SOFT_REASONS]
        if hard_reasons:
            result.verdict = Verdict.REJECT
        elif score >= self.config.confidence_accept:
            result.verdict = Verdict.ACCEPT
        else:
            result.verdict = Verdict.UNCERTAIN

        result.confidence = score
        result.score = score
        result.score_breakdown = breakdown
        result.reject_reasons = reasons
        result.reject_evidence = "; ".join(evidence_parts)
        result.funding_evidence = funding
        result.why = self._build_why(result, funding)
        result.notes = self._build_notes(
            result, alignment_blocker or review_needed, stack_match, text_low, title
        )
        result.details = {
            "author": author,
            "state": state,
            "labels": labels,
            "comments": comments,
        }
        return result

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _extract_labels(issue: Dict[str, Any]) -> List[str]:
        out: List[str] = []
        for lab in issue.get("labels") or []:
            if isinstance(lab, dict) and lab.get("name"):
                out.append(str(lab["name"]).lower())
            elif isinstance(lab, str):
                out.append(lab.lower())
        return out

    def _is_stale(self, updated_at: str) -> bool:
        if not updated_at:
            return True
        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        return (datetime.now(timezone.utc) - dt).days > self.config.max_age_days

    @staticmethod
    def _is_taken(issue: Dict[str, Any]) -> Tuple[bool, str]:
        if issue.get("assignee"):
            return True, "assignee set"
        if (issue.get("state") or "").lower() == "closed":
            return True, "issue closed"
        if issue.get("linked_pr") or issue.get("_linked_pr") or issue.get("pull_request"):
            return True, "linked pull request present"
        return False, ""

    def _is_aggregator_digest(self, issue: Dict[str, Any]) -> Tuple[bool, str]:
        title = (issue.get("title") or "").lower()
        author = ((issue.get("user") or {}).get("login") or "").lower()
        labels = self._extract_labels(issue)
        for pat in self.config.bot_author_patterns:
            if pat.lower() in author:
                return True, f"bot author: {author}"
        for pat in self.config.digest_title_patterns:
            if pat in title:
                return True, f"digest title: {pat}"
        for lab in labels:
            if lab in ("intake", "release-watch", "bounty-alert", "intake-release-watch"):
                return True, f"digest label: {lab}"
        return False, ""

    def _is_farm_repo(
        self, issue: Dict[str, Any], repo_meta: Optional[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        repo_name = issue.get("_gh_repo") or ""
        if not repo_name:
            parts = (issue.get("repository_url") or "").rstrip("/").split("/")
            if len(parts) >= 2:
                repo_name = f"{parts[-2]}/{parts[-1]}"
        if repo_meta and repo_meta.get("full_name"):
            repo_name = repo_meta["full_name"]
        low = repo_name.lower()
        for pat in self.config.farm_repo_patterns:
            if pat in low:
                return True, f"farm repo name: {repo_name}"
        # Only judge size when we actually have it. A missing/failed metadata
        # fetch (size=None) must NEVER be read as "almost no code".
        if isinstance(repo_meta, dict):
            size = repo_meta.get("size")
            if isinstance(size, (int, float)) and not isinstance(size, bool):
                if size < self.config.thresholds.min_repo_size_kb:
                    return True, f"repo has almost no real code ({int(size)}KB)"
        return False, ""

    def _has_repeated_title_phrase(self, title: str) -> bool:
        words = re.findall(r"\w+", (title or "").lower())
        if len(words) < 4:
            return False
        bigrams = [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]
        return len(bigrams) != len(set(bigrams))

    def _has_no_task(self, body: str) -> Tuple[bool, str]:
        if not body or len(body.strip()) < self.config.min_body_length:
            return True, "no body or too short"
        low = body.lower()
        verbs = (
            "fix", "add", "remove", "update", "change", "implement",
            "create", "resolve", "refactor", "migrate", "support",
        )
        if not any(v in low for v in verbs):
            return True, "no concrete change described"
        return False, ""

    def _is_not_a_coding_task(self, title: str, body: str) -> Tuple[bool, str]:
        """Detect non-code issues: submissions, listings, announcements, spam."""
        title_low = (title or "").lower()
        text = f"{title} {body or ''}".lower()

        # Directory / marketplace / awesome-list submission forms.
        submission_markers = (
            "[server submission]", "[submission]", "submission form",
            "add to awesome", "awesome list", "directory submission",
            "listing request", "add my project", "add a tool",
        )
        if any(m in title_low or m in text[:400] for m in submission_markers):
            return True, "submission/listing form, not a code change"

        # Talks, events, meetup announcements.
        if re.search(r"\b(talk|symposium|meetup|webinar|conference|podcast)\b", title_low):
            if not re.search(r"\b(fix|bug|implement|refactor|add support)\b", title_low):
                return True, "event/talk announcement, not a code change"

        # Software-download / SEO spam.
        spam_markers = (
            "download ", "latest version", "free download", "crack", "keygen",
            "full version", "activation key", "torrent", "serial number",
        )
        if sum(1 for m in spam_markers if m in text) >= 2:
            return True, "software-download spam"

        return False, ""

    def _is_platform_feature(self, title: str, body: str) -> Tuple[bool, str]:
        text = f"{title} {body}".lower()
        for kw in self.config.platform_feature_keywords:
            if kw in text:
                return True, f"platform feature keyword: {kw}"
        return False, ""

    def _detect_funding_evidence(
        self, title: str, body: str, issue: Dict[str, Any]
    ) -> Tuple[bool, Optional[FundingEvidence], str]:
        """Platform signal (link/label/bot) AND a parseable amount in the body."""
        labels = self._extract_labels(issue)
        platform_signal: Optional[str] = None
        source_type: Optional[str] = None
        source_url: Optional[str] = None

        text = f"{title} {body or ''}"
        for plat in self.config.platforms:
            if plat.lower() in text.lower():
                platform_signal = plat
                source_type = "link"
                break

        if not platform_signal:
            label_candidates = list(self.config.bounty_labels) + list(self.config.platforms)
            for lab in labels:
                for plat_label in label_candidates:
                    if plat_label.lower() in lab:
                        platform_signal = plat_label
                        source_type = "label"
                        break
                if platform_signal:
                    break

        author = ((issue.get("user") or {}).get("login") or "").lower()
        if not platform_signal:
            for bot in self.config.platform_bots:
                if bot.lower() in author:
                    platform_signal = bot
                    source_type = "bot"
                    break

        if not platform_signal:
            return False, None, ""

        amounts = extract_money(body or "")
        valid = [
            (a, c) for a, c in amounts
            if a and self.config.min_amount_usd <= a <= self.config.max_amount_usd
        ]
        if not valid:
            return False, None, platform_signal

        amount, currency = valid[0]
        evidence = FundingEvidence(
            platform=platform_signal,
            amount=amount,
            currency=currency,
            source_url=issue.get("html_url") or "",
            source_type=source_type,
        )
        return True, evidence, f"{platform_signal} ({source_type}) + {amount} {currency}"

    def _detect_crypto_payment(self, title: str, body: str) -> Tuple[bool, str]:
        """Detect a bounty paid in crypto (illegal to receive in Nepal).

        Deliberately narrow: a coding issue about crypto software is fine, but
        paying/receiving in crypto, or a crypto amount attached to a reward, is
        not workable from Nepal.
        """
        text = f"{title} {body or ''}"
        low = text.lower()

        # Ticker/code adjacent to a number, e.g. "450 USDC", "$600 in ETH".
        amount_re = re.compile(
            r"(?:\b\d[\d,]*(?:\.\d+)?\s*"
            r"(?:usdc|usdt|btc|eth|sol|xlm|ltc|dai|usd\s*coin|sats?)\b"
            r"|\b(?:usdc|usdt|btc|eth|sol|xlm|ltc|dai|sats?)\s*\d)",
            re.IGNORECASE,
        )
        m = amount_re.search(text)
        if m:
            return True, f"crypto amount: {m.group(0).strip()}"

        # Explicit payment-in-crypto phrasing (needs a payment word too).
        payment_words = (
            "paid in", "pay in", "payment in", "reward in", "pays in",
            "pay via", "paid via", "payout in", "payouts in", "compensation in",
            "send crypto", "crypto payment", "crypto reward", "crypto bounty",
            "pay me in", "pay to my wallet", "wallet address",
        )
        if any(w in low for w in payment_words) and self.config.crypto_payment_re.search(text):
            hit = self.config.crypto_payment_re.search(text)
            return True, f"crypto payment phrasing: {hit.group(0)}"

        return False, ""

    def _is_unfunded_notice(self, body: str) -> bool:
        low = (body or "").lower()
        return any(p in low for p in self.config.unfunded_phrases)

    def _is_word_only_match(self, title: str, body: str) -> bool:
        return "bounty" in f"{title} {body or ''}".lower()

    def _is_trivial_task(self, body: str) -> Tuple[bool, str]:
        low = (body or "").lower()
        if "no coding required" in low or "under 1 minute" in low or "just paste" in low:
            return True, "trivial task phrase"
        if "placeholder" in low and any(ext in low for ext in (".json", ".txt", ".yml")):
            return True, "placeholder data file only"
        return False, ""

    def _is_templated_issue(
        self,
        title: str,
        body: str,
        author: str,
        author_recent_issues: int,
        template_group_size: int = 0,
    ) -> Tuple[bool, str]:
        low_title = title.lower()
        if "variation" in low_title:
            return True, "templated title with 'variation'"
        if re.search(r"answer the \d+ linked question", low_title):
            return True, "templated 'answer the N linked question' phrasing"
        # Near-identical titles from one author (same leading words) = bulk template.
        if template_group_size >= 3:
            return True, f"{template_group_size} near-identical titles from {author}"
        if author_recent_issues >= 5:
            return True, f"{author_recent_issues + 1} issues from one author in one run"
        return False, ""

    @staticmethod
    def _has_substance(body: str) -> bool:
        low = (body or "").lower()
        signals = [
            "file", "module", "acceptance criteria", "reproduce", "repro",
            "steps to reproduce", "test", "unit test", "line ", "function",
            "class ", "workflow", ".yml", ".yaml", ".py", ".js", ".ts",
            "expected", "actual", "steps:", "suggested fix", "patch",
        ]
        return any(s in low for s in signals)

    def _is_maintainer_authored(
        self, issue: Dict[str, Any], repo_meta: Optional[Dict[str, Any]]
    ) -> bool:
        author = (issue.get("user") or {}).get("login", "")
        if not author:
            return False
        if issue.get("_maintainer_authored") is True:
            return True
        if repo_meta:
            if repo_meta.get("maintainers") and author in repo_meta["maintainers"]:
                return True
            owner = (repo_meta.get("owner") or {}).get("login")
            if owner and owner.lower() == author.lower():
                return True
            full = (repo_meta.get("full_name") or "")
            if full and full.split("/")[0].lower() == author.lower():
                return True
        return False

    @staticmethod
    def _is_fresh(created_at: str) -> bool:
        if not created_at:
            return False
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (datetime.now(timezone.utc) - dt).days <= 7

    def _stack_match(self, title: str, body: str, labels: List[str]) -> str:
        text = f"{title} {body} {' '.join(labels)}".lower()
        strong = sum(1 for s in self.config.stack.strong if s.lower() in text)
        weak = sum(1 for s in self.config.stack.weak if s.lower() in text)
        # A workflow file is a GitHub Actions task even without the literal label.
        if any(sig in text for sig in ("workflow", ".github/workflows", ".yml", ".yaml")):
            strong += 1
        if strong > weak and strong > 0:
            return "strong"
        if weak > 0:
            return "weak"
        return "none"

    def _avoid_domain(self, title: str, body: str) -> bool:
        text = f"{title} {body}".lower()
        return any(d.lower() in text for d in self.config.avoid_domains)

    def _build_why(
        self, result: BountyVerdictResult, funding: Optional[FundingEvidence]
    ) -> str:
        if result.verdict == Verdict.ACCEPT:
            if funding:
                return (
                    f"Funded: {funding.platform} {funding.amount} {funding.currency} "
                    f"— platform evidence in body, score {result.score}"
                )
            return f"Unfunded but real, well-scoped issue, score {result.score}"
        if result.verdict == Verdict.UNCERTAIN:
            return f"Uncertain: score {result.score}, routed to triage"
        return f"Rejected: {result.reject_evidence or 'failed quality gate'}"

    def _build_notes(
        self,
        result: BountyVerdictResult,
        needs_alignment: bool,
        stack_match: str,
        text_low: str,
        title: str,
    ) -> str:
        notes: List[str] = []
        if needs_alignment:
            if "s0: review needed" in text_low:
                notes.append("S0: Review Needed, ask the maintainers before starting")
            else:
                notes.append("ask maintainers before starting")
        dep = re.search(
            r"(?:depends on|blocked by|may depend on)(?:\s+issue)?\s+#?(\d+)",
            text_low,
        )
        if dep:
            notes.append(f"may depend on issue #{dep.group(1)}")
        if "very large codebase with heavy setup" in (result.reject_evidence or ""):
            notes.append("very large codebase, heavy local setup")
        if stack_match == "weak":
            notes.append("weak stack match")
        if result.funding_evidence and result.verdict != Verdict.REJECT:
            notes.append("human must verify funding before messaging")
        if RejectReason.CRYPTO_PAYMENT in result.reject_reasons:
            notes.append("crypto payment is illegal in Nepal: do not accept")
        return "; ".join(notes)

    @staticmethod
    def verdict_to_db_fields(result: BountyVerdictResult) -> Dict[str, Any]:
        funding = None
        if result.funding_evidence is not None:
            funding = {
                "platform": result.funding_evidence.platform,
                "amount": result.funding_evidence.amount,
                "currency": result.funding_evidence.currency,
                "source_url": result.funding_evidence.source_url,
                "source_type": result.funding_evidence.source_type,
            }
        return {
            "bounty_verdict": result.verdict,
            "reject_reasons": result.reject_reasons,
            "funding_evidence": funding,
            "bounty_confidence": result.confidence,
            "reject_evidence": result.reject_evidence,
            "score": result.score,
            "score_breakdown": result.score_breakdown,
            "why": result.why,
            "notes": result.notes,
        }


def material_state_hash(issue: Dict[str, Any], verdict: Optional[BountyVerdictResult] = None) -> str:
    """Stable hash of the fields that matter for dedupe/resurface decisions."""
    import hashlib
    import json

    labels = sorted(
        (l.get("name") if isinstance(l, dict) else str(l))
        for l in (issue.get("labels") or [])
    )
    payload = {
        "state": (issue.get("state") or "").lower(),
        "assignee": (issue.get("assignee") or {}).get("login") if isinstance(issue.get("assignee"), dict) else issue.get("assignee"),
        "linked_pr": bool(issue.get("linked_pr") or issue.get("_linked_pr") or issue.get("pull_request")),
        "labels": labels,
        "verdict": verdict.verdict if verdict else None,
        "funding": (
            {"platform": verdict.funding_evidence.platform, "amount": verdict.funding_evidence.amount}
            if verdict and verdict.funding_evidence else None
        ),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def should_resurface(previous_hash: Optional[str], current_hash: str) -> bool:
    """True only when something material changed (never on identical state)."""
    if not previous_hash:
        return True
    return previous_hash != current_hash


# Backward-compatible aliases
LaneVerdictEngine = BountyVerdictEngine
LaneVerdictResult = BountyVerdictResult
