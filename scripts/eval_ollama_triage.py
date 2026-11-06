"""Phase 3a+3b: Evaluate Ollama qwen2.5:3b triage vs human gold labels.

This script:
1. Loads all gold jobs (v2_role_fit_only) from DB.
2. For each job, calls Ollama triage with schema-validated TriageResult (read-only,
   NEVER writes to laya_labels).
3. Caches results in job_llm_features (feature_type='triage').
4. Computes per-class precision/recall/F1, Cohen's kappa, confusion matrix.
5. Computes confidence calibration: reliability table + ECE.
6. Saves results to evals/runs/<timestamp>/ollama_triage_eval.json
   and evals/runs/<timestamp>/calibration.json.

Prints an honest banner at the top: n=147, good_fit=5, gate=BLOCKED.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = PROJECT_ROOT / "evals" / "gold"
RUNS_DIR = PROJECT_ROOT / "evals" / "runs"
GOLD_LATEST = GOLD_DIR / "gold_latest.csv"

LABEL_ORDER = ["good_fit", "maybe", "bad_fit"]


def get_db_conn():
    """Get psycopg connection using env config."""
    import psycopg

    db_url = (
        f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', '5432')}"
        f"/{os.environ['POSTGRES_DB']}"
    )
    return psycopg.connect(db_url)


def load_gold_with_descriptions(conn) -> List[Dict[str, Any]]:
    """Load gold jobs from DB with their description text."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (ll.job_id)
                ll.job_id::text,
                ll.label,
                ll.label_guideline_version,
                jp.title,
                jp.company_name,
                jp.description_text,
                jp.source
            FROM laya_labels ll
            JOIN job_postings jp ON jp.id = ll.job_id
            WHERE ll.label_guideline_version = 'v2_role_fit_only'
              AND ll.label IS NOT NULL
            ORDER BY ll.job_id, ll.labeled_at DESC
            """
        )
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    logger.info("Loaded %d gold jobs from DB", len(rows))
    return rows


EVAL_PROMPT_VERSION = "v1_eval_disjoint"


def compute_content_hash(description: str) -> str:
    return hashlib.sha256((description or "").encode()).hexdigest()[:16]


def load_cached_triage(conn, job_id: str, model_digest: str) -> Optional[Dict]:
    """Try to load a cached triage result from job_llm_features."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT json_data FROM job_llm_features
            WHERE job_id = %s::uuid
              AND feature_type = 'triage'
              AND prompt_version = %s
              AND model_digest = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (job_id, EVAL_PROMPT_VERSION, model_digest),
        )
        row = cur.fetchone()
        if row and row[0]:
            return dict(row[0])
    return None


