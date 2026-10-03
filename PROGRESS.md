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
  - **Empirical Gate & Polarity Audit**: Verified Laya's `noul` outputs $P(\text{true})$. Polarity in code is correct.
  - **Root Cause**: Zero-shot uncalibrated predictions hover near 0.50–0.75. Old 0.55 threshold was too aggressive.
  - **Warn-Only Mode**: `gates_warn_only: true` in config. Laya gates flag warnings without disqualifying.
  - **High Configurable Threshold**: `gate_disqualify_threshold: 0.90` for post-calibration activation.
  - **Polarity Unit Tests**: Polarity pinned down for all gate directions, warn-only mode, and threshold boundary.
  - **Terminology Fix**: Updated `TASKS.md` and `TRAINING.md` to specify "supervised head training with proper scoring rules (Brier/RPS)".
- **Gate Cleanup (pre-7.5):**
  - Removed `requires_other_language` gate from `config/laya_questions.yaml`. Language is detected by enrichment (`detected_language` column) and filtered by plain-code hard filter. No Laya pass needed.
  - Added `gate_warn_threshold: 0.85` (configurable). Only records a gate_warning when `p_bad >= 0.85`. Suppresses noisy zero-shot noise until calibration.
  - Removed gate warnings from the 10-job summary table (still in per-job detail). Raw probabilities still stored.
- **Task 7.5 (needs_review flag):**
  - Added `use_confidence_flag: false` to `config/laya_questions.yaml`.
  - `needs_review` flag is always **computed** (low confidence on any question sets it), but never used to filter or rank while `use_confidence_flag = false`.
  - Tests confirm flag is stored but scoring proceeds regardless.
- **Task 7.6 (laya_job_scores table + batch scoring):**
  - Migration `004_laya_job_scores.sql` applied. Table has: `final_score`, `is_passed`, `disqualification_reason`, `needs_review`, `role_type`, `gate_warnings` (JSONB), `per_question_data` (JSONB), `laya_checkpoint`, `config_version`, `tokens_used`, `scored_at`.
  - Unique constraint `(job_id, laya_checkpoint, config_version)` makes batch scoring resumable.
  - `scripts/score_jobs.py`: fetches English/accessible jobs, skips already-scored, shows live progress with ETA and time-per-job.
  - Ran `--limit 20` to get timing baseline before full run.
- **Total Test Suite**: 76 passed, 0 failures!

## What's Broken / Incomplete
- Real fine-tuning (Task 7.8b) intentionally gated pending human labels (`laya_labels` count < 150).
- Task 7.7 (labeled CSV evaluation vs MatchScorer) not started — user will label jobs next.
- Full batch scoring (`scripts/score_jobs.py` without `--limit`) pending user's timing review of the 20-job run.

## Next Step
- User reviews 20-job timing output, then approves full run: `python scripts/score_jobs.py`
- After that: **Task 7.7** — label 30–50 jobs and compare MatchScorer vs Laya vs labels.
- Do NOT start 7.7 or 7.8 training until user confirms labeling is ready.
