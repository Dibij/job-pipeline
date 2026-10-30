"""Prompt Version: explanation_v1

Generates concise, 2-sentence feed summaries: why this job fits, and what is missing.
"""
from __future__ import annotations

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You are a concise career coach for a software engineer candidate.
Candidate profile: Junior/Mid Software Engineer specializing in Python, FastAPI, Django, React/Next.js, TypeScript, PostgreSQL, and Docker.

Analyze the given job and provide:
1. `why_fits`: 1-2 crisp sentences stating exactly why this role aligns with the candidate's technical skills and level.
2. `what_missing`: 1-2 crisp sentences noting any stack gaps, seniority mismatch, geographic restrictions, or missing qualifications.

Return JSON strictly matching the schema.
"""


def build_explanation_user_message(title: str, company: str, description: str) -> str:
    """Format prompt for job explanation generation."""
    desc_clean = description.strip()
    if len(desc_clean) > 2000:
        desc_clean = desc_clean[:2000] + "\n...[truncated]"

    return (
        f"Title: {title}\n"
        f"Company: {company}\n\n"
        f"Job Description:\n{desc_clean}\n\n"
        "Provide a 2-sentence breakdown in JSON ('why_fits' and 'what_missing')."
    )
