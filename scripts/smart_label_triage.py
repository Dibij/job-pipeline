"""scripts/smart_label_triage.py -- Smart active-learning triage pipeline (Phase 2d).

Strategy:
  1. Run MatchScorer (fast, rule-based, no GPU) on all unlabeled eligible jobs.
  2. Laya scorer (GPU, ~40ms each on CUDA) on those same jobs.
  3. Triage each job into one of four buckets:
     OBVIOUS_BAD   -- Both agree it's bad (MS < 35 AND Laya < 40). Skip Ollama.
     STRONG_CAND   -- Both agree it's good (MS >= 55 AND Laya >= 55). Send to Ollama.
     CONFLICT      -- Scorers disagree by > 25 points. Send to Ollama as tiebreaker.
     UNCERTAIN     -- Laya score is in uncertain zone (40-60). Send to Ollama.
  4. For non-OBVIOUS_BAD jobs, call local Ollama qwen2.5:3b with:
     - Prompt-versioned, schema-validated output (TriageResult: label, confidence, reason, quote).
     - Dynamic few-shot examples from human labels, STRICTLY EXCLUDING the target job.
     - Fallback: continues cleanly without LLM if Ollama is down or --no-llm flag passed.
     - Caches to table job_llm_features.
  5. Save suggestions as JSON for human review.
     CRITICAL: Never auto-writes to laya_labels (human confirmation only).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection
from src.llm.caching import (
    compute_job_content_hash,
    get_cached_llm_feature,
    store_llm_feature,
)
from src.llm.client import (
    OllamaGenerationError,
    OllamaUnavailableError,
    call_structured_ollama,
    get_model_digest,
    is_ollama_available,
)
from src.llm.few_shot import select_few_shot_examples
from src.llm.prompts.triage_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_triage_user_message,
)
from src.llm.schemas import TriageResult
from src.matching.eligibility import check_eligibility
from src.matching.scorer import MatchScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"

# Triage threshold configuration
MS_HIGH = 55.0
LAYA_HIGH = 55.0
MS_BAD_CUTOFF = 35.0
LAYA_BAD_CUTOFF = 40.0
CONFLICT_GAP = 25.0
LAYA_UNCERTAIN_LO = 40.0
LAYA_UNCERTAIN_HI = 60.0


def fetch_unlabeled_jobs(limit: Optional[int] = None) -> List[Dict]:
    """Fetch all active jobs that do not yet have a human label."""
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    sql = f"""
        SELECT
            j.id,
            j.title,
            j.company_name,
            j.location_raw,
            j.is_remote,
            j.remote_restriction,
            j.description_text,
            j.source,
            j.apply_url,
            j.posted_at,
            j.created_at,
            j.accessibility,
            j.detected_language,
            j.is_unpaid,
            j.exclude_reason,
            s.final_score AS laya_score,
            s.needs_human_review AS laya_needs_review
        FROM jobs j
        LEFT JOIN laya_labels l ON l.job_id = j.id
        LEFT JOIN laya_job_scores s ON s.job_id = j.id
        WHERE l.id IS NULL
          AND j.exclude_reason IS NULL
        ORDER BY j.created_at DESC
        {limit_clause};
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def filter_eligible(jobs: List[Dict]) -> List[Dict]:
    """Keep only jobs that pass HardFilter eligibility."""
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

    if ms_norm < MS_BAD_CUTOFF and laya_val < LAYA_BAD_CUTOFF:
        return "OBVIOUS_BAD"
    if laya_needs_review:
        return "UNCERTAIN"
    if conflict:
        return "CONFLICT"
    if laya_uncertain:
        return "UNCERTAIN"
    if ms_high and laya_high:
        return "STRONG_CAND"
    return "OBVIOUS_BAD"


