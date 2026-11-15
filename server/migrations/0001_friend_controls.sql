
CREATE TABLE IF NOT EXISTS friend_vehicle_controls (
 device_id text NOT NULL REFERENCES native_device_refs(device_id),
 requester_id text NOT NULL REFERENCES team_accounts(account_id),
 owner_id text NOT NULL REFERENCES team_accounts(account_id),
 protected bytea NOT NULL,
 PRIMARY KEY(device_id,requester_id)
);
CREATE TABLE IF NOT EXISTS friend_vehicle_commands (
 request_id text PRIMARY KEY,
 device_id text NOT NULL REFERENCES native_device_refs(device_id),
 requester_id text NOT NULL REFERENCES team_accounts(account_id),
 owner_id text NOT NULL REFERENCES team_accounts(account_id),
 event_hash text NOT NULL,
 protected bytea NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(requester_id,event_hash)
);

CREATE INDEX IF NOT EXISTS friend_vehicle_controls_requester ON friend_vehicle_controls(requester_id);
CREATE INDEX IF NOT EXISTS friend_vehicle_commands_target ON friend_vehicle_commands(device_id,created_at DESC);
REVOKE ALL ON friend_vehicle_controls,friend_vehicle_commands FROM PUBLIC;
