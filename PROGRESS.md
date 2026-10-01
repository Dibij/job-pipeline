# Project Progress

## Current State
- Phase 2 (Clean API Ingestion & Normalization) complete!
- Raw staging established for Arbeitnow (326 jobs) and Remotive (16 jobs).
- Pydantic schema `NormalizedJob` implemented in `src/models/job.py`.
- Source transformers `transform_arbeitnow` and `transform_remotive` implemented in `src/models/transformers.py`.
- HTML stripping, tag extraction, UTC timestamp parsing, and SHA-256 content fingerprinting verified.
- Test suite passing (15 tests passed).

## What's Broken / Incomplete
- Normalized jobs are not yet written to the main `jobs` table in PostgreSQL.

## Next Step
- Task 3.1: Implement SHA-256 fingerprint deduplication & PostgreSQL upsert pipeline loading normalized jobs into `jobs`.
