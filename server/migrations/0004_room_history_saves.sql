
-- Personal archive saves are idempotent while the resulting record exists.
CREATE TABLE IF NOT EXISTS team_room_history_saves (
    room_id char(32) NOT NULL REFERENCES team_rooms(room_id) ON DELETE CASCADE,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    history_id char(32) NOT NULL UNIQUE REFERENCES team_histories(history_id) ON DELETE CASCADE,
    PRIMARY KEY(room_id,account_id)
);
