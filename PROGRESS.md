# Project Progress

## Current State
- Phase 1, Phase 2, Phase 3, and Phase 5 complete!
- 618 unique jobs stored in PostgreSQL with rule-based baseline `MatchScorer`.
- Task 5b.1 Seniority Audit completed:
  - Out of 346 jobs marked `senior`, 321 (92.8%) were triggered by title keywords (`senior`, `lead`, `manager`, `architect`).
  - 25 jobs (7.2%) were triggered solely by body text (`5+ years`).
- Task 7.1 Laya Spike completed locally:
  - **Model**: `convaiinnovations/laya` (ModernBERT-large architecture, 421M parameters).
  - **Hardware used**: CPU (`torch 2.14.1+cpu`). System GPU: NVIDIA GeForce RTX 2050 4GB VRAM (CUDA build not yet installed).
  - **Speed**: Cold load 94.8s; Inference: **2,830.9 ms (~2.8s) per forward pass** on CPU across 3 typed questions.
  - **Input Token Limit**: 1,024 tokens maximum (Spike used 511 input + 119 state tokens = 630 total).
  - **Spike Decisions** on "Junior Python/Django Dev @ KoboToolbox":
    - `skills_fit` (score): 3.32 / 4.0 → strong match.
    - `is_remote` (noul): 0.7961 → 79.6% remote.
    - `seniority_level` (choice): `junior` → 79.5% confidence.
  - **Warning**: checkpoint ships uncalibrated temperatures — fine-tuning (Task 7.8) is required for reliable confidence scores.
- Task 7.2 JD section extractor complete (`src/matching/jd_extractor.py`):
  - Handles ALL CAPS, Title Case, markdown headings, and no-heading prose fallback.
  - Strips HTML and converts `<li>` to bullets before detection to prevent misclassification.
  - 24 tests pass covering all messy formats.
- **Total: 52 tests passing.**

## What's Broken / Incomplete
- CPU inference at ~2.8s/job is fine for batch scoring overnight, but slow for interactive use.
- Laya confidence scores are uncalibrated until Task 7.8 fine-tuning.
- Phases 5b.2, 5b.3, 6.1–6.4 not yet started.

## Next Step
- Task 7.3: Build `src/matching/jd_truncator.py` to assemble a Laya scoring input from `JDSections` within `LAYA_INPUT_TOKEN_BUDGET` (default: 900 tokens), counted with the real tokenizer. Drop benefits/legal boilerplate first. Add `[...]` markers. Include compact CV summary from `cv_profile.json`.
