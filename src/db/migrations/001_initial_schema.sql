-- 001_initial_schema.sql: Core schema for job pipeline

-- Required extension for UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Raw staging table (ELT pattern: store original untouched JSON payload)
CREATE TABLE IF NOT EXISTS raw_job_listings (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(64) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    processed BOOLEAN DEFAULT FALSE,
    CONSTRAINT uq_source_external_id UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_job_listings_processed ON raw_job_listings(processed);

-- 2. Core normalized jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(64) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    company_url VARCHAR(500),
    location_raw VARCHAR(255),
    is_remote BOOLEAN DEFAULT FALSE,
    remote_restriction VARCHAR(255),
    job_type VARCHAR(64),
    experience_level VARCHAR(64),
    description_text TEXT NOT NULL,
    description_html TEXT,
    apply_url VARCHAR(1000) NOT NULL,
    salary_min NUMERIC(12, 2),
    salary_max NUMERIC(12, 2),
    salary_currency VARCHAR(10),
    tags TEXT[],
    posted_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    fingerprint_hash CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_jobs_source_external_id UNIQUE (source, external_id),
    CONSTRAINT uq_jobs_fingerprint UNIQUE (fingerprint_hash)
);

CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_is_remote ON jobs(is_remote);
CREATE INDEX IF NOT EXISTS idx_jobs_experience ON jobs(experience_level);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint_hash);

-- 3. CV Match and Ranking table
CREATE TABLE IF NOT EXISTS job_matches (
    job_id UUID PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    match_score NUMERIC(5, 2) NOT NULL,
    matched_skills TEXT[],
    missing_skills TEXT[],
    score_breakdown JSONB,
    is_starred BOOLEAN DEFAULT FALSE,
    is_hidden BOOLEAN DEFAULT FALSE,
    applied_at TIMESTAMPTZ,
    scored_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_matches_score ON job_matches(match_score DESC);
