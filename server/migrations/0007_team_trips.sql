
CREATE TABLE IF NOT EXISTS team_trips (
    trip_id char(32) PRIMARY KEY,
    owner_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS team_trips_owner ON team_trips(owner_id);
CREATE TABLE IF NOT EXISTS team_trip_members (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    protected bytea NOT NULL,
    PRIMARY KEY(trip_id,account_id)
);
CREATE INDEX IF NOT EXISTS team_trip_members_account ON team_trip_members(account_id);
CREATE TABLE IF NOT EXISTS team_trip_links (
    trip_id char(32) PRIMARY KEY REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    token_sha256 char(64) UNIQUE NOT NULL,
    created_by text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS team_friend_links (
    account_id text PRIMARY KEY REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    token_sha256 char(64) UNIQUE NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS team_trip_cars (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    car_id char(32) NOT NULL,
    driver_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(trip_id,car_id),
    UNIQUE(trip_id,driver_id),
    FOREIGN KEY(trip_id,driver_id) REFERENCES team_trip_members(trip_id,account_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS team_trip_riders (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    car_id char(32) NOT NULL,
    PRIMARY KEY(trip_id,account_id),
    FOREIGN KEY(trip_id,account_id) REFERENCES team_trip_members(trip_id,account_id) ON DELETE CASCADE,
    FOREIGN KEY(trip_id,car_id) REFERENCES team_trip_cars(trip_id,car_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS team_trip_courses (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    pack_id text NOT NULL,
    added_by text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(trip_id,pack_id)
);
CREATE TABLE IF NOT EXISTS team_trip_remote_requests (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    request_id char(32) NOT NULL,
    requester_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    driver_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    car_id char(32) NOT NULL,
    protected bytea NOT NULL,
    PRIMARY KEY(trip_id,request_id),
    FOREIGN KEY(trip_id,car_id) REFERENCES team_trip_cars(trip_id,car_id) ON DELETE CASCADE
);
