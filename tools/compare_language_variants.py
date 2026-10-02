"""Test language gate question variants on English jobs to compare behavior."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query
from src.matching.jd_extractor import extract_sections
from src.matching.jd_truncator import build_truncated_laya_state
import laya

def test_variants():
    # Pick Deliveroo, Voleon, Destinus, Voodoo, Artefact + 1 French job
    job_ids = [
        '00e247a1-3a94-4807-bcce-c115990a7d99', # Deliveroo
        '018b84ba-2339-415b-b272-552a004df10f', # Voleon
        '0216a7ad-dfad-453c-9229-b81e0e24554a', # Destinus
        '02eb8819-0890-475d-ab56-ba7553386c45', # Voodoo
        '03187523-3cb0-4154-99ba-fff6736be365', # Artefact
        '00179e61-0fb6-4e5f-baba-77b167209eac', # PRECIA MOLEN (French)
    ]
    
    rows = execute_query(
        "SELECT id, title, company_name, location_raw, description_text FROM jobs WHERE id = ANY(%s)",
        (job_ids,)
    )

    agent = laya.load("convaiinnovations/laya", device="cpu")

    questions = {
        "var_a_neg": {
            "type": "noul",
            "instructions": "Does this job require fluency in a language other than English?"
        },
        "var_b_pos": {
            "type": "noul",
            "instructions": "Is the job posting written in English?"
        },
        "var_c_pos": {
            "type": "noul",
            "instructions": "Is English the primary language for this job?"
        },
    }

    print(f"{'Company':<15} | {'Title':<30} | {'Var A (non-Eng?)':<18} | {'Var B (written Eng?)':<20} | {'Var C (primary Eng?)':<20}")
    print("-" * 115)

    for job in rows:
        sections = extract_sections(job["description_text"], job["title"], job["company_name"], job["location_raw"])
        state = build_truncated_laya_state(sections, tokenizer=agent.tok)
        res = laya.decide(agent, state, questions=questions, return_details=True)
        
        va = res.values.get("var_a_neg", {}).get("noul", 0.0)
        vb = res.values.get("var_b_pos", {}).get("noul", 0.0)
        vc = res.values.get("var_c_pos", {}).get("noul", 0.0)
        
        comp = job["company_name"][:14]
        tit = job["title"][:29]
        print(f"{comp:<15} | {tit:<30} | p(yes)={va:.3f}          | p(yes)={vb:.3f}            | p(yes)={vc:.3f}")

if __name__ == "__main__":
    test_variants()
