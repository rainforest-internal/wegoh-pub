CREATE TABLE IF NOT EXISTS team_room_playlist_tracks (
    room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
    track_id char(32) NOT NULL,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    member_joined_at timestamptz NOT NULL,
    protected bytea NOT NULL,
    position bigserial NOT NULL,
    PRIMARY KEY(room_id,track_id)
);
CREATE INDEX IF NOT EXISTS room_playlist_order ON team_room_playlist_tracks(room_id,position);

ALTER TABLE team_rooms ADD COLUMN IF NOT EXISTS archived_at timestamptz;
ALTER TABLE team_rooms ADD COLUMN IF NOT EXISTS archived_music bytea;
CREATE INDEX IF NOT EXISTS team_rooms_archive_pending ON team_rooms(expires_at,room_id)
    WHERE archived_at IS NULL;
