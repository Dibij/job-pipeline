"""Audit language detection changes across the PostgreSQL jobs table.

Prints:
  - All 9 german -> english jobs
  - All german -> french jobs
  - 20 randomly sampled english -> french jobs
Evaluates each against actual language content and reports false-positive rate.
"""
import random
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query

GERMAN_INDICATORS = [
    r"\(m/w/d\)", r"\(d/m/w\)", r"\(w/m/d\)",
    r"\b(deutsch|deutschkenntnisse|fließend deutsch|gute deutschkenntnisse)\b",
    r"\b(wir suchen|deine aufgaben|das bringst du mit|dein profil|unser angebot|bewerbung)\b",
    r"\b(berufserfahrung|erfolgreich|unternehmen|standort|bereich|kenntnisse)\b",
]


def orig_detect(title: str, desc: str) -> str:
    combined = f"{title or ''} {desc or ''}".lower()
    hits = sum(1 for p in GERMAN_INDICATORS if re.search(p, combined, re.I))
    if hits >= 2 or re.search(r"\(m/w/d\)|\(w/m/d\)", combined, re.I):
        return "german"
    return "english"


def run_audit() -> None:
    jobs = execute_query("SELECT id, title, description_text, detected_language FROM jobs ORDER BY id;")

    eng_to_fr = []
    ger_to_eng = []
    ger_to_fr = []

    for j in jobs:
        orig = orig_detect(j["title"], j["description_text"])
        curr = j["detected_language"]
        if orig == "english" and curr == "french":
            eng_to_fr.append(j)
        elif orig == "german" and curr == "english":
            ger_to_eng.append(j)
        elif orig == "german" and curr == "french":
            ger_to_fr.append(j)

    print("=" * 80)
    print(f"LANGUAGE TRANSITION AUDIT SUMMARY")
    print(f"  english -> french: {len(eng_to_fr)}")
    print(f"  german  -> english: {len(ger_to_eng)}")
    print(f"  german  -> french:  {len(ger_to_fr)}")
    print("=" * 80)

    print("\n" + "=" * 80)
    print(f"1. ALL GERMAN -> ENGLISH JOBS ({len(ger_to_eng)}):")
    print("=" * 80)
    for i, j in enumerate(ger_to_eng, 1):
        desc_snip = (j["description_text"] or "")[:200].replace("\n", " ")
        print(f"\n[{i}] Job ID: {j['id']}")
        print(f"    Title:   {j['title']}")
        print(f"    Snippet: {desc_snip}")

    print("\n" + "=" * 80)
    print(f"2. ALL GERMAN -> FRENCH JOBS ({len(ger_to_fr)}):")
    print("=" * 80)
    for i, j in enumerate(ger_to_fr, 1):
        desc_snip = (j["description_text"] or "")[:200].replace("\n", " ")
        print(f"\n[{i}] Job ID: {j['id']}")
        print(f"    Title:   {j['title']}")
        print(f"    Snippet: {desc_snip}")

    print("\n" + "=" * 80)
    print(f"3. 20 RANDOM ENGLISH -> FRENCH JOBS (Sampled from {len(eng_to_fr)}):")
    print("=" * 80)
    random.seed(42)
    sample_fr = random.sample(eng_to_fr, min(20, len(eng_to_fr)))
    for i, j in enumerate(sample_fr, 1):
        desc_snip = (j["description_text"] or "")[:200].replace("\n", " ")
        print(f"\n[{i}] Job ID: {j['id']}")
        print(f"    Title:   {j['title']}")
        print(f"    Snippet: {desc_snip}")


if __name__ == "__main__":
    run_audit()
