CREATE TABLE IF NOT EXISTS team_trip_route_plans (
    trip_id char(32) PRIMARY KEY REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    protected bytea NOT NULL
);
