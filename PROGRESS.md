# Project Progress

## Current State
- Phase 1 (Foundations & Local Database) complete.
- Two live public REST API extractors implemented and tested:
  - `ArbeitnowExtractor`: 326 jobs staged.
  - `RemotiveExtractor`: 16 jobs staged.
- Total raw listings staged in `raw_job_listings`: 342.
- Interactive database inspector available via `python -m src.db.connection`.
- Test suite passing (12 tests passed).

## What's Broken / Incomplete
- Jobs reside in raw JSONB staging (`raw_job_listings`); unified transformation into `jobs` table not yet built.

## Next Step
- Task 2.3: Implement unified Pydantic normalization model (`NormalizedJob`) and source transformers for Arbeitnow and Remotive.
