# Laya Training & Calibration Workstream (`TRAINING.md`)

This document tracks the calibration and fine-tuning engineering for Laya (Task 7.8). It is self-contained so any session can pick up the workstream directly.

---

## 1. Current State
* **Spike and Scoring Active**: Base checkpoint `convaiinnovations/laya` (ModernBERT-large, 421M params). Inference on CPU takes ~15–20s per full JD (on CUDA RTX 2050 ~40ms).
* **Database Table Active**: `laya_labels` (in `src/db/migrations/003_laya_labels.sql`, `007_labeling_schema.sql`, `010_laya_labels_gates.sql`, `011_widen_label_stratum.sql`, `012_add_exclude_reason.sql`, `013_job_llm_features.sql`, and `014_add_job_matches_reason_code.sql`) stores human fit labels with 5-gate audit columns and explicit `exclude_reason`.
* **Current Human Labeled Dataset**: **30 labels (24 `bad_fit`, 5 `maybe`, 1 `good_fit`) as of 2026-11-09**, first labeling session in progress. The 2026-11-06 Linux rebuild recreated the database; the old Windows labels were not migrated, and the stale `data/labeled_jobs_*.jsonl` exports were archived to `data/pre_rebuild_20261106/`. Run `export_labeled_descriptions.py` after labeling. Historical pre-rebuild state (2026-10-29) was 147 distinct `v2_role_fit_only` jobs / 266 events (`bad_fit` 201/110, `maybe` 55/32, `good_fit` 10/5). The 20 legacy `good_fit` jobs are also gone.
  - **22 Ollama suggestions** pending human review in `data/triage_suggestions_20261106_2017.json` (15 `maybe`, 5 `bad_fit`, 2 `good_fit`). The old 2026-10-29 file references deleted UUIDs.
* **In-Browser Labeling Active**: `app.py` writes directly to `laya_labels` stamped with `label_guideline_version="v2_role_fit_only"`, supporting rapid interactive review with Feed & Rejected tabs without CSV round-trips. It does not populate the 5 gate audit columns.
* **Training Gate Status**: **30/150 v2 labels**, **1/30 role-fit `good_fit`** as of 2026-11-09. Label from scratch in `app.py` or via the triage ingestion flow.
* **Scaffolding & Execution Operational**:
  1. `scripts/make_labeling_batch.py`: Exports balanced batches (70% title-rule score, 30% random) with company historical caps ($\le 5$) stamped `v2_role_fit_only`.
  2. `scripts/ingest_labels.py`: Ingests and validates human labels (`good_fit`, `maybe`, `bad_fit`) without overwriting old records.
  3. `scripts/train_title_classifier.py`: Trains char n-gram TF-IDF title classifier (`src/matching/title_classifier.py`) providing soft role penalties. The claimed +12.7% recall / 0.000 FPR is unverified (no committed report).
  4. `scripts/train_ranker.py`: Trains production ranker strictly gated on $\ge 150$ v2 labels and $\ge 30$ role-fit `good_fit` positives with bootstrap 95% CIs and ElevenLabs ablation.
  5. `scripts/report_labels.py`: Comprehensive audit script reporting source yield, stratum yield, gate checks, and comparative model metrics (precision@10, recall@10, recall@20, PR-AUC).
  6. `scripts/smart_label_triage.py`: Active-learning triage — buckets unlabeled eligible jobs by MatchScorer/Laya agreement, routes CONFLICT/UNCERTAIN to Ollama `qwen2.5:3b` for label suggestions. Output saved to `data/triage_suggestions_*.json`.
  7. `scripts/ingest_triage_suggestions.py`: Interactive CLI to review Ollama label suggestions before any DB write. `--auto-ingest` for high-confidence (≥80%) batch apply.



---

## 2. Research Findings on Laya Architecture & Scoring Rules
From package inspection of `laya` (specifically `laya.proper_reward` and `laya.RLAgent`):
* **Encoder Backbone**: ModernBERT-large (421M parameters) for English, mmBERT-base (322M) for multilingual.
* **Scoring Rules & Training**: The package provides `laya.proper_reward`, documented as:
  > *"Strictly proper scoring rule reward: log score + spherical score + ranked probability score. q: [..., N, K] reported distributions, target: [N, K]"*
  The official package does not explicitly document "RLCD"; therefore, the training approach is accurately described as **supervised head training with proper scoring rules (Brier/RPS)**.
