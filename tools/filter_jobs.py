#!/usr/bin/env python3
"""
filter_jobs.py — Command-Line Remote Job Filter

USAGE:
    python filter_jobs.py --remote-ok-nepal --tags python,react --min-salary 40000

FLAGS:
    --remote-ok-nepal  Matches Worldwide, Anywhere, APAC, Asia, Nepal, South Asia, Global
                       Excludes specific region locks (USA Only, EU Only, UK Only, etc.)
    --min-salary NUM   Filter jobs with listed annual salary >= NUM (USD)
    --tags TAGS        Comma-separated list of tech tags (e.g. python,react,flutter)
    --keywords TERMS   Comma-separated list of search terms in job title/description

OUTPUT:
    Prints matching jobs as a table in terminal and writes filtered_jobs.json
"""

import os
import sys
import json
import argparse
import re
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.resolve()
JOBS_JSON = TOOLS_DIR / "jobs.json"
FILTERED_JSON = TOOLS_DIR / "filtered_jobs.json"

NEPAL_FRIENDLY_LOCATIONS = ["worldwide", "anywhere", "global", "apac", "asia", "nepal", "south asia", "remote", "all locations", "international"]
RESTRICTED_LOCATIONS = ["usa only", "us only", "eu only", "uk only", "canada only", "us timezones", "latam only"]

def is_nepal_friendly(location_str):
    if not location_str:
        return True
    loc_low = str(location_str).lower().strip()
    
    # Exclude strict region locks
    for restr in RESTRICTED_LOCATIONS:
        if restr in loc_low:
            return False
            
    # Match allowed phrases
    if any(allowed in loc_low for allowed in NEPAL_FRIENDLY_LOCATIONS):
        return True
        
    # Default to true if general location string without strict lock
    if not any(r in loc_low for r in ["only", "timezones"]):
        return True

    return False

def parse_salary_num(sal_str):
    if not sal_str or sal_str == "Not Listed":
        return 0
    nums = [int(n) for n in re.findall(r'\d+', str(sal_str).replace(',', ''))]
    if nums:
        return max(nums)
    return 0

def main():
    parser = argparse.ArgumentParser(description="Filter remote jobs from jobs.json")
    parser.add_argument("--remote-ok-nepal", action="store_true", help="Match global/Nepal remote friendly roles and exclude strict regional locks.")
    parser.add_argument("--min-salary", type=int, default=0, help="Minimum annual salary filter.")
    parser.add_argument("--tags", type=str, default="", help="Comma-separated technology tags (e.g. python,react,flutter).")
    parser.add_argument("--keywords", type=str, default="", help="Comma-separated keyword search terms.")

    args = parser.parse_args()

    if not JOBS_JSON.exists():
        print(f"Error: {JOBS_JSON} not found. Run fetch_jobs.py first.")
        sys.exit(1)

    with open(JOBS_JSON, "r", encoding="utf-8") as f:
        all_jobs = json.load(f)

    print(f"Filtering {len(all_jobs)} total listings...")

    target_tags = [t.strip().lower() for t in args.tags.split(",") if t.strip()]
    target_kw = [k.strip().lower() for k in args.keywords.split(",") if k.strip()]

    matched_jobs = []

    for j in all_jobs:
        loc = j.get("location", "")
        title = j.get("title", "")
        desc = j.get("description", "")
        raw_tags = j.get("tags", [])
        
        tags = []
        if isinstance(raw_tags, list):
            for t in raw_tags:
                if isinstance(t, list):
                    tags.extend([str(x).lower() for x in t])
                elif t:
                    tags.append(str(t).lower())
        elif isinstance(raw_tags, str):
            tags.append(raw_tags.lower())

        sal_str = j.get("salary", "")
        
        # Location check
        if args.remote_ok_nepal:
            if not is_nepal_friendly(loc):
                continue

        # Salary check
        if args.min_salary > 0:
            val = parse_salary_num(sal_str)
            if val < args.min_salary:
                continue

        # Tag check
        if target_tags:
            tag_match = False
            job_text = f"{title} {' '.join(tags)} {desc}".lower()
            if any(t in job_text for t in target_tags):
                tag_match = True
            if not tag_match:
                continue

        # Keyword check
        if target_kw:
            text = f"{title} {desc}".lower()
            if not any(k in text for k in target_kw):
                continue

        matched_jobs.append(j)

    # Output results
    print("\n" + "="*95)
    print(f" {'COMPANY':<22} | {'JOB TITLE':<35} | {'LOCATION':<18} | {'SALARY'}")
    print("="*95)

    for j in matched_jobs[:30]: # print top 30
        comp = str(j.get('company', ''))[:20]
        title = str(j.get('title', ''))[:33]
        loc = str(j.get('location', ''))[:16]
        sal = str(j.get('salary', ''))[:15]
        print(f" {comp:<22} | {title:<35} | {loc:<18} | {sal}")

    print("="*95)
    print(f"Total Matched Jobs: {len(matched_jobs)}")

    with open(FILTERED_JSON, "w", encoding="utf-8") as f:
        json.dump(matched_jobs, f, indent=2, ensure_ascii=False)

    print(f"Filtered results written to {FILTERED_JSON}\n")

if __name__ == "__main__":
    main()
