-- 015_add_opportunity_fields.sql
-- Extend jobs into a unified opportunity model without breaking existing job rows.
-- Every new column is nullable or defaulted so the existing job pipeline is unaffected.

-- Discriminator: what kind of opportunity this is.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS opportunity_type VARCHAR(32) NOT NULL DEFAULT 'job';
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS chk_jobs_opportunity_type;
ALTER TABLE jobs ADD CONSTRAINT chk_jobs_opportunity_type
    CHECK (opportunity_type IN ('job', 'freelance', 'bounty', 'open_source'));

-- Compensation: distinct from salary. A project budget or hourly rate is not a salary.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS compensation_type VARCHAR(32);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS budget_min NUMERIC(12, 2);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS budget_max NUMERIC(12, 2);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS budget_currency VARCHAR(10);

-- Deadline (freelance/bounty acceptance or closing date).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deadline TIMESTAMPTZ;

-- Payment verification: verified | unverified | none | unknown
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS payment_verification_status VARCHAR(32) DEFAULT 'unknown';

-- Risk assessment (explainable flags, not a binary verdict).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS scam_risk_score NUMERIC(4, 3) DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS risk_flags TEXT[] DEFAULT '{}';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS risk_explanation TEXT;

-- Lifecycle: is the opportunity still open?
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'open';

-- Canonical source URL (distinct from apply_url, e.g. the GitHub issue permalink).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_url VARCHAR(1000);

-- Freshness: last time the source still listed this opportunity.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_jobs_opportunity_type ON jobs(opportunity_type);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON jobs(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_deadline ON jobs(deadline);
