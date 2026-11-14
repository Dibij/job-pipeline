-- 019_github_closed_feed_gate.sql
-- Fixes closed / self-assigned / owner-backlog issues reaching the feed.
--
-- 1. Issue-level state and provenance columns on jobs (all nullable/defaulted).
-- 2. Fresh re-check timestamps + UNVERIFIED marker.
-- 3. repo_health fields needed by OWNER_BACKLOG and watchlist suggestion.
-- 4. Rejected ledger keeps evidence + a verified_at column; rows are never deleted.

-- --- 1. Issue state and provenance on jobs ----------------------------------
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS issue_state TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS issue_state_reason TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS issue_closed_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS author_login TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS author_association TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS assignee_logins TEXT[];
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS issue_created_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS labels_with_actor JSONB;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS parent_issue_url TEXT;
-- Language detection was dropped from the gate; remove the column if an earlier
-- draft of this migration created it.
ALTER TABLE jobs DROP COLUMN IF EXISTS body_language;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS sub_issue_urls JSONB;

-- --- 2. Fresh re-check (Step 2) ---------------------------------------------
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS verification_status TEXT
    NOT NULL DEFAULT 'UNVERIFIED';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lane TEXT;

-- Only accepted, verified, non-held GitHub issues may enter the feed.
CREATE INDEX IF NOT EXISTS idx_jobs_github_feed
    ON jobs(score DESC)
    WHERE source = 'github'
      AND bounty_verdict = 'accept'
      AND verification_status = 'VERIFIED';

-- --- 3. Repo health additions (Step 3) --------------------------------------
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS owner_login TEXT;
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS owner_type TEXT;
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS contributor_count INTEGER;
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS outside_merged_prs_recent INTEGER NOT NULL DEFAULT 0;
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS open_issue_count INTEGER;
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS owner_issue_share NUMERIC(4, 3);
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS watchlist_candidate BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE repo_health ADD COLUMN IF NOT EXISTS watchlist_reason TEXT;

-- --- 4. Rejected ledger: never delete, keep evidence and verification -------
ALTER TABLE rejected_issues ADD COLUMN IF NOT EXISTS reject_reason TEXT;
ALTER TABLE rejected_issues ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE rejected_issues ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ;
ALTER TABLE rejected_issues ADD COLUMN IF NOT EXISTS verification_status TEXT
    NOT NULL DEFAULT 'VERIFIED';

CREATE INDEX IF NOT EXISTS idx_rejected_reason
    ON rejected_issues(reject_reason);
