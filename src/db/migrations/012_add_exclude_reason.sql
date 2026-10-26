-- 012_add_exclude_reason.sql: Add exclude_reason to jobs and laya_labels
-- Used to exclude unparseable titles, corrupted rows, or duplicate records from labeling batches and training
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS exclude_reason VARCHAR(64);

ALTER TABLE laya_labels
    ADD COLUMN IF NOT EXISTS exclude_reason VARCHAR(64);

COMMENT ON COLUMN jobs.exclude_reason IS 'Reason to exclude from labeling/training: unparseable_title | corrupted_posting | non_job | etc.';
COMMENT ON COLUMN laya_labels.exclude_reason IS 'Reason to exclude labeled job from training/evaluation';
