"""scripts/smart_label_triage.py -- Smart active-learning triage pipeline.

Strategy:
  1. Run MatchScorer (fast, rule-based, no GPU) on all unlabeled eligible jobs.
  2. Laya scorer (GPU, ~40ms each on CUDA) on those same jobs.
  3. Triage each job into one of four buckets based on agreement / uncertainty:

     OBVIOUS_BAD   -- Both agree it's bad (MS < 35 AND Laya < 40). Skip Ollama.
     STRONG_CAND   -- Both agree it's good (MS >= 55 AND Laya >= 55). Send to Ollama.
     CONFLICT      -- Scorers disagree by > 25 points. Send to Ollama as tiebreaker.
     UNCERTAIN     -- Laya score is in uncertain zone (40-60). Send to Ollama.

  4. For all non-OBVIOUS_BAD jobs, call local Ollama qwen2.5:3b for a label suggestion.
  5. Save all suggestions as JSON for human review. Nothing auto-inserts into laya_labels.

Used standalone:
    python scripts/smart_label_triage.py
    python scripts/smart_label_triage.py --limit 50 --no-laya
    python scripts/smart_label_triage.py --ollama-model qwen2.5:1.5b

Used from daily pipeline (imported):
    from scripts.smart_label_triage import run_triage
    stats = run_triage(limit=300, use_ollama=True, ollama_model="qwen2.5:3b")
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.matching.scorer import MatchScorer
from src.matching.eligibility import check_eligibility

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
OLLAMA_URL = "http://localhost:11434/api/chat"

# ─────────────────────────────────────────────────────────────────────────────
# Triage thresholds
# ─────────────────────────────────────────────────────────────────────────────
MS_HIGH = 50            # MatchScorer >= this -> "high"
LAYA_HIGH = 55          # Laya >= this -> "high"
LAYA_UNCERTAIN_LO = 38  # Laya in [lo, hi] -> uncertain zone
LAYA_UNCERTAIN_HI = 62
CONFLICT_GAP = 22       # |MS_norm - Laya| > this -> conflict

BUCKET_LABELS = {
    "STRONG_CAND": "Both Laya & MatchScorer agree: strong candidate",
    "CONFLICT":    "Laya vs MatchScorer disagree significantly",
    "UNCERTAIN":   "Laya is in uncertain zone (40-60)",
    "OBVIOUS_BAD": "Both agree: likely bad (skipping Ollama)",
}

# ─────────────────────────────────────────────────────────────────────────────
# Ollama prompt
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a job relevance classifier for a junior/mid-level software developer based in Nepal.
Use the v2_role_fit_only guideline -- focus ONLY on whether the actual work and tech stack
suit a junior/mid Python, AI/ML, backend, or full-stack developer.

Labels:
  good_fit -- Role and day-to-day work clearly suits a junior Python/AI/ML/full-stack developer.
  maybe    -- Borderline: partial overlap, ambiguous scope, or adjacent engineering domain.
  bad_fit  -- Non-technical, pure management, wrong domain, or irrelevant stack.

STRICT RULES:
  - IGNORE location, remote restrictions, work authorization, years-required. These are pre-filtered.
  - Focus on: does the actual technical work suit this developer?
  - Reply ONLY with valid JSON (no markdown, no extra text):
    {"label": "good_fit|maybe|bad_fit", "confidence": 0.0-1.0, "reason": "one sentence"}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────
def fetch_unlabeled_jobs(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch unlabeled remote-eligible jobs from DB with stored Laya scores."""
    sql = """
        SELECT DISTINCT ON (j.id)
               j.id, j.title, j.company_name, j.description_text, j.location_raw,
               j.is_remote, j.remote_restriction, j.experience_level,
               j.detected_language, j.is_unpaid, j.reachable_from_nepal,
               j.reachable_reason, j.tags, j.source, j.apply_url, j.exclude_reason,
               ls.final_score  AS laya_score,
               ls.needs_review AS laya_needs_review,
               ls.disqualification_reason AS laya_disq,
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
        WHERE lbl.job_id IS NULL        -- not yet labeled
          AND j.exclude_reason IS NULL   -- not excluded by normalization
          AND j.is_remote = TRUE         -- pre-filter: skip obviously non-remote
        ORDER BY j.id, j.created_at DESC
    """
    if limit:
        sql += f" LIMIT {limit}"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Eligibility filter
