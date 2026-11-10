-- 018_github_lanes.sql
-- GitHub lane rebuild: PAID (funded bounty) and PROOF (unfunded real issue).
-- Adds repo health, watchlist, and rejected-issues tracking, plus lane/score
-- columns on jobs. All new columns are nullable/defaulted so existing rows
-- are unaffected.

-- New columns on jobs for the two-lane GitHub feed
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lane VARCHAR(16);
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS chk_jobs_lane;
ALTER TABLE jobs ADD CONSTRAINT chk_jobs_lane
    CHECK (lane IS NULL OR lane IN ('PAID', 'PROOF'));

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS score NUMERIC(3, 0);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS score_breakdown JSONB;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS why TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_lane_score ON jobs(lane, score DESC) WHERE lane IS NOT NULL;

-- Repo health: cached per-repo assessment for 7 days
CREATE TABLE IF NOT EXISTS repo_health (
    repo TEXT PRIMARY KEY,
    healthy BOOLEAN NOT NULL DEFAULT FALSE,
    pushed_at TIMESTAMP WITH TIME ZONE,
    is_fork BOOLEAN,
    is_archived BOOLEAN,
    has_contributing BOOLEAN,
    recent_merged_prs INTEGER,
    maintainer_reply_days NUMERIC,
    repo_size_kb INTEGER,
    language TEXT,
    open_prs INTEGER,
    merged_prs_recent INTEGER,
    checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    blocklisted BOOLEAN NOT NULL DEFAULT FALSE,
    blocklisted_until TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_repo_health_blocklisted
    ON repo_health(blocklisted, blocklisted_until) WHERE blocklisted;

-- Watchlist: repos that passed health check and are polled directly
CREATE TABLE IF NOT EXISTS watchlist (
    repo TEXT PRIMARY KEY,
    source VARCHAR(32) NOT NULL DEFAULT 'seed',
    added_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_polled_at TIMESTAMP WITH TIME ZONE,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Rejected issues: mirror of rejected rows so nothing is ever deleted
CREATE TABLE IF NOT EXISTS rejected_issues (
    id SERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    title TEXT,
    lane VARCHAR(16),
    verdict VARCHAR(16) NOT NULL DEFAULT 'reject',
    reject_reasons TEXT[] NOT NULL DEFAULT '{}',
    reject_evidence TEXT,
    funding_evidence JSONB,
    score NUMERIC(3, 0),
    score_breakdown JSONB,
    why TEXT,
    notes TEXT,
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_state_hash VARCHAR(64),
    source_url TEXT NOT NULL,
    UNIQUE (repo, issue_number)
);

CREATE INDEX IF NOT EXISTS idx_rejected_reasons ON rejected_issues USING GIN(reject_reasons);
CREATE INDEX IF NOT EXISTS idx_rejected_last_seen ON rejected_issues(last_seen_at DESC);
