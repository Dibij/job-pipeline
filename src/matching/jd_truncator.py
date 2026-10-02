"""Token budget truncation for Laya scoring inputs.

Fits JD sections and candidate profile into Laya's 1,024 token limit using
the real model tokenizer.
Priority order:
  1. Title, Company, Location (structured metadata)
  2. Candidate CV summary
  3. Requirements / Qualifications
  4. Responsibilities
  5. Nice-to-haves
  6. Company blurb
Drops benefits, legal/EEO boilerplate, and other non-essential text first.
Adds ' [...]' marker when cutting inside a section.
"""
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.matching.jd_extractor import JDSections

logger = logging.getLogger(__name__)

# Config path
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
TOKEN_BUDGET_FILE = CONFIG_DIR / "token_budget.json"
CV_PROFILE_FILE = Path(__file__).resolve().parent / "cv_profile.json"

DEFAULT_JD_BUDGET = 566
DEFAULT_SAFETY_MARGIN = 50
TRUNCATION_MARKER = " [...]"

# Lazy-loaded tokenizer singleton
_TOKENIZER = None


def get_tokenizer():
    """Get the cached Laya tokenizer instance."""
    global _TOKENIZER
    if _TOKENIZER is None:
        import laya
        agent = laya.load("convaiinnovations/laya", device="cpu")
        _TOKENIZER = agent.tok
    return _TOKENIZER


def load_token_budget_config() -> Dict[str, Any]:
    """Load token budget limits from config file if available."""
    if TOKEN_BUDGET_FILE.exists():
        try:
            with open(TOKEN_BUDGET_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not read token_budget.json: %s", e)
    return {
        "max_model_tokens": 1024,
        "safety_margin": DEFAULT_SAFETY_MARGIN,
        "laya_input_token_budget": DEFAULT_JD_BUDGET
    }


def get_compact_cv_summary(cv_profile_path: Optional[Path] = None) -> str:
    """Generate a compact CV summary string for prompt context."""
    path = cv_profile_path or CV_PROFILE_FILE
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cand = data.get("candidate", {})
            skills = data.get("skills", {})
            prim = [s["name"] for s in skills.get("primary", [])]
            sec = [s["name"] for s in skills.get("secondary", [])]
            return (
                f"Candidate: {cand.get('name', 'Applicant')}, {cand.get('location', 'Remote')}. "
                f"Experience: {cand.get('experience_years', 0)} years. "
                f"Target: {', '.join(cand.get('target_seniority', ['junior']))}. "
                f"Skills: {', '.join(prim[:8])}. Also: {', '.join(sec[:4])}. "
                f"Seeking: remote, entry-level/junior. No German. No unpaid."
            )
        except Exception as e:
            logger.warning("Failed to load CV profile: %s", e)

    return (
        "Candidate: Junior CS student in Kathmandu, Nepal (UTC+5:45). "
        "Experience: 0 years. Skills: Python, Django, React, TypeScript, PostgreSQL, Docker. "
        "Seeking: remote entry-level/junior developer roles. No German. No unpaid."
    )


def count_tokens(text: str, tokenizer: Optional[Any] = None) -> int:
    """Count tokens using Laya's real tokenizer."""
    if not text:
        return 0
    tok = tokenizer or get_tokenizer()
    return len(tok(text, add_special_tokens=False)["input_ids"])


def truncate_text_to_tokens(
    text: str,
    max_tokens: int,
    tokenizer: Optional[Any] = None,
    marker: str = TRUNCATION_MARKER
) -> str:
    """Truncate a single text string to at most max_tokens, appending marker if cut."""
    if not text or max_tokens <= 0:
        return ""

    tok = tokenizer or get_tokenizer()
    input_ids = tok(text, add_special_tokens=False)["input_ids"]
    if len(input_ids) <= max_tokens:
        return text

    marker_tokens = len(tok(marker, add_special_tokens=False)["input_ids"])
    cut_tokens = max(1, max_tokens - marker_tokens)
    truncated_ids = input_ids[:cut_tokens]
    
    # Decode back to text
    decoded = tok.decode(truncated_ids, skip_special_tokens=True).strip()
    return decoded + marker


def build_truncated_laya_state(
    sections: JDSections,
    max_jd_tokens: Optional[int] = None,
    tokenizer: Optional[Any] = None,
    cv_summary: Optional[str] = None
) -> Dict[str, str]:
    """Fit JD sections into Laya's token budget according to priority rules.

    Priority order:
      1. requirements (most critical for matching)
      2. responsibilities
      3. nice_to_have
      4. company_blurb
    (benefits, legal_eeo, and other are dropped first).

    Args:
        sections: Extracted JDSections object.
        max_jd_tokens: Configurable token budget for JD text (defaults to config).
        tokenizer: Real Laya tokenizer instance.
        cv_summary: Optional candidate summary.

    Returns:
        Dict representing state ready for Laya decision engine.
    """
    tok = tokenizer or get_tokenizer()
    if max_jd_tokens is None:
        cfg = load_token_budget_config()
        max_jd_tokens = cfg.get("laya_input_token_budget", DEFAULT_JD_BUDGET)

    summary = cv_summary or get_compact_cv_summary()

    # Priorities to include from JD body
    priority_fields = [
        ("requirements", sections.requirements),
        ("responsibilities", sections.responsibilities),
        ("nice_to_have", sections.nice_to_have),
        ("company_blurb", sections.company_blurb)
    ]

    remaining_budget = max_jd_tokens
    state_body: Dict[str, str] = {}

    for field_name, content in priority_fields:
        if not content or not content.strip():
            state_body[field_name] = ""
            continue

        field_tokens = len(tok(content, add_special_tokens=False)["input_ids"])
        if field_tokens <= remaining_budget:
            state_body[field_name] = content.strip()
            remaining_budget -= field_tokens
        elif remaining_budget > 15:
            # Cut inside section with marker
            state_body[field_name] = truncate_text_to_tokens(
                content, remaining_budget, tokenizer=tok
            )
            remaining_budget = 0
        else:
            # Not enough tokens left
            state_body[field_name] = ""

    # Assemble final structured state
    return {
        "title": sections.title,
        "company": sections.company,
        "location": sections.location,
        "candidate_summary": summary,
        "requirements": state_body.get("requirements", ""),
        "responsibilities": state_body.get("responsibilities", ""),
        "nice_to_have": state_body.get("nice_to_have", ""),
        "company_blurb": state_body.get("company_blurb", "")
    }
