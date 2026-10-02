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
* **Current Torch Installation**: CPU-only (`torch 2.14.1+cpu`, CUDA unavailable in Python).
* **Available VRAM at Idle**: ~2.8 GB free (display and Windows system processes use ~1.1 GB).

### What Installing CUDA PyTorch Would Involve
To enable GPU execution:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```
*(Approx. 2.4 GB wheel download).*

### What Fits in 4 GB VRAM (and what does NOT):
* **FITS in 4 GB VRAM**:
  - **Inference (Evaluation & Scoring)**: ModernBERT-large weights take ~840 MB in fp16/bf16. Running forward passes with batch size 1–2 takes ~1.2 GB VRAM total. This drops latency from ~2.8s down to ~40 ms per job.
  - **Decision Head Training (Task 7.8b)**: Because the ModernBERT encoder is **frozen**, we only compute gradients for the small linear head (~1–2 MB of weights). Optimizer state and activations take < 200 MB. In fact, pre-computing and caching the 1024-dim embeddings to disk allows training the head in seconds using < 500 MB of VRAM.
  - **Temperature Fitting (Task 7.8a)**: Runs purely on output probability vectors; consumes virtually zero GPU memory (< 50 MB).
* **DOES NOT FIT in 4 GB VRAM (Will OOM)**:
  - **Full-Model End-to-End Backpropagation**: Training all 421M parameters of ModernBERT-large un-frozen with AdamW requires:
    - Model weights (fp16): 842 MB
    - Gradients: 842 MB
    - AdamW optimizer states (fp32): ~3.3 GB
    - Transformer activations (seq len 1024): ~1.5 GB
    - Total: **> 6.5 GB VRAM** (will crash with CUDA Out of Memory on a 4GB GPU).
  - Therefore, fine-tuning must strictly keep the encoder frozen (or use LoRA/QLoRA if encoder tuning is ever desired).

---

## 4. Safeguards Enforced in Code
1. **Refusal on Small Datasets**: `scripts/train_laya.py` strictly refuses to train if labeled rows < 150. (Fine-tuning decision heads with too few samples causes severe overfitting).
2. **No Training on Predictions**: Training queries only rows from `laya_labels` where human labels exist. Never treats Laya's own guesses as truth.
3. **Split by Job ID**: Data is split into train and validation sets by `job_id` using a fixed random seed (42). Multiple records from the same job never leak across splits.
4. **Versioned Checkpoints**: Weights are saved under `models/laya_head_{version}/` and gitignored. Original base weights are never overwritten.

---

## 5. Workflow Guide & Next Steps

### Step 1: Export Jobs for Labeling
```bash
.\.venv\Scripts\python scripts/export_for_labeling.py --batch-size 30
```
This generates `data/labeling_batch_YYYYMMDD.csv` with low-confidence jobs at the top.

### Step 2: Human Labeling
Open the generated CSV and fill the `my_label` column:
* `good_fit`: Matches candidate stack, junior-friendly, Nepal accessible.
* `maybe`: Borderline or missing details.
* `bad_fit`: Senior, wrong language, region-locked, or non-technical.

### Step 3: Ingest Labels
```bash
.\.venv\Scripts\python scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv
```

### Step 4: Calibrate Temperatures (Task 7.8a)
Once 15+ labels are ingested:
```bash
.\.venv\Scripts\python scripts/calibrate_laya.py --version v1
```

### Step 5: Decision Head Fine-Tuning (Task 7.8b)
Once 150+ labels are accumulated:
```bash
.\.venv\Scripts\python scripts/train_laya.py --version v1
```
