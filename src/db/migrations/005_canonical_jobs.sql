-- Migration 005: canonical_job_id for cross-posted deduplication
--
-- Strategy:
--   1. Add a canonical_job_id column to jobs (nullable, UUID).
--      When NULL, the job IS its own canonical.
--   2. Add a stable canonical key: normalized(company_slug + title_slug + listing_id_suffix).
--      listing_id_suffix = last path segment of apply_url (numeric or slug).
--   3. Create a view `canonical_jobs` that returns one row per canonical posting:
--      the one with the highest job_matches.match_score, or newest created_at.
--   4. Add the view `canonical_job_scores` for the feed query.
--
-- NOTE: This migration does NOT auto-merge existing rows. Run
--   scripts/canonicalize_jobs.py   to populate canonical_job_id.

-- Step 1: canonical_job_id column
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS canonical_job_id UUID REFERENCES jobs(id) DEFAULT NULL;

-- Step 2: helper function to extract listing ID from URL path
CREATE OR REPLACE FUNCTION listing_id_from_url(url TEXT)
RETURNS TEXT AS $$
    SELECT regexp_replace(
        split_part(rtrim(url, '/'), '/', -1),
        '^(remote-)?([a-z0-9-]+?)-(\d+)$', '\3'
    );
$$ LANGUAGE SQL IMMUTABLE;

-- Step 3: view returning the canonical representative for each posting.
-- A posting is "canonical" when canonical_job_id IS NULL (it IS the canonical).
-- Other rows point to their canonical via canonical_job_id.
CREATE OR REPLACE VIEW canonical_jobs AS
    SELECT j.*
    FROM jobs j
    WHERE j.canonical_job_id IS NULL;

-- Step 4: view for feed — one match row per canonical job, latest scored_at
CREATE OR REPLACE VIEW canonical_job_matches AS
    SELECT DISTINCT ON (jm.job_id)
        jm.*
    FROM job_matches jm
    JOIN canonical_jobs cj ON cj.id = jm.job_id
    ORDER BY jm.job_id, jm.scored_at DESC;
