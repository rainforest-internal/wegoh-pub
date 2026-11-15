ALTER TABLE team_trips
    ADD COLUMN IF NOT EXISTS start_date date,
    ADD COLUMN IF NOT EXISTS end_date date;

ALTER TABLE team_trip_cars ADD COLUMN IF NOT EXISTS route_order bytea;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_trips'::regclass AND conname='team_trips_dates') THEN
        ALTER TABLE team_trips ADD CONSTRAINT team_trips_dates CHECK (
            (start_date IS NULL OR start_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31') AND
            (end_date IS NULL OR end_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31') AND
            (start_date IS NULL OR end_date IS NULL OR end_date - start_date BETWEEN 0 AND 30));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_trip_riders'::regclass AND conname='team_trip_riders_car_account') THEN
        ALTER TABLE team_trip_riders ADD CONSTRAINT team_trip_riders_car_account UNIQUE (trip_id,car_id,account_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS team_trip_car_places (
    trip_id char(32) NOT NULL,
    car_id char(32) NOT NULL,
    place_id char(32) NOT NULL,
    kind varchar(6) NOT NULL CHECK (kind IN ('pickup','drop')),
    added_by text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trip_id,car_id,place_id),
    UNIQUE (trip_id,car_id,place_id,kind),
    FOREIGN KEY (trip_id,car_id) REFERENCES team_trip_cars(trip_id,car_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS team_trip_car_place_selections (
    trip_id char(32) NOT NULL,
    car_id char(32) NOT NULL,
    place_id char(32) NOT NULL,
    account_id text NOT NULL,
    kind varchar(6) NOT NULL,
    PRIMARY KEY (trip_id,car_id,account_id,kind),
    FOREIGN KEY (trip_id,car_id,place_id,kind) REFERENCES team_trip_car_places(trip_id,car_id,place_id,kind) ON DELETE CASCADE,
    FOREIGN KEY (trip_id,car_id,account_id) REFERENCES team_trip_riders(trip_id,car_id,account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS team_trip_ride_invites (
    trip_id char(32) NOT NULL,
    car_id char(32) NOT NULL,
    invite_id char(32) NOT NULL,
    account_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trip_id,car_id,invite_id),
    UNIQUE (trip_id,car_id,account_id),
    FOREIGN KEY (trip_id,car_id) REFERENCES team_trip_cars(trip_id,car_id) ON DELETE CASCADE,
    FOREIGN KEY (trip_id,account_id) REFERENCES team_trip_members(trip_id,account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS team_trip_car_course_completions (
    trip_id char(32) NOT NULL,
    car_id char(32) NOT NULL,
    pack_id varchar(80) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trip_id,car_id,pack_id),
    FOREIGN KEY (trip_id,car_id) REFERENCES team_trip_cars(trip_id,car_id) ON DELETE CASCADE,
    FOREIGN KEY (trip_id,pack_id) REFERENCES team_trip_courses(trip_id,pack_id) ON DELETE CASCADE
);
