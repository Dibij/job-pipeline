# Laya Training & Calibration Workstream (`TRAINING.md`)

This document tracks the calibration and fine-tuning engineering for Laya (Task 7.8). It is self-contained so any session can pick up the workstream directly.

---

## 1. Current State
* **Spike and Scoring Active**: Base checkpoint `convaiinnovations/laya` (ModernBERT-large, 421M params) runs on CPU with ~2.8s latency per job.
* **Database Table Created**: `laya_labels` (in `src/db/migrations/003_laya_labels.sql`) stores candidate fit labels with columns `(job_id, label, notes, metadata, labeled_at)`.
* **Scaffolding Complete**: All 4 pipeline scripts are implemented and tested:
  1. `scripts/export_for_labeling.py`: Exports unlabeled jobs to `data/labeling_batch_YYYYMMDD.csv` prioritizing low-confidence predictions.
  2. `scripts/ingest_labels.py`: Ingests and validates human labels (`good_fit`, `maybe`, `bad_fit`) without overwriting old records.
  3. `scripts/calibrate_laya.py`: Fits temperature scaling parameters (Task 7.8a) to calibrate confidence scores.
  4. `scripts/train_laya.py`: Supervises decision head training with strict safeguards and `--dry-run` support (Task 7.8b).

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
* **CUDA Torch**: `torch 2.5.1+cu121`, RTX 2050 confirmed (`torch.cuda.is_available() = True`).
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
.\.venv\Scripts\python scripts/export_for_labeling.py --batch-size 30
```
Generates `data/labeling_batch_YYYYMMDD.csv`. Each row includes a `sampling_stratum` field (see Section 6.5). Laya columns must be hidden or absent during labeling -- see Task 7.7b.

### Step 2: Human Labeling
Open the CSV and fill the `my_label` column using the definitions in Section 6.3. **Never accept Laya's suggestion as a default -- a skipped job is unlabeled, not `bad_fit`.**

### Step 3: Ingest Labels
```bash
.\.venv\Scripts\python scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv
```

### Step 4: Calibrate Temperatures (Task 7.8a) -- M1
Once ~150 labels (including the random stratum) are reached:
```bash
.\.venv\Scripts\python scripts/calibrate_laya.py --version v1
```
Uses natural-distribution data (or stratum-weighted data) to preserve real class rates.

### Step 5: Decision Head Fine-Tuning (Task 7.8b) -- M3
Once 500+ labels and at least 30 `good_fit` are reached:
```bash
.\.venv\Scripts\python scripts/train_laya.py --version v1
```

---

## 6. Labeling Strategy & Class Balance

### 6.1 Observed Distribution (Oct 2026)
86 labels ingested so far:

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

### 6.3 Label Definitions
> **DRAFT -- needs confirmation against `cv_profile.json` before use. Label guideline version: `v1-draft`.**

| Label | Meaning |
|-------|---------|
| `good_fit` | Role matches candidate tech stack, is junior/mid level, is accessible from Nepal (remote-worldwide or Nepal-based), and is a paid position. |
| `maybe` | Borderline -- one of the above criteria is unclear, seniority is ambiguous, or key details are missing. |
| `bad_fit` | Senior-required, wrong primary language, US/EU/specific-country only, unpaid, or entirely non-technical. |

Each label row must include a `label_guideline_version` (stored in `metadata`) and the `labeled_at` timestamp already stored by the DB.

### 6.4 Labeling Hygiene Rules
- Every label comes from the human labeler. Accepting Laya's output as a default is **not allowed**.
- Laya's answers must not be visible while labeling (anchoring bias). Task 7.7b tracks moving Laya columns out of the export CSV or hiding them until after the label is entered.
- A skipped job is **unlabeled**, never `bad_fit`.

### 6.5 Labeling Queue -- Sampling Strata
Each exported job must have a `sampling_stratum` field recorded in `laya_labels.metadata`:

| Stratum | Default share | Selection rule |
|---------|--------------|----------------|
| `random` | 40% | Uniformly sampled from the natural stream after hard filters. Must always be present -- provides unbiased rates for calibration. |
| `high_match_scorer` | 30% | Highest MatchScorer scores among unlabeled, hard-filter-passing jobs. Finds positives using a signal independent of Laya. |
| `laya_uncertainty` | 30% | Jobs where calibrated Laya confidence is lowest. **Only active after 7.8a calibration.** Before calibration, fill this share with additional `random` jobs. |

> **Important**: Do not use uncalibrated Laya outputs to discard jobs or decide labeling order. Raw confidence scores (~0.10-0.26 on score questions) are noise, not signal, until 7.8a is done.

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

Observed score-question range: ~0.10-0.26, confirming the model is miscalibrated out of the box.

### 8.3 Measuring uncertainty post-calibration
After 7.8a:
- **Boolean questions (`noul`)**: distance from 0.5, i.e. `|p - 0.5|`. Closer to 0.5 = more uncertain.
- **Choice questions**: entropy of the output distribution.

---

## 9. Milestones

With ~22–60 deduplicated HardFilter survivors from current sources (Arbeitnow & Remotive), targets of 150 and 500 labels cannot be reached without onboarding new data sources.

| Milestone | Target | Requirements | Unlocks |
|-----------|--------|--------------|---------|
| **M1** | All deduplicated survivors labeled (~60–80 jobs) | Random stratum included; labels complete for current stream | Provisional 7.8a calibration re-run; initial ranking report |
| **M2** | ~150–300 labels | Requires onboarding new job sources (Jobicy, WWR, HN Algolia) | First Laya vs MatchScorer comparison with bootstrap CIs |
| **M3** | 500+ labels | ≥ 30 `good_fit` positives | Consider 7.8b decision head fine-tuning (stays BLOCKED until then) |

M3 gates strictly on `min_positive_labels = 30` (default, configurable in `scripts/train_laya.py`). Task 7.8b stays BLOCKED.
