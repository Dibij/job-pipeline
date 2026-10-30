"""Prompt Version: extraction_v1

Factual structured extraction of job requirements and constraints with verbatim evidence quotes.
"""
from __future__ import annotations

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You are a rigorous, factual job description analysis engine.
Your task is to extract job requirements and constraints strictly matching the requested JSON schema.

Rules:
1. Extract ONLY facts explicitly stated in the job posting. Do NOT guess or extrapolate.
2. For each field, include a short verbatim `evidence_quote` from the text as proof.
3. If a field is not explicitly mentioned, leave `value` as null (or 'unknown' for seniority/remote) and provide an empty evidence quote.
4. `required_stack`: List only the primary technical languages, libraries, and frameworks strictly required.
5. `seniority`: Choose from 'intern', 'junior', 'mid', 'senior', 'lead', 'unknown'.
6. `years_experience_min`: Number of minimum years explicitly stated (e.g., 2.0). If not stated, null.
7. `degree_required`: True only if a university/bachelor's degree is explicitly mandatory.
8. `remote_policy`: 'remote', 'hybrid', 'onsite', or 'unknown'.
9. `region_restrictions`: List explicit geographic bounds (e.g. ['US only', 'Europe only']). If globally remote, empty list.
10. `work_authorization`: Explicit visa/citizenship restrictions (e.g. 'US Citizen only', 'No visa sponsorship'). If unmentioned, null.
11. `salary_if_stated`: Verbatim compensation text if mentioned, else null.
"""


def build_user_message(title: str, company: str, location: str, description: str) -> str:
    """Format user message for extraction."""
    desc_clean = description.strip()
    if len(desc_clean) > 4000:
        desc_clean = desc_clean[:4000] + "\n...[truncated]"

    return (
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n\n"
        f"Job Description:\n{desc_clean}\n\n"
        "Extract the structured criteria as valid JSON conforming strictly to the schema."
    )
