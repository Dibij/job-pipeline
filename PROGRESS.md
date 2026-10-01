# Project Progress

## Current State
- Phase 1 (Foundations & Local Database) complete.
- Base extractor architecture (`BaseExtractor`) established in `src/extractors/base.py`.
- `ArbeitnowExtractor` implemented and verified against live API (326 jobs staged into `raw_job_listings`).
- Idempotency verified: re-running staging safely skips duplicate `(source, external_id)` pairs with zero errors.
- Test suite passing (10 tests passed).

## What's Broken / Incomplete
- Only Arbeitnow extractor is built; Remotive extractor is needed next.
- Jobs are currently sitting in raw JSON staging (`raw_job_listings`) and need normalization models.

## Next Step
- Task 2.2: Implement Remotive API extractor (`RemotiveExtractor`) with polite rate limiting and raw DB staging.
