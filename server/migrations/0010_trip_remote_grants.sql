CREATE UNIQUE INDEX IF NOT EXISTS team_trip_cars_car_driver
    ON team_trip_cars (trip_id, car_id, driver_id);

CREATE TABLE IF NOT EXISTS team_trip_remote_grants (
    trip_id char(32) NOT NULL,
    car_id char(32) NOT NULL,
    requester_id text NOT NULL,
    driver_id text NOT NULL,
    device_id text NOT NULL REFERENCES native_device_refs(device_id) ON DELETE CASCADE,
    protected bytea NOT NULL,
    PRIMARY KEY (trip_id, requester_id),
    CHECK (requester_id <> driver_id),
    FOREIGN KEY (trip_id, car_id, requester_id)
        REFERENCES team_trip_riders(trip_id, car_id, account_id) ON DELETE CASCADE,
    FOREIGN KEY (trip_id, car_id, driver_id)
        REFERENCES team_trip_cars(trip_id, car_id, driver_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS team_trip_remote_grants_device
    ON team_trip_remote_grants (device_id);
REVOKE ALL ON team_trip_remote_grants FROM PUBLIC;
