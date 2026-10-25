"""Generate Step 7 comprehensive audit and evaluation report.

Generates:
  A) Label x HardFilter table (de-duplicated by canonical_job_id) + list failing good/maybe rows.
  B) NEEDS_REVIEW rows audit (all 23 with reason for ambiguity).
  C) Scorer comparison on post-HardFilter pool (match_score vs laya_score vs head v2) with bootstrap 95% CI.
  D) Embedding baseline (all-MiniLM-L6-v2) whole-text & chunked cosine AUC + 2D t-SNE plot PNG.
  E) Unverified items list.
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from collections import Counter, defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
from sentence_transformers import SentenceTransformer

from src.db.connection import get_connection
from src.matching.hard_filter import apply as hf_apply, FilterReason
from src.models.transformers import clean_description_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "laya_comparison_all_labeled.csv"
CV_PROFILE_PATH = PROJECT_ROOT / "src" / "matching" / "cv_profile.json"
PORTFOLIO_PATH = PROJECT_ROOT / "docs" / "Resume_Portfolio_Master.md"
OUTPUT_PLOT_PATH = PROJECT_ROOT / "data" / "embedding_baseline_tsne.png"


def load_labeled_jobs() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Load labeled CSV and join with jobs table from PostgreSQL."""
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


def run_part_a(rows: List[Dict[str, Any]], db_jobs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Part A: Label x HardFilter table (de-duplicated by canonical_job_id)."""
    # De-duplicate by canonical_job_id
    seen_canonical = set()
    deduped_rows = []
    for r in rows:
        jid = r["job_id"]
        db_j = db_jobs.get(jid)
        cid = str(db_j["canonical_job_id"]) if (db_j and db_j.get("canonical_job_id")) else jid
        if cid not in seen_canonical:
            seen_canonical.add(cid)
            deduped_rows.append(r)

    matrix = defaultdict(lambda: defaultdict(int))
    failing_good_maybe = []

    for r in deduped_rows:
        jid = r["job_id"]
        job_dict = db_jobs.get(jid)
        res = hf_apply(job_dict)

        if res.reason == FilterReason.PASS:
            outcome = "PASS"
        elif res.reason == FilterReason.NEEDS_REVIEW:
            outcome = "NEEDS_REVIEW"
        else:
            outcome = f"FAIL:{res.reason.value}"

        ulabel = r["user_label"]
        matrix[outcome][ulabel] += 1

        if not res.passed and ulabel in ("good_fit", "maybe"):
            failing_good_maybe.append({
                "job_id": jid,
                "title": r["title"],
                "company": r["company_name"],
                "label": ulabel,
                "reason": res.reason.value,
                "detail": res.detail,
            })

    return {
        "total_unique": len(deduped_rows),
        "matrix": matrix,
        "failing_good_maybe": failing_good_maybe,
    }


def run_part_b(rows: List[Dict[str, Any]], db_jobs: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Part B: NEEDS_REVIEW rows audit (all 23 with reason for ambiguity)."""
    needs_review_jobs = []
    for r in rows:
        jid = r["job_id"]
        job_dict = db_jobs.get(jid)
        res = hf_apply(job_dict)
        if res.reason == FilterReason.NEEDS_REVIEW:
            needs_review_jobs.append({
                "job_id": jid,
                "title": r["title"],
                "company": r["company_name"],
                "user_label": r["user_label"],
                "reachability": job_dict.get("reachable_from_nepal") or r.get("reachability", ""),
                "reachable_reason": job_dict.get("reachable_reason", ""),
                "detail": res.detail,
            })
    return needs_review_jobs


def run_part_c(
    rows: List[Dict[str, Any]],
    db_jobs: Dict[str, Dict[str, Any]],
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Part C: Scorer comparison on the post-HardFilter pool (PASS + NEEDS_REVIEW)."""
    pool_rows = []
    for r in rows:
        jid = r["job_id"]
        job_dict = db_jobs.get(jid)
        res = hf_apply(job_dict)
        if res.passed:  # PASS or NEEDS_REVIEW
            pool_rows.append(r)

    labels = [r["user_label"] for r in pool_rows]
    label_counts = Counter(labels)
    n_good = label_counts.get("good_fit", 0)

    if n_good < 5:
        return {
            "refused": True,
            "reason": f"Fewer than 5 good_fit in pool ({n_good})",
            "label_counts": dict(label_counts),
            "pool_size": len(pool_rows),
        }

    # Binary target: 1 for good_fit, 0 for not-good_fit (maybe or bad_fit)
    y_true = np.array([1 if r["user_label"] == "good_fit" else 0 for r in pool_rows])
    match_scores = np.array([float(r["match_score"] or 0.0) for r in pool_rows])
    laya_scores = np.array([float(r["laya_score"] or 0.0) for r in pool_rows])
    head_scores = np.array([float(r["head_prob_good"] or 0.0) for r in pool_rows])

    auc_match = float(roc_auc_score(y_true, match_scores))
    auc_laya = float(roc_auc_score(y_true, laya_scores))
    auc_head = float(roc_auc_score(y_true, head_scores))

    # Clustered bootstrap by company
    companies = np.array([r["company_name"] for r in pool_rows])
    unique_companies = np.unique(companies)
    rng = np.random.default_rng(seed)

    boot_match = []
    boot_laya = []
    boot_head = []

    for _ in range(n_bootstrap):
        sampled_cos = rng.choice(unique_companies, size=len(unique_companies), replace=True)
        # gather indices
        indices = []
        for co in sampled_cos:
            indices.extend(np.where(companies == co)[0])
        idx = np.array(indices)
        if len(np.unique(y_true[idx])) < 2 or np.sum(y_true[idx]) < 2:
            continue

        boot_match.append(roc_auc_score(y_true[idx], match_scores[idx]))
        boot_laya.append(roc_auc_score(y_true[idx], laya_scores[idx]))
        boot_head.append(roc_auc_score(y_true[idx], head_scores[idx]))

    ci_match = (float(np.percentile(boot_match, 2.5)), float(np.percentile(boot_match, 97.5)))
    ci_laya = (float(np.percentile(boot_laya, 2.5)), float(np.percentile(boot_laya, 97.5)))
    ci_head = (float(np.percentile(boot_head, 2.5)), float(np.percentile(boot_head, 97.5)))

    return {
        "refused": False,
        "pool_size": len(pool_rows),
        "label_counts": dict(label_counts),
        "auc_match": auc_match,
        "ci_match": ci_match,
        "auc_laya": auc_laya,
        "ci_laya": ci_laya,
        "auc_head": auc_head,
        "ci_head": ci_head,
        "pool_rows": pool_rows,
    }


def run_part_d(
    pool_rows: List[Dict[str, Any]],
    db_jobs: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Part D: Embedding baseline (all-MiniLM-L6-v2) whole-text & chunked cosine + t-SNE plot."""
    logger.info("Loading sentence-transformers/all-MiniLM-L6-v2...")
    embedder = SentenceTransformer("all-MiniLM-L6-v2")

    # Build Candidate CV text representation
    with open(CV_PROFILE_PATH, "r", encoding="utf-8") as f:
        profile = json.load(f)
    portfolio_text = PORTFOLIO_PATH.read_text(encoding="utf-8") if PORTFOLIO_PATH.exists() else ""

    primary_skills = [s["name"] for s in profile.get("skills", {}).get("primary", [])]
    secondary_skills = [s["name"] for s in profile.get("skills", {}).get("secondary", [])]
    all_skills = ", ".join(primary_skills + secondary_skills)

    cv_full_text = (
        f"Kshitish Pandit - Full-Stack & AI/ML Software Engineer\n"
        f"Skills: {all_skills}\n"
        f"Target seniority: Junior, Entry-Level, Intern. Remote software developer.\n"
        f"Experience and Projects:\n{portfolio_text}"
    )

    # Chunked CV lines (bullet points, skills, project achievements)
    cv_lines = [
        line.strip()
        for line in cv_full_text.splitlines()
        if len(line.strip()) > 15 and not line.strip().startswith("#")
    ]

    # Pre-embed CV
    cv_emb = embedder.encode(cv_full_text, normalize_embeddings=True)
    cv_line_embs = embedder.encode(cv_lines, normalize_embeddings=True)

    job_texts = []
    job_chunk_scores = []
    y_true = np.array([1 if r["user_label"] == "good_fit" else 0 for r in pool_rows])

    for r in pool_rows:
        jid = r["job_id"]
        db_j = db_jobs.get(jid, {})
        title = r["title"]
        desc = db_j.get("description_text") or ""
        clean_desc = clean_description_text(desc)
        job_full_text = f"{title}\n{clean_desc}"
        job_texts.append(job_full_text)

        # Chunked cosine: split JD into requirements/bullet lines
        jd_lines = [
            line.strip()
            for line in clean_desc.splitlines()
            if len(line.strip()) > 15
        ][:30]  # top 30 requirement lines

        if jd_lines:
            jd_embs = embedder.encode(jd_lines, normalize_embeddings=True)
            # pairwise cosine: (n_jd, n_cv)
            sim_matrix = np.dot(jd_embs, cv_line_embs.T)
            # best CV match per JD line, averaged
            best_per_line = np.max(sim_matrix, axis=1)
            chunked_score = float(np.mean(best_per_line))
        else:
            chunked_score = 0.0

        job_chunk_scores.append(chunked_score)

    logger.info("Encoding %d jobs...", len(job_texts))
    job_embs = embedder.encode(job_texts, normalize_embeddings=True)

    # Whole text cosine similarity
    whole_text_sims = np.dot(job_embs, cv_emb)
    chunked_sims = np.array(job_chunk_scores)

    auc_whole = float(roc_auc_score(y_true, whole_text_sims))
    auc_chunked = float(roc_auc_score(y_true, chunked_sims))

    # 2D t-SNE plot
    all_embs = np.vstack([job_embs, cv_emb[np.newaxis, :]])
    tsne = TSNE(n_components=2, perplexity=min(12, len(all_embs) - 1), random_state=42, init="pca")
    coords = tsne.fit_transform(all_embs)

    job_coords = coords[:-1]
    cv_coord = coords[-1]

    # Plot
    plt.figure(figsize=(10, 7), dpi=150)
    colors = {"good_fit": "#22c55e", "maybe": "#eab308", "bad_fit": "#ef4444"}
    markers = {"good_fit": "o", "maybe": "s", "bad_fit": "x"}

    for label in ["good_fit", "maybe", "bad_fit"]:
        idx = [i for i, r in enumerate(pool_rows) if r["user_label"] == label]
        if idx:
            plt.scatter(
                job_coords[idx, 0],
                job_coords[idx, 1],
                c=colors[label],
                marker=markers[label],
                label=f"{label} (N={len(idx)})",
                alpha=0.85,
                s=70,
                edgecolors="none" if markers[label] == "x" else "black",
                linewidth=0.5,
            )

    # Plot Candidate CV
    plt.scatter(
        [cv_coord[0]],
        [cv_coord[1]],
        c="#3b82f6",
        marker="*",
        s=320,
        label="Candidate CV",
        edgecolors="black",
        linewidth=1.5,
        zorder=10,
    )

    plt.title(
        f"2D t-SNE Embedding Space (all-MiniLM-L6-v2)\nPost-HardFilter Pool (N={len(pool_rows)}) + Candidate CV",
        fontsize=12,
        fontweight="bold",
    )
    plt.xlabel("t-SNE Dimension 1")
    plt.ylabel("t-SNE Dimension 2")
    plt.grid(True, linestyle="--", alpha=0.4)
    plt.legend(frameon=True, facecolor="#f8fafc", edgecolor="#cbd5e1")
    plt.tight_layout()

    OUTPUT_PLOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUTPUT_PLOT_PATH)
    plt.close()
    logger.info("Saved t-SNE plot to %s", OUTPUT_PLOT_PATH)

    return {
        "auc_whole": auc_whole,
        "auc_chunked": auc_chunked,
        "plot_path": str(OUTPUT_PLOT_PATH),
    }


def main():
    rows, db_jobs = load_labeled_jobs()

    # Part A
    part_a = run_part_a(rows, db_jobs)

    # Part B
    part_b = run_part_b(rows, db_jobs)

    # Part C
    part_c = run_part_c(rows, db_jobs)

    # Part D
    part_d = run_part_d(part_c["pool_rows"], db_jobs)

    # Print Report
    print("\n" + "=" * 90)
    print("STEP 7 COMPREHENSIVE AUDIT & EVALUATION REPORT")
    print("=" * 90)

    print("\n--- PART A: LABEL x HARDFILTER TABLE ---")
    print(f"Total labeled jobs de-duplicated by canonical_job_id: {part_a['total_unique']}")
    labels = ["good_fit", "maybe", "bad_fit"]
    hdr = f"{'HardFilter Result':<25} | " + " | ".join(f"{l:<10}" for l in labels) + " | Total"
    print(hdr)
    print("-" * len(hdr))
    matrix = part_a["matrix"]
    for outcome in sorted(matrix.keys()):
        row_str = f"{outcome:<25} | " + " | ".join(f"{matrix[outcome][l]:<10}" for l in labels)
        row_tot = sum(matrix[outcome][l] for l in labels)
        print(f"{row_str} | {row_tot}")
    print("-" * len(hdr))
    tot_str = f"{'TOTAL':<25} | " + " | ".join(f"{sum(matrix[o][l] for o in matrix):<10}" for l in labels)
    grand_tot = sum(sum(matrix[o][l] for l in labels) for o in matrix)
    print(f"{tot_str} | {grand_tot}")

    print(f"\nFailing good_fit / maybe rows ({len(part_a['failing_good_maybe'])} total):")
    for item in part_a["failing_good_maybe"]:
        print(f"  [{item['label']:<8}] {item['title'][:35]:<36} | {item['company'][:18]:<19} | {item['reason']:<15} | {item['detail']}")

    print("\n--- PART B: NEEDS_REVIEW ROWS (N=23) ---")
    for i, item in enumerate(part_b, 1):
        print(f"  {i:>2}. [{item['user_label']:<8}] {item['title'][:35]:<36} | {item['company'][:18]:<19} | {item['reachable_reason']:<30} | {item['detail']}")

    print("\n--- PART C: SCORER COMPARISON ON POST-HARDFILTER POOL ---")
    print(f"Pool size (PASS + NEEDS_REVIEW): {part_c['pool_size']}")
    print(f"Label breakdown in pool: {part_c['label_counts']}")
    print(f"  - MatchScorer AUC:    {part_c['auc_match']:.4f}  [95% CI: {part_c['ci_match'][0]:.4f} - {part_c['ci_match'][1]:.4f}]")
    print(f"  - LayaScorer AUC:     {part_c['auc_laya']:.4f}  [95% CI: {part_c['ci_laya'][0]:.4f} - {part_c['ci_laya'][1]:.4f}]")
    print(f"  - Decision Head v2:   {part_c['auc_head']:.4f}  [95% CI: {part_c['ci_head'][0]:.4f} - {part_c['ci_head'][1]:.4f}]  (NOTE: in-sample)")

    print("\n--- PART D: EMBEDDING BASELINE (all-MiniLM-L6-v2) ---")
    print(f"  - Whole-text Cosine AUC:  {part_d['auc_whole']:.4f}")
    print(f"  - Chunked Requirement AUC:{part_d['auc_chunked']:.4f}")
    print(f"  - 2D t-SNE plot generated: {part_d['plot_path']}")
    print("  - Sample status: Zero-shot embedding model is un-trained on labels (out-of-sample representation, evaluated on pool).")

    print("\n--- PART E: UNVERIFIABLE ITEMS ---")
    print("  1. Out-of-fold generalization performance of Head v2: only 14 good_fit in post-HardFilter pool (19 in full dataset). Grouped 5-fold CV remains invalid.")
    print("  2. Full body text for external ATS jobs where only snippets or raw HTML was scraped without direct ATS markdown.")
    print("  3. Unstated remote policy for 23 NEEDS_REVIEW jobs: without emailing recruiter/company, whether 'Remote' implies worldwide or country-only cannot be strictly verified.")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
