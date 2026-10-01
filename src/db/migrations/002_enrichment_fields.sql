-- 002_enrichment_fields.sql: Add language, unpaid flag, and nepal_accessible columns

ALTER TABLE jobs 
ADD COLUMN IF NOT EXISTS detected_language VARCHAR(32) DEFAULT 'english',
ADD COLUMN IF NOT EXISTS is_unpaid BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS nepal_accessible BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_jobs_language ON jobs(detected_language);
CREATE INDEX IF NOT EXISTS idx_jobs_nepal_accessible ON jobs(nepal_accessible);
CREATE INDEX IF NOT EXISTS idx_jobs_experience_level ON jobs(experience_level);
