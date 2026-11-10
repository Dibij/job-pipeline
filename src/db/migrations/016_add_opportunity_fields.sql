-- 016_add_opportunity_fields.sql
-- Add outreach context and opportunity-specific fields for the multi-source
-- opportunity intelligence system. All new columns are nullable/defaulted so
-- existing job rows are unaffected.

-- Outreach context (human-reviewable drafts, NOT auto-sent)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS outreach_draft TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS technical_angle TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS clarification_questions TEXT[] DEFAULT '{}';

-- Compound indexes for dashboard low-latency queries
CREATE INDEX IF NOT EXISTS idx_jobs_opportunity_type_status
    ON jobs(opportunity_type, status DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scam_risk_type
    ON jobs(scam_risk_score DESC, opportunity_type);
CREATE INDEX IF NOT EXISTS idx_jobs_freshness
    ON jobs(last_seen_at DESC) WHERE opportunity_type != 'job';
