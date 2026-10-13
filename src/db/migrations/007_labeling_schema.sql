-- 007_labeling_schema.sql: Add sampling_stratum and label_guideline_version to laya_labels
-- sampling_stratum: which sampling bucket selected this row (random, high_match_scorer, laya_uncertainty)
-- label_guideline_version: version string of the labeling rules active when this label was recorded

ALTER TABLE laya_labels
    ADD COLUMN IF NOT EXISTS sampling_stratum VARCHAR(32),
    ADD COLUMN IF NOT EXISTS label_guideline_version VARCHAR(16);

COMMENT ON COLUMN laya_labels.sampling_stratum IS
    'Sampling bucket that selected this job: random | high_match_scorer | laya_uncertainty';
COMMENT ON COLUMN laya_labels.label_guideline_version IS
    'Labeling guideline version (e.g. v1) in force when this label was recorded';