* **Decision Heads**: The encoder produces pooled sentence embeddings (1024-dim), which pass into lightweight multi-task classification heads for `score`, `choice`, and `noul` decisions.
* **Trainable vs Frozen**: Fine-tuning keeps the 421M parameter ModernBERT backbone **frozen** and optimizes only the classification heads. This dramatically reduces memory and compute requirements.

---

## 3. Hardware & GPU Compatibility Analysis

### Current Machine Configuration
* **GPU**: NVIDIA GeForce RTX 2050 Laptop GPU (4,096 MiB / 4 GB VRAM).
* **CUDA Torch**: `torch 2.15.0+cu132` installed in `.venv` (2026-11-06), RTX 2050 confirmed (`torch.cuda.is_available() = True`).
* **Available VRAM at Idle**: ~2.8 GB free (display and Windows system processes use ~1.1 GB).

### What Fits in 4 GB VRAM (and what does NOT):
* **FITS in 4 GB VRAM**:
  - **Inference (Evaluation & Scoring)**: ModernBERT-large weights take ~840 MB in fp16/bf16. Running forward passes with batch size 1-2 takes ~1.2 GB VRAM total. This drops latency from ~2.8s down to ~40 ms per job.
  - **Decision Head Training (Task 7.8b)**: Because the ModernBERT encoder is **frozen**, we only compute gradients for the small linear head (~1-2 MB of weights). Optimizer state and activations take < 200 MB. Pre-computing and caching the 1024-dim embeddings to disk allows training the head in seconds using < 500 MB of VRAM.
  - **Temperature Fitting (Task 7.8a)**: Runs purely on output probability vectors; consumes virtually zero GPU memory (< 50 MB).
* **DOES NOT FIT in 4 GB VRAM (Will OOM)**:
  - **Full-Model End-to-End Backpropagation**: Training all 421M parameters of ModernBERT-large un-frozen with AdamW requires Model weights (fp16): 842 MB + Gradients: 842 MB + AdamW optimizer states (fp32): ~3.3 GB + Transformer activations (seq len 1024): ~1.5 GB = **> 6.5 GB VRAM** (will crash with CUDA Out of Memory on a 4GB GPU).
  - Therefore, fine-tuning must strictly keep the encoder frozen (or use LoRA/QLoRA if encoder tuning is ever desired).

---

## 4. Safeguards Enforced in Code
1. **Refusal on Small Datasets**: `scripts/train_laya.py` strictly refuses to train if labeled rows < 150 **and** if `good_fit` labels < `min_positive_labels` (configurable, default 30). Fine-tuning a decision head with 9 positives cannot learn anything useful.
2. **No Training on Predictions**: Training queries only rows from `laya_labels` where human labels exist. Never treats Laya's own guesses as truth.
3. **Grouped k-fold Split**: Data is split by `job_id` using repeated stratified grouped k-fold (see Section 7). Near-duplicates (same company + title) are grouped into the same fold. No job leaks across folds.
4. **Versioned Checkpoints**: Weights are saved under `models/laya_head_{version}/` and gitignored. Original base weights are never overwritten.
5. **No Uncalibrated Gating**: Laya's raw score/gate outputs (currently 0.10-0.26 range on score questions) are stored but never used to discard jobs or decide labeling priority until 7.8a calibration is done.

---

## 5. Workflow Guide

### Step 1: Export Jobs for Labeling
```bash
.venv/bin/python scripts/make_labeling_batch.py --batch-size 30
```
This is the current 70/30 title-rule/random generator (`--batch-size` aliases `--count`). The older `scripts/export_for_labeling.py` (40/30/30 strata) is still available for the legacy protocol in Section 6.5. Both now stamp `v2_role_fit_only` and hide Laya columns.

### Step 2: Human Labeling
Open the CSV and fill the `my_label` column using the definitions in Section 6.3. **Never accept Laya's suggestion as a default -- a skipped job is unlabeled, not `bad_fit`.**

### Step 3: Ingest Labels
```bash
.venv/bin/python scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv
```

### Step 4: Calibrate Temperatures (Task 7.8a) -- M1
Once ~150 labels (including the random stratum) are reached:
```bash
.venv/bin/python scripts/calibrate_laya.py --version v4
```
Uses natural-distribution data (or stratum-weighted data) to preserve real class rates. `v3` exists but is a no-op artifact (`n_eval=0`, all temperatures 1.0); use the next free version tag.

### Step 5: Decision Head Fine-Tuning (Task 7.8b) -- M3
Once the gate clears (>=150 v2 labels and >=30 `good_fit`) and a fresh calibration has been validated:
```bash
.venv/bin/python scripts/train_laya.py --version v3
```

---

## 6. Labeling Strategy & Class Balance

