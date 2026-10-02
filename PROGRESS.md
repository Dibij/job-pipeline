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
  - **Token budget measured accurately with real tokenizer**:
    - Max model limit: 1,024 tokens.
    - Questions overhead (12 questions + keys): 258 tokens.
    - State JSON wrapper + CV summary: 150 tokens.
    - Safety margin: 50 tokens.
    - **Calculated JD text budget (`LAYA_INPUT_TOKEN_BUDGET`)**: **566 tokens** (saved in `config/token_budget.json`).
  - Priority truncation: preserves requirements > responsibilities > nice-to-have > blurb. Drops benefits and legal boilerplate. Appends ` [...]` when cutting.
  - 6 unit & integration tests covering very long, very short, empty, priority, and real PostgreSQL database JDs.
- **Total Test Suite**: 58 passed, 0 failures!

## What's Broken / Incomplete
- Task 7.4 (Typed questions & scoring module `src/matching/laya_scorer.py`) is next.
- Task 7.8 (Training workstream & scaffolding scripts) to be launched via subagent.

## Next Step
- Task 7.4: Build `src/matching/laya_scorer.py` using `config/laya_questions.yaml`, evaluate on 10 real jobs, and print per-question breakdown.
