-- Migration 009: Add source_runs table for extraction observability
-- Down: DROP TABLE IF EXISTS source_runs;

CREATE TABLE IF NOT EXISTS source_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL,
    source VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetched INT NOT NULL DEFAULT 0,
    inserted INT NOT NULL DEFAULT 0,
    skipped INT NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_runs_source_started_at ON source_runs(source, started_at);
