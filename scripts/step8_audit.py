"""Step 8 comprehensive audit script: TOO_SENIOR audit, consistency check, and rerun.
"""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from sklearn.metrics import roc_auc_score

from src.db.connection import get_connection
from src.matching.hard_filter import (
    apply as hf_apply,
    FilterReason,
    FilterResult,
    BLOCKED_SENIORITY,
    _check_seniority_degree,
)

CSV_PATH = PROJECT_ROOT / "data" / "laya_comparison_all_labeled.csv"


def load_labeled_jobs() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    labeled_ids = [r["job_id"] for r in rows]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, canonical_job_id, title, company_name, location_raw, is_remote,
                       remote_restriction, description_text, detected_language, is_unpaid,
                       accessibility, reachable_from_nepal, reachable_reason
                FROM jobs
                WHERE id::text = ANY(%s)
            """, (labeled_ids,))
            db_jobs = {str(j["id"]): j for j in cur.fetchall()}

    return rows, db_jobs


def audit_too_senior(rows: List[Dict[str, Any]], db_jobs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    # 1. Investigate the 8 specific rows cited in Step 8 prompt:
    # Upgrade, Coalition, Swarmaero, Lemon.io x3, A.Team x2
    target_specs = [
        ("Upgrade", "AI Experience Engineer (Conversational AI)"),
        ("Coalition Technologies", "Freelance Copywriter"),
        ("Swarmaero", "Perception and Fusion Engineer"),
        ("Lemon.io", "Senior AI Engineer"),
        ("Lemon.io", "Senior .NET Full-stack Developer"),
        ("Lemon.io", "Senior React Full-stack Developer"),
        ("A.Team", "Senior Independent AI Engineer / Architect"),
        ("A.Team", "Senior Independent Software Developer"),
    ]

    cited_8_details = []
    for comp, tit in target_specs:
        matching_rows = [
            r for r in rows
            if comp.lower() in r.get("company_name", "").lower()
            and (tit.lower() in r.get("title", "").lower() or r.get("title", "").lower() in tit.lower())
        ]
        if not matching_rows:
            # Try matching company only
            matching_rows = [r for r in rows if comp.lower() in r.get("company_name", "").lower()]

        for r in matching_rows:
            jid = r["job_id"]
            db_j = db_jobs.get(jid, {})
            res = hf_apply(db_j)
            sen_res = _check_seniority_degree(db_j.get("title", ""), db_j.get("description_text", ""))
            
            # Find matched word in title or description
            db_title = db_j.get("title", "")
            csv_title = r.get("title", "")
            desc = db_j.get("description_text", "")

            matched_sen_word = None
            title_context = None
            for w in BLOCKED_SENIORITY:
                m = re.search(r"\b" + re.escape(w) + r"\b", db_title, re.IGNORECASE)
                if m:
                    matched_sen_word = w
                    start = max(0, m.start() - 40)
                    end = min(len(db_title), m.end() + 40)
                    title_context = f"...{db_title[start:end]}... (matched '{m.group()}' at [{m.start()}:{m.end()}])"
                    break

            cited_8_details.append({
                "job_id": jid,
                "company_csv": r.get("company_name"),
                "company_db": db_j.get("company_name"),
                "title_csv": csv_title,
                "title_db": db_title,
                "user_label": r.get("user_label"),
                "hf_passed": res.passed,
                "hf_reason": res.reason.value,
                "hf_detail": res.detail,
                "sen_check_reason": sen_res.reason.value,
                "sen_check_detail": sen_res.detail,
                "matched_sen_word": matched_sen_word,
                "title_context": title_context,
            })

    # 2. Check all 150 labeled titles against BLOCKED_SENIORITY
    # and verify if matched word always appears in title field
    all_title_matches = []
    discrepancies = []

    for r in rows:
        jid = r["job_id"]
        db_j = db_jobs.get(jid, {})
        db_title = db_j.get("title", "")
        csv_title = r.get("title", "")
        res = hf_apply(db_j)

        # Check title against BLOCKED_SENIORITY
        matched_words_db = [
            w for w in BLOCKED_SENIORITY
            if re.search(r"\b" + re.escape(w) + r"\b", db_title, re.IGNORECASE)
        ]
        matched_words_csv = [
            w for w in BLOCKED_SENIORITY
            if re.search(r"\b" + re.escape(w) + r"\b", csv_title, re.IGNORECASE)
        ]

        if res.reason == FilterReason.TOO_SENIOR:
            # Extract word from detail
            m_detail = re.search(r"title contains seniority word: '([^']+)'", res.detail or "")
            word_in_detail = m_detail.group(1) if m_detail else ""

            # Check if word_in_detail appears in db_title
            word_in_db = bool(re.search(r"\b" + re.escape(word_in_detail) + r"\b", db_title, re.IGNORECASE))
            word_in_csv = bool(re.search(r"\b" + re.escape(word_in_detail) + r"\b", csv_title, re.IGNORECASE))

            all_title_matches.append({
                "job_id": jid,
                "user_label": r.get("user_label"),
                "word": word_in_detail,
                "db_title": db_title,
                "csv_title": csv_title,
                "in_db_title": word_in_db,
                "in_csv_title": word_in_csv,
            })

            if not word_in_db:
                discrepancies.append({
                    "job_id": jid,
                    "issue": f"Matched word '{word_in_detail}' not in db_title",
                    "title": db_title,
                })
            if not word_in_csv:
                discrepancies.append({
                    "job_id": jid,
                    "issue": f"Matched word '{word_in_detail}' not in csv_title",
                    "title": csv_title,
                })

    return {
        "cited_8_details": cited_8_details,
        "all_too_senior_count": len(all_title_matches),
        "all_title_matches": all_title_matches,
        "discrepancies": discrepancies,
    }


def audit_consistency(rows: List[Dict[str, Any]], db_jobs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    hifi_r = next((r for r in rows if r["job_id"].startswith("220ca519")), None)
    cardog_r = next((r for r in rows if r["job_id"].startswith("fa31e393")), None)

    # Check HIFI Labs in DB
    hifi_info = {}
    if hifi_r:
        jid = hifi_r["job_id"]
        db_j = db_jobs.get(jid, {})
        res_db = hf_apply(db_j)
        hifi_info = {
            "job_id": jid,
            "csv_title": hifi_r.get("title"),
            "csv_company": hifi_r.get("company_name"),
            "csv_label": hifi_r.get("user_label"),
            "db_title": db_j.get("title"),
            "db_company": db_j.get("company_name"),
            "db_location_raw": db_j.get("location_raw"),
            "db_is_remote": db_j.get("is_remote"),
            "db_reachable_from_nepal": db_j.get("reachable_from_nepal"),
            "db_reachable_reason": db_j.get("reachable_reason"),
            "current_hf_result": {
                "passed": res_db.passed,
                "reason": res_db.reason.value,
                "detail": res_db.detail,
            },
        }

    # Check Cardog in DB
    cardog_info = {}
    if cardog_r:
        jid = cardog_r["job_id"]
        db_j = db_jobs.get(jid, {})
        res_db = hf_apply(db_j)
        cardog_info = {
            "job_id": jid,
            "csv_title": cardog_r.get("title"),
            "csv_company": cardog_r.get("company_name"),
            "csv_label": cardog_r.get("user_label"),
            "db_title": db_j.get("title"),
            "db_company": db_j.get("company_name"),
            "db_location_raw": db_j.get("location_raw"),
            "db_is_remote": db_j.get("is_remote"),
            "db_reachable_from_nepal": db_j.get("reachable_from_nepal"),
            "db_reachable_reason": db_j.get("reachable_reason"),
            "current_hf_result": {
                "passed": res_db.passed,
                "reason": res_db.reason.value,
                "detail": res_db.detail,
            },
        }

    return {
        "hifi": hifi_info,
        "cardog": cardog_info,
    }


def rerun_step7_pool_and_scorers(
    rows: List[Dict[str, Any]],
    db_jobs: Dict[str, Dict[str, Any]],
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> Dict[str, Any]:
    # Evaluate HardFilter fresh on every row
    pool_rows = []
    hf_matrix = defaultdict(lambda: defaultdict(int))

    seen_canonical = set()
    deduped_rows = []
    for r in rows:
        jid = r["job_id"]
        db_j = db_jobs.get(jid)
        cid = str(db_j["canonical_job_id"]) if (db_j and db_j.get("canonical_job_id")) else jid
        if cid not in seen_canonical:
            seen_canonical.add(cid)
            deduped_rows.append(r)

    for r in deduped_rows:
        jid = r["job_id"]
        job_dict = db_jobs.get(jid, {})
        res = hf_apply(job_dict)

        if res.reason == FilterReason.PASS:
            outcome = "PASS"
        elif res.reason == FilterReason.NEEDS_REVIEW:
            outcome = "NEEDS_REVIEW"
        else:
            outcome = f"FAIL:{res.reason.value}"

        ulabel = r["user_label"]
        hf_matrix[outcome][ulabel] += 1

        if res.passed:  # PASS or NEEDS_REVIEW
            pool_rows.append((r, job_dict))

    label_counts = Counter([r["user_label"] for r, _ in pool_rows])
    n_good = label_counts.get("good_fit", 0)
    n_maybe = label_counts.get("maybe", 0)
    n_bad = label_counts.get("bad_fit", 0)

    # Scorer comparison
    y_true = np.array([1 if r["user_label"] == "good_fit" else 0 for r, _ in pool_rows])
    s_match = np.array([float(r.get("match_score") or 0.0) for r, _ in pool_rows])
    s_laya = np.array([float(r.get("laya_score") or 0.0) for r, _ in pool_rows])
    s_head = np.array([float(r.get("head_prob_good") or 0.0) for r, _ in pool_rows])
    companies = np.array([r.get("company_name", "") for r, _ in pool_rows])

    auc_match = float(roc_auc_score(y_true, s_match))
    auc_laya = float(roc_auc_score(y_true, s_laya))
    auc_head = float(roc_auc_score(y_true, s_head))

    # Bootstrap grouped by company
    rng = np.random.RandomState(seed)
    unique_cos = np.unique(companies)
    co_to_idx = {c: np.where(companies == c)[0] for c in unique_cos}

    boot_match, boot_laya, boot_head = [], [], []
    for _ in range(n_bootstrap):
        sampled_cos = rng.choice(unique_cos, size=len(unique_cos), replace=True)
        sampled_indices = np.concatenate([co_to_idx[c] for c in sampled_cos])
        b_y = y_true[sampled_indices]
        if len(np.unique(b_y)) < 2 or np.sum(b_y) < 2:
            continue
        boot_match.append(roc_auc_score(b_y, s_match[sampled_indices]))
        boot_laya.append(roc_auc_score(b_y, s_laya[sampled_indices]))
        boot_head.append(roc_auc_score(b_y, s_head[sampled_indices]))

    ci_match = (float(np.percentile(boot_match, 2.5)), float(np.percentile(boot_match, 97.5)))
    ci_laya = (float(np.percentile(boot_laya, 2.5)), float(np.percentile(boot_laya, 97.5)))
    ci_head = (float(np.percentile(boot_head, 2.5)), float(np.percentile(boot_head, 97.5)))

    return {
        "deduped_total": len(deduped_rows),
        "hf_matrix": dict(hf_matrix),
        "pool_size": len(pool_rows),
        "label_counts": {"good_fit": n_good, "maybe": n_maybe, "bad_fit": n_bad},
        "auc_match": auc_match,
        "ci_match": ci_match,
        "auc_laya": auc_laya,
        "ci_laya": ci_laya,
        "auc_head": auc_head,
        "ci_head": ci_head,
    }


def main():
    rows, db_jobs = load_labeled_jobs()

    # Part A
    part_a = audit_too_senior(rows, db_jobs)
    print("=" * 80)
    print("PART A: TOO_SENIOR AUDIT")
    print("=" * 80)
    print("\n1. Specific Audit of the 8 Rows Cited in Step 8:")
    for item in part_a["cited_8_details"]:
        print(f"\n- Company: {item['company_csv']} (DB: {item['company_db']})")
        print(f"  Job ID: {item['job_id']}")
        print(f"  CSV Title: {item['title_csv']!r}")
        print(f"  DB Title seen by filter: {item['title_db']!r}")
        print(f"  User Label: {item['user_label']}")
        print(f"  Overall HardFilter: passed={item['hf_passed']}, reason={item['hf_reason']} ({item['hf_detail']})")
        print(f"  _check_seniority_degree result: reason={item['sen_check_reason']} ({item['sen_check_detail']})")
        print(f"  Seniority word matched: {item['matched_sen_word']}")
        print(f"  Context in title: {item['title_context']}")

    print(f"\n2. Audit of all 150 labeled titles:")
    print(f"  Total rows failing TOO_SENIOR in current DB: {part_a['all_too_senior_count']}")
    print(f"  Discrepancies where matched word does NOT appear in title field: {len(part_a['discrepancies'])}")
    for d in part_a["discrepancies"]:
        print(f"    DISCREPANCY: {d}")

    # Part B
    part_b = audit_consistency(rows, db_jobs)
    print("\n" + "=" * 80)
    print("PART B: CONSISTENCY AUDIT (HIFI Labs & Cardog)")
    print("=" * 80)
    print("\nHIFI Labs:")
    print(json.dumps(part_b["hifi"], indent=2))
    print("\nCardog:")
    print(json.dumps(part_b["cardog"], indent=2))

    # Part C
    part_c = rerun_step7_pool_and_scorers(rows, db_jobs)
    print("\n" + "=" * 80)
    print("PART C: RERUN STEP 7 POOL AND SCORER TABLE AFTER FIXING NOTHING")
    print("=" * 80)
    print(f"De-duplicated total rows: {part_c['deduped_total']}")
    print(f"Post-HardFilter Pool Size: {part_c['pool_size']}")
    print(f"Label breakdown: {part_c['label_counts']}")
    print("\nMatrix:")
    for outcome, counts in sorted(part_c["hf_matrix"].items()):
        print(f"  {outcome:<25}: good={counts.get('good_fit', 0):<2} maybe={counts.get('maybe', 0):<2} bad={counts.get('bad_fit', 0):<2} Total={sum(counts.values())}")
    print("\nScorer Comparison:")
    print(f"  MatchScorer:  AUC = {part_c['auc_match']:.4f} [95% CI: {part_c['ci_match'][0]:.4f}, {part_c['ci_match'][1]:.4f}]")
    print(f"  LayaScorer:   AUC = {part_c['auc_laya']:.4f} [95% CI: {part_c['ci_laya'][0]:.4f}, {part_c['ci_laya'][1]:.4f}]")
    print(f"  Head v2:      AUC = {part_c['auc_head']:.4f} [95% CI: {part_c['ci_head'][0]:.4f}, {part_c['ci_head'][1]:.4f}] (in-sample)")


if __name__ == "__main__":
    main()