### 6.1 Observed Distribution (historical, Oct 2026 — pre-rebuild)
86 labels were ingested at the time; the current DB has 0 labels:

| Label | Count | % |
|-------|-------|---|
| `bad_fit` | 65 | 75.6% |
| `maybe` | 12 | 14.0% |
| `good_fit` | 9 | 10.5% |

The ~10% `good_fit` rate is a **property of the data sources** (Arbeitnow, Remotive skew senior and US/EU). It is not a labeling error and must not be artificially rebalanced in the calibration or evaluation set.

### 6.2 Two Datasets with Different Rules

**MEASURE / CALIBRATE set** (used for 7.8a and all evaluation metrics):
- Must reflect the real stream (natural distribution), or be a stratified sample with stratum and inclusion weights recorded so natural rates can be recovered.
- **Never rebalance this set.** Calibration fitted on an artificial mix gives wrong probabilities for the real stream.

**TRAIN set** (used only in 7.8b, train split only):
- May be rebalanced using class weights or by downsampling `bad_fit`.
- The **held-out fold** within 7.8b is never rebalanced -- same rule as the MEASURE set.

### 6.3 Label Definitions: `v2_role_fit_only`
> **CANONICAL STANDARD: All current and future labels are stamped `label_guideline_version="v2_role_fit_only"`.**

#### Core Design Principle
- **Facts about a job are RULES**: Unpaid status, language, remote/region locks, minimum years required, and extreme seniority words are handled deterministically by `HardFilter` rules (`src/matching/eligibility.py`).
- **Judgments about whether a job suits me are LEARNED from my labels**: Role fit asks only: *"Does this kind of technical work and level suit me?"*
- **Ignore location, work authorization, and years-required**: These are handled upstream by filters. Do not reject a job for being US-only or requiring 5 years of experience if the actual work is an ideal junior developer role.

| Label | Canonical Meaning under `v2_role_fit_only` |
|---|---|
| `good_fit` | The role, stack, and day-to-day work suit me (e.g. junior/entry/mid Python, AI/ML, backend, frontend, full-stack, data engineering). |
| `maybe` | Borderline work fit: partial stack overlap, ambiguous technical scope, or adjacent engineering domain. |
| `bad_fit` | Work does not suit me: pure management/director roles, non-technical positions (sales, recruiting, copywriter, customer support), or irrelevant technical domains (e.g. senior mainframe COBOL, hardware firmware). |

#### Strict Label Hygiene Rules
- **Exactly Three Classes**: Every label must be exactly `good_fit`, `maybe`, or `bad_fit`.
- **Never add a fourth class**: Never use `drop`, `unknown`, `blank`, or `unusable` as label values.
- **Exclusion Mechanism**: Unusable rows (e.g. corrupted text, unparseable HN comments, non-junior ATS boards) are flagged via the `exclude_reason` column (Migration 012), never by inventing a label. Excluded rows are omitted from training datasets.

### 6.4 Labeling Hygiene Rules
- Every label comes from the human labeler. Accepting Laya's output as a default is **not allowed**.
- Laya's answers must not be visible while labeling (anchoring bias). Task 7.7b tracks moving Laya columns out of the export CSV or hiding them until after the label is entered.
- A skipped job is **unlabeled**, never `bad_fit`.
- **Pre-Export HardFilter Enforcement (Phase 8 / tmp/4.txt)**: All exported candidate jobs must pass `HardFilter.apply()` (via shared `src/matching/eligibility.py`) to prevent ITAR defense restrictions, US-citizen locks, and non-technical titles from leaking into human labeling batches.

### 6.5 Labeling Queue -- Sampling Strata
Each exported job must have a `sampling_stratum` field recorded in `laya_labels.metadata`:

| Stratum | Default share | Selection rule |
|---------|--------------|----------------|
| `random` | 40% | Uniformly sampled from the natural stream after hard filters. Must always be present -- provides unbiased rates for calibration. |
| `high_match_scorer` | 30% | Highest MatchScorer scores among unlabeled, hard-filter-passing jobs. Finds positives using a signal independent of Laya. |
| `laya_uncertainty` | 30% | Jobs where calibrated Laya confidence is lowest. **Only active after 7.8a calibration is verified.** If uncalibrated or if insufficient Laya-scored eligible jobs exist, fill remainder from the `random` eligible pool to avoid picking senior, score-0 jobs. |

> **Important**: Do not use uncalibrated Laya outputs to discard jobs or decide labeling order. Raw confidence scores (~0.10-0.26 on score questions) are noise, not signal, until calibration is verified. When Laya-scored eligible jobs are fewer than the allocated batch share, automatically fall back to the random pool.

