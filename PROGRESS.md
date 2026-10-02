# Project Progress

## Current State
- Phase 1, Phase 2, Phase 3, and Phase 5 complete!
- 618 unique jobs stored in PostgreSQL with rule-based baseline `MatchScorer`.
- Task 5b.1 Seniority Audit completed (report on 30 jobs).
- Task 7.1 Laya Spike completed locally:
  - **Model**: `convaiinnovations/laya` (ModernBERT-large, 421M parameters).
  - **Inference speed**: ~2.8s per forward pass on CPU.
  - **Limit**: 1,024 max tokens.
- Task 7.2 JD Section Extractor complete (`src/matching/jd_extractor.py`) with 24 tests.
- Task 7.3 Token Budget Truncation complete (`src/matching/jd_truncator.py`):
  - **Calculated JD text budget (`LAYA_INPUT_TOKEN_BUDGET`)**: **566 tokens** (saved in `config/token_budget.json`).
  - 6 unit & integration tests covering very long, very short, empty, priority, and real PostgreSQL database JDs.
- Task 7.4 Typed Questions & Scoring complete (`src/matching/laya_scorer.py`):
  - Schema loaded from `config/laya_questions.yaml` (never hard-coded).
  - Evaluated on 10 real database jobs: gates correctly disqualify region-locked and non-technical roles with reason codes.
  - 5 tests covering formula normalization, gate disqualification, penalty application, and confidence review gating.
- Task 7.4b Gate Debugging complete (`src/matching/laya_scorer.py`, `config/laya_questions.yaml`):
  - **Empirical Gate & Polarity Audit**: Analyzed real database jobs. Verified Laya's `noul` outputs $P(\text{true})$. Polarity in code is correct ($P(\text{bad}) = \text{noul}$ when `bad_answer=True`, $1-\text{noul}$ when `bad_answer=False`).
  - **Root Cause**: Zero-shot uncalibrated predictions hover near 0.50–0.75 for language and work-authorization questions even on English jobs. The previous 0.55 threshold was overly aggressive.
  - **Warn-Only Mode**: Defaulted `gates_warn_only: true` in config. Laya gates now flag warnings in `gate_warnings` without disqualifying. Plain-code hard filters remain the sole disqualifiers until calibration (Task 7.8a).
  - **High Configurable Threshold**: Added `gate_disqualify_threshold: 0.90` for post-calibration activation.
  - **Polarity Unit Tests**: Added unit tests pinning down polarity for `bad_answer: true` and `bad_answer: false`, warn-only mode, and threshold boundary checks.
  - **Terminology Fix**: Updated `TASKS.md` and `TRAINING.md` to specify "supervised head training with proper scoring rules (Brier/RPS)" citing `laya.proper_reward` docstring.
- **Total Test Suite**: 65 passed, 0 failures!

## What's Broken / Incomplete
- Real fine-tuning (Task 7.8b) is intentionally gated pending human labels (`laya_labels` count < 150).
- Task 7.5 (confidence gating in storage) & Task 7.6 (PostgreSQL table `laya_job_scores`).

## Next Step
- Task 7.5 / 7.6: Create `laya_job_scores` table migration and batch-score pipeline to persist all Laya predictions alongside existing baseline `job_matches`.
