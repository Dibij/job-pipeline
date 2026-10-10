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

## Current State (Oct 10 2026)

### Infrastructure
- Phase 1, Phase 2, Phase 3, Phase 5, and Phase 6 complete.
- 1,194 unique jobs in PostgreSQL (576 added Oct 9). MatchScorer re-run on all.
- CUDA enabled: `torch 2.5.1+cu121`, RTX 2050 confirmed.
- Task 5b.2 seniority fix and Task 5b.3 HardFilter complete.
- Task 7.1-7.7 Laya spike, JD extraction, truncation, typed questions, confidence gating, batch scoring, and labeling scaffolding all complete.
- Task 7.8a `calibrate_laya.py` rewritten (removed train/val split that caused n_eval=0).

### Labeling (as of Oct 10 2026)
86 human labels in `laya_labels`:

| Label | Count | % |
|-------|-------|---|
| `bad_fit` | 65 | 75.6% |
| `maybe` | 12 | 14.0% |
| `good_fit` | 9 | 10.5% |

The ~10% `good_fit` rate reflects the source bias (Arbeitnow, Remotive skew senior/US/EU). This is not a labeling error.

### Key Decisions Recorded (Oct 10 2026)
See `TRAINING.md` for full rationale. Summary:

1. **Two datasets**: MEASURE/CALIBRATE set preserves natural distribution (never rebalanced). TRAIN set (7.8b only, train split only) may be rebalanced.
2. **Training gated on both** total labels >= 150 AND `good_fit` >= 30 (`min_positive_labels`, configurable, default 30).
3. **Binary primary view**: `good_fit` vs not. `maybe` = not good_fit. 3-class view reported as secondary.
4. **Evaluation**: repeated stratified grouped k-fold; metrics are precision@k, recall@k, PR-AUC with bootstrap CIs. Primary metric is `recall@20`. Never report raw accuracy.
5. **Labeling queue strata**: 40% random, 30% high MatchScorer, 30% Laya-uncertainty (last stratum deferred until 7.8a calibration is done).
6. **No uncalibrated Laya gating**: raw probabilities (~0.10-0.26) are stored only; never used to discard jobs or decide labeling priority.
7. **Label hygiene**: Laya columns must be hidden from the export CSV; accepting Laya's suggestion is not allowed. `label_guideline_version` must be recorded per row.
8. **`noul` correction**: it is Laya's boolean primitive (P(yes)), not a nuance/variance signal. Checkpoint is uncalibrated until 7.8a; never call outputs "calibrated confidence" before that.

---

## What's Broken / Incomplete
- Task 7.7b NOT STARTED: `laya_labels` table missing `sampling_stratum` and `label_guideline_version`; export CSV still shows Laya columns.
- Task 7.8a NOT RUN yet with the fixed calibrate script (needs re-run after Oct 9 fix).
- Task 7.8b BLOCKED: needs 150+ labels and 30+ `good_fit` (currently 9).
- Task 7.9 NOT STARTED: no per-source / per-stratum report script.
- Full Laya batch scoring (`score_jobs.py` without `--limit`) on 1,194 jobs -- pending.
- Task 6.4 (dashboard wired to hard-filter output) -- not started.

---

## Next Step
**Task 7.7b** -- add `sampling_stratum` and `label_guideline_version` to the labeling schema and hide Laya columns from the export CSV. This unblocks clean stratified labeling towards M1 (150 labels).
