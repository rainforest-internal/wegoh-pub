ALTER TABLE team_trips ADD COLUMN IF NOT EXISTS next_car_ordinal integer NOT NULL DEFAULT 1
    CHECK (next_car_ordinal > 0);
ALTER TABLE team_trip_cars ADD COLUMN IF NOT EXISTS ordinal integer CHECK (ordinal > 0);
WITH numbered AS (
    SELECT trip_id,car_id,row_number() OVER (PARTITION BY trip_id ORDER BY created_at,car_id)::integer AS ordinal
    FROM team_trip_cars
)
UPDATE team_trip_cars c SET ordinal=n.ordinal FROM numbered n
WHERE c.trip_id=n.trip_id AND c.car_id=n.car_id AND c.ordinal IS NULL;
ALTER TABLE team_trip_cars ALTER COLUMN ordinal SET DEFAULT 1;
ALTER TABLE team_trip_cars ALTER COLUMN ordinal SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS team_trip_cars_ordinal ON team_trip_cars(trip_id,ordinal);
UPDATE team_trips t SET next_car_ordinal=GREATEST(t.next_car_ordinal,
    COALESCE((SELECT max(c.ordinal)+1 FROM team_trip_cars c WHERE c.trip_id=t.trip_id),1));
