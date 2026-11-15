CREATE TABLE IF NOT EXISTS team_trip_car_driving_scores (
    trip_id char(32) NOT NULL,
    car_id char(32) NOT NULL,
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    protected bytea NOT NULL,
    PRIMARY KEY (trip_id,car_id,pack_id,version),
    FOREIGN KEY (trip_id,car_id) REFERENCES team_trip_cars(trip_id,car_id) ON DELETE CASCADE,
    FOREIGN KEY (trip_id,pack_id) REFERENCES team_trip_courses(trip_id,pack_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_id,version) REFERENCES pack_versions(pack_id,version) ON DELETE CASCADE
);