def run_triage(
    limit: Optional[int] = None,
    use_laya: bool = False,
    use_ollama: bool = True,
    ollama_model: str = "qwen2.5:3b",
    excluded_job_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Run the full triage pipeline and return a stats dict."""
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

    # MatchScorer pass
    t0 = time.time()
    ms_scores = run_match_scorer(jobs)
    logger.info("MatchScorer done in %.1fs.", time.time() - t0)

    # Laya scorer pass
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

    send_to_ollama = (
        buckets["STRONG_CAND"] + buckets["CONFLICT"] + buckets["UNCERTAIN"]
    )
    priority_order = {"STRONG_CAND": 0, "CONFLICT": 1, "UNCERTAIN": 2}
    send_to_ollama.sort(key=lambda j: priority_order.get(j.get("_bucket", "UNCERTAIN"), 2))

    suggestions: List[Dict] = []
    ollama_errors = 0

    if not use_ollama:
        logger.info(
            "Triage: use_ollama=False (--no-llm) -- skipping Ollama calls (%d jobs queued).",
            len(send_to_ollama),
        )
    elif not is_ollama_available():
        logger.warning("Ollama daemon is not reachable at localhost:11434; skipping LLM triage gracefully.")
    else:
        logger.info(
            "Triage: calling Ollama (%s) on %d jobs with few-shot guidance...",
            ollama_model, len(send_to_ollama)
        )
        model_digest = get_model_digest(ollama_model)

        for i, job in enumerate(send_to_ollama, 1):
            jid = str(job["id"])
            title = job.get("title") or "Untitled"
            company = job.get("company_name") or "Unknown"
            desc = job.get("description_text") or ""
            ms = job["_ms_score"]
            ly = job["_laya_score"]

            content_hash = compute_job_content_hash(job)

            # Check DB cache first
            cached_triage = get_cached_llm_feature(
                job_id=jid,
                feature_type="triage",
                prompt_version=PROMPT_VERSION,
                model_digest=model_digest,
                content_hash=content_hash,
            )

            result: Optional[TriageResult] = None
            if cached_triage:
                try:
                    result = TriageResult.model_validate(cached_triage)
                except Exception:
                    pass

            if result is None:
                # Retrieve human few-shot examples strictly excluding target job and excluded set
                few_shots = select_few_shot_examples(
                    target_job_id=jid,
                    excluded_job_ids=excluded_job_ids,
                    n_per_class=1,
                )
                user_msg = build_triage_user_message(
                    title=title,
                    company=company,
                    description=desc,
                    few_shot_examples=few_shots,
                )
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ]

                try:
                    result = call_structured_ollama(
                        messages=messages,
                        response_model=TriageResult,
                        model=ollama_model,
                        temperature=0.0,
                        seed=42,
                        timeout=45.0,
                    )
                    # Cache in DB
                    store_llm_feature(
                        job_id=jid,
                        feature_type="triage",
                        prompt_version=PROMPT_VERSION,
                        model=ollama_model,
                        model_digest=model_digest,
                        content_hash=content_hash,
                        json_data=result.model_dump(),
                    )
                except (OllamaUnavailableError, OllamaGenerationError) as err:
                    logger.warning("Ollama triage failed for '%s': %s", title[:40], err)
                    ollama_errors += 1
                    continue
                except Exception as exc:
                    logger.error("Unexpected error triaging '%s': %s", title[:40], exc)
                    ollama_errors += 1
                    continue

            label = result.label
            conf = result.confidence
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
                "ollama_reason": result.reason,
                "ollama_evidence_quote": result.evidence_quote,
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
    else:
        logger.info("Triage: no new suggestions to save.")

    return {
        "fetched": len(all_jobs),
        "eligible": len(jobs),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "suggestions_count": len(suggestions),
        "ollama_errors": ollama_errors,
        "out_path": str(out_path) if out_path else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Smart triage labeling pipeline.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max unlabeled jobs to process")
    parser.add_argument("--no-laya", action="store_true",
                        help="Skip fresh Laya scoring (use stored scores only)")
    parser.add_argument("--ollama-model", default="qwen2.5:3b",
                        help="Ollama model name (default: qwen2.5:3b)")
    parser.add_argument("--no-ollama", "--no-llm", action="store_true", dest="no_llm",
                        help="Triage only, skip Ollama LLM calls")
    args = parser.parse_args()

    print("\n" + "=" * 72)
    print("  SMART LABEL TRIAGE: MatchScorer + Laya -> Triage -> Ollama")
    print("=" * 72)

    stats = run_triage(
        limit=args.limit,
        use_laya=not args.no_laya,
        use_ollama=not args.no_llm,
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
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
