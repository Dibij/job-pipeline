"""Prompt Version: triage_v1

Triage classification of job postings according to candidate profile guidelines (v2_role_fit_only).
Supports few-shot dynamic example injection.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You are an expert AI talent recruiter assisting a software developer candidate.
Evaluate the given job description and classify it into one of three labels:
- 'good_fit': Technical software development role (Junior, Entry, Mid, or unstated seniority) matching the candidate's core stack (Python, FastAPI, Django, React, Next.js, TypeScript, PostgreSQL, backend/fullstack). Remote-friendly and realistic.
- 'maybe': Potentially relevant technical role with slight stack overlap or moderate stretch (e.g., 2-3 years exp, adjacent frameworks, interesting AI/ML engineering).
- 'bad_fit': Hard misfits: Senior/Staff/Lead/Manager roles, non-technical positions (sales, recruiting, customer success), incompatible tech stacks (pure iOS/Swift, C++, PHP/WordPress, embedded), unpaid roles, or geographically restricted positions excluding remote workers in South Asia/Nepal.

Output JSON strictly conforming to the requested schema with `label`, `confidence` (0.0 to 1.0), `reason`, and `evidence_quote`.
"""


def build_triage_user_message(
    title: str,
    company: str,
    description: str,
    few_shot_examples: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Format user prompt including optional few-shot examples."""
    parts = []

    if few_shot_examples:
        parts.append("### Reference Examples from Human Review:")
        for idx, ex in enumerate(few_shot_examples, start=1):
            ex_title = ex.get("title", "")
            ex_company = ex.get("company", "")
            ex_label = ex.get("label", "")
            ex_snippet = ex.get("description_snippet", "")[:180]
            parts.append(
                f"Example {idx}:\n"
                f"  Title: {ex_title} at {ex_company}\n"
                f"  Snippet: {ex_snippet}...\n"
                f"  Human Label: {ex_label}\n"
            )
        parts.append("### Target Job to Evaluate:")

    desc_clean = description.strip()
    if len(desc_clean) > 2500:
        desc_clean = desc_clean[:2500] + "\n...[truncated]"

    parts.append(f"Title: {title}\nCompany: {company}\n\nJob Description:\n{desc_clean}")
    parts.append("\nClassify this role into 'good_fit', 'maybe', or 'bad_fit' with confidence score, brief reason, and evidence quote.")

    return "\n\n".join(parts)
