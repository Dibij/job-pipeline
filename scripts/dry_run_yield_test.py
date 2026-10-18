"""Task: Dry-run yield test across 10 ATS company boards (no DB writes).

Boards tested:
  Greenhouse: gitlab, givedirectly
  Lever: curai, peerspace
  Ashby: openai, elevenlabs, supabase, omnea, runway-ml, duck-duck-go

Usage:
    python scripts/dry_run_yield_test.py
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.enrichment.enricher import JobEnricher
from src.matching.hard_filter import apply as hard_filter_job
from src.matching.scorer import MatchScorer
from src.models.transformers import clean_description_text

CACHE_DIR = PROJECT_ROOT / "data" / "cache_ats_dry_run"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
}

BOARDS = [
    # (board_slug, platform)
    ("gitlab", "greenhouse"),
    ("openai", "ashby"),
    ("elevenlabs", "ashby"),
    ("supabase", "ashby"),
    ("omnea", "ashby"),
    ("runway-ml", "ashby"),
    ("duck-duck-go", "ashby"),
    ("curai", "lever"),
    ("peerspace", "lever"),
    ("givedirectly", "greenhouse"),
]


def fetch_board_data(board: str, platform: str) -> Tuple[int, List[Dict[str, Any]]]:
    """Fetch board listings with caching and 1-2s politeness delay."""
    cache_file = CACHE_DIR / f"{board}_{platform}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return 200, data
        except Exception:
            pass

    time.sleep(1.2)  # 1-2s delay

    if platform == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code == 200:
            items = r.json().get("jobs", [])
            cache_file.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            return 200, items
        return r.status_code, []

    elif platform == "lever":
        url = f"https://api.lever.co/v0/postings/{board}?mode=json"
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code == 200 and isinstance(r.json(), list):
            items = r.json()
            cache_file.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            return 200, items
        return r.status_code, []

    elif platform == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code == 200:
            items = r.json().get("jobs", [])
            cache_file.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            return 200, items
        return r.status_code, []

    return 404, []


def normalize_item(item: Dict[str, Any], platform: str, company_name: str) -> Dict[str, Any]:
    """Convert raw ATS item into in-memory job dict for HardFilter and MatchScorer."""
    if platform == "greenhouse":
        title = item.get("title", "Untitled")
        loc_obj = item.get("location") or {}
        location_raw = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
        content_html = item.get("content", "")
        desc_clean = clean_description_text(content_html) if content_html else title
        is_remote = any(k in location_raw.lower() for k in ["remote", "anywhere", "virtual", "distributed"]) or "remote" in title.lower()

    elif platform == "lever":
        title = item.get("text", "Untitled")
        cats = item.get("categories") or {}
        location_raw = cats.get("location", "")
        workplace_type = str(item.get("workplaceType", "")).lower()
        content_html = (item.get("description", "") or "") + " " + (item.get("additional", "") or "")
        desc_clean = clean_description_text(content_html) if content_html.strip() else (item.get("descriptionPlain", "") or title)
        is_remote = (workplace_type == "remote") or ("remote" in location_raw.lower()) or ("remote" in title.lower())

    elif platform == "ashby":
        title = item.get("title", "Untitled")
        location_raw = item.get("location", "")
        workplace_type = str(item.get("workplaceType", "")).lower()
        content_html = item.get("descriptionHtml", "")
        desc_clean = clean_description_text(content_html) if content_html else (item.get("descriptionPlain", "") or title)
        is_remote = bool(item.get("isRemote", False)) or (workplace_type == "remote") or ("remote" in location_raw.lower()) or ("remote" in title.lower())

    else:
        title = "Untitled"
        location_raw = ""
        desc_clean = ""
        is_remote = False

    job_dict = {
        "id": item.get("id", ""),
        "title": title,
        "company_name": company_name,
        "location_raw": location_raw,
        "remote_restriction": location_raw or "unspecified",
        "is_remote": is_remote,
        "description_text": desc_clean,
        "job_type": "full-time",
    }

    # Enrich in memory
    enrichment = JobEnricher.enrich_job(job_dict)
    job_dict.update(enrichment)
    return job_dict


def run_dry_run_test():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n" + "=" * 115)
    print("  ATS BOARDS DRY-RUN YIELD TEST (No DB writes)")
    print("=" * 115)
    print(f"  {'Board':<16} {'Platform':<12} {'Jobs':>6} {'PassedHF':>10} {'Scored>=60':>11} {'Yield':>8} | {'Top Rejection Reasons'}")
    print("  " + "-" * 113)

    scorer = MatchScorer()

    board_stats = []

    for board, platform in BOARDS:
        status, items = fetch_board_data(board, platform)
        if status != 200:
            print(f"  {board:<16} {platform:<12} [HTTP {status} - Board not found]")
            board_stats.append({
                "board": board, "platform": platform, "total": 0, "passed_hf": 0,
                "scored_60": 0, "yield_pct": 0.0, "status": status
            })
            continue

        total_jobs = len(items)
        passed_hf_count = 0
        scored_60_count = 0
        rejection_counts = {}

        for raw in items:
            job = normalize_item(raw, platform, board)
            hf_result = hard_filter_job(job)
            if not hf_result.passed:
                code = hf_result.reason.value
                rejection_counts[code] = rejection_counts.get(code, 0) + 1
                continue

            passed_hf_count += 1
            score, matched_skills, missing_skills, breakdown = scorer.score_job(job)
            flags = breakdown.get("flags", [])

            if "PLACEHOLDER" in flags:
                code = "PLACEHOLDER"
                rejection_counts[code] = rejection_counts.get(code, 0) + 1
            elif "NO_TECH_SIGNAL" in flags:
                code = "NO_TECH_SIGNAL"
                rejection_counts[code] = rejection_counts.get(code, 0) + 1
            elif "SENIOR" in flags:
                code = "SENIOR"
                rejection_counts[code] = rejection_counts.get(code, 0) + 1
            elif score < 60.0:
                code = "SCORE<60"
                rejection_counts[code] = rejection_counts.get(code, 0) + 1
            else:
                scored_60_count += 1

        yield_pct = (scored_60_count / total_jobs * 100) if total_jobs else 0.0

        top_rejections = sorted(rejection_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        rej_str = ", ".join(f"{k}: {v}" for k, v in top_rejections) if top_rejections else "None"

        print(f"  {board:<16} {platform:<12} {total_jobs:>6,} {passed_hf_count:>10,} {scored_60_count:>11,} {yield_pct:>7.2f}% | {rej_str}")

        board_stats.append({
            "board": board,
            "platform": platform,
            "total": total_jobs,
            "passed_hf": passed_hf_count,
            "scored_60": scored_60_count,
            "yield_pct": yield_pct,
            "status": 200,
            "top_rejections": top_rejections,
        })

    print("  " + "-" * 113)
    tot_jobs = sum(b["total"] for b in board_stats)
    tot_hf = sum(b["passed_hf"] for b in board_stats)
    tot_60 = sum(b["scored_60"] for b in board_stats)
    tot_yield = (tot_60 / tot_jobs * 100) if tot_jobs else 0.0
    print(f"  {'TOTAL':<16} {'':<12} {tot_jobs:>6,} {tot_hf:>10,} {tot_60:>11,} {tot_yield:>7.2f}% |")
    print("=" * 115 + "\n")

    # Check boards beating 2%
    beating_2pct = [b for b in board_stats if b["yield_pct"] >= 2.0]
    print("--- BOARDS BEATING 2% YIELD ---")
    if beating_2pct:
        for b in beating_2pct:
            print(f"  * {b['board']} ({b['platform']}): {b['yield_pct']:.2f}% yield ({b['scored_60']}/{b['total']} jobs)")
    else:
        print("  None of the tested boards beat 2% yield.")


if __name__ == "__main__":
    run_dry_run_test()
