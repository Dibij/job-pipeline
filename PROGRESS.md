# Project Progress

## Current State
- Phase 1 (Foundations & DB) and Phase 2 (Clean Extraction & Normalization) complete.
- SHA-256 fingerprint deduplication & upsert pipeline (`JobRepository`) implemented.
- End-to-end pipeline run executed: 656 raw staged listings normalized and deduplicated into **618 unique jobs** in PostgreSQL `jobs` table.
- Test suite passing (16 tests passed).

## What's Broken / Incomplete
- Seniority levels (`intern`, `junior`, `mid`, `senior`) are currently defaulting; regex enrichment engine needed.

## Next Step
- Task 3.2: Implement regex enrichment for seniority (`intern`, `junior`) and tech tags.
