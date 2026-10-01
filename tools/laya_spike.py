"""Task 7.1 Spike: Run Laya locally on one hard-coded example and print raw output."""
import time
import laya

print("=" * 60)
print("  LAYA MODEL SPIKE TEST")
print("=" * 60)

# 1. Load model and record loading time
print("\n[1/3] Loading Laya model ('convaiinnovations/laya')...")
t0 = time.perf_counter()
# Explicitly use CPU (or CUDA if torch cuda available)
device = "cpu"
agent = laya.load("convaiinnovations/laya", device=device)
load_time = time.perf_counter() - t0
print(f"Model loaded successfully in {load_time:.2f}s on {device.upper()}!")

# 2. Hard-coded sample job description
sample_job_state = {
    "title": "Junior Python / Django Developer",
    "company": "KoboToolbox",
    "location": "Remote - Worldwide",
    "experience": "0-1 years of experience, fresh graduates welcome",
    "description": (
        "We are looking for a Junior Backend Developer to join our core team. "
        "You will build REST APIs using Python and Django, write unit tests, and collaborate with frontend developers. "
        "Requirements: solid understanding of Python, Git, and relational databases (PostgreSQL). "
        "Compensation is $25-$35/hr, 100% remote with flexible hours."
    )
}

# 3. Define typed questions (score, noul, choice)
questions = {
    "skills_fit": {
        "type": "score",
        "instructions": "Rate how well this job matches a junior Python and Django developer",
        "criteria": [
            "completely unrelated",
            "poor match",
            "partial match",
            "strong match",
            "perfect match"
        ]
    },
    "is_remote": {
        "type": "noul",
        "instructions": "Is this position 100% remote and open globally?"
    },
    "seniority_level": {
        "type": "choice",
        "instructions": "What experience level is required for this role?",
        "criteria": {
            "junior": "entry-level, 0-2 years, fresh graduates, or junior",
            "mid": "mid-level, 2-5 years experience",
            "senior": "senior, lead, staff, principal, or 5+ years experience",
            "unspecified": "no clear experience level stated"
        }
    }
}

# 4. Predict
print("\n[2/3] Running prediction on hard-coded sample...")
t_inf_start = time.perf_counter()
raw_result = laya.decide(agent, sample_job_state, questions=questions, return_details=True)
inf_time_ms = (time.perf_counter() - t_inf_start) * 1000

# 5. Output
print(f"\n[3/3] Inference completed in {inf_time_ms:.1f} ms!")
print("\n--- RAW LAYA OUTPUT ---")
print(raw_result)

if hasattr(raw_result, "__dict__"):
    print("\n--- ATTRIBUTES ---")
    for k, v in raw_result.__dict__.items():
        print(f"  {k}: {v}")
