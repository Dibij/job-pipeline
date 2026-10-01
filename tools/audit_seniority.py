"""Audit seniority detection on 30 sample jobs labeled 'senior'."""
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.enrichment.enricher import SENIOR_TITLE_PATTERNS

def audit_senior_jobs(sample_size: int = 30):
    rows = execute_query("""
        SELECT id, title, company_name, description_text, experience_level
        FROM jobs
        WHERE experience_level = 'senior'
        ORDER BY id
        LIMIT 100;
    """)

    if not rows:
        print("No senior jobs found.")
        return

    # Select 30 representative samples across the list
    step = max(1, len(rows) // sample_size)
    sampled = rows[::step][:sample_size]

    print(f"=== SENIORITY AUDIT: 30 SAMPLE JOBS (Total Senior in DB: 346) ===\n")

    false_positives = 0
    true_positives = 0
    borderline = 0

    results = []

    for i, job in enumerate(sampled, 1):
        title = job["title"] or ""
        desc = job["description_text"] or ""
        
        # Check what triggered it
        title_triggers = []
        for pat in SENIOR_TITLE_PATTERNS:
            m = re.search(pat, title, re.IGNORECASE)
            if m:
                title_triggers.append(m.group(0))

        desc_triggers = []
        m_desc = re.search(r"\b(5\+|6\+|7\+|8\+|10\+)\s*(?:years?|yrs)\b", desc, re.IGNORECASE)
        if m_desc:
            # Get surrounding context (+- 50 chars)
            start = max(0, m_desc.start() - 40)
            end = min(len(desc), m_desc.end() + 40)
            context = desc[start:end].replace("\n", " ").strip()
            desc_triggers.append((m_desc.group(0), context))

        # Classification judgment
        is_title_senior = bool(title_triggers)
        is_desc_senior = bool(desc_triggers)

        category = "UNKNOWN"
        notes = ""

        # Analyze false positives:
        # 1. Company history ("10+ years of experience in market")
        # 2. "manager" in title when it's not a senior software engineering manager
        # 3. Mentioning "senior" in body but title is normal developer
        if not is_title_senior and is_desc_senior:
            # Check if desc trigger is about company or requirements
            context = desc_triggers[0][1].lower()
            if any(term in context for term in ["we have", "company has", "founded", "industry for", "over", "established"]):
                category = "FALSE_POSITIVE"
                notes = "Company history / years in business, not candidate requirement!"
                false_positives += 1
            elif any(term in context for term in ["minimum", "at least", "experience", "qualifications", "required"]):
                category = "TRUE_POSITIVE"
                notes = "Requires 5+ years experience in body"
                true_positives += 1
            else:
                category = "BORDERLINE"
                notes = "Years mentioned in body, context ambiguous"
                borderline += 1
        elif is_title_senior:
            # Look at title triggers
            trig = title_triggers[0].lower()
            if trig in ["manager", "architect", "teamleitung"]:
                if any(role in title.lower() for role in ["account", "sales", "office", "property", "store", "product"]):
                    category = "NON_DEV_SENIOR"
                    notes = f"Non-dev managerial title ('{trig}')"
                    borderline += 1
                else:
                    category = "TRUE_POSITIVE"
                    notes = f"Title contains '{trig}'"
                    true_positives += 1
            else:
                category = "TRUE_POSITIVE"
                notes = f"Title explicitly contains '{trig}'"
                true_positives += 1

        print(f"[{i:02d}] Title: {title}")
        print(f"     Company: {job['company_name']}")
        print(f"     Title Trigger: {title_triggers if title_triggers else 'None'}")
        if desc_triggers:
            for dt, ctx in desc_triggers:
                print(f"     Body Trigger: '{dt}' in context: \"...{ctx}...\"")
        else:
            print(f"     Body Trigger: None")
        print(f"     Audit Assessment: {category} ({notes})")
        print("-" * 75)

    print("\n=== AUDIT SUMMARY ===")
    print(f"Sampled: {len(sampled)}")
    print(f"True Senior Positions: {true_positives} ({true_positives/len(sampled)*100:.1f}%)")
    print(f"False Positives: {false_positives} ({false_positives/len(sampled)*100:.1f}%)")
    print(f"Borderline / Non-Dev Titles: {borderline} ({borderline/len(sampled)*100:.1f}%)")

if __name__ == "__main__":
    audit_senior_jobs(30)
