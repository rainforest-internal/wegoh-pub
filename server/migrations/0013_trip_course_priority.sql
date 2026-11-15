ALTER TABLE team_trip_courses
    ADD COLUMN IF NOT EXISTS priority smallint CHECK (priority BETWEEN 1 AND 10);
