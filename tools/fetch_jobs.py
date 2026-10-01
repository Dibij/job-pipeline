#!/usr/bin/env python3
"""
fetch_jobs.py — Multi-Source Remote Job Collector

SUMMARY:
    Pulls fresh remote job listings from public APIs and RSS feeds that explicitly
    allow programmatic access. 
    
COMPLIANCE & TERMS OF SERVICE NOTE:
    Sites like LinkedIn, Indeed, Glassdoor, and ZipRecruiter are DELIBERATELY OMITTED.
    Scraping those platforms violates their Terms of Service (ToS) and risks IP/account
    bans. We strictly use public REST APIs and official RSS feeds provided by remote-first
    job boards.

INCLUDED SOURCES:
    1. Remotive API        (https://remotive.com/api/remote-jobs)
    2. Jobicy API          (https://jobicy.com/api/v2/remote-jobs)
    3. Arbeitnow API       (https://www.arbeitnow.com/api/job-board-api)
    4. RemoteOK API        (https://remoteok.com/api)
    5. WeWorkRemotely RSS  (https://weworkremotely.com/remote-jobs.rss)

OUTPUT:
    Saves deduplicated job listings to D:\\Code\\Job\\tools\\jobs.json
"""

import os
import sys
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.resolve()
JOBS_JSON = TOOLS_DIR / "jobs.json"

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RemoteJobCollector/1.0"

def clean_html(raw_html):
    if not raw_html:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', str(raw_html))
    return ' '.join(clean.split())

def extract_email(text):
    if not text:
        return ""
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    if emails:
        valid = [e for e in emails if not any(x in e.lower() for x in ["example", "sentry", "domain", "schema", "w3.org"])]
        if valid:
            return valid[0]
    return ""

