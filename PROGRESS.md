# Project Progress

## Current State
- Phase 1, Phase 2, Phase 3, and Phase 5 complete!
- 618 unique jobs stored in PostgreSQL with rule-based baseline `MatchScorer`.
- Task 5b.1 Seniority Audit completed:
  - Out of 346 jobs marked `senior`, 321 (92.8%) were triggered by title keywords (`senior`, `lead`, `manager`, `architect`).
  - 25 jobs (7.2%) were triggered solely by body text (`5+ years`).
- Task 7.1 Laya Spike completed locally:
  - **Model**: `convaiinnovations/laya` (ModernBERT-large architecture, 421M parameters).
  - **Hardware used**: CPU (via `torch 2.14.1+cpu`). (System GPU: NVIDIA GeForce RTX 2050 4GB VRAM).
  - **Speed**: Cold load 94.8s; Inference: **2,830.9 ms (~2.8s) per forward pass** on CPU across 3 typed questions.
  - **Input Token Limit**: 1,024 tokens maximum (Spike used 511 input tokens, 119 state tokens).
  - **Spike Decisions**:
    - `skills_fit` (score): 3.32 / 4.0 (47.6% strong match, 44.4% perfect match).
    - `is_remote` (noul/boolean): 0.7961 (79.6% remote probability).
    - `seniority_level` (choice): `junior` (79.5% junior probability).

## What's Broken / Incomplete
- Full job descriptions easily exceed Laya's 1,024 token limit and need structured section splitting and truncation (Task 7.2 & 7.3).
- Model weights cached in `~/.cache/huggingface/` (gitignored).

## Next Step
- Task 7.2: Build JD section extraction module (`src/matching/extractor.py`) to split listings into sections (requirements, responsibilities, boilerplate) with test coverage on messy JDs.
