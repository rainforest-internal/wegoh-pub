-- Functional consent is separate from base credentials and old ciphertext.
-- Apply after schema.sql and native_access_schema.sql as the application owner.
CREATE TABLE IF NOT EXISTS native_device_refs (
 device_id text PRIMARY KEY CHECK(device_id ~ '^[a-f0-9]{32}$'),
 kind text NOT NULL CHECK(kind IN ('native','retired'))
);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM team_devices d JOIN native_v2_grants g ON g.device_id=d.device_id) THEN
  RAISE EXCEPTION 'Device reference identity collision';
 END IF;
 IF EXISTS(SELECT 1 FROM native_device_refs r JOIN team_devices d ON d.device_id=r.device_id WHERE r.kind<>'retired')
 OR EXISTS(SELECT 1 FROM native_device_refs r JOIN native_v2_grants g ON g.device_id=r.device_id WHERE r.kind<>'native') THEN
  RAISE EXCEPTION 'Device reference kind differs';
 END IF;
END $$;
INSERT INTO native_device_refs(device_id,kind) SELECT device_id,'retired' FROM team_devices ON CONFLICT DO NOTHING;
INSERT INTO native_device_refs(device_id,kind) SELECT device_id,'native' FROM native_v2_grants WHERE device_id IS NOT NULL ON CONFLICT DO NOTHING;
DO $$ DECLARE t text;c record;name text; BEGIN
 FOREACH t IN ARRAY ARRAY['team_mission_device_grants','team_device_command_access','team_device_command_grants','team_device_commands','team_vehicle_purposes','team_vehicle_latest_reports','team_vehicle_report_receipts'] LOOP
  FOR c IN SELECT conname FROM pg_constraint WHERE conrelid=t::regclass AND contype='f' AND confrelid='team_devices'::regclass LOOP
   EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',t,c.conname);
  END LOOP;
  name=t||'_functional_device_ref';
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid=t::regclass AND conname=name) THEN
   EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY(device_id) REFERENCES native_device_refs(device_id)',t,name);
  END IF;
 END LOOP;
END $$;
CREATE TABLE IF NOT EXISTS native_functional_authorizations (
 grant_id text PRIMARY KEY REFERENCES native_v2_grants(grant_id),
 device_id text REFERENCES native_device_refs(device_id),
 installation_key_id text NOT NULL REFERENCES native_v2_installations(installation_key_id),
 revision integer NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
 state text NOT NULL CHECK(state IN ('APPROVED','ACTIVE','REVOKED')),
 protected bytea CHECK(octet_length(protected)>=32),
 expires_at bigint NOT NULL CHECK(expires_at BETWEEN 0 AND 253402300799),
 CHECK(state<>'ACTIVE' OR(device_id IS NOT NULL AND protected IS NOT NULL))
);
REVOKE ALL ON native_device_refs,native_functional_authorizations FROM PUBLIC;

