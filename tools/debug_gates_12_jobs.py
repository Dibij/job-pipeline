"""Step 1 & 2: Pick 12 real jobs from DB and debug gate question outputs and polarities."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.laya_scorer import LayaScorer


def run_debug():
    # Pick 12 diverse, verifiable jobs from the DB
    # 4 clearly remote worldwide / english
    # 4 clearly local / hybrid in Germany or specific country
    # 4 others (internships, account managers, etc.)
    rows = execute_query("""
        SELECT id, title, company_name, location_raw, is_remote, description_text, detected_language
        FROM jobs
        WHERE id IN (
            -- Sample specific known jobs from Arbeitnow and Remotive
            SELECT id FROM jobs WHERE nepal_accessible = true AND detected_language = 'english' LIMIT 4
        )
        UNION ALL
        SELECT id, title, company_name, location_raw, is_remote, description_text, detected_language
        FROM jobs
        WHERE id IN (
            SELECT id FROM jobs WHERE detected_language = 'german' LIMIT 3
        )
        UNION ALL
        SELECT id, title, company_name, location_raw, is_remote, description_text, detected_language
        FROM jobs
        WHERE id IN (
            SELECT id FROM jobs WHERE nepal_accessible = false AND detected_language = 'english' LIMIT 5
        );
    """)

    print(f"Fetched {len(rows)} real jobs for gate polarity audit.\n")
    scorer = LayaScorer(device="cpu")

    gate_configs = scorer.config.get("gate_questions", {})

    print("=" * 80)
    print(" GATE CONFIGURATION REFERENCE (FROM laya_questions.yaml):")
    for q_id, q_cfg in gate_configs.items():
        print(f"  - {q_id:<26}: bad_answer={str(q_cfg['bad_answer']):<5} (reason={q_cfg.get('reason_code')})")
        print(f"    Instructions: \"{q_cfg['instructions']}\"")
    print("=" * 80)

    for i, job in enumerate(rows, 1):
        safe_title = job["title"].encode("ascii", "replace").decode("ascii")
        safe_company = job["company_name"].encode("ascii", "replace").decode("ascii")
        safe_loc = (job["location_raw"] or "").encode("ascii", "replace").decode("ascii")

        print(f"\n[{i:02d}] {safe_title} @ {safe_company}")
        print(f"     Location: {safe_loc} | Remote: {job['is_remote']} | Language: {job['detected_language']}")

        res = scorer.score_job(job)

        for q_id, q_cfg in gate_configs.items():
            q_res = res.questions.get(q_id)
            if not q_res:
                continue
            # Laya raw noul: p[1] is probability that statement is TRUE ("yes, statement holds")
            # p[0] is probability that statement is FALSE ("no, statement does not hold")
            p_true = q_res.normalized_value
            p_false = 1.0 - p_true
            bad_dir = "YES (p_true >= 0.5)" if q_cfg["bad_answer"] is True else "NO (p_true < 0.5)"
            
            # Did code treat it as bad?
            is_bad = (q_res.raw_value == q_cfg["bad_answer"])
            status = "TRIGGERED_BAD" if is_bad else "PASS"

            print(f"     - Gate '{q_id}':")
            print(f"         Laya p(true)='yes': {p_true:.4f} | p(false)='no': {p_false:.4f} | conf: {q_res.confidence:.4f}")
            print(f"         Bad Direction: {bad_dir} -> Decision: {status}")

        print(f"     FINAL RESULT: {'PASSED' if res.is_passed else 'DISQUALIFIED'} (Reason: {res.disqualification_reason})")
        print("-" * 80)


if __name__ == "__main__":
    run_debug()
