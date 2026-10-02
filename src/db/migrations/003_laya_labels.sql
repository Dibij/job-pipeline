-- 003_laya_labels.sql: Storage for human candidate fit labels
CREATE TABLE IF NOT EXISTS laya_labels (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    label VARCHAR(32) NOT NULL, -- 'good_fit', 'maybe', 'bad_fit'
    notes TEXT,
    metadata JSONB,
    labeled_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_job_label_time UNIQUE (job_id, labeled_at)
);

CREATE INDEX IF NOT EXISTS idx_laya_labels_job_id ON laya_labels(job_id);
CREATE INDEX IF NOT EXISTS idx_laya_labels_label ON laya_labels(label);