def save_triage_to_cache(
    conn,
    job_id: str,
    content_hash: str,
    model_digest: str,
    triage_dict: Dict,
) -> None:
    """Cache triage result to job_llm_features (no laya_labels write ever)."""
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO job_llm_features
                (job_id, feature_type, prompt_version, model, model_digest, content_hash, json_data, created_at)
            VALUES (%s::uuid, 'triage', %s, 'qwen2.5:3b', %s, %s, %s, now())
            ON CONFLICT DO NOTHING
            """,
            (job_id, EVAL_PROMPT_VERSION, model_digest, content_hash, Jsonb(triage_dict)),
        )
    conn.commit()


def run_ollama_triage(
    job: Dict[str, Any],
    all_gold_ids: Set[str],
    gold_pool: List[Dict[str, Any]],
    model_digest: str,
    timeout: float = 60.0,
) -> Optional[Dict]:
    """Run triage for one job; returns result dict or None on failure."""
    from src.llm.client import (
        OllamaGenerationError,
        OllamaUnavailableError,
        call_structured_ollama,
    )
    from src.llm.few_shot import select_few_shot_examples
    from src.llm.prompts.triage_v1 import SYSTEM_PROMPT, build_triage_user_message
    from src.llm.schemas import TriageResult

    job_id = job["job_id"]
    description = job.get("description_text") or ""
    if not description.strip():
        logger.warning("Job %s has no description text — skipping", job_id)
        return None

    # Few-shot pool is a fixed set reserved before evaluation; the eval set is
    # explicitly excluded as a second guard (no test-label leakage).
    few_shot_examples = select_few_shot_examples(
        target_job_id=job_id,
        excluded_job_ids=all_gold_ids,
        n_per_class=2,
        gold_pool=gold_pool,
    )

    user_msg = build_triage_user_message(
        title=job.get("title", ""),
        company=job.get("company_name", ""),
        description=description,
        few_shot_examples=few_shot_examples,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    try:
        result: TriageResult = call_structured_ollama(
            messages=messages,
            response_model=TriageResult,
            timeout=timeout,
        )
        return {
            "label": result.label,
            "confidence": result.confidence,
            "reason": result.reason,
            "evidence_quote": result.evidence_quote,
        }
    except OllamaUnavailableError as e:
        logger.error("Ollama unavailable: %s", e)
        return None
    except OllamaGenerationError as e:
        logger.warning("Triage generation failed for job %s: %s", job_id, e)
        return None
    except Exception as e:
        logger.error("Unexpected error for job %s: %s", job_id, e)
        return None


def compute_per_class_metrics(
    true_labels: List[str],
    pred_labels: List[str],
    labels: List[str] = LABEL_ORDER,
) -> Dict[str, Any]:
    """Compute per-class precision, recall, F1 and Cohen's kappa."""
    from sklearn.metrics import classification_report, cohen_kappa_score, confusion_matrix

    # For 3-class, we also produce binary good_fit vs rest for P/R/F1 more clearly
    int_map = {lbl: i for i, lbl in enumerate(labels)}
    y_true_int = [int_map.get(l, -1) for l in true_labels]
    y_pred_int = [int_map.get(l, -1) for l in pred_labels]

    # Filter to valid (known labels)
    pairs = [(t, p) for t, p in zip(y_true_int, y_pred_int) if t >= 0 and p >= 0]
    if not pairs:
        return {"error": "No valid labels to compare"}

    y_true_arr = [p[0] for p in pairs]
    y_pred_arr = [p[1] for p in pairs]

    cm = confusion_matrix(y_true_arr, y_pred_arr, labels=list(range(len(labels))))
    kappa = cohen_kappa_score(y_true_arr, y_pred_arr) if len(set(y_true_arr)) > 1 else None

    per_class = {}
    for i, lbl in enumerate(labels):
        binary_true = [1 if t == i else 0 for t in y_true_arr]
        binary_pred = [1 if p == i else 0 for p in y_pred_arr]
        n_true = sum(binary_true)
        if n_true == 0:
            per_class[lbl] = {"precision": None, "recall": None, "f1": None, "support": 0}
            continue
        prec = sum(1 for t, p in zip(binary_true, binary_pred) if p == 1 and t == 1) / max(
            sum(binary_pred), 1
        )
        rec = sum(1 for t, p in zip(binary_true, binary_pred) if t == 1 and p == 1) / n_true
        f1_val = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        per_class[lbl] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1_val, 4),
            "support": n_true,
        }

    return {
        "n": len(pairs),
        "kappa": round(kappa, 4) if kappa is not None else None,
        "kappa_note": "None — only one class present in true labels" if kappa is None else None,
        "confusion_matrix": cm.tolist(),
        "confusion_matrix_labels": labels,
        "per_class": per_class,
    }


