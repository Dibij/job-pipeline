import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.enrichment.enricher import SENIOR_TITLE_PATTERNS

rows = execute_query("SELECT id, title, description_text FROM jobs WHERE experience_level = 'senior';")

title_hit = 0
body_only_hit = 0
body_only_samples = []

for r in rows:
    title = r["title"] or ""
    desc = r["description_text"] or ""

    has_title = any(re.search(pat, title, re.IGNORECASE) for pat in SENIOR_TITLE_PATTERNS)
    if has_title:
        title_hit += 1
    else:
        body_only_hit += 1
        m = re.search(r"\b(5\+|6\+|7\+|8\+|10\+)\s*(?:years?|yrs)\b", desc, re.IGNORECASE)
        context = ""
        if m:
            start = max(0, m.start() - 40)
            end = min(len(desc), m.end() + 40)
            context = desc[start:end].replace("\n", " ").strip()
        body_only_samples.append((title, m.group(0) if m else "N/A", context))

print(f"Total senior jobs in DB: {len(rows)}")
print(f"Triggered by Title keyword: {title_hit}")
print(f"Triggered SOLELY by Body regex (no senior keyword in title): {body_only_hit}")
print("\n--- Samples of Body-Only Senior Triggers ---")
for title, trig, ctx in body_only_samples[:15]:
    safe_title = title.encode('ascii', 'replace').decode('ascii')
    safe_ctx = ctx.encode('ascii', 'replace').decode('ascii')
    print(f"Title: {safe_title}")
    print(f"  Trigger: '{trig}' in: \"...{safe_ctx}...\"")
    print()