def fetch_remotive():
    print("Fetching from Remotive API...")
    url = "https://remotive.com/api/remote-jobs?limit=150"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for item in data.get("jobs", []):
                title = item.get("title", "")
                company = item.get("company_name", "")
                url_link = item.get("url", "")
                location = item.get("candidate_required_location", "Worldwide")
                desc = clean_html(item.get("description", ""))
                salary = item.get("salary", "")
                tags = item.get("tags", [])
                cat = item.get("category", "")
                if cat and cat not in tags:
                    tags.append(cat)

                jobs.append({
                    "id": f"remotive_{item.get('id', url_link)}",
                    "source": "Remotive",
                    "company": company,
                    "title": title,
                    "location": location if location else "Worldwide",
                    "salary": salary if salary else "Not Listed",
                    "tags": tags,
                    "url": url_link,
                    "email": extract_email(desc),
                    "description": desc,
                    "fetched_at": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"  Error fetching Remotive: {e}")
    return jobs

def fetch_jobicy():
    print("Fetching from Jobicy API...")
    url = "https://jobicy.com/api/v2/remote-jobs?count=100"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for item in data.get("jobs", []):
                title = item.get("jobTitle", "")
                company = item.get("companyName", "")
                url_link = item.get("url", "")
                location = item.get("jobGeo", "Worldwide")
                desc = clean_html(item.get("jobDescription", ""))
                salary = item.get("annualSalaryMin", "")
                salary_max = item.get("annualSalaryMax", "")
                currency = item.get("salaryCurrency", "USD")
                
                sal_str = "Not Listed"
                if salary and salary_max:
                    sal_str = f"{currency} {salary} - {salary_max}"
                elif salary:
                    sal_str = f"{currency} {salary}"

                tags = []
                if item.get("jobCategory"):
                    tags.append(item.get("jobCategory"))
                if item.get("jobType"):
                    tags.append(item.get("jobType"))

                jobs.append({
                    "id": f"jobicy_{item.get('id', url_link)}",
                    "source": "Jobicy",
                    "company": company,
                    "title": title,
                    "location": location if location else "Worldwide",
                    "salary": sal_str,
                    "tags": tags,
                    "url": url_link,
                    "email": extract_email(desc),
                    "description": desc,
                    "fetched_at": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"  Error fetching Jobicy: {e}")
    return jobs

def fetch_arbeitnow():
    print("Fetching from Arbeitnow API...")
    url = "https://www.arbeitnow.com/api/job-board-api"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for item in data.get("data", []):
                if not item.get("remote", True):
                    continue
                title = item.get("title", "")
                company = item.get("company_name", "")
                url_link = item.get("url", "")
                location = item.get("location", "Remote")
                desc = clean_html(item.get("description", ""))
                tags = item.get("tags", [])

                jobs.append({
                    "id": f"arbeitnow_{url_link}",
                    "source": "Arbeitnow",
                    "company": company,
                    "title": title,
                    "location": location if location else "Worldwide",
                    "salary": "Not Listed",
                    "tags": tags,
                    "url": url_link,
                    "email": extract_email(desc),
                    "description": desc,
                    "fetched_at": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"  Error fetching Arbeitnow: {e}")
    return jobs

def fetch_remoteok():
    print("Fetching from RemoteOK API...")
    url = "https://remoteok.com/api"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for item in data:
                if not isinstance(item, dict) or not item.get("position"):
                    continue
                title = item.get("position", "")
                company = item.get("company", "")
                url_link = item.get("url", "")
                location = item.get("location", "Worldwide")
                desc = clean_html(item.get("description", ""))
                tags = item.get("tags", [])
                
                salary_min = item.get("salary_min", "")
                salary_max = item.get("salary_max", "")
                sal_str = "Not Listed"
                if salary_min or salary_max:
                    sal_str = f"${salary_min} - ${salary_max}"

                jobs.append({
                    "id": f"remoteok_{item.get('id', url_link)}",
                    "source": "RemoteOK",
                    "company": company,
                    "title": title,
                    "location": location if location else "Worldwide",
                    "salary": sal_str,
                    "tags": tags,
                    "url": url_link,
                    "email": extract_email(desc),
                    "description": desc,
                    "fetched_at": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"  Error fetching RemoteOK: {e}")
    return jobs

def fetch_weworkremotely():
    print("Fetching from WeWorkRemotely RSS...")
    url = "https://weworkremotely.com/remote-jobs.rss"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for item in root.findall("./channel/item"):
                title_text = item.findtext("title", "")
                url_link = item.findtext("link", "")
                desc = clean_html(item.findtext("description", ""))
                category = item.findtext("category", "")
                
                parts = title_text.split(" is hiring a ")
                if len(parts) == 2:
                    company = parts[0].strip()
                    title = parts[1].strip()
                else:
                    company = "WeWorkRemotely Posting"
                    title = title_text

                jobs.append({
                    "id": f"wwr_{url_link}",
                    "source": "WeWorkRemotely",
                    "company": company,
                    "title": title,
                    "location": "Worldwide",
                    "salary": "Not Listed",
                    "tags": [category] if category else [],
                    "url": url_link,
                    "email": extract_email(desc),
                    "description": desc,
                    "fetched_at": datetime.now().isoformat()
                })
    except Exception as e:
        print(f"  Error fetching WeWorkRemotely: {e}")
    return jobs

def main():
    print("==================================================")
    print("      MULTI-SOURCE REMOTE JOB FETCHING TOOL      ")
    print("==================================================")
    
    existing_jobs = {}
    if JOBS_JSON.exists():
        try:
            with open(JOBS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                for j in data:
                    existing_jobs[j["url"]] = j
            print(f"Loaded {len(existing_jobs)} existing jobs from jobs.json.")
        except Exception as e:
            print(f"Could not load existing jobs.json: {e}")

    fetched_list = []
    fetched_list.extend(fetch_remotive())
    fetched_list.extend(fetch_jobicy())
    fetched_list.extend(fetch_arbeitnow())
    fetched_list.extend(fetch_remoteok())
    fetched_list.extend(fetch_weworkremotely())

    print(f"\nFetched {len(fetched_list)} raw listings total.")

    new_count = 0
    updated_count = 0

    for j in fetched_list:
        url = j["url"]
        if not url:
            continue
        if url not in existing_jobs:
            existing_jobs[url] = j
            new_count += 1
        else:
            # update listing
            existing_jobs[url].update(j)
            updated_count += 1

    final_jobs = list(existing_jobs.values())

    with open(JOBS_JSON, "w", encoding="utf-8") as f:
        json.dump(final_jobs, f, indent=2, ensure_ascii=False)

    print("\n--------------------------------------------------")
    print(f"SUCCESS: Total unique jobs saved in jobs.json: {len(final_jobs)}")
    print(f"New added: {new_count} | Updated: {updated_count}")
    print("--------------------------------------------------")

if __name__ == "__main__":
    main()
