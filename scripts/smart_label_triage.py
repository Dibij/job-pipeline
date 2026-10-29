"""scripts/smart_label_triage.py — Smart active-learning triage pipeline.

Strategy:
  1. Run MatchScorer (fast, rule-based, no GPU load) on all unlabeled eligible jobs.
  2. Run Laya scorer (GPU, ~40ms each on CUDA) on those same jobs.
  3. Triage each job into one of four buckets based on agreement / uncertainty:

     OBVIOUS_BAD   — Both agree it's bad (MS < 35 AND Laya < 40). Skip Ollama.
     STRONG_CAND   — Both agree it's good (MS >= 55 AND Laya >= 55). Send to Ollama.
     CONFLICT      — Scorers disagree by > 25 points. Send to Ollama as tiebreaker.
     UNCERTAIN     — Laya score is in uncertain zone (40–60). Send to Ollama.

  4. For all non-OBVIOUS_BAD jobs, call local Ollama qwen2.5:3b for a label suggestion.
  5. Save all suggestions as JSON for human review. Nothing auto-inserts into laya_labels.

Usage:
    python scripts/smart_label_triage.py
    python scripts/smart_label_triage.py --limit 50 --no-laya
    python scripts/smart_label_triage.py --ollama-model qwen2.5:1.5b
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.matching.scorer import MatchScorer
from src.matching.eligibility import check_eligibility
from src.matching.hard_filter import FilterReason

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
OLLAMA_URL = "http://localhost:11434/api/chat"

# ──────────────────────────────────────────────────────────────────────────────
# Triage thresholds
# ──────────────────────────────────────────────────────────────────────────────
MS_HIGH = 50        # MatchScorer >= this → "high"
LAYA_HIGH = 55      # Laya >= this → "high"
LAYA_UNCERTAIN_LO = 38  # Laya in [lo, hi] → uncertain zone
LAYA_UNCERTAIN_HI = 62
CONFLICT_GAP = 22   # |MS_norm - Laya| > this → conflict

# ──────────────────────────────────────────────────────────────────────────────
# Ollama prompt
# ──────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a job relevance classifier for a junior/mid-level software developer based in Nepal.
Use the v2_role_fit_only guideline — focus ONLY on whether the actual work and tech stack
suit a junior/mid Python, AI/ML, backend, or full-stack developer.

Labels:
  good_fit — Role and day-to-day work clearly suits a junior Python/AI/ML/full-stack developer.
  maybe    — Borderline: partial overlap, ambiguous scope, or adjacent engineering domain.
  bad_fit  — Non-technical, pure management, wrong domain, or irrelevant stack.

STRICT RULES:
  - IGNORE location, remote restrictions, work authorization, years-required. These are pre-filtered.
  - Focus on: does the actual technical work suit this developer?
  - Reply ONLY with valid JSON (no markdown, no extra text):
    {"label": "good_fit|maybe|bad_fit", "confidence": 0.0-1.0, "reason": "one sentence"}
""".strip()


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────
def fetch_unlabeled_jobs(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch eligible unlabeled jobs from DB with existing Laya scores if available."""
    sql = """
        SELECT DISTINCT ON (j.id)
               j.id, j.title, j.company_name, j.description_text, j.location_raw,
               j.is_remote, j.remote_restriction, j.experience_level,
               j.detected_language, j.is_unpaid, j.reachable_from_nepal,
               j.reachable_reason, j.tags, j.source, j.apply_url, j.exclude_reason,
               -- Existing Laya score if already scored
               ls.final_score  AS laya_score,
               ls.needs_review AS laya_needs_review,
               ls.disqualification_reason AS laya_disq,
               -- Existing MatchScorer score
               COALESCE(jm.match_score, -1) AS match_score
        FROM jobs j
        LEFT JOIN laya_labels lbl ON j.id = lbl.job_id
        LEFT JOIN LATERAL (
            SELECT final_score, needs_review, disqualification_reason
            FROM laya_job_scores
            WHERE job_id = j.id
            ORDER BY scored_at DESC LIMIT 1
        ) ls ON true
        LEFT JOIN job_matches jm ON j.id = jm.job_id
        WHERE lbl.job_id IS NULL       -- not yet labeled
          AND j.exclude_reason IS NULL  -- not excluded by normalization
          AND j.is_remote = TRUE        -- pre-filter obvious non-remote to reduce HardFilter waste
        ORDER BY j.id, j.created_at DESC
    """
    if limit:
        sql += f" LIMIT {limit}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


# ──────────────────────────────────────────────────────────────────────────────
# Eligibility filter
# ──────────────────────────────────────────────────────────────────────────────
def filter_eligible(jobs: List[Dict]) -> List[Dict]:
    """Keep only jobs that pass HardFilter (using shared eligibility module)."""
    passed = []
    blocked_counts: Dict[str, int] = {}
    for job in jobs:
        ok, result = check_eligibility(job)
        if ok:
            passed.append(job)
        else:
            code = result.reason.value
            blocked_counts[code] = blocked_counts.get(code, 0) + 1
    logger.info(
        "Eligibility: %d passed, %d blocked: %s",
        len(passed), len(jobs) - len(passed), blocked_counts,
    )
    return passed


# ──────────────────────────────────────────────────────────────────────────────
# MatchScorer pass
# ──────────────────────────────────────────────────────────────────────────────
def run_match_scorer(jobs: List[Dict]) -> Dict[str, float]:
    """Return map of job_id → normalized match score (0–100)."""
    scorer = MatchScorer()
    scores = {}
    for job in jobs:
        try:
            score, _, _, _ = scorer.score_job(job)
            scores[str(job["id"])] = float(score)
        except Exception as e:
            logger.warning("MatchScorer failed on %s: %s", job.get("title"), e)
            scores[str(job["id"])] = 0.0
    return scores


# ──────────────────────────────────────────────────────────────────────────────
# Laya pass (optional — skip if already scored or --no-laya)
# ──────────────────────────────────────────────────────────────────────────────
def run_laya_scorer(jobs: List[Dict]) -> Dict[str, float]:
    """Return map of job_id → Laya final_score. Uses stored score if available."""
    # Pre-populate with already-scored jobs
    laya_scores = {}
    needs_scoring = []
    for job in jobs:
        stored = job.get("laya_score")
        if stored is not None and float(stored) >= 0:
            laya_scores[str(job["id"])] = float(stored)
        else:
            needs_scoring.append(job)

    if not needs_scoring:
        logger.info("Laya: all %d jobs already scored (using stored).", len(jobs))
        return laya_scores

    logger.info("Laya: %d jobs need fresh scoring...", len(needs_scoring))
    try:
        import torch
        from src.matching.laya_scorer import LayaScorer
        device = "cuda" if torch.cuda.is_available() else "cpu"
        laya = LayaScorer(device=device)
        for i, job in enumerate(needs_scoring):
            try:
                res = laya.score_job(job)
                laya_scores[str(job["id"])] = float(res.final_score)
                if (i + 1) % 10 == 0:
                    logger.info("  Laya scored %d/%d...", i + 1, len(needs_scoring))
            except Exception as e:
                logger.warning("  Laya failed on %s: %s", job.get("title"), e)
                laya_scores[str(job["id"])] = -1.0
    except Exception as e:
        logger.warning("Could not load Laya scorer: %s — using stored scores only.", e)

    return laya_scores


# ──────────────────────────────────────────────────────────────────────────────
# Triage logic
# ──────────────────────────────────────────────────────────────────────────────
BUCKET_LABELS = {
    "STRONG_CAND": "Both Laya & MatchScorer agree: strong candidate",
    "CONFLICT":    "Laya vs MatchScorer disagree significantly",
    "UNCERTAIN":   "Laya is in uncertain zone (40-60)",
    "OBVIOUS_BAD": "Both agree: likely bad (skipping Ollama)",
}


def triage(
    job: Dict,
    ms_score: float,
    laya_score: float,
    laya_needs_review: Optional[bool],
) -> str:
    """Assign a triage bucket to a job."""
    ms_norm = ms_score  # already 0–100
    laya_val = float(laya_score) if laya_score is not None and float(laya_score) >= 0 else 0.0

    ms_high = ms_norm >= MS_HIGH
    laya_high = laya_val >= LAYA_HIGH
    laya_uncertain = LAYA_UNCERTAIN_LO <= laya_val <= LAYA_UNCERTAIN_HI
    conflict = abs(ms_norm - laya_val) > CONFLICT_GAP and (ms_high != laya_high)

    if laya_needs_review:
        return "UNCERTAIN"
    if conflict:
        return "CONFLICT"
    if laya_uncertain:
        return "UNCERTAIN"
    if ms_high and laya_high:
        return "STRONG_CAND"
    return "OBVIOUS_BAD"


# ──────────────────────────────────────────────────────────────────────────────
# Ollama classifier
# ──────────────────────────────────────────────────────────────────────────────
def call_ollama(title: str, description: str, model: str) -> Optional[Dict]:
    """Call Ollama and return parsed JSON result or None on failure."""
    truncated_desc = (description or "")[:1800]
    payload = {
        "model": model,
        "format": "json",
        "stream": False,
        "options": {"num_ctx": 2048, "temperature": 0.1},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Title: {title}\n\nJob Description:\n{truncated_desc}",
            },
        ],
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=45)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"]
        result = json.loads(raw)
        label = result.get("label", "").strip().lower()
        if label not in ("good_fit", "maybe", "bad_fit"):
            logger.warning("Ollama returned invalid label %r for: %s", label, title[:50])
            return None
        return {
            "label": label,
            "confidence": float(result.get("confidence", 0.5)),
            "reason": str(result.get("reason", "")).strip(),
        }
    except Exception as e:
        logger.warning("Ollama call failed for '%s': %s", title[:50], e)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Smart triage labeling pipeline.")
    parser.add_argument("--limit", type=int, default=None, help="Max unlabeled jobs to process")
    parser.add_argument("--no-laya", action="store_true", help="Skip fresh Laya scoring (use stored only)")
    parser.add_argument("--ollama-model", default="qwen2.5:3b", help="Ollama model name")
    parser.add_argument("--no-ollama", action="store_true", help="Triage only, skip Ollama calls")
    args = parser.parse_args()

    print("\n" + "=" * 72)
    print("  SMART LABEL TRIAGE: MatchScorer + Laya -> Triage -> Ollama")
    print("=" * 72)

    # ── Step 1: Fetch unlabeled jobs ──────────────────────────────────────────
    logger.info("Fetching unlabeled eligible jobs from DB...")
    all_jobs = fetch_unlabeled_jobs(limit=args.limit)
    logger.info("Found %d unlabeled jobs total.", len(all_jobs))

    # ── Step 2: Eligibility filter ────────────────────────────────────────────
    jobs = filter_eligible(all_jobs)
    if not jobs:
        print("No eligible unlabeled jobs found. Run the daily pipeline first.")
        return

    # ── Step 3: MatchScorer ───────────────────────────────────────────────────
    logger.info("Running MatchScorer on %d jobs...", len(jobs))
    t0 = time.time()
    ms_scores = run_match_scorer(jobs)
    logger.info("MatchScorer done in %.1fs.", time.time() - t0)

    # ── Step 4: Laya scorer ───────────────────────────────────────────────────
    if args.no_laya:
        logger.info("--no-laya: using stored Laya scores only.")
        laya_scores = {str(j["id"]): float(j.get("laya_score") or -1.0) for j in jobs}
    else:
        laya_scores = run_laya_scorer(jobs)

    # ── Step 5: Triage ────────────────────────────────────────────────────────
    buckets: Dict[str, List[Dict]] = {
        "STRONG_CAND": [], "CONFLICT": [], "UNCERTAIN": [], "OBVIOUS_BAD": [],
    }
    for job in jobs:
        jid = str(job["id"])
        ms = ms_scores.get(jid, 0.0)
        ly = laya_scores.get(jid, -1.0)
        needs_rev = job.get("laya_needs_review", False)
        bucket = triage(job, ms, ly, needs_rev)
        buckets[bucket].append({**job, "_ms_score": ms, "_laya_score": ly})

    print("\n[TRIAGE RESULTS]")
    print(f"{'Bucket':<14} {'Count':>6}  Description")
    print("-" * 72)
    for bname, blist in buckets.items():
        print(f"{bname:<14} {len(blist):>6}  {BUCKET_LABELS[bname]}")
    print("-" * 72)

    # ── Step 6: Ollama classification ─────────────────────────────────────────
    send_to_ollama = (
        buckets["STRONG_CAND"] +
        buckets["CONFLICT"] +
        buckets["UNCERTAIN"]
    )
    # Sort: STRONG_CAND first (most likely good_fit, most interesting)
    priority_order = {"STRONG_CAND": 0, "CONFLICT": 1, "UNCERTAIN": 2}
    send_to_ollama.sort(key=lambda j: priority_order.get(j.get("_bucket", "UNCERTAIN"), 2))

    suggestions = []
    skipped = 0

    if args.no_ollama:
        print(f"\n--no-ollama: skipping Ollama calls. {len(send_to_ollama)} jobs queued.")
    else:
        print(f"\n[OLLAMA] Classifying {len(send_to_ollama)} jobs with {args.ollama_model}...")
        print("(OBVIOUS_BAD jobs are skipped — both scorers agree they're bad)\n")

        for i, job in enumerate(send_to_ollama, 1):
            jid = str(job["id"])
            title = job.get("title") or "Untitled"
            company = job.get("company_name") or "Unknown"
            ms = job["_ms_score"]
            ly = job["_laya_score"]

            result = call_ollama(title, job.get("description_text") or "", args.ollama_model)
            if result is None:
                skipped += 1
                continue

            label = result["label"]
            conf = result["confidence"]
            reason = result["reason"]

            # Visual indicator
            icon = {"good_fit": "[OK]", "maybe": "[?] ", "bad_fit": "[X] "}.get(label, "[ ]")
            conf_str = f"{conf:.0%}"
            print(
                f"  [{i:3}/{len(send_to_ollama)}] {icon} {label:<10} ({conf_str}) "
                f"MS={ms:.0f} Laya={ly:.0f}  {title[:45]:<45}  {company[:18]}"
            )
            if label in ("good_fit", "maybe"):
                print(f"           -> {reason}")

            suggestions.append({
                "job_id": jid,
                "title": title,
                "company": company,
                "source": job.get("source"),
                "apply_url": job.get("apply_url"),
                "ms_score": round(ms, 1),
                "laya_score": round(ly, 1),
                "ollama_label": label,
                "ollama_confidence": round(conf, 3),
                "ollama_reason": reason,
                "ollama_model": args.ollama_model,
                "triaged_at": datetime.now(timezone.utc).isoformat(),
            })

    # ── Step 7: Save suggestions ──────────────────────────────────────────────
    out_path = DATA_DIR / f"triage_suggestions_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    out_path.write_text(json.dumps(suggestions, indent=2, ensure_ascii=False))

    print(f"\n{'=' * 72}")
    print(f"  Done. {len(suggestions)} suggestions saved -> {out_path.name}")
    print(f"  Skipped (Ollama error): {skipped}")
    print(f"  Skipped (OBVIOUS_BAD):  {len(buckets['OBVIOUS_BAD'])}")
    print(f"\n  [!] These are SUGGESTIONS -- review in app.py before inserting into laya_labels.")
    print(f"  Run: python scripts/ingest_triage_suggestions.py {out_path.name}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