def compute_calibration(
    true_labels: List[str],
    pred_labels: List[str],
    confidences: List[float],
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Compute reliability diagram data and ECE for good_fit class."""
    # We treat good_fit as positive class for calibration
    binary_correct = [1 if t == p else 0 for t, p in zip(true_labels, pred_labels)]

    bins: List[Dict[str, Any]] = []
    bin_size = 1.0 / n_bins
    ece_sum = 0.0
    n_total = len(confidences)

    for i in range(n_bins):
        low = i * bin_size
        high = (i + 1) * bin_size
        indices = [j for j, c in enumerate(confidences) if low <= c < high]
        if not indices:
            continue
        avg_conf = sum(confidences[j] for j in indices) / len(indices)
        avg_acc = sum(binary_correct[j] for j in indices) / len(indices)
        count = len(indices)
        ece_sum += (count / n_total) * abs(avg_conf - avg_acc)
        bins.append(
            {
                "bin_low": round(low, 2),
                "bin_high": round(high, 2),
                "count": count,
                "avg_confidence": round(avg_conf, 4),
                "avg_accuracy": round(avg_acc, 4),
            }
        )

    return {
        "ece": round(ece_sum, 4),
        "n_bins": n_bins,
        "n_samples": n_total,
        "note": "Calibration is overall prediction correctness (label match) vs confidence; not binary good_fit only.",
        "reliability_bins": bins,
    }


def gate_banner(gold_rows: List[Dict]) -> str:
    """Print honest gate status from gold rows."""
    n_total = len(gold_rows)
    n_good = sum(1 for r in gold_rows if r["label"] == "good_fit")
    status = "BLOCKED" if (n_total < 150 or n_good < 30) else "UNLOCKED"
    return (
        f"\n{'='*60}\n"
        f"  GATE STATUS: {status}\n"
        f"  Total v2_role_fit_only labels: {n_total}/150\n"
        f"  good_fit labels:               {n_good}/30\n"
        f"{'='*60}\n"
    )


def build_gold_pool_for_few_shot(gold_rows: List[Dict]) -> List[Dict]:
    """Convert DB gold rows to pool format for few_shot module."""
    pool = []
    for r in gold_rows:
        desc = r.get("description_text") or ""
        pool.append(
            {
                "job_id": r["job_id"],
                "title": r.get("title", ""),
                "company": r.get("company_name", ""),
                "label": r["label"],
                "guideline_version": "v2_role_fit_only",
                "description_snippet": desc[:200],
            }
        )
    return pool


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Ollama triage vs human gold labels.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip Ollama calls entirely (useful for testing without Ollama).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of jobs to evaluate (for quick testing).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-job Ollama timeout in seconds.",
    )
    parser.add_argument(
        "--use-cache-only",
        action="store_true",
        help="Only use cached results; skip any new Ollama calls.",
    )
    args = parser.parse_args()

    # --- Docker & DB ---
    from src.db.docker_control import ensure_docker_and_postgres

    ensure_docker_and_postgres()
    conn = get_db_conn()

    # --- Load Gold ---
    gold_rows = load_gold_with_descriptions(conn)
    print(gate_banner(gold_rows))

    if args.limit:
        gold_rows = gold_rows[: args.limit]
        logger.info("Limited to %d jobs for evaluation", args.limit)

    # --- Ollama availability check ---
    ollama_available = False
    model_digest = "unknown"
    if not args.no_llm:
        from src.llm.client import get_model_digest, is_ollama_available

        ollama_available = is_ollama_available()
        if ollama_available:
            model_digest = get_model_digest()
            logger.info("Ollama available, model digest: %s", model_digest)
        else:
            logger.warning("Ollama not available — will use cached results only")

    # --- Build few-shot pool (disjoint from the evaluation set) ---
    from src.llm.few_shot import select_few_shot_examples

    full_pool = build_gold_pool_for_few_shot(gold_rows)
    reserved = select_few_shot_examples(
        target_job_id="",
        n_per_class=2,
        gold_pool=full_pool,
    )
    reserved_ids = {str(e["job_id"]) for e in reserved}
    eval_rows = [r for r in gold_rows if str(r["job_id"]) not in reserved_ids]
    if reserved_ids:
        logger.info(
            "Reserved %d gold jobs as fixed few-shot examples; evaluation set is %d jobs.",
            len(reserved_ids), len(eval_rows),
        )
    # The model only ever sees this disjoint, human-labeled pool.
    gold_pool = reserved
    all_gold_ids = {str(r["job_id"]) for r in eval_rows}

    # --- Triage each job ---
    results = []
    n_cached = 0
    n_inferred = 0
    n_failed = 0
    n_skipped = 0

    for idx, job in enumerate(eval_rows):
        job_id = job["job_id"]
        content_hash = compute_content_hash(job.get("description_text") or "")

        # Try cache first
        cached = load_cached_triage(conn, job_id, model_digest)
        if cached:
            results.append(
                {
                    "job_id": job_id,
                    "title": job.get("title", ""),
                    "company": job.get("company_name", ""),
                    "source": job.get("source", ""),
                    "true_label": job["label"],
                    "pred_label": cached.get("label"),
                    "confidence": cached.get("confidence"),
                    "reason": cached.get("reason", ""),
                    "from_cache": True,
                }
            )
            n_cached += 1
            logger.debug("[%d/%d] %s — loaded from cache", idx + 1, len(eval_rows), job.get("title", ""))
            continue

        if args.no_llm or args.use_cache_only or not ollama_available:
            n_skipped += 1
            logger.debug("[%d/%d] %s — no Ollama, skipping", idx + 1, len(eval_rows), job.get("title", ""))
            continue

        # Run Ollama triage
        logger.info(
            "[%d/%d] Triaging: %s @ %s",
            idx + 1,
            len(eval_rows),
            job.get("title", ""),
            job.get("company_name", ""),
        )
        triage_dict = run_ollama_triage(
            job=job,
            all_gold_ids=all_gold_ids,
            gold_pool=gold_pool,
            model_digest=model_digest,
            timeout=args.timeout,
        )

        if triage_dict:
            save_triage_to_cache(conn, job_id, content_hash, model_digest, triage_dict)
            results.append(
                {
                    "job_id": job_id,
                    "title": job.get("title", ""),
                    "company": job.get("company_name", ""),
                    "source": job.get("source", ""),
                    "true_label": job["label"],
                    "pred_label": triage_dict.get("label"),
                    "confidence": triage_dict.get("confidence"),
                    "reason": triage_dict.get("reason", ""),
                    "from_cache": False,
                }
            )
            n_inferred += 1
        else:
            n_failed += 1

    conn.close()

    logger.info(
        "Triage complete: %d cached, %d new, %d failed, %d skipped",
        n_cached, n_inferred, n_failed, n_skipped,
    )

    if not results:
        print("\n⚠️  No triage results available.")
        if args.no_llm or not ollama_available:
            print("   Run without --no-llm and with Ollama running to generate predictions.")
        sys.exit(0)

    # --- Compute metrics ---
    true_labels = [r["true_label"] for r in results]
    pred_labels = [r["pred_label"] for r in results if r.get("pred_label")]
    confidences = [r["confidence"] for r in results if r.get("confidence") is not None]

    # Re-filter results to only those with valid predictions
    valid_results = [r for r in results if r.get("pred_label") and r.get("confidence") is not None]
    true_labels_v = [r["true_label"] for r in valid_results]
    pred_labels_v = [r["pred_label"] for r in valid_results]
    confidences_v = [r["confidence"] for r in valid_results]

    metrics = compute_per_class_metrics(true_labels_v, pred_labels_v)
    calibration = compute_calibration(true_labels_v, pred_labels_v, confidences_v)

    # Agreement stats
    n_agree = sum(1 for t, p in zip(true_labels_v, pred_labels_v) if t == p)
    accuracy = n_agree / len(valid_results) if valid_results else 0.0

    # Label distribution comparison
    from collections import Counter
    true_dist = Counter(true_labels_v)
    pred_dist = Counter(pred_labels_v)

    # --- Save results ---
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / f"ollama_eval_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    triage_eval = {
        "timestamp": timestamp,
        "model": "qwen2.5:3b",
        "model_digest": model_digest,
        "prompt_version": "v1",
        "n_gold_total": len(gold_rows),
        "n_gold_eval_set": len(eval_rows),
        "n_few_shot_reserved": len(reserved_ids),
        "n_gold_evaluated": len(valid_results),
        "n_cached": n_cached,
        "n_inferred": n_inferred,
        "n_failed": n_failed,
        "n_skipped": n_skipped,
        "gate": {
            "total_labels": len(gold_rows),
            "good_fit_labels": sum(1 for r in gold_rows if r["label"] == "good_fit"),
            "gate_status": "BLOCKED",
            "gate_required_total": 150,
            "gate_required_good_fit": 30,
        },
        "overall_accuracy": round(accuracy, 4),
        "per_class_metrics": metrics,
        "label_distribution": {
            "true": dict(true_dist),
            "predicted": dict(pred_dist),
        },
        "predictions": [
            {
                "job_id": r["job_id"],
                "title": r["title"],
                "company": r["company"],
                "source": r["source"],
                "true_label": r["true_label"],
                "pred_label": r["pred_label"],
                "confidence": r["confidence"],
                "reason": r.get("reason", "")[:200],
                "from_cache": r.get("from_cache", False),
            }
            for r in valid_results
        ],
    }

    triage_eval_path = run_dir / "ollama_triage_eval.json"
    with open(triage_eval_path, "w", encoding="utf-8") as f:
        json.dump(triage_eval, f, indent=2, default=str)

    calibration_path = run_dir / "calibration.json"
    with open(calibration_path, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2)

    # Also save a summary .txt
    summary_lines = [
        "=" * 60,
        "OLLAMA TRIAGE EVALUATION — Phase 3a+3b",
        "=" * 60,
        f"Timestamp:        {timestamp}",
        f"Model:            qwen2.5:3b (digest: {model_digest[:16]}...)",
        f"Prompt version:   v1",
        f"Gold set:         {len(gold_rows)} distinct jobs",
        f"  - good_fit:     {sum(1 for r in gold_rows if r['label']=='good_fit')}",
        f"  - maybe:        {sum(1 for r in gold_rows if r['label']=='maybe')}",
        f"  - bad_fit:      {sum(1 for r in gold_rows if r['label']=='bad_fit')}",
        f"GATE STATUS:      BLOCKED (147/150 labels, 5/30 good_fit)",
        "",
        f"Eval set:         {len(eval_rows)} jobs ({len(reserved_ids)} reserved as few-shot)",
        f"Evaluated:        {len(valid_results)} / {len(eval_rows)} jobs",
        f"  - from cache:   {n_cached}",
        f"  - new inferred: {n_inferred}",
        f"  - failed:       {n_failed}",
        f"  - skipped:      {n_skipped}",
        "",
        f"Overall accuracy (label match): {accuracy:.1%}  (n={len(valid_results)})",
        f"Cohen's kappa:    {metrics.get('kappa')} {metrics.get('kappa_note', '')}",
        "",
        "Per-class metrics:",
    ]
    for lbl in LABEL_ORDER:
        pc = metrics.get("per_class", {}).get(lbl, {})
        prec = f"{pc.get('precision'):.3f}" if pc.get("precision") is not None else "n/a"
        rec = f"{pc.get('recall'):.3f}" if pc.get("recall") is not None else "n/a"
        f1v = f"{pc.get('f1'):.3f}" if pc.get("f1") is not None else "n/a"
        sup = pc.get("support", 0)
        summary_lines.append(f"  {lbl:15}  prec={prec}  rec={rec}  f1={f1v}  n={sup}")

    summary_lines += [
        "",
        "Label distribution:",
        f"  True:      {dict(true_dist)}",
        f"  Predicted: {dict(pred_dist)}",
        "",
        f"Calibration ECE:  {calibration['ece']:.4f}",
        f"  Note: {calibration['note']}",
        "",
        "Files saved:",
        f"  {triage_eval_path}",
        f"  {calibration_path}",
        "=" * 60,
    ]
    summary_text = "\n".join(summary_lines)

    summary_path = run_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_text)

    print(summary_text)
    print(f"\nRun artifacts saved to: {run_dir}")


if __name__ == "__main__":
    main()
