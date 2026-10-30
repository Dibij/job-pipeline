-- Migration 013: job_llm_features for caching structured Ollama outputs
CREATE TABLE IF NOT EXISTS job_llm_features (
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    feature_type VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(64) NOT NULL,
    model VARCHAR(128) NOT NULL,
    model_digest VARCHAR(128) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    json_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (job_id, feature_type, prompt_version, model_digest)
);

CREATE INDEX IF NOT EXISTS idx_job_llm_features_lookup 
ON job_llm_features (content_hash, feature_type, prompt_version, model_digest);
