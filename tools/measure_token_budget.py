"""Measure token usage of different input components to compute real budget for 7.3."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import laya

print("Loading Laya agent...")
agent = laya.load("convaiinnovations/laya", device="cpu")
tokenizer = agent.tok
MAX_MODEL_TOKENS = 1024
print(f"Model max tokens: {MAX_MODEL_TOKENS}")

def count_tokens(text: str) -> int:
    return len(tokenizer(text, add_special_tokens=False)["input_ids"])

# 1. CV summary (what we will inject into the state)
cv_summary = """Candidate: Junior CS student in Kathmandu, Nepal (UTC+5:45).
Skills: Python, Django, React, TypeScript, Next.js, Node.js, PostgreSQL, JavaScript, REST APIs, AI/ML, Docker.
Seeking: remote-friendly, entry-level or junior, web/full-stack/AI roles.
Available: worldwide remote. No German. No unpaid."""

cv_tokens = count_tokens(cv_summary)

# 2. Question text & keys from laya_questions.yaml
question_texts = [
    "How well do the skills this job requires match the candidate's skills?",
    "Is the experience level this job requires suitable for a student or fresh graduate with little professional experience?",
    "Is this job in a field the candidate wants: web, full-stack, backend, or AI development?",
    "Would this job give a junior person room to learn, with duties that are clear and manageable?",
    "Is this a genuine job posting with clear duties and requirements?",
    "Can this job be done fully remotely by someone living in Nepal?",
    "Does this job require residency or work authorization in a specific country?",
    "Is this job unpaid, volunteer, or commission-only?",
    "Does this job require fluency in a language other than English?",
    "Does this job require working fixed hours in a US or European timezone?",
    "Does this job require 3 or more years of professional experience?",
    "What type of role is this? web_fullstack, frontend, backend, ai_ml, data, mobile, devops, admin_ops, other",
]
question_keys = [
    "skills_match", "seniority_fit", "domain_fit", "growth_fit",
    "is_real_job", "remote_from_nepal", "needs_work_authorization",
    "unpaid_or_commission_only", "requires_other_language",
    "fixed_overlap_hours", "needs_multi_years", "role_type"
]

question_token_total = sum(count_tokens(q) for q in question_texts)
question_keys_total = sum(count_tokens(k) for k in question_keys)

# 3. State JSON structure overhead (field names and syntax)
minimal_state = {
    "title": "Junior Python Developer",
    "company": "KoboToolbox",
    "location": "Remote - Worldwide",
    "candidate_summary": cv_summary,
    "requirements": "",
    "responsibilities": "",
    "nice_to_have": "",
    "company_blurb": ""
}
# Measure tokens of the minimal state keys & title/company/location
minimal_state_tokens = count_tokens(json.dumps(minimal_state))

# 4. Total questions and schema overhead in prompt
total_question_overhead = question_token_total + question_keys_total

# 5. Safety margin
SAFETY_MARGIN = 50

# Total reserved for everything except the job description body
reserved = minimal_state_tokens + total_question_overhead + SAFETY_MARGIN
jd_budget = MAX_MODEL_TOKENS - reserved

print(f"\n{'='*55}")
print(f"       EXACT LAYA TOKEN BUDGET CALCULATION")
print(f"{'='*55}")
print(f"Model Max Limit:                     {MAX_MODEL_TOKENS:>5} tokens")
print(f"State structure + CV summary:        {minimal_state_tokens:>5} tokens")
print(f"  (of which CV summary alone is {cv_tokens} tokens)")
print(f"All 12 Question texts:               {question_token_total:>5} tokens")
print(f"All 12 Question keys:                {question_keys_total:>5} tokens")
print(f"Safety Margin:                       {SAFETY_MARGIN:>5} tokens")
print(f"{'-'*55}")
print(f"Total Reserved:                      {reserved:>5} tokens")
print(f"Available JD Text Budget:            {jd_budget:>5} tokens")
print(f"{'='*55}")

# Save to a budget json file for src/matching/jd_truncator.py to read
budget_info = {
    "max_model_tokens": MAX_MODEL_TOKENS,
    "safety_margin": SAFETY_MARGIN,
    "cv_tokens": cv_tokens,
    "state_overhead_tokens": minimal_state_tokens,
    "questions_overhead_tokens": total_question_overhead,
    "reserved_tokens": reserved,
    "laya_input_token_budget": jd_budget
}

with open(Path(__file__).resolve().parent.parent / "config" / "token_budget.json", "w") as f:
    json.dump(budget_info, f, indent=2)
print("\nWrote budget config to config/token_budget.json")