-- Native room consent is auth-sensitive, default-off and never inherited from Web account flags.
CREATE TABLE IF NOT EXISTS native_room_music_authorizations (
 grant_id text NOT NULL REFERENCES native_v2_grants(grant_id),
 room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
 device_id text NOT NULL REFERENCES native_device_refs(device_id),
 revision integer NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
 state text NOT NULL CHECK(state IN ('ACTIVE','WITHDRAWN')),
 protected bytea CHECK(octet_length(protected)>=32),
 member_joined_at timestamptz NOT NULL,
 expires_at bigint NOT NULL CHECK(expires_at BETWEEN 0 AND 253402300799),
 PRIMARY KEY(grant_id,room_id),
 CHECK((state='ACTIVE')=(protected IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS native_room_music_device ON native_room_music_authorizations(device_id,room_id);
REVOKE ALL ON native_room_music_authorizations FROM PUBLIC;

-- Native room consent is auth-sensitive, default-off and never inherited from Web account flags.
CREATE TABLE IF NOT EXISTS native_room_voice_authorizations (
 grant_id text NOT NULL REFERENCES native_v2_grants(grant_id),
 room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
 device_id text NOT NULL REFERENCES native_device_refs(device_id),
 revision integer NOT NULL CHECK(revision BETWEEN 1 AND 2147483647),
 state text NOT NULL CHECK(state IN ('ACTIVE','WITHDRAWN')),
 protected bytea CHECK(octet_length(protected)>=32),
 member_joined_at timestamptz NOT NULL,
 expires_at bigint NOT NULL CHECK(expires_at BETWEEN 0 AND 253402300799),
 PRIMARY KEY(grant_id,room_id),
 CHECK((state='ACTIVE')=(protected IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS native_room_voice_device ON native_room_voice_authorizations(device_id,room_id);
REVOKE ALL ON native_room_voice_authorizations FROM PUBLIC;

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

-- Product metrics for the read-only Grafana role. Days and months are Asia/Seoul.
-- This file is applied last, so the views can read every application table.
-- metrics_private keeps per-account rows for reuse; it is never granted.
-- metrics exposes aggregate rows only. See docs/product-metrics.md.
CREATE SCHEMA IF NOT EXISTS metrics_private;
CREATE SCHEMA IF NOT EXISTS metrics;
REVOKE ALL ON SCHEMA metrics_private, metrics FROM PUBLIC;

CREATE OR REPLACE VIEW metrics_private.accounts AS
SELECT account_id, (created_at AT TIME ZONE 'Asia/Seoul')::date AS signup_day
FROM public.team_accounts
WHERE account_status <> 'deleted';

CREATE OR REPLACE VIEW metrics_private.calendar_days AS
SELECT generate_series(min(signup_day), (now() AT TIME ZONE 'Asia/Seoul')::date, interval '1 day')::date AS day
FROM metrics_private.accounts;

CREATE OR REPLACE VIEW metrics_private.calendar_months AS
SELECT DISTINCT date_trunc('month', day)::date AS month FROM metrics_private.calendar_days;

-- Membership has no join time, so a member takes part on the trip start day.
CREATE OR REPLACE VIEW metrics_private.trip_members AS
SELECT t.trip_id, m.account_id, t.state, t.started_at, t.ended_at,
       (t.started_at AT TIME ZONE 'Asia/Seoul')::date AS started_day,
       (t.ended_at AT TIME ZONE 'Asia/Seoul')::date AS ended_day
FROM public.team_trips t
JOIN public.team_trip_members m ON m.trip_id = t.trip_id
JOIN metrics_private.accounts a ON a.account_id = m.account_id
WHERE t.source_kind = 'trip' AND t.started_at IS NOT NULL;

-- One row per account, day and core action. Every user count reuses this view.
CREATE OR REPLACE VIEW metrics_private.account_activity AS
SELECT DISTINCT e.account_id, (e.happened_at AT TIME ZONE 'Asia/Seoul')::date AS day, e.action
FROM (
    SELECT account_id, started_at, 'trip' FROM metrics_private.trip_members
    UNION ALL SELECT creator_id, created_at, 'course_share' FROM public.pack_versions
    UNION ALL SELECT account_id, starred_at, 'course_save' FROM public.team_course_stars
    UNION ALL SELECT added_by, created_at, 'course_load' FROM public.team_trip_courses
    UNION ALL SELECT account_id, created_at, 'course_load' FROM public.team_remix_drafts
    UNION ALL SELECT follower_id, followed_at, 'creator_follow' FROM public.team_creator_follows
    UNION ALL SELECT account_id, created_at, 'hand_raise' FROM public.team_room_signals
    UNION ALL SELECT account_id, updated_at, 'hand_raise_reply' FROM public.team_room_votes
    UNION ALL SELECT requester_id, created_at, 'vehicle_control' FROM public.friend_vehicle_commands
) AS e(account_id, happened_at, action)
JOIN metrics_private.accounts a ON a.account_id = e.account_id;

CREATE OR REPLACE VIEW metrics_private.retention_users AS
WITH first_trip AS (
    SELECT DISTINCT ON (account_id) account_id, trip_id, ended_at, ended_day
    FROM metrics_private.trip_members
    WHERE state = 'completed'
    ORDER BY account_id, ended_at, trip_id
)
SELECT f.account_id, f.ended_day AS first_trip_day,
       EXISTS (SELECT 1 FROM metrics_private.account_activity a
               WHERE a.account_id = f.account_id AND a.action IN ('trip', 'course_save', 'course_load')
                 AND a.day BETWEEN f.ended_day + 30 AND f.ended_day + 59) AS returned_30_59,
       EXISTS (SELECT 1 FROM metrics_private.trip_members t
               WHERE t.account_id = f.account_id AND t.trip_id <> f.trip_id
                 AND t.started_at > f.ended_at AND t.started_day <= f.ended_day + 90) AS retrip_90,
       f.ended_day + 60 AS returned_30_59_measurable_on,
       f.ended_day + 91 AS retrip_90_measurable_on
FROM first_trip f;

CREATE OR REPLACE VIEW metrics.daily_users AS
SELECT d.day,
       (SELECT count(*) FROM metrics_private.accounts a WHERE a.signup_day = d.day)::integer AS new_users,
       (SELECT count(*) FROM metrics_private.accounts a WHERE a.signup_day <= d.day)::integer AS total_users,
       (SELECT count(DISTINCT account_id) FROM metrics_private.account_activity a
        WHERE a.day = d.day)::integer AS active_users
FROM metrics_private.calendar_days d;

CREATE OR REPLACE VIEW metrics.monthly_users AS
SELECT m.month, u.active_users, u.total_users,
       round(u.active_users::numeric / NULLIF(u.total_users, 0), 4) AS active_share
FROM metrics_private.calendar_months m
CROSS JOIN LATERAL (
    SELECT (SELECT count(DISTINCT account_id) FROM metrics_private.account_activity a
            WHERE a.day >= m.month AND a.day < (m.month + interval '1 month')::date)::integer AS active_users,
           (SELECT count(*) FROM metrics_private.accounts a
            WHERE a.signup_day < (m.month + interval '1 month')::date)::integer AS total_users
) u;

CREATE OR REPLACE VIEW metrics.overview AS
WITH today AS (SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS day),
month AS (SELECT * FROM metrics.monthly_users WHERE month = date_trunc('month', (SELECT day FROM today))::date)
SELECT t.day AS today,
       COALESCE((SELECT active_users FROM metrics.daily_users WHERE day = t.day), 0) AS dau,
       COALESCE((SELECT active_users FROM month), 0) AS mau,
       round((SELECT avg(active_users) FROM metrics.daily_users
              WHERE day >= date_trunc('month', t.day)::date) / NULLIF((SELECT active_users FROM month), 0), 4) AS dau_mau,
       (SELECT count(*) FROM metrics_private.accounts)::integer AS total_users,
       (SELECT active_share FROM month) AS monthly_active_share,
       (SELECT count(DISTINCT g.account_id)
        FROM public.native_v2_grants g
        JOIN public.native_v2_installations i ON i.installation_key_id = g.installation_key_id
        JOIN metrics_private.accounts a ON a.account_id = g.account_id
        WHERE g.state = 'TOKEN_ISSUED' AND i.active_grant_id = g.grant_id AND i.revoked_at IS NULL
          AND g.expires_at > extract(epoch FROM now()))::integer AS vehicle_connected_users
FROM today t;

CREATE OR REPLACE VIEW metrics.retention_cohorts AS
SELECT date_trunc('month', r.first_trip_day)::date AS cohort_month,
       count(*)::integer AS first_trip_users,
       count(*) FILTER (WHERE r.returned_30_59)::integer AS returned_30_59_users,
       max(r.returned_30_59_measurable_on) AS returned_30_59_measurable_on,
       max(r.returned_30_59_measurable_on) <= t.day AS returned_30_59_measurable,
       CASE WHEN max(r.returned_30_59_measurable_on) <= t.day
            THEN round(count(*) FILTER (WHERE r.returned_30_59)::numeric / count(*), 4) END AS returned_30_59_rate,
       count(*) FILTER (WHERE r.retrip_90)::integer AS retrip_90_users,
       max(r.retrip_90_measurable_on) AS retrip_90_measurable_on,
       max(r.retrip_90_measurable_on) <= t.day AS retrip_90_measurable,
       CASE WHEN max(r.retrip_90_measurable_on) <= t.day
            THEN round(count(*) FILTER (WHERE r.retrip_90)::numeric / count(*), 4) END AS retrip_90_rate
FROM metrics_private.retention_users r
CROSS JOIN (SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS day) t
GROUP BY 1, t.day;

-- Pools every user whose window has fully passed; next date when nobody qualifies yet.
CREATE OR REPLACE VIEW metrics.retention_overview AS
WITH t AS (SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS day)
SELECT count(r.account_id)::integer AS first_trip_users,
       count(*) FILTER (WHERE r.returned_30_59_measurable_on <= t.day)::integer AS returned_30_59_base_users,
       count(*) FILTER (WHERE r.returned_30_59_measurable_on <= t.day AND r.returned_30_59)::integer AS returned_30_59_users,
       round(count(*) FILTER (WHERE r.returned_30_59_measurable_on <= t.day AND r.returned_30_59)::numeric
             / NULLIF(count(*) FILTER (WHERE r.returned_30_59_measurable_on <= t.day), 0), 4) AS returned_30_59_rate,
       min(r.returned_30_59_measurable_on) FILTER (WHERE r.returned_30_59_measurable_on > t.day) AS returned_30_59_next_measurable_on,
       count(*) FILTER (WHERE r.retrip_90_measurable_on <= t.day)::integer AS retrip_90_base_users,
       count(*) FILTER (WHERE r.retrip_90_measurable_on <= t.day AND r.retrip_90)::integer AS retrip_90_users,
       round(count(*) FILTER (WHERE r.retrip_90_measurable_on <= t.day AND r.retrip_90)::numeric
             / NULLIF(count(*) FILTER (WHERE r.retrip_90_measurable_on <= t.day), 0), 4) AS retrip_90_rate,
       min(r.retrip_90_measurable_on) FILTER (WHERE r.retrip_90_measurable_on > t.day) AS retrip_90_next_measurable_on
FROM t LEFT JOIN metrics_private.retention_users r ON true
GROUP BY t.day;

CREATE OR REPLACE VIEW metrics.monthly_trips AS
WITH trips AS (
    SELECT t.state,
           date_trunc('month', t.started_at AT TIME ZONE 'Asia/Seoul')::date AS started_month,
           date_trunc('month', t.ended_at AT TIME ZONE 'Asia/Seoul')::date AS ended_month,
           (SELECT count(*) FROM public.team_trip_cars c WHERE c.trip_id = t.trip_id) AS cars,
           (SELECT count(*) FROM public.team_trip_members m WHERE m.trip_id = t.trip_id) AS members
    FROM public.team_trips t
    WHERE t.source_kind = 'trip' AND t.started_at IS NOT NULL
)
SELECT m.month,
       count(*) FILTER (WHERE t.started_month = m.month)::integer AS started_trips,
       count(*) FILTER (WHERE t.state = 'completed' AND t.ended_month = m.month)::integer AS completed_trips,
       count(*) FILTER (WHERE t.started_month = m.month AND t.cars >= 2)::integer AS multi_car_trips,
       round(count(*) FILTER (WHERE t.started_month = m.month AND t.cars >= 2)::numeric
             / NULLIF(count(*) FILTER (WHERE t.started_month = m.month), 0), 4) AS multi_car_share,
       round(avg(t.members) FILTER (WHERE t.started_month = m.month), 2) AS average_members
FROM metrics_private.calendar_months m
LEFT JOIN trips t ON m.month IN (t.started_month, t.ended_month)
GROUP BY m.month;

CREATE OR REPLACE VIEW metrics.monthly_group_actions AS
SELECT m.month,
       (SELECT count(*) FROM public.team_room_signals s
        WHERE date_trunc('month', s.created_at AT TIME ZONE 'Asia/Seoul')::date = m.month)::integer AS hand_raises,
       (SELECT count(*) FROM public.team_room_votes v
        WHERE date_trunc('month', v.updated_at AT TIME ZONE 'Asia/Seoul')::date = m.month)::integer AS hand_raise_replies,
       (SELECT count(*) FROM public.friend_vehicle_commands c
        WHERE date_trunc('month', c.created_at AT TIME ZONE 'Asia/Seoul')::date = m.month)::integer AS vehicle_control_requests
FROM metrics_private.calendar_months m;

CREATE OR REPLACE VIEW metrics.monthly_course_flow AS
WITH creators AS (
    SELECT DISTINCT ON (pack_id) pack_id, creator_id FROM public.pack_versions ORDER BY pack_id, version
),
others_courses AS (
    SELECT c.trip_id, c.created_at
    FROM public.team_trip_courses c JOIN creators p ON p.pack_id = c.pack_id
    WHERE c.added_by <> p.creator_id
),
started AS (
    SELECT date_trunc('month', t.started_at AT TIME ZONE 'Asia/Seoul')::date AS month,
           EXISTS (SELECT 1 FROM others_courses o WHERE o.trip_id = t.trip_id AND o.created_at <= t.started_at) AS with_others_course
    FROM public.team_trips t
    WHERE t.source_kind = 'trip' AND t.started_at IS NOT NULL
)
SELECT m.month,
       (SELECT count(*) FROM public.pack_versions p JOIN metrics_private.accounts a ON a.account_id = p.creator_id
        WHERE date_trunc('month', p.created_at AT TIME ZONE 'Asia/Seoul')::date = m.month)::integer AS courses_shared,
       (SELECT count(*) FROM public.team_course_stars s
        JOIN public.pack_versions p ON p.pack_id = s.pack_id AND p.version = s.version
        WHERE s.account_id <> p.creator_id
          AND date_trunc('month', s.starred_at AT TIME ZONE 'Asia/Seoul')::date = m.month)::integer AS courses_saved,
       (SELECT count(*) FROM public.team_creator_follows f
        WHERE date_trunc('month', f.followed_at AT TIME ZONE 'Asia/Seoul')::date = m.month)::integer AS creator_follows,
       (SELECT count(*) FROM others_courses o
        WHERE date_trunc('month', o.created_at AT TIME ZONE 'Asia/Seoul')::date = m.month)::integer AS others_courses_loaded,
       (SELECT count(*) FROM started s WHERE s.month = m.month)::integer AS started_trips,
       (SELECT count(*) FROM started s WHERE s.month = m.month AND s.with_others_course)::integer AS trips_with_others_course,
       round((SELECT count(*) FROM started s WHERE s.month = m.month AND s.with_others_course)::numeric
             / NULLIF((SELECT count(*) FROM started s WHERE s.month = m.month), 0), 4) AS trips_with_others_course_share
FROM metrics_private.calendar_months m;
