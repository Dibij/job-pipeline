-- Migration 004: laya_job_scores table (Task 7.6)
--
-- Stores per-job Laya scoring results. NEVER touches job_matches.
-- Unique constraint on (job_id, laya_checkpoint, config_version) makes the
-- batch scoring script naturally resumable: skip rows that already exist.
--
-- config_version is a short hash of the YAML content so any change to
-- questions, weights, or thresholds invalidates old scores automatically.

CREATE TABLE IF NOT EXISTS laya_job_scores (
    id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Foreign key to the jobs table
    job_id                 UUID        NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,

    -- Final numeric score and pass/fail status
    final_score            NUMERIC(6, 2),
    is_passed              BOOLEAN     NOT NULL DEFAULT TRUE,
    disqualification_reason TEXT,

    -- Task 7.5: needs_review flag (computed but not used to filter until 7.8a)
    needs_review           BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Role classification from the choice question
    role_type              TEXT,

    -- Gate warnings (list of strings, stored for inspection / calibration)
    gate_warnings          JSONB       NOT NULL DEFAULT '[]'::jsonb,

    -- Per-question raw scores, normalized scores, probabilities, confidence
    -- Structure: { "<q_id>": { "type": "score|noul|choice", "raw": ...,
    --               "normalized": ..., "confidence": ..., "probabilities": {} } }
    per_question_data      JSONB       NOT NULL DEFAULT '{}'::jsonb,

    -- Version information for resumability
    laya_checkpoint        TEXT        NOT NULL,  -- e.g. "convaiinnovations/laya"
    config_version         TEXT        NOT NULL,  -- short SHA256 hash of laya_questions.yaml

    -- Metadata
    tokens_used            INTEGER     NOT NULL DEFAULT 0,
    scored_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique constraint: re-scoring the same job with the same model+config
-- is idempotent; the batch script uses this to skip already-scored jobs.
CREATE UNIQUE INDEX IF NOT EXISTS uq_laya_job_scores_job_checkpoint_config
    ON laya_job_scores (job_id, laya_checkpoint, config_version);

-- Index for querying by score (ranking, top-N)
CREATE INDEX IF NOT EXISTS idx_laya_job_scores_final_score
    ON laya_job_scores (final_score DESC)
    WHERE is_passed = TRUE;

-- Index for looking up scores by job
CREATE INDEX IF NOT EXISTS idx_laya_job_scores_job_id
    ON laya_job_scores (job_id);
