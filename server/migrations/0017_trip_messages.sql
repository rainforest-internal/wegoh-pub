CREATE TABLE IF NOT EXISTS team_trip_messages (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    sender_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    message_id text NOT NULL CHECK (message_id ~ '^[0-9a-f]{32}$'),
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (trip_id, sender_id, message_id)
);
CREATE INDEX IF NOT EXISTS team_trip_messages_timeline
    ON team_trip_messages (trip_id, created_at DESC, sender_id, message_id);
CREATE INDEX IF NOT EXISTS team_trip_messages_sender
    ON team_trip_messages (sender_id);
REVOKE ALL ON team_trip_messages FROM PUBLIC;
