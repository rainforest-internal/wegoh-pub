ALTER TABLE pack_versions ADD COLUMN IF NOT EXISTS tags text[] NOT NULL DEFAULT '{}'::text[];