### 6.6 Per-Source Tracking
Track `good_fit` rate per source and per stratum (Task 7.9 report script). This makes it visible when a new source (e.g. Nepal-friendly boards) actually improves yield.

---

## 7. Evaluation Protocol (Small-Data Regime)

### 7.1 Cross-Validation Strategy
Use **repeated stratified grouped k-fold** instead of a single train/test split:
- Group by `job_id` so no job leaks across folds.
- Also group near-duplicates (same company + title) into the same fold.
- Stratify by label so each fold preserves the natural `good_fit` rate.

> With fewer than ~30 `good_fit` labels, all results are **indicative only**. Report this caveat explicitly alongside every metric.

### 7.2 Metrics
**Primary metric** (a missed good job costs more than a wasted look -- prioritize recall):
- `recall@20` -- fraction of all `good_fit` jobs that appear in the top 20 ranked results.

**Full reported set** (all with bootstrap 95% confidence intervals):
- `precision@10`, `precision@20`
- `recall@10`, `recall@20`
- `PR-AUC` for the `good_fit` class (binary view)

**Never report raw accuracy** -- it is dominated by the `bad_fit` majority and is misleading.

### 7.3 Binary vs Three-Class View
- **Primary view**: binary (`good_fit` vs not). `maybe` maps to `not good_fit`.
- **Secondary view**: three-class reported alongside for completeness.
- All 3 labels are always kept in the DB; only the view used for a specific metric changes.

### 7.4 Comparison Baseline
Every metric must be computed for **both** Laya and the rule-based MatchScorer on the same folds.

---

## 8. Laya Primitives -- Corrections & Clarifications

### 8.1 What `noul` actually is
`noul` is Laya's **boolean primitive**: it returns the probability that a yes/no statement is true -- specifically `p[1] = P(yes)`. Confirmed empirically in task 7.4b via polarity pinning tests.

> **Correction**: `noul` is **not** a nuance, tension, or variance signal. Any earlier description of it as such is incorrect.

### 8.2 Calibration status
The `convaiinnovations/laya` checkpoint ships **uncalibrated temperatures**. Its raw output probabilities must never be described as "calibrated confidence" until task 7.8a has been completed and the resulting temperature config applied.

Observed score-question range: ~0.10-0.26, confirming the model is miscalibrated out of the box. **The `v3` config is not evidence otherwise:** it was written with `n_eval=0` and all-`1.0` temperatures, i.e. no calibration was applied (see §9).

### 8.3 Measuring uncertainty post-calibration
After 7.8a:
- **Boolean questions (`noul`)**: distance from 0.5, i.e. `|p - 0.5|`. Closer to 0.5 = more uncertain.
- **Choice questions**: entropy of the output distribution.

---

## 9. Milestones & Training Roadmap

With **2,364 jobs across 26 pipeline sources** and **30 distinct jobs labeled** as of 2026-11-09 (first session in progress):

| Milestone | Target | Requirements | Status | Unlocks |
|-----------|--------|--------------|:------:|---------|
| **M1** | Baseline Calibration & Evaluation | Random + High-Match strata labeled | **INVALID** — `v3` artifact has `n_eval=0`, all temperatures 1.0 | Re-run `calibrate_laya.py --version v4` after labels |
| **M2** | Total v2 Labels Gate | $\ge 150$ distinct jobs with `v2_role_fit_only` | **30 / 150** | Stratified cross-validation splits and ranker evaluation |
| **M3** | Production Ranker Training Gate | $\ge 150$ unique v2 jobs AND $\ge 30$ role-fit `good_fit` | **1 / 30 positives** | Unlocks `scripts/train_ranker.py` and `scripts/train_laya.py` |

> **Training Readiness & Safety Gates Enforced**:
> `scripts/train_ranker.py` and `scripts/train_laya.py` strictly refuse to train or evaluate ranker models if:
> 1. Total `v2_role_fit_only` unexcluded labels $< 150$.
> 2. Total role-fit `good_fit` labels $< 30$.
> 3. Any cross-validation fold contains fewer than 3 positive cases (`fold guard`).
>
> **Promotion Rule**: The learned ranker replaces the rule baseline only if its out-of-fold lower 95% bootstrap CI exceeds 0.70 AND outperforms the title-rule baseline by $\ge 0.05$ AUC.
>
> The old 20 legacy `good_fit` roles were lost with the Windows DB; there is nothing to re-evaluate. Label fresh postings from the 8 enabled ATS boards in `app.py` to clear the gate.

