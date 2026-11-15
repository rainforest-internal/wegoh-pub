-- Existing saves receive the migration time; new saves record their own time.
ALTER TABLE team_course_stars ADD COLUMN IF NOT EXISTS starred_at timestamptz NOT NULL DEFAULT now();
