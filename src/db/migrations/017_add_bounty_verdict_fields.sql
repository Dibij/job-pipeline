-- 017_add_bounty_verdict_fields.sql
-- Bounty verdict fields: capture why each GitHub issue was accepted or rejected
-- as a real bounty, with evidence for audit.
-- Every column is nullable/defaulted so existing job rows are unaffected.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS bounty_verdict VARCHAR(16);
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS chk_jobs_bounty_verdict;
ALTER TABLE jobs ADD CONSTRAINT chk_jobs_bounty_verdict
    CHECK (bounty_verdict IS NULL OR bounty_verdict IN ('accept', 'reject', 'uncertain'));

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS reject_reasons TEXT[] DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS funding_evidence JSONB;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS bounty_confidence NUMERIC(3, 0);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS reject_evidence TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_bounty_verdict ON jobs(bounty_verdict) WHERE opportunity_type = 'bounty';
CREATE INDEX IF NOT EXISTS idx_jobs_reject_reasons ON jobs USING GIN(reject_reasons);
