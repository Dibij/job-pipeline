# Project Progress

## ⚡ Quick Commands Cheatsheet

| Task | PowerShell Command | Note |
| :--- | :--- | :--- |
| **🌐 Web Dashboard** | `& .\.venv\Scripts\python.exe tools/app.py` | Open **http://localhost:5000** in browser |
| **🚀 Generate FEED.md** | `& .\.venv\Scripts\python.exe scripts/export_feed.py` | Exports top matched jobs to `FEED.md` |
| **🔄 Run Daily Pipeline** | `& .\.venv\Scripts\python.exe scripts/run_daily.py` | Fetch → Normalize → MatchScorer → Update FEED.md |
| **📋 Interactive CLI Review** | `& .\.venv\Scripts\python.exe scripts/review_jobs.py` | Review jobs (`y/n/s/q`), saves to `data/reviewed_jobs.json` |
| **📥 Export Labeling Batch** | `& .\.venv\Scripts\python.exe scripts/export_for_labeling.py --no-rescore --batch-size 30` | Creates `data/labeling_batch_YYYYMMDD.csv` |
| **📤 Ingest Human Labels** | `& .\.venv\Scripts\python.exe scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv` | Ingests CSV into `laya_labels` in Postgres |
| **🎯 Calibrate Laya** | `& .\.venv\Scripts\python.exe scripts/calibrate_laya.py --version v1` | Fits temperature scaling on human labels |

---

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
- **Total Test Suite**: 81 passed, 0 failures! (+5 seniority regression tests from 5b.1 audit)

## Session — Oct 9 2026
- **CUDA enabled**: `torch 2.5.1+cu121`, RTX 2050 confirmed (`torch.cuda.is_available() = True`).
- **DB refreshed**: 1,194 jobs now (was 618, +576 new from Arbeitnow/Remotive). MatchScorer re-run on all.
- **Task 5b.2 — Seniority fix**: Body-only `5+/6+ years` no longer → `senior`. Now requires explicit must-have language + 7+ years. Word `seniority` no longer triggers. Title always wins. 5 regression tests added.
- **Task 5b.3 — HardFilter**: New `src/matching/hard_filter.py`. Typed `FilterReason` codes: `GERMAN_ONLY`, `UNPAID`, `REGION_LOCKED`, `NOT_REMOTE`. `service.py` now runs HardFilter first; failed jobs skip scoring and are stored with reason_code. Sample on 300 jobs: 65 German, 9 unpaid, 211 on-site-abroad caught.
- **Task 7.8a — Calibration fix**: `calibrate_laya.py` rewritten. Removed train/val split (caused n_eval=0 with 34 labels). Now uses all 34 labels for fitting, `compute_ece=False` until 150+. Removed silent fake-value fallback. Re-run needed (other AGY instance handling).

## What's Broken / Incomplete
- Real fine-tuning (Task 7.8b) gated pending human labels (`laya_labels` count < 150).
- Task 7.7 (labeled CSV evaluation vs MatchScorer) not started — user will label jobs next.
- Full Laya batch scoring (`score_jobs.py` without `--limit`) on 1,194 jobs — pending CUDA confirmation then run with `--device cuda`.
- Phase 6 output layer (FEED.md, CLI review, daily runner, dashboard) — in progress this session.

## Next Step
- Run fixed `calibrate_laya.py --version v1` to get real temperatures.
- Run `score_jobs.py` (no limit) with CUDA device for full Laya scoring.
- Phase 6.1: FEED.md exporter → actionable daily digest of top jobs.

