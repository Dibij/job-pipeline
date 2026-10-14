-- Migration 008: Add reachable_from_nepal and reachable_reason to jobs table
-- Values for reachable_from_nepal: accessible, unknown, blocked (default: unknown)
-- reachable_reason: machine-readable reason string for auditability and Laya routing

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS reachable_from_nepal VARCHAR(20) DEFAULT 'unknown'
    CHECK (reachable_from_nepal IN ('accessible', 'unknown', 'blocked')),
    ADD COLUMN IF NOT EXISTS reachable_reason TEXT DEFAULT 'no_location_restriction_stated';

CREATE INDEX IF NOT EXISTS idx_jobs_reachable_from_nepal ON jobs(reachable_from_nepal);
