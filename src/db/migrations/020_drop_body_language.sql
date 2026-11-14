-- 020_drop_body_language.sql
-- Language detection was dropped from the GitHub gate at the user's request.
-- 019 originally added jobs.body_language; remove it where that already ran.
ALTER TABLE jobs DROP COLUMN IF EXISTS body_language;