# ─────────────────────────────────────────────────────────────────────────────
def filter_eligible(jobs: List[Dict]) -> List[Dict]:
    """Keep only jobs that pass HardFilter."""
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


# ─────────────────────────────────────────────────────────────────────────────
# MatchScorer pass
# ─────────────────────────────────────────────────────────────────────────────
def run_match_scorer(jobs: List[Dict]) -> Dict[str, float]:
    """Return map of job_id -> normalized match score (0-100)."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Laya scorer pass (optional)
# ─────────────────────────────────────────────────────────────────────────────
def run_laya_scorer(jobs: List[Dict]) -> Dict[str, float]:
    """Return map of job_id -> Laya final_score. Uses stored score if available."""
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
        logger.warning("Could not load Laya scorer: %s -- using stored scores only.", e)

    return laya_scores


# ─────────────────────────────────────────────────────────────────────────────
# Triage logic
# ─────────────────────────────────────────────────────────────────────────────
def triage(
    job: Dict,
    ms_score: float,
    laya_score: float,
    laya_needs_review: Optional[bool],
) -> str:
    """Assign a triage bucket to a job."""
    ms_norm = float(ms_score)
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


# ─────────────────────────────────────────────────────────────────────────────
# Ollama classifier
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (importable by run_daily.py)
# ─────────────────────────────────────────────────────────────────────────────
def run_triage(
    limit: Optional[int] = None,
    use_laya: bool = False,
    use_ollama: bool = True,
    ollama_model: str = "qwen2.5:3b",
) -> Dict[str, Any]:
    """Run the full triage pipeline and return a stats dict.

    Args:
        limit:        Max unlabeled jobs to fetch (None = all remote-eligible).
        use_laya:     If True, run fresh Laya scoring on unseen jobs (GPU).
                      If False, use stored Laya scores only (safe for daily run).
        use_ollama:   If True, call Ollama for non-obvious-bad jobs.
                      If False, triage only -- no Ollama calls (fast, no GPU).
        ollama_model: Ollama model tag (default: qwen2.5:3b).

    Returns:
        dict: fetched, eligible, buckets (count per bucket), suggestions_count,
              ollama_errors, out_path (str or None).
    """
    logger.info("Fetching unlabeled eligible jobs from DB...")
    all_jobs = fetch_unlabeled_jobs(limit=limit)
    logger.info("Found %d unlabeled jobs total.", len(all_jobs))

    jobs = filter_eligible(all_jobs)
    if not jobs:
        logger.info("Triage: no eligible unlabeled jobs -- skipping.")
        return {
            "fetched": len(all_jobs), "eligible": 0,
            "buckets": {}, "suggestions_count": 0,
            "ollama_errors": 0, "out_path": None,
        }

    # MatchScorer
    t0 = time.time()
    ms_scores = run_match_scorer(jobs)
    logger.info("MatchScorer done in %.1fs.", time.time() - t0)

    # Laya scorer
    if use_laya:
        laya_scores = run_laya_scorer(jobs)
    else:
        logger.info("Triage: using stored Laya scores only (use_laya=False).")
        laya_scores = {str(j["id"]): float(j.get("laya_score") or -1.0) for j in jobs}

    # Triage into buckets
    buckets: Dict[str, List[Dict]] = {
        "STRONG_CAND": [], "CONFLICT": [], "UNCERTAIN": [], "OBVIOUS_BAD": [],
    }
    for job in jobs:
        jid = str(job["id"])
        ms = ms_scores.get(jid, 0.0)
        ly = laya_scores.get(jid, -1.0)
        b = triage(job, ms, ly, job.get("laya_needs_review", False))
        buckets[b].append({**job, "_ms_score": ms, "_laya_score": ly, "_bucket": b})

    logger.info(
        "Triage: STRONG=%d  CONFLICT=%d  UNCERTAIN=%d  OBVIOUS_BAD=%d",
        len(buckets["STRONG_CAND"]), len(buckets["CONFLICT"]),
        len(buckets["UNCERTAIN"]), len(buckets["OBVIOUS_BAD"]),
    )

    # Ollama classification
    send_to_ollama = (
        buckets["STRONG_CAND"] + buckets["CONFLICT"] + buckets["UNCERTAIN"]
    )
    priority_order = {"STRONG_CAND": 0, "CONFLICT": 1, "UNCERTAIN": 2}
    send_to_ollama.sort(key=lambda j: priority_order.get(j.get("_bucket", "UNCERTAIN"), 2))

    suggestions: List[Dict] = []
    ollama_errors = 0

    if not use_ollama:
        logger.info(
            "Triage: use_ollama=False -- skipping Ollama calls (%d jobs queued).",
            len(send_to_ollama),
        )
    else:
        logger.info(
            "Triage: calling Ollama (%s) on %d jobs...", ollama_model, len(send_to_ollama)
        )
        for i, job in enumerate(send_to_ollama, 1):
            jid = str(job["id"])
            title = job.get("title") or "Untitled"
            company = job.get("company_name") or "Unknown"
            ms = job["_ms_score"]
            ly = job["_laya_score"]

            result = call_ollama(title, job.get("description_text") or "", ollama_model)
            if result is None:
                ollama_errors += 1
                continue

            label = result["label"]
            conf = result["confidence"]
            icon = {"good_fit": "[OK]", "maybe": "[?] ", "bad_fit": "[X] "}.get(label, "[ ]")
            logger.info(
                "  [%d/%d] %s %s (%.0f%%) MS=%.0f Laya=%.0f  %s @ %s",
                i, len(send_to_ollama), icon, label, conf * 100,
                ms, ly, title[:40], company[:20],
            )

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
                "ollama_reason": result["reason"],
                "ollama_model": ollama_model,
                "triage_bucket": job.get("_bucket"),
                "triaged_at": datetime.now(timezone.utc).isoformat(),
            })

    # Save suggestions file
    out_path: Optional[Path] = None
    if suggestions:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        out_path = DATA_DIR / f"triage_suggestions_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        out_path.write_text(
            json.dumps(suggestions, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Triage: %d suggestions saved -> %s", len(suggestions), out_path.name)
        logger.info(
            "[!] Review with: python scripts/ingest_triage_suggestions.py %s", out_path
        )
    else:
        logger.info("Triage: no Ollama suggestions to save.")

    return {
        "fetched": len(all_jobs),
        "eligible": len(jobs),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "suggestions_count": len(suggestions),
        "ollama_errors": ollama_errors,
        "out_path": str(out_path) if out_path else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Smart triage labeling pipeline.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max unlabeled jobs to process")
    parser.add_argument("--no-laya", action="store_true",
                        help="Skip fresh Laya scoring (use stored scores only)")
    parser.add_argument("--ollama-model", default="qwen2.5:3b",
                        help="Ollama model name (default: qwen2.5:3b)")
    parser.add_argument("--no-ollama", action="store_true",
                        help="Triage only, skip Ollama calls")
    args = parser.parse_args()

    print("\n" + "=" * 72)
    print("  SMART LABEL TRIAGE: MatchScorer + Laya -> Triage -> Ollama")
    print("=" * 72)

    stats = run_triage(
        limit=args.limit,
        use_laya=not args.no_laya,
        use_ollama=not args.no_ollama,
        ollama_model=args.ollama_model,
    )

    print(f"\n{'=' * 72}")
    print(f"  Done.  Fetched={stats['fetched']}  Eligible={stats['eligible']}")
    for bname in ("STRONG_CAND", "CONFLICT", "UNCERTAIN", "OBVIOUS_BAD"):
        print(f"    {bname:<14}: {stats['buckets'].get(bname, 0)}")
    print(f"  Ollama suggestions: {stats['suggestions_count']}")
    print(f"  Ollama errors:      {stats['ollama_errors']}")
    if stats.get("out_path"):
        print(f"  File: {stats['out_path']}")
        print(f"  Review: python scripts/ingest_triage_suggestions.py {stats['out_path']}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
