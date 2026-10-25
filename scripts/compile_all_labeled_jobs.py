"""Compile all labeled jobs into master dataset with MatchScorer, Laya, Head v2, and HardFilter.

Evaluates any unlabeled/unscored jobs with Laya on GPU, records scores in laya_job_scores,
and writes the complete comparative dataset (296 unique labeled jobs) to:
  - data/laya_comparison_all_labeled.csv
  - data/laya_comparison_all_labeled.json
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Set
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection, execute_query
from src.matching.laya_scorer import LayaScorer, LayaScoreResult
from src.matching.hard_filter import apply as hard_filter_apply, FilterReason
from scripts.train_laya import LayaDecisionHead, REV_LABEL_MAP
from laya.shortlist import embed_fn_from_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
INITIAL_CSV_PATH = DATA_DIR / "laya_comparison_all_labeled.csv"


def get_initial_150_ids() -> Set[str]:
    """Get the job IDs that were part of the initial 150-job Head v2 evaluation/training set."""
    if not INITIAL_CSV_PATH.exists():
        return set()
    with open(INITIAL_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {r["job_id"] for r in reader if "job_id" in r}


def compile_labeled_jobs():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Compiling all labeled jobs on device=%s...", device)

    initial_150_ids = get_initial_150_ids()
    logger.info("Found %d jobs in previous initial 150-job comparison set.", len(initial_150_ids))

    # 1. Fetch latest distinct label per job
    query = """
        SELECT 
            j.id, j.title, j.company_name, j.location_raw, j.is_remote,
            j.remote_restriction, j.detected_language, j.is_unpaid,
            j.accessibility, j.reachable_from_nepal, j.reachable_reason,
            j.description_text, j.apply_url, j.company_url,
            COALESCE(m.match_score, 0.0) as match_score,
            COALESCE(m.matched_skills, '{}') as matched_skills,
            m.reason_code as match_reason,
            lbl.label as user_label,
            lbl.notes as user_notes,
            lbl.sampling_stratum,
            lbl.label_guideline_version,
            lbl.labeled_at,
            lbl.metadata as user_metadata,
            js.final_score as existing_laya_score,
            js.is_passed as existing_laya_passed,
            js.disqualification_reason as existing_laya_disqualify_reason,
            js.role_type as existing_laya_role,
            js.gate_warnings as existing_gate_warnings
        FROM (
            SELECT DISTINCT ON (job_id) job_id, label, notes, sampling_stratum,
                                        label_guideline_version, metadata, labeled_at
            FROM laya_labels
            ORDER BY job_id, labeled_at DESC
        ) lbl
        JOIN jobs j ON lbl.job_id = j.id
        LEFT JOIN job_matches m ON (m.job_id = j.id OR m.job_id = j.canonical_job_id)
        LEFT JOIN laya_job_scores js ON (
            j.id = js.job_id AND js.laya_checkpoint = 'convaiinnovations/laya' AND js.config_version = 'v2'
        )
        ORDER BY lbl.label ASC, m.match_score DESC NULLS LAST, j.title;
    """
    rows = execute_query(query)
    total_jobs = len(rows)
    logger.info("Found %d unique labeled jobs in database.", total_jobs)

    # 2. Check how many need Laya scoring
    needs_laya = [r for r in rows if r.get("existing_laya_score") is None]
    logger.info("%d jobs already have Laya scores; %d jobs need Laya evaluation.",
                total_jobs - len(needs_laya), len(needs_laya))

    # 3. Load LayaScorer and Decision Head v2
    logger.info("Initializing LayaScorer...")
    scorer = LayaScorer(device=device)

    head_ckpt = PROJECT_ROOT / "models" / "laya_head_v2" / "head_weights.pt"
    head = None
    if head_ckpt.exists():
        head = LayaDecisionHead(in_features=1024, num_classes=3).to(device)
        head.load_state_dict(torch.load(head_ckpt, map_location=device, weights_only=True))
        head.eval()
        logger.info("Loaded trained Decision Head v2 from: %s", head_ckpt.name)
    else:
        logger.warning("Decision Head v2 checkpoint not found!")

    embed_fn = embed_fn_from_agent(scorer.agent, max_length=512, batch_size=16)

    # 4. Process all rows
    records = []
    logger.info("Processing and scoring jobs...")

    for idx, r in enumerate(rows, 1):
        jid = str(r["id"])
        title = r["title"] or "Untitled"
        company = r["company_name"] or "Unknown"

        if idx % 25 == 0 or idx == total_jobs:
            logger.info("Progress: [%d/%d] (%.1f%%) — %s (%s)",
                        idx, total_jobs, (idx / total_jobs) * 100, title[:30], company[:20])

        # A. LayaScorer evaluation (use existing or compute fresh)
        if r.get("existing_laya_score") is not None:
            laya_score = float(r["existing_laya_score"])
            laya_passed = bool(r["existing_laya_passed"])
            laya_role = r["existing_laya_role"] or "unknown"
            laya_disqualify = r["existing_laya_disqualify_reason"] or ""
            raw_gate_warn = r["existing_gate_warnings"]
            if isinstance(raw_gate_warn, str):
                try:
                    gate_warnings = json.loads(raw_gate_warn)
                except Exception:
                    gate_warnings = [raw_gate_warn] if raw_gate_warn else []
            elif isinstance(raw_gate_warn, list):
                gate_warnings = raw_gate_warn
            else:
                gate_warnings = []
        else:
            job_dict = {
                "id": jid,
                "title": title,
                "company_name": company,
                "location_raw": r["location_raw"] or "",
                "description_text": r["description_text"] or "",
            }
            res: LayaResult = scorer.score_job(job_dict)
            laya_score = round(res.final_score, 2)
            laya_passed = res.is_passed
            laya_role = res.role_type
            laya_disqualify = res.disqualification_reason or ""
            gate_warnings = res.gate_warnings

            # Save newly computed score to DB
            now = datetime.now(timezone.utc)
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO laya_job_scores
                            (job_id, final_score, is_passed, disqualification_reason,
                             needs_review, role_type, gate_warnings, per_question_data,
                             laya_checkpoint, config_version, tokens_used, scored_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (job_id, laya_checkpoint, config_version) DO UPDATE SET
                            final_score = EXCLUDED.final_score,
                            is_passed = EXCLUDED.is_passed,
                            disqualification_reason = EXCLUDED.disqualification_reason,
                            needs_review = EXCLUDED.needs_review,
                            role_type = EXCLUDED.role_type,
                            gate_warnings = EXCLUDED.gate_warnings,
                            tokens_used = EXCLUDED.tokens_used,
                            scored_at = EXCLUDED.scored_at;
                    """, (
                        jid,
                        res.final_score,
                        res.is_passed,
                        res.disqualification_reason,
                        res.needs_review,
                        res.role_type,
                        json.dumps(res.gate_warnings),
                        json.dumps({k: v.__dict__ for k, v in res.questions.items()}),
                        "convaiinnovations/laya",
                        "v2",
                        res.tokens_used,
                        now
                    ))
                conn.commit()

        # B. Decision Head v2 prediction
        pred_class = "unknown"
        p_bad, p_maybe, p_good = 0.0, 0.0, 0.0
        if head is not None:
            text = f"Title: {title}\nCompany: {company}\n\n{(r['description_text'] or '')[:1500]}"
            emb = embed_fn([text])
            with torch.no_grad():
                logits = head(torch.tensor(emb, dtype=torch.float32).to(device))
                probs = torch.softmax(logits, dim=-1).cpu().numpy()[0]
                pred_class = REV_LABEL_MAP[int(probs.argmax())]
                p_bad, p_maybe, p_good = float(probs[0]), float(probs[1]), float(probs[2])

        # C. HardFilter evaluation
        hf_res = hard_filter_apply(r)
        hf_status = "PASS" if hf_res.reason == FilterReason.PASS else ("NEEDS_REVIEW" if hf_res.reason == FilterReason.NEEDS_REVIEW else f"FAIL:{hf_res.reason.value}")

        # D. Training set membership
        in_training_eval = jid in initial_150_ids

        skills = r.get("matched_skills")
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except Exception:
                skills = [skills] if skills else []
        skills_str = ", ".join(skills) if isinstance(skills, list) else str(skills)

        records.append({
            "job_id": jid,
            "title": title,
            "company_name": company,
            "location": r["location_raw"] or "",
            "is_remote": bool(r["is_remote"]),
            "reachability": r.get("reachable_from_nepal") or "unknown",
            "apply_url": r.get("apply_url") or r.get("company_url") or "",
            "user_label": r["user_label"],
            "user_notes": r["user_notes"] or "",
            "sampling_stratum": r.get("sampling_stratum") or "",
            "label_guideline_version": r.get("label_guideline_version") or "",
            "match_score": round(float(r["match_score"] or 0.0), 1),
            "matched_skills": skills_str,
            "laya_score": round(laya_score, 2),
            "laya_role": laya_role,
            "laya_passed": laya_passed,
            "laya_disqualify_reason": laya_disqualify,
            "laya_head_v2_pred": pred_class,
            "head_prob_good": round(p_good, 4),
            "head_prob_maybe": round(p_maybe, 4),
            "head_prob_bad": round(p_bad, 4),
            "hard_filter_status": hf_status,
            "hard_filter_detail": hf_res.detail,
            "used_in_head_v2_eval": in_training_eval,
            "gate_warnings": "; ".join(gate_warnings) if isinstance(gate_warnings, list) else str(gate_warnings),
        })

    # 5. Save backup copy and overwrite master comparison files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_csv = DATA_DIR / f"laya_comparison_all_labeled_{timestamp}.csv"
    master_csv = DATA_DIR / "laya_comparison_all_labeled.csv"
    backup_json = DATA_DIR / f"laya_comparison_all_labeled_{timestamp}.json"
    master_json = DATA_DIR / "laya_comparison_all_labeled.json"

    headers = list(records[0].keys())
    for target in (backup_csv, master_csv):
        with open(target, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(records)

    for target in (backup_json, master_json):
        with open(target, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)

    logger.info("Successfully compiled %d labeled jobs!", len(records))
    logger.info("Master CSV updated: %s", master_csv)
    logger.info("Master JSON updated: %s", master_json)
    return records


if __name__ == "__main__":
    compile_labeled_jobs()
