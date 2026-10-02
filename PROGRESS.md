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
- Task 7.8 Calibration & Fine-Tuning Scaffolding complete:
  - Researched Laya architecture: ModernBERT encoder is frozen; decision heads use RLCD (`laya.proper_reward` with Brier score loss) or supervised cross-entropy.
  - Added migration `src/db/migrations/003_laya_labels.sql` for `laya_labels` table.
  - `scripts/export_for_labeling.py`: exports unlabeled jobs sorted by lowest confidence + random distribution.
  - `scripts/ingest_labels.py`: ingests and validates human labels without overwriting.
  - `scripts/calibrate_laya.py`: temperature fitting for Task 7.8a using `laya.fit_temperatures`.
  - `scripts/train_laya.py`: supervised decision head trainer for Task 7.8b with verified `--dry-run` and strict refusal safeguard (< 150 labels).
  - `TRAINING.md`: comprehensive documentation of architecture, GPU memory requirements (4GB RTX 2050 compatibility), and step-by-step labeling guide.
- **Total Test Suite**: 63 passed, 0 failures!

## What's Broken / Incomplete
- Real fine-tuning (Task 7.8b) is intentionally gated pending human labels (`laya_labels` count < 150).
- Task 7.5 (confidence gating in storage) & Task 7.6 (PostgreSQL table `laya_job_scores`).

## Next Step
- Task 7.5 / 7.6: Create `laya_job_scores` table migration and batch-score pipeline to persist all Laya predictions alongside existing baseline `job_matches`.
