-- Migration 014: persist the hard-filter / scorer reason code on job_matches.
-- The column was previously created lazily by src/matching/service.py at runtime,
-- which meant a fresh database broke import_manual_jobs.py and other writers.
ALTER TABLE job_matches
    ADD COLUMN IF NOT EXISTS reason_code TEXT DEFAULT NULL;
