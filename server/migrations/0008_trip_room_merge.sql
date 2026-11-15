ALTER TABLE team_trips
    ADD COLUMN IF NOT EXISTS state varchar(16) NOT NULL DEFAULT 'planned',
    ADD COLUMN IF NOT EXISTS started_at timestamptz,
    ADD COLUMN IF NOT EXISTS ended_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS source_kind varchar(16) NOT NULL DEFAULT 'trip',
    ADD COLUMN IF NOT EXISTS state_revision integer NOT NULL DEFAULT 1;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_trips'::regclass AND conname='team_trips_revision_positive') THEN
        ALTER TABLE team_trips
            ADD CONSTRAINT team_trips_revision_positive CHECK (revision > 0),
            ADD CONSTRAINT team_trips_state_revision CHECK (state_revision > 0 AND state_revision <= revision),
            ADD CONSTRAINT team_trips_source_kind CHECK (source_kind IN ('trip', 'legacy_room')),
            ADD CONSTRAINT team_trips_lifecycle CHECK (
                (state = 'planned' AND started_at IS NULL AND ended_at IS NULL) OR
                (state = 'active' AND started_at IS NOT NULL AND ended_at IS NULL) OR
                (state = 'completed' AND started_at IS NOT NULL AND ended_at IS NOT NULL AND ended_at >= started_at) OR
                (state = 'cancelled' AND started_at IS NULL AND ended_at IS NOT NULL)
            ),
            ADD CONSTRAINT team_trips_deleted_closed CHECK (deleted_at IS NULL OR state IN ('completed', 'cancelled'));
    END IF;
END $$;

ALTER TABLE team_rooms
    ADD COLUMN IF NOT EXISTS trip_id char(32),
    ALTER COLUMN code_hash DROP NOT NULL,
    ALTER COLUMN expires_at DROP NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_rooms'::regclass AND conname='team_rooms_one_per_trip') THEN
        ALTER TABLE team_rooms
            ADD CONSTRAINT team_rooms_one_per_trip UNIQUE (trip_id),
            ADD CONSTRAINT team_rooms_trip_fk FOREIGN KEY (trip_id) REFERENCES team_trips(trip_id) ON DELETE RESTRICT,
            ADD CONSTRAINT team_rooms_context_kind CHECK (
                (trip_id IS NULL AND expires_at IS NOT NULL AND code_hash IS NOT NULL) OR
                (trip_id IS NOT NULL AND expires_at IS NULL AND code_hash IS NULL)
            );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS team_trip_place_proposals (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    proposal_id char(32) NOT NULL,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trip_id, proposal_id)
);
CREATE INDEX IF NOT EXISTS team_trip_place_proposals_order ON team_trip_place_proposals(trip_id, created_at, proposal_id);

CREATE TABLE IF NOT EXISTS team_trip_signal_contexts (
    signal_id char(32) PRIMARY KEY REFERENCES team_room_signals(signal_id),
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)
);

CREATE TABLE IF NOT EXISTS team_trip_results (
    trip_id char(32) PRIMARY KEY REFERENCES team_trips(trip_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
