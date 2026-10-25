-- 011_widen_label_stratum.sql: Widen sampling_stratum and label_guideline_version to prevent overflow
ALTER TABLE laya_labels
    ALTER COLUMN sampling_stratum TYPE VARCHAR(64),
    ALTER COLUMN label_guideline_version TYPE VARCHAR(64);
