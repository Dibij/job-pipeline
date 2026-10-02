"""Task 7.4: Run LayaScorer on 10 real jobs and display per-question breakdown."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.laya_scorer import LayaScorer


def run_evaluation(limit: int = 10):
    print("=" * 70)
    print("       LAYA SCORING: 10 REAL JOBS EVALUATION")
    print("=" * 70)

    # Fetch 10 diverse jobs that pass language check
    rows = execute_query("""
        SELECT id, title, company_name, location_raw, is_remote, description_text
        FROM jobs
        WHERE detected_language = 'english'
        ORDER BY id
        LIMIT %s;
    """, (limit,))

    if not rows:
        print("No jobs found in database.")
        return

    scorer = LayaScorer(device="cpu")
    print("\nModel ready. Scoring jobs...\n")

    results = []
    for i, job in enumerate(rows, 1):
        result = scorer.score_job(job)
        results.append((job, result))
        safe_title = job["title"].encode("ascii", "replace").decode("ascii")
        safe_company = job["company_name"].encode("ascii", "replace").decode("ascii")

        print(f"[{i:02d}] {safe_title} @ {safe_company}")
        print(f"     Status: {'PASSED' if result.is_passed else 'DISQUALIFIED'} | "
              f"Final Score: {result.final_score:.1f}/100 | "
              f"Role: {result.role_type} | "
              f"Needs Review: {result.needs_review} | "
              f"Tokens: {result.tokens_used}")

        if result.gate_warnings:
            print(f"     Gate Warnings: {', '.join(result.gate_warnings)}")

        if not result.is_passed:
            print(f"     Reason: {result.disqualification_reason}")

        print("     Per-Question Breakdown:")
        for q_id, q_res in result.questions.items():
            if q_res.question_type == "score":
                print(f"       - [SCORE] {q_id:<20}: raw={q_res.raw_value:.2f}/4.0 -> norm={q_res.normalized_value:.1f}/100 (conf={q_res.confidence:.2f})")
            elif q_res.question_type == "choice":
                print(f"       - [CHOICE] {q_id:<19}: '{q_res.raw_value}' (+{q_res.normalized_value:.0f} pts, conf={q_res.confidence:.2f})")
            elif q_res.question_type == "noul":
                val_str = "YES" if q_res.raw_value else "NO"
                print(f"       - [BOOL]  {q_id:<20}: {val_str:<3} (p={q_res.normalized_value:.2f}, conf={q_res.confidence:.2f})")

        print("-" * 70)

    # Print summary table
    print("\n" + "=" * 90)
    print("                     10-JOB EVALUATION SUMMARY (WARN-ONLY MODE)")
    print("=" * 90)
    print(f"{'#':<3} | {'Company':<15} | {'Title':<28} | {'Score':<6} | {'Status':<6} | {'Warnings'}")
    print("-" * 90)
    for i, (job, res) in enumerate(results, 1):
        comp = job['company_name'][:14]
        tit = job['title'][:27]
        warns = ", ".join(res.gate_warnings) if res.gate_warnings else "None"
        status = "PASS" if res.is_passed else "DISQ"
        print(f"{i:<3} | {comp:<15} | {tit:<28} | {res.final_score:5.1f} | {status:<6} | {warns}")
    print("=" * 90)


if __name__ == "__main__":
    run_evaluation(10)
