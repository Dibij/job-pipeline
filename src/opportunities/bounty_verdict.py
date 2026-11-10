"""Lane-based verdict engine for GitHub issues.

Two lanes:
  PAID   - real funding evidence (platform link/label + amount). Rare. Highest priority.
  PROOF  - unfunded but real, well-scoped issues in healthy repos.

Everything else is rejected with reasons. Nothing is auto-accepted or
auto-contacted; humans decide via triage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.opportunities.bounty_config import LaneConfig, load_github_config
from src.opportunities.compensation import extract_money


class Lane:
    PAID = "PAID"
    PROOF = "PROOF"


class RejectReason:
    NO_FUNDING_EVIDENCE = "NO_FUNDING_EVIDENCE"
    WORD_ONLY_MATCH = "WORD_ONLY_MATCH"
    AGGREGATOR_DIGEST = "AGGREGATOR_DIGEST"
    TAKEN = "TAKEN"
    CRYPTO_WALLET_IN_BODY = "CRYPTO_WALLET_IN_BODY"
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
    LARGE_CODEBASE = "LARGE_CODEBASE"


class Verdict:
    ACCEPT = "accept"
    REJECT = "reject"
    UNCERTAIN = "uncertain"


@dataclass
class FundingEvidence:
    platform: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None  # 'link' or 'label'


@dataclass
class LaneVerdictResult:
    lane: str = Lane.PROOF
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


class LaneVerdictEngine:
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
    ) -> LaneVerdictResult:
        title = issue.get("title") or ""
        body = issue.get("body") or ""
        state = (issue.get("state") or "open").lower()
        labels = self._extract_labels(issue)
        author = (issue.get("user") or {}).get("login", "")
        updated_at = issue.get("updated_at") or ""
        created_at = issue.get("created_at") or ""
        assignee = issue.get("assignee")
        closed_at = issue.get("closed_at")

        result = LaneVerdictResult(lane=Lane.PROOF)
        breakdown: Dict[str, int] = {}
        reasons: List[str] = []
        evidence_parts: List[str] = []
        funding = FundingEvidence()
        score = 50  # neutral start

        # ---- Stale ----
        stale = self._is_stale(updated_at)
        if stale:
            reasons.append(RejectReason.STALE)
            evidence_parts.append("not updated within threshold days")
            breakdown["stale_penalty"] = -30
            score -= 30

        # ---- Taken (closed / assignee / linked PR) ----
        taken, taken_ev = self._is_taken(issue)
        if taken:
            reasons.append(RejectReason.TAKEN)
            evidence_parts.append(taken_ev)
            breakdown["taken_penalty"] = -40
            score -= 40

        # ---- Crypto wallet ----
        crypto_hits = self._crypto_re.findall(body or "")
        if crypto_hits:
            reasons.append(RejectReason.CRYPTO_WALLET_IN_BODY)
            evidence_parts.append("crypto wallet address in body")
            breakdown["crypto_penalty"] = -50
            score -= 50

        # ---- Aggregator digest ----
        digest, digest_ev = self._is_aggregator_digest(issue)
        if digest:
            reasons.append(RejectReason.AGGREGATOR_DIGEST)
            evidence_parts.append(digest_ev)
            breakdown["digest_penalty"] = -40
            score -= 40

        # ---- Bot / farm repo ----
        farm, farm_ev = self._is_farm_repo(issue, repo_meta)
        if farm:
            reasons.append(RejectReason.BOT_OR_FARM_REPO)
            evidence_parts.append(farm_ev)
            breakdown["farm_penalty"] = -30
            score -= 30

        # ---- Clone farm ----
        if similar_titles_count >= self.config.clone_farm_min_repos:
            reasons.append(RejectReason.CLONE_FARM)
            breakdown["clonefarm_penalty"] = -30
            score -= 30
            evidence_parts.append(f"same title in {similar_titles_count}+ repos")

        # ---- Repeated title ----
        if self._has_repeated_title_phrase(title):
            reasons.append(RejectReason.REPEATED_TITLE)
            breakdown["repeated_title_penalty"] = -15
            score -= 15

        # ---- No task ----
        no_task, no_task_ev = self._has_no_task(body)
        if no_task:
            reasons.append(RejectReason.NO_TASK)
            evidence_parts.append(no_task_ev)
            breakdown["notask_penalty"] = -25
            score -= 25

        # ---- Platform feature ----
        platform_feat, pf_ev = self._is_platform_feature(title, body)
        if platform_feat:
            reasons.append(RejectReason.PLATFORM_FEATURE)
            breakdown["platform_feature_penalty"] = -10
            score -= 10
            evidence_parts.append(pf_ev)

        # ---- Funding evidence (PAID lane) ----
        funding_ok, funding_evidence, funding_src = self._detect_funding_evidence(
            title, body, issue
        )
        if funding_ok:
            funding = funding_evidence
            result.lane = Lane.PAID
            breakdown["funding_evidence"] = 40
            score += 40
            evidence_parts.append(f"funding: {funding_src}")
        else:
            if self._is_word_only_match(title, body):
                reasons.append(RejectReason.WORD_ONLY_MATCH)
                evidence_parts.append("bounty word only, no funding")
                breakdown["wordonly_penalty"] = -25
                score -= 25
            else:
                reasons.append(RejectReason.NO_FUNDING_EVIDENCE)
                evidence_parts.append("no funding evidence")

        # ---- Unfunded notice ----
        if self._is_unfunded_notice(body):
            reasons.append(RejectReason.UNFUNDED_NOTICE)
            evidence_parts.append("explicit unfunded notice")
            breakdown["unfunded_penalty"] = -40
            score -= 40

        # ---- Trivial task ----
        trivial, trivial_ev = self._is_trivial_task(body)
        if trivial:
            reasons.append(RejectReason.TRIVIAL_TASK)
            evidence_parts.append(trivial_ev)
            breakdown["trivial_penalty"] = -30
            score -= 30

        # ---- Templated issue ----
        templated, templated_ev = self._is_templated_issue(title, body, author, author_recent_issues)
        if templated:
            reasons.append(RejectReason.TEMPLATED_ISSUE)
            breakdown["templated_penalty"] = -20
            score -= 20
            evidence_parts.append(templated_ev)

        # ---- Label stuffing ----
        if len(labels) >= self.config.label_stuffing_threshold:
            reasons.append(RejectReason.LABEL_STUFFING)
            breakdown["labelstuffing_penalty"] = -20
            score -= 20

        # ---- Low trust poster ----
        low_trust = author_age_days is not None and author_age_days < 30
        if low_trust:
            breakdown["lowtrust_penalty"] = -20
            score -= 20
            evidence_parts.append("new author (<30d)")

        # ---- Closed or archived repo ----
        if repo_meta:
            if (repo_meta.get("archived") or repo_meta.get("is_archived")):
                reasons.append(RejectReason.CLOSED_OR_ARCHIVED_REPO)
                breakdown["archived_penalty"] = -50
                score -= 50

        # ---- Closed issue ----
        if state == "closed" or closed_at:
            if RejectReason.TAKEN not in reasons:
                reasons.append(RejectReason.TAKEN)
                evidence_parts.append("issue closed")
                breakdown["closed_penalty"] = -40
                score -= 40

        # ---- Positive signals (PROOF lane & PAID lane) ----
        # Effort labels
        effort_labels = {"e1", "e2", "easy", "small", "good first issue", "help wanted"}
        has_effort = any(l in effort_labels for l in labels)
        if has_effort:
            breakdown["effort_label"] = 10
            score += 10

        # Good first issue / help wanted only with substance
        gfi_hw = any(l in ("good first issue", "help wanted") for l in labels)
        has_substance = self._has_substance(body)
        if gfi_hw and has_substance:
            breakdown["gfi_with_substance"] = 10
            score += 10
        elif gfi_hw and not has_substance:
            breakdown["gfi_no_substance"] = -10
            score -= 10

        # Maintainer authored / labeled
        if self._is_maintainer_authored(issue, repo_meta):
            breakdown["maintainer_authored"] = 10
            score += 10

        # Fresh (created within 7 days)
        if self._is_fresh(created_at):
            breakdown["fresh"] = 8
            score += 8

        # Few comments
        comments = int(issue.get("comments") or 0)
        if comments <= 5:
            breakdown["few_comments"] = 5
            score += 5

        # Stack match
        stack_match = self._stack_match(title, body, labels)
        if stack_match == "strong":
            breakdown["stack_strong"] = 12
            score += 12
        elif stack_match == "weak":
            breakdown["stack_weak"] = 4
            score += 4

        # Avoid domains
        if self._avoid_domain(title, body):
            breakdown["avoid_domain_penalty"] = -20
            score -= 20
            reasons.append(RejectReason.LOW_TRUST_POSTER)  # placeholder; use domain note
            evidence_parts.append("avoid domain")

        # Large codebase penalty
        if repo_meta and int(repo_meta.get("size") or 0) > self.config.repo_size_warn_kb:
            breakdown["large_codebase_penalty"] = -15
            score -= 15
            evidence_parts.append("large codebase with heavy setup")

        # Review needed / not triaged note
        needs_alignment = any(
            p in (title + " " + body).lower()
            for p in ("needs alignment", "s0: review needed", "needs triage")
        )
        if needs_alignment:
            breakdown["review_needed_note"] = 0
            evidence_parts.append("needs alignment / review before starting")

        # Clamp score
        score = max(0, min(100, score))
        result.score = score
        result.score_breakdown = breakdown
        result.reject_reasons = reasons
        result.reject_evidence = "; ".join(evidence_parts)

        # ---- Verdict ----
        accept_ok = (
            not reasons
            and score >= self.config.confidence_accept
        )
        if result.lane == Lane.PAID:
            accept_ok = accept_ok and funding_ok and not stale and not taken

        if accept_ok:
            result.verdict = Verdict.ACCEPT
            result.confidence = score
        elif reasons:
            result.verdict = Verdict.REJECT
            result.confidence = max(0, min(100, score))
        else:
            result.verdict = Verdict.UNCERTAIN
            result.confidence = score

        result.why = self._build_why(result, title, funding, breakdown)
        result.notes = self._build_notes(result, needs_alignment, stack_match)
        result.funding_evidence = funding if (funding and funding.amount is not None) else None
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
        labels = issue.get("labels") or []
        out: List[str] = []
        for lab in labels:
            if isinstance(lab, dict):
                out.append(str(lab.get("name", "")).lower())
            else:
                out.append(str(lab).lower())
        return out

    @staticmethod
    def _is_stale(updated_at: str) -> bool:
        if not updated_at:
            return True
        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        return (datetime.now(timezone.utc) - dt).days > 14

    @staticmethod
    def _is_taken(issue: Dict[str, Any]) -> Tuple[bool, str]:
        if issue.get("assignee"):
            return True, "assignee set"
        if issue.get("state", "").lower() == "closed":
            return True, "issue closed"
        # Linked PR / cross reference - inspected via timeline fields if present
        pr = issue.get("linked_pr") or issue.get("pull_request")
        if pr:
            return True, "linked pull request present"
        return False, ""

    def _is_aggregator_digest(self, issue: Dict[str, Any]) -> Tuple[bool, str]:
        title = (issue.get("title") or "").lower()
        author = ((issue.get("user") or {}).get("login") or "").lower()
        labels = self._extract_labels(issue)
        # Bot author
        for pat in self.config.bot_author_patterns:
            if pat.lower() in author:
                return True, f"bot author: {author}"
        # Digest title patterns
        for pat in self.config.digest_title_patterns:
            if pat in title:
                return True, f"digest title: {pat}"
        # Digest labels
        for lab in labels:
            if lab in ("intake", "release-watch", "bounty-alert"):
                return True, f"digest label: {lab}"
        return False, ""

    def _is_farm_repo(self, issue: Dict[str, Any], repo_meta: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        repo_url = issue.get("repository_url") or issue.get("repo_url") or ""
        repo_name = ""
        parts = repo_url.rstrip("/").split("/")
        if len(parts) >= 2:
            repo_name = f"{parts[-2]}/{parts[-1]}"
        if repo_meta:
            repo_name = repo_meta.get("full_name") or repo_name
        low = repo_name.lower()
        for pat in self.config.farm_repo_patterns:
            if pat in low:
                return True, f"farm repo name: {repo_name}"
        # Almost no real code (size tiny)
        if repo_meta and int(repo_meta.get("size") or 0) < 50:
            return True, "repo has almost no code"
        return False, ""

    def _has_repeated_title_phrase(self, title: str) -> bool:
        # Same phrase repeated within title
        words = re.findall(r"\w+", title.lower())
        if len(words) < 4:
            return False
        return len(set(words)) < len(words) * 0.6

    def _has_no_task(self, body: str) -> Tuple[bool, str]:
        if not body or len(body.strip()) < 20:
            return True, "no body or too short"
        # Look for concrete change words
        change_words = ["fix", "add", "remove", "update", "change", "implement", "create", "resolve"]
        low = body.lower()
        if not any(w in low for w in change_words):
            return True, "no concrete change described"
        return False, ""

    def _is_platform_feature(self, title: str, body: str) -> Tuple[bool, str]:
        text = (title + " " + body).lower()
        for kw in self.config.platform_feature_keywords:
            if kw in text:
                return True, f"platform feature keyword: {kw}"
        return False, ""

    def _detect_funding_evidence(
        self, title: str, body: str, issue: Dict[str, Any]
    ) -> Tuple[bool, Optional[FundingEvidence], str]:
        """Return (ok, evidence, source_desc). Needs platform signal + amount."""
        labels = self._extract_labels(issue)
        platform_signal = None
        source_type = None
        source_url = None

        # Platform link in body or html_url
        text = (title + " " + (body or ""))
        for plat in self.config.platforms:
            if plat in text:
                platform_signal = plat
                source_type = "link"
                break
        # Platform label
        if not platform_signal:
            for lab in labels:
                for plat_label in self.config.bounty_labels:
                    if plat_label in lab:
                        platform_signal = plat_label
                        source_type = "label"
                        break
                if platform_signal:
                    break
        # Platform bot comment / author
        author = ((issue.get("user") or {}).get("login") or "").lower()
        for bot in self.config.platform_bots:
            if bot in author:
                platform_signal = bot
                source_type = "bot"
                break

        if not platform_signal:
            return False, None, ""

        # Need parseable amount in body (title-only amount is NOT enough)
        amounts = extract_money(body or "")
        valid = [(a, c) for a, c in amounts if a and self.config.min_amount_usd <= a <= self.config.max_amount_usd]
        if not valid:
            return False, None, platform_signal

        amount, currency = valid[0]
        fe = FundingEvidence(
            platform=platform_signal,
            amount=amount,
            currency=currency,
            source_url=issue.get("html_url") or "",
            source_type=source_type,
        )
        return True, fe, f"{platform_signal} ({source_type}) + {amount} {currency}"

    def _is_unfunded_notice(self, body: str) -> bool:
        low = (body or "").lower()
        return any(p in low for p in self.config.unfunded_phrases)

    def _is_word_only_match(self, title: str, body: str) -> bool:
        text = (title + " " + (body or "")).lower()
        if "bounty" not in text:
            return False
        # If there's funding evidence, not word-only
        return True  # caller already checked funding_ok is False

    def _is_trivial_task(self, body: str) -> Tuple[bool, str]:
        low = (body or "").lower()
        if "no coding required" in low or "under 1 minute" in low or "just paste" in low:
            return True, "trivial task phrase"
        # Only data/text file with placeholder content
        if ("placeholder" in low and (".json" in low or ".txt" in low or ".yml" in low)):
            return True, "placeholder data file only"
        return False, ""

    def _is_templated_issue(self, title: str, body: str, author: str, author_recent_issues: int) -> Tuple[bool, str]:
        low_title = title.lower()
        if "variation" in low_title or re.search(r"\d+\s*$", low_title):
            return True, "templated title with incrementing number"
        if author_recent_issues >= 3:
            return True, f"many recent issues from {author}"
        return False, ""

    @staticmethod
    def _has_substance(body: str) -> bool:
        low = (body or "").lower()
        substance = ["file", "module", "acceptance", "reproduce", "test", "line:", "function", "class"]
        return any(w in low for w in substance)

    def _is_maintainer_authored(self, issue: Dict[str, Any], repo_meta: Optional[Dict[str, Any]]) -> bool:
        # If we have repo_meta with maintainer info, compare
        if repo_meta and repo_meta.get("maintainers"):
            author = (issue.get("user") or {}).get("login", "")
            return author in repo_meta["maintainers"]
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
        text = (title + " " + body + " " + " ".join(labels)).lower()
        strong_hits = sum(1 for s in self.config.stack.strong if s.lower() in text)
        weak_hits = sum(1 for s in self.config.stack.weak if s.lower() in text)
        if strong_hits > weak_hits and strong_hits > 0:
            return "strong"
        if weak_hits > 0:
            return "weak"
        return "none"

    def _avoid_domain(self, title: str, body: str) -> bool:
        text = (title + " " + body).lower()
        return any(d in text for d in self.config.avoid_domains)

    def _build_why(self, result: LaneVerdictResult, title: str, funding: Optional[FundingEvidence], breakdown: Dict[str, int]) -> str:
        if result.verdict == Verdict.ACCEPT:
            if result.lane == Lane.PAID:
                return f"PAID bounty: {funding.platform} {funding.amount} {funding.currency} — real funding evidence"
            return f"PROOF: real unpaid issue, score {result.score}, good first-issue candidate"
        if result.verdict == Verdict.UNCERTAIN:
            return f"Uncertain: score {result.score}, needs human review"
        return f"Rejected: {result.reject_evidence or 'no positive evidence'}"

    def _build_notes(self, result: LaneVerdictResult, needs_alignment: bool, stack_match: str) -> str:
        notes = []
        if needs_alignment:
            notes.append("ask maintainers before starting")
        if stack_match == "weak":
            notes.append("weak stack match")
        if result.lane == Lane.PAID:
            notes.append("human must verify funding before messaging")
        return "; ".join(notes)

    @staticmethod
    def verdict_to_db_fields(result: LaneVerdictResult) -> Dict[str, Any]:
        return {
            "bounty_verdict": result.verdict,
            "reject_reasons": result.reject_reasons,
            "funding_evidence": (
                {
                    "platform": result.funding_evidence.platform,
                    "amount": result.funding_evidence.amount,
                    "currency": result.funding_evidence.currency,
                    "source_url": result.funding_evidence.source_url,
                    "source_type": result.funding_evidence.source_type,
                }
                if result.funding_evidence
                else None
            ),
            "bounty_confidence": result.confidence,
            "reject_evidence": result.reject_evidence,
            "lane": result.lane,
            "score": result.score,
            "score_breakdown": result.score_breakdown,
            "why": result.why,
            "notes": result.notes,
        }


# Backwards compatibility aliases
BountyVerdictEngine = LaneVerdictEngine
BountyVerdictResult = LaneVerdictResult

