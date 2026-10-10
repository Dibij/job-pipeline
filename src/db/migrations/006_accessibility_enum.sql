-- Migration 006: Add 3-state accessibility column
-- Values: ACCESSIBLE, BLOCKED, UNKNOWN (default: UNKNOWN)
-- Retains existing nepal_accessible column until verified.

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS accessibility VARCHAR(20) DEFAULT 'UNKNOWN'
    CHECK (accessibility IN ('ACCESSIBLE', 'BLOCKED', 'UNKNOWN'));

CREATE INDEX IF NOT EXISTS idx_jobs_accessibility ON jobs(accessibility);
