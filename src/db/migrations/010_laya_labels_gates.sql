-- 010_laya_labels_gates.sql: Persist 5-gate audit fields and structured metadata to laya_labels
ALTER TABLE laya_labels
    ADD COLUMN IF NOT EXISTS gate_failed INTEGER,
    ADD COLUMN IF NOT EXISTS workplace_type VARCHAR(20),
    ADD COLUMN IF NOT EXISTS country_restriction VARCHAR(100),
    ADD COLUMN IF NOT EXISTS seniority VARCHAR(20),
    ADD COLUMN IF NOT EXISTS degree_required VARCHAR(20),
    ADD COLUMN IF NOT EXISTS years_required INTEGER,
    ADD COLUMN IF NOT EXISTS pay_type VARCHAR(30),
    ADD COLUMN IF NOT EXISTS tz_overlap_required VARCHAR(20);

COMMENT ON COLUMN laya_labels.gate_failed IS 'Which gate failed (1-5), or NULL if passed';
COMMENT ON COLUMN laya_labels.workplace_type IS 'remote | hybrid | onsite | unknown';
COMMENT ON COLUMN laya_labels.country_restriction IS 'none | nepal | worldwide | apac | asia | us | eu | uk | canada | india | other:<x> | unknown';
COMMENT ON COLUMN laya_labels.seniority IS 'intern | junior | mid | senior | unknown';
COMMENT ON COLUMN laya_labels.degree_required IS 'true | false | unknown';
COMMENT ON COLUMN laya_labels.years_required IS 'Minimum years of experience required or NULL';
COMMENT ON COLUMN laya_labels.pay_type IS 'salary | hourly | stipend | equity | commission | unknown';
COMMENT ON COLUMN laya_labels.tz_overlap_required IS 'none | apac | eu | us_east | us_west | unknown';
