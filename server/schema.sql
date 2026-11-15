CREATE TABLE IF NOT EXISTS dev_assets (
    checksum char(64) PRIMARY KEY CHECK (checksum ~ '^[0-9a-f]{64}$'),
    media_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size > 0 AND byte_size <= 26214400),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS studio_sessions (
    token_hash char(64) PRIMARY KEY,
    creator_id text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS pack_versions (
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    creator_id text NOT NULL,
    checksum char(64) NOT NULL,
    title varchar(100) NOT NULL,
    author varchar(80) NOT NULL,
    description varchar(500) NOT NULL,
    stop_count integer NOT NULL CHECK (stop_count BETWEEN 1 AND 3),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack_id, version)
);
CREATE TABLE IF NOT EXISTS visited_places (
    visit_id varchar(80) PRIMARY KEY,
    creator_id text NOT NULL,
    place jsonb,
    visited_at bigint NOT NULL CHECK (visited_at > 0)
);
ALTER TABLE visited_places ADD COLUMN IF NOT EXISTS protected bytea;
ALTER TABLE visited_places ALTER COLUMN place DROP NOT NULL;

-- Review rows retain post-publication reports and operator decisions; publication has no review prerequisite.
-- The original immutable pack bytes and historical versions are never deleted.
CREATE TABLE IF NOT EXISTS pack_reviews (
    checksum char(64) PRIMARY KEY CHECK (checksum ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('approved','rejected','quarantined')),
    reviewer varchar(80) NOT NULL,
    review_note varchar(1000) NOT NULL,
    reviewed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS content_reports (
    report_id char(32) PRIMARY KEY,
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL,
    checksum char(64) NOT NULL,
    creator_id text NOT NULL,
    reason text NOT NULL CHECK (reason IN ('harmful','privacy','rights','other')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (checksum,creator_id,reason),
    FOREIGN KEY (pack_id,version) REFERENCES pack_versions(pack_id,version)
);
CREATE TABLE IF NOT EXISTS pack_review_events (
    event_id bigserial PRIMARY KEY,
    checksum char(64) NOT NULL,
    state text NOT NULL CHECK (state IN ('approved','rejected','quarantined')),
    reviewer varchar(80) NOT NULL,
    review_note varchar(1000) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Shared team-demo state is additive. Existing local records/keys are untouched.
CREATE TABLE IF NOT EXISTS team_accounts (
    account_id text PRIMARY KEY,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE team_accounts ADD COLUMN IF NOT EXISTS handle text;
ALTER TABLE team_accounts ADD COLUMN IF NOT EXISTS account_status text NOT NULL DEFAULT 'active'
    CHECK (account_status IN ('active','suspended','deleted'));
ALTER TABLE team_accounts ADD COLUMN IF NOT EXISTS handle_changed_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS team_accounts_handle_unique ON team_accounts (lower(handle));
ALTER TABLE team_accounts ALTER COLUMN handle SET DEFAULT
    ('user_' || left(replace(gen_random_uuid()::text,'-',''),15));
DO $$
DECLARE account text; candidate text; attempt integer;
BEGIN
    FOR account IN SELECT account_id FROM team_accounts WHERE handle IS NULL ORDER BY account_id LOOP
        attempt := 0;
        LOOP
            candidate := 'user_' || left(md5(account || ':' || attempt::text),15);
            IF NOT EXISTS (SELECT 1 FROM team_accounts WHERE lower(handle)=candidate) THEN
                UPDATE team_accounts SET handle=candidate WHERE account_id=account AND handle IS NULL;
                EXIT;
            END IF;
            attempt := attempt + 1;
        END LOOP;
    END LOOP;
END $$;
ALTER TABLE team_accounts ALTER COLUMN handle SET NOT NULL;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_accounts'::regclass AND conname='team_accounts_handle_format') THEN
        ALTER TABLE team_accounts ADD CONSTRAINT team_accounts_handle_format
            CHECK (handle ~ '^[a-z0-9][a-z0-9_.]{2,19}$');
    END IF;
END $$;
CREATE TABLE IF NOT EXISTS team_pairings (
    device_hash char(64) PRIMARY KEY,
    user_code char(8) UNIQUE NOT NULL,
    challenge char(43) NOT NULL,
    protected bytea NOT NULL,
    account_id text REFERENCES team_accounts(account_id),
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
    last_polled_at timestamptz
);
CREATE TABLE IF NOT EXISTS team_devices (
    device_id char(32) PRIMARY KEY,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    access_hash char(64) UNIQUE NOT NULL,
    access_expires_at timestamptz NOT NULL,
    refresh_hash char(64) UNIQUE NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);
CREATE TABLE IF NOT EXISTS team_rate_limits (
    scope_hash char(64) PRIMARY KEY,
    bucket bigint NOT NULL,
    hits integer NOT NULL CHECK (hits>0)
);

CREATE TABLE IF NOT EXISTS team_playlists (
    playlist_id char(32) PRIMARY KEY,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS team_resource_versions (
    account_id text NOT NULL,
    resource text NOT NULL CHECK(resource = ANY(ARRAY['courses'::text,'playlists'::text,'devices'::text,'friends'::text,'rooms'::text,'history'::text,'vehicle'::text,'content'::text,'recommendations'::text,'cautions'::text])),
    revision bigint NOT NULL CHECK(revision>0),
    PRIMARY KEY(account_id,resource)
);
CREATE TABLE IF NOT EXISTS team_socket_leases (
    lease_id char(32) PRIMARY KEY,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    expires_at timestamptz NOT NULL
);

-- Minimal pseudonymous ownership index; relationship state is AES-GCM protected.
CREATE TABLE IF NOT EXISTS team_friend_pairs (
    account_a text NOT NULL REFERENCES team_accounts(account_id),
    account_b text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(account_a,account_b),
    CHECK(account_a<account_b)
);

CREATE TABLE IF NOT EXISTS team_rooms (
    room_id char(32) PRIMARY KEY,
    owner_id text NOT NULL REFERENCES team_accounts(account_id),
    code_hash char(64) UNIQUE NOT NULL,
    expiry_notified_at timestamptz,
    protected bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    closed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS team_room_members (
    room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    joined_at timestamptz NOT NULL DEFAULT now(),
    left_at timestamptz,
    PRIMARY KEY(room_id,account_id)
);
CREATE TABLE IF NOT EXISTS team_room_signals (
    signal_id char(32) PRIMARY KEY,
    room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS team_room_votes (
    signal_id char(32) NOT NULL REFERENCES team_room_signals(signal_id),
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(signal_id,account_id)
);


-- Private trip objects remain owner-scoped; all place/review/trace/grant data is encrypted.
CREATE TABLE IF NOT EXISTS team_histories (
    history_id char(32) PRIMARY KEY,
    owner_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
    permission_revision integer NOT NULL DEFAULT 1 CHECK(permission_revision>0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS team_history_visits (
    history_id char(32) NOT NULL REFERENCES team_histories(history_id) ON DELETE CASCADE,
    visit_id char(32) NOT NULL,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(history_id,visit_id)
);
CREATE TABLE IF NOT EXISTS team_history_shares (
    history_id char(32) NOT NULL REFERENCES team_histories(history_id) ON DELETE CASCADE,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    PRIMARY KEY(history_id,account_id)
);
CREATE TABLE IF NOT EXISTS team_history_trace_batches (
    history_id char(32) NOT NULL REFERENCES team_histories(history_id) ON DELETE CASCADE,
    batch_id char(32) NOT NULL,
    protected bytea NOT NULL,
    point_count integer NOT NULL CHECK(point_count BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(history_id,batch_id)
);
CREATE INDEX IF NOT EXISTS team_history_owner_updated ON team_histories(owner_id,updated_at DESC,history_id DESC);
CREATE INDEX IF NOT EXISTS team_history_receiver ON team_history_shares(account_id,history_id);

-- Purpose-limited sanitized visit photos. Existing records/keys are untouched.
CREATE TABLE IF NOT EXISTS team_history_photos (
    history_id char(32) NOT NULL,
    visit_id char(32) NOT NULL,
    photo_id char(32) NOT NULL,
    owner_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    image_protected bytea NOT NULL,
    byte_size integer NOT NULL CHECK(byte_size>0 AND byte_size<=3145728),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(history_id,visit_id,photo_id),
    FOREIGN KEY(history_id,visit_id) REFERENCES team_history_visits(history_id,visit_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS team_history_photos_owner ON team_history_photos(owner_id);

-- Explicitly submitted, purpose-limited UGC projections only. Originals remain private.
CREATE TABLE IF NOT EXISTS team_content_reviews (
    kind text NOT NULL CHECK(kind = ANY(ARRAY['history'::text,'room'::text,'room-place'::text,'photo'::text,'room-music'::text,'caution'::text])),
    content_key text NOT NULL,
    owner_id text NOT NULL REFERENCES team_accounts(account_id),
    checksum char(64) NOT NULL,
    state text NOT NULL CHECK(state IN('private','quarantined','approved','rejected')),
    protected bytea NOT NULL,
    expires_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(kind,content_key)
);
CREATE INDEX IF NOT EXISTS team_content_reviews_queue ON team_content_reviews(state,updated_at,kind,content_key);
CREATE TABLE IF NOT EXISTS team_content_review_events (
    event_id char(32) PRIMARY KEY,
    kind text NOT NULL,
    content_key text NOT NULL,
    owner_id text NOT NULL,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS team_content_events_item ON team_content_review_events(kind,content_key,created_at);

-- Add the administrator-only review feed without deleting existing versions.
ALTER TABLE team_resource_versions DROP CONSTRAINT IF EXISTS team_resource_versions_resource_check;
ALTER TABLE team_resource_versions ADD CONSTRAINT team_resource_versions_resource_check
CHECK(resource = ANY(ARRAY['courses'::text,'playlists'::text,'devices'::text,'friends'::text,'rooms'::text,'history'::text,'vehicle'::text,'content'::text,'recommendations'::text,'cautions'::text]));

-- Separate, default-off external-file purposes. Private payloads use the existing key.
CREATE TABLE IF NOT EXISTS team_story_permissions (
    history_id char(32) NOT NULL REFERENCES team_histories(history_id) ON DELETE CASCADE,
    exporter_id text NOT NULL REFERENCES team_accounts(account_id),
    revision integer NOT NULL CHECK(revision>0),
    protected bytea NOT NULL,
    PRIMARY KEY(history_id,exporter_id)
);
CREATE TABLE IF NOT EXISTS team_story_manifests (
    manifest_id char(32) PRIMARY KEY,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS team_story_manifests_actor ON team_story_manifests(account_id,expires_at);

-- Live voice stores individual filters and audio-free report metadata only.
CREATE TABLE IF NOT EXISTS team_voice_filters (
 room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
 account_id text NOT NULL REFERENCES team_accounts(account_id),
 speaker_id text NOT NULL REFERENCES team_accounts(account_id),
 protected bytea NOT NULL,
 PRIMARY KEY(room_id,account_id,speaker_id)
);
CREATE TABLE IF NOT EXISTS team_voice_reports (
 report_id char(32) PRIMARY KEY,
 room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
 account_id text NOT NULL REFERENCES team_accounts(account_id),
 speaker_id text NOT NULL REFERENCES team_accounts(account_id),
 protected bytea NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 resolved_at timestamptz
);
CREATE INDEX IF NOT EXISTS team_voice_reports_pending ON team_voice_reports(room_id,speaker_id)WHERE resolved_at IS NULL;

-- Room DJ selection only; metadata remains in the owner's encrypted playlist.
CREATE TABLE IF NOT EXISTS team_room_music (
    room_id char(32) PRIMARY KEY REFERENCES team_rooms(room_id),
    revision integer NOT NULL CHECK(revision>0),
    protected bytea,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE team_content_reviews DROP CONSTRAINT IF EXISTS team_content_reviews_kind_check;
ALTER TABLE team_content_reviews ADD CONSTRAINT team_content_reviews_kind_check
    CHECK(kind = ANY(ARRAY['history'::text,'room'::text,'room-place'::text,'photo'::text,'room-music'::text,'caution'::text]));


-- Separate personal recommendation purposes/preferences and bounded feedback.
-- Exact search anchors/GPS, original history and provider data are not copied here.
CREATE TABLE IF NOT EXISTS team_recommendations (
    account_id text PRIMARY KEY REFERENCES team_accounts(account_id),
    revision integer NOT NULL CHECK(revision>0),
    protected bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Mission identities/relations are indexed; purpose, progress and course are AES-GCM records.
CREATE TABLE IF NOT EXISTS team_driving_grants (
    room_id varchar(32) NOT NULL REFERENCES team_rooms(room_id),
    account_id varchar(64) NOT NULL REFERENCES team_accounts(account_id),
    device_id varchar(32) NOT NULL,
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY(room_id,account_id,device_id)
);
CREATE TABLE IF NOT EXISTS team_driving_sessions (
    session_id varchar(32) PRIMARY KEY,
    room_id varchar(32) NOT NULL REFERENCES team_rooms(room_id),
    account_id varchar(64) NOT NULL REFERENCES team_accounts(account_id),
    device_id varchar(32) NOT NULL,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    closed_at timestamptz
);
CREATE INDEX IF NOT EXISTS team_driving_owner ON team_driving_sessions(account_id,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS team_driving_one_active ON team_driving_sessions(account_id) WHERE closed_at IS NULL;
CREATE TABLE IF NOT EXISTS team_driving_samples (
    session_id varchar(32) NOT NULL REFERENCES team_driving_sessions(session_id),
    sequence integer NOT NULL CHECK(sequence BETWEEN 1 AND 86400),
    protected bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(session_id,sequence)
);

CREATE TABLE IF NOT EXISTS team_missions (
    mission_id varchar(32) PRIMARY KEY,
    room_id varchar(32) NOT NULL REFERENCES team_rooms(room_id),
    owner_id varchar(64) NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    state varchar(16) NOT NULL DEFAULT 'enrolling' CHECK(state::text = ANY (ARRAY['enrolling'::text,'active'::text,'completed'::text,'cancelled'::text])),
    revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS team_missions_room ON team_missions(room_id,created_at);
CREATE TABLE IF NOT EXISTS team_mission_members (
    mission_id varchar(32) NOT NULL REFERENCES team_missions(mission_id),
    account_id varchar(64) NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(mission_id,account_id)
);
CREATE TABLE IF NOT EXISTS team_mission_events (
    mission_id varchar(32) NOT NULL,
    account_id varchar(64) NOT NULL,
    event_id varchar(32) NOT NULL,
    protected bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(mission_id,account_id,event_id),
    FOREIGN KEY(mission_id,account_id) REFERENCES team_mission_members(mission_id,account_id)
);
CREATE TABLE IF NOT EXISTS team_mission_device_grants (
    mission_id varchar(32) NOT NULL,
    account_id varchar(64) NOT NULL,
    device_id varchar(32) NOT NULL REFERENCES team_devices(device_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY(mission_id,account_id,device_id),
    FOREIGN KEY(mission_id,account_id) REFERENCES team_mission_members(mission_id,account_id)
);

CREATE TABLE IF NOT EXISTS team_recommendation_learning (
    account_id text PRIMARY KEY REFERENCES team_accounts(account_id),
    revision integer NOT NULL CHECK(revision > 0),
    protected bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Independent command protocol. Payload/consent/lease/ACK bodies are GCM records.
CREATE TABLE IF NOT EXISTS team_device_command_access (
    device_id text PRIMARY KEY REFERENCES team_devices(device_id),
    protected bytea NOT NULL
);
CREATE TABLE IF NOT EXISTS team_device_command_members (
    room_id text NOT NULL REFERENCES team_rooms(room_id),
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    PRIMARY KEY(room_id,account_id)
);
CREATE TABLE IF NOT EXISTS team_device_command_grants (
    room_id text NOT NULL REFERENCES team_rooms(room_id),
    device_id text NOT NULL REFERENCES team_devices(device_id),
    requester_id text NOT NULL REFERENCES team_accounts(account_id),
    owner_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    PRIMARY KEY(room_id,device_id,requester_id)
);
CREATE TABLE IF NOT EXISTS team_device_commands (
    request_id text PRIMARY KEY,
    room_id text NOT NULL REFERENCES team_rooms(room_id),
    device_id text NOT NULL REFERENCES team_devices(device_id),
    requester_id text NOT NULL REFERENCES team_accounts(account_id),
    owner_id text NOT NULL REFERENCES team_accounts(account_id),
    event_hash text NOT NULL,
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(requester_id,event_hash)
);

-- Separate explicit derivative purposes. Personal source links/drafts are AES-GCM.
CREATE TABLE IF NOT EXISTS team_course_reuse_permissions (
    pack_id text NOT NULL,
    version integer NOT NULL,
    revision integer NOT NULL CHECK(revision>0),
    protected bytea NOT NULL,
    PRIMARY KEY(pack_id,version),
    FOREIGN KEY(pack_id,version) REFERENCES pack_versions(pack_id,version) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS team_history_remix_permissions (
    history_id text NOT NULL REFERENCES team_histories(history_id) ON DELETE CASCADE,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    kind text NOT NULL CHECK(kind = ANY(ARRAY['course'::text,'visits'::text])),
    revision integer NOT NULL CHECK(revision>0),
    protected bytea NOT NULL,
    PRIMARY KEY(history_id,account_id,kind)
);
CREATE TABLE IF NOT EXISTS team_remix_drafts (
    draft_id text PRIMARY KEY,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    history_id text REFERENCES team_histories(history_id) ON DELETE SET NULL,
    draft_pack_id text NOT NULL UNIQUE,
    protected bytea NOT NULL,
    state text NOT NULL DEFAULT 'draft' CHECK(state = ANY(ARRAY['draft'::text,'published'::text])),
    created_at timestamptz NOT NULL DEFAULT now()
);


CREATE TABLE IF NOT EXISTS team_cautions (
    caution_id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
    permission_revision integer NOT NULL DEFAULT 1 CHECK(permission_revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS team_cautions_owner ON team_cautions(owner_id,updated_at,caution_id);
CREATE TABLE IF NOT EXISTS team_caution_shares (
    caution_id text NOT NULL REFERENCES team_cautions(caution_id) ON DELETE CASCADE,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY(caution_id,account_id)
);
CREATE TABLE IF NOT EXISTS team_caution_receipts (
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    event_id text NOT NULL,
    caution_id text REFERENCES team_cautions(caution_id) ON DELETE SET NULL,
    protected bytea NOT NULL,
    PRIMARY KEY(account_id,event_id)
);
-- The receipt contains only an owner/AAD-encrypted canonical request hash.
-- Deletion clears the caution/source snapshot and leaves a bounded minimal nonce
-- tombstone, so uncertain retries do not silently resurrect a deleted record.

-- LIVE-11 explicit report purposes and latest-only room reports. No trace/history copy.
CREATE TABLE IF NOT EXISTS team_vehicle_purposes (
    device_id char(32) PRIMARY KEY REFERENCES team_devices(device_id),
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
    expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS team_vehicle_room_grants (
    room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY(room_id,account_id)
);
CREATE TABLE IF NOT EXISTS team_vehicle_latest_reports (
    room_id char(32) NOT NULL REFERENCES team_rooms(room_id),
    device_id char(32) NOT NULL REFERENCES team_devices(device_id),
    kind varchar(16) NOT NULL CHECK(kind::text = ANY (ARRAY['location'::text,'visits'::text])),
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(room_id,device_id,kind)
);
CREATE TABLE IF NOT EXISTS team_vehicle_report_receipts (
    device_id char(32) NOT NULL REFERENCES team_devices(device_id),
    event_id char(32) NOT NULL,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(device_id,event_id)
);

-- Shared nonpersonal public/mock fuel snapshots. No account, coordinate or key data.
CREATE TABLE IF NOT EXISTS fuel_quote_cache (
    namespace varchar(96) NOT NULL,
    region varchar(4) NOT NULL CHECK(region ~ '^[0-9]{2}([0-9]{2})?$'),
    fuel varchar(16) NOT NULL CHECK(fuel IN ('gasoline','diesel','lpg')),
    payload jsonb,
    fetched_at timestamptz,
    fresh_until timestamptz,
    retry_after timestamptz,
    last_error varchar(64),
    PRIMARY KEY(namespace,region,fuel),
    CHECK((payload IS NULL AND fetched_at IS NULL AND fresh_until IS NULL) OR
          (payload IS NOT NULL AND fetched_at IS NOT NULL AND fresh_until>fetched_at))
);
CREATE TABLE IF NOT EXISTS fuel_upstream_attempts (
    attempt_id char(32) PRIMARY KEY,
    budget_key varchar(80) NOT NULL,
    attempted_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS fuel_attempts_rolling_budget ON fuel_upstream_attempts(budget_key,attempted_at);

-- E3 shared room playlist
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

-- E1 room archive
ALTER TABLE team_rooms ADD COLUMN IF NOT EXISTS archived_at timestamptz;
ALTER TABLE team_rooms ADD COLUMN IF NOT EXISTS archived_music bytea;
CREATE INDEX IF NOT EXISTS team_rooms_archive_pending ON team_rooms(expires_at,room_id)
    WHERE archived_at IS NULL;

-- Personal archive saves are idempotent while the resulting record exists.
CREATE TABLE IF NOT EXISTS team_room_history_saves (
    room_id char(32) NOT NULL REFERENCES team_rooms(room_id) ON DELETE CASCADE,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    history_id char(32) NOT NULL UNIQUE REFERENCES team_histories(history_id) ON DELETE CASCADE,
    PRIMARY KEY(room_id,account_id)
);

CREATE TABLE IF NOT EXISTS team_course_stars (
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    PRIMARY KEY(pack_id,version,account_id),
    FOREIGN KEY(pack_id,version) REFERENCES pack_versions(pack_id,version) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS team_course_stars_account ON team_course_stars(account_id);

CREATE TABLE IF NOT EXISTS team_creator_follows (
    follower_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    creator_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    follow_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    followed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(follower_id,creator_id),
    CHECK (follower_id <> creator_id)
);
CREATE TABLE IF NOT EXISTS team_course_news_reads (
    follow_id uuid NOT NULL REFERENCES team_creator_follows(follow_id) ON DELETE CASCADE,
    event_id bigint NOT NULL REFERENCES pack_review_events(event_id) ON DELETE CASCADE,
    PRIMARY KEY(follow_id,event_id)
);
CREATE INDEX IF NOT EXISTS pack_first_approval ON pack_review_events(checksum,event_id)
    WHERE state='approved';

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
ALTER TABLE team_trips
    ADD COLUMN IF NOT EXISTS state varchar(16) NOT NULL DEFAULT 'planned',
    ADD COLUMN IF NOT EXISTS started_at timestamptz,
    ADD COLUMN IF NOT EXISTS ended_at timestamptz,
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz,
    ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS source_kind varchar(16) NOT NULL DEFAULT 'trip',
    ADD COLUMN IF NOT EXISTS state_revision integer NOT NULL DEFAULT 1;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_trips'::regclass AND conname='team_trips_revision_positive') THEN
        ALTER TABLE team_trips
            ADD CONSTRAINT team_trips_revision_positive CHECK (revision > 0),
            ADD CONSTRAINT team_trips_state_revision CHECK (state_revision > 0 AND state_revision <= revision),
            ADD CONSTRAINT team_trips_source_kind CHECK (source_kind IN ('trip', 'legacy_room')),
            ADD CONSTRAINT team_trips_lifecycle CHECK (
                (state = 'planned' AND started_at IS NULL AND ended_at IS NULL) OR
                (state = 'active' AND started_at IS NOT NULL AND ended_at IS NULL) OR
                (state = 'completed' AND started_at IS NOT NULL AND ended_at IS NOT NULL AND ended_at >= started_at) OR
                (state = 'cancelled' AND started_at IS NULL AND ended_at IS NOT NULL)
            ),
            ADD CONSTRAINT team_trips_deleted_closed CHECK (deleted_at IS NULL OR state IN ('completed', 'cancelled'));
    END IF;
END $$;

ALTER TABLE team_rooms
    ADD COLUMN IF NOT EXISTS trip_id char(32),
    ALTER COLUMN code_hash DROP NOT NULL,
    ALTER COLUMN expires_at DROP NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_rooms'::regclass AND conname='team_rooms_one_per_trip') THEN
        ALTER TABLE team_rooms
            ADD CONSTRAINT team_rooms_one_per_trip UNIQUE (trip_id),
            ADD CONSTRAINT team_rooms_trip_fk FOREIGN KEY (trip_id) REFERENCES team_trips(trip_id) ON DELETE RESTRICT,
            ADD CONSTRAINT team_rooms_context_kind CHECK (
                (trip_id IS NULL AND expires_at IS NOT NULL AND code_hash IS NOT NULL) OR
                (trip_id IS NOT NULL AND expires_at IS NULL AND code_hash IS NULL)
            );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS team_trip_place_proposals (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    proposal_id char(32) NOT NULL,
    account_id text NOT NULL REFERENCES team_accounts(account_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (trip_id, proposal_id)
);
CREATE INDEX IF NOT EXISTS team_trip_place_proposals_order ON team_trip_place_proposals(trip_id, created_at, proposal_id);

CREATE TABLE IF NOT EXISTS team_trip_signal_contexts (
    signal_id char(32) PRIMARY KEY REFERENCES team_room_signals(signal_id),
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)
);

CREATE TABLE IF NOT EXISTS team_trip_results (
    trip_id char(32) PRIMARY KEY REFERENCES team_trips(trip_id),
    protected bytea NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

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

CREATE TABLE IF NOT EXISTS iphone_login_requests (
    request_id text PRIMARY KEY,
    callback_state text NOT NULL,
    code_challenge text NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'DENIED', 'USED', 'CANCELLED')),
    account_id text REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    code_hash text,
    expires_at bigint NOT NULL CHECK (expires_at > 0)
);
CREATE INDEX IF NOT EXISTS iphone_login_requests_account ON iphone_login_requests (account_id);
CREATE INDEX IF NOT EXISTS iphone_login_requests_expiry ON iphone_login_requests (expires_at);

CREATE TABLE IF NOT EXISTS iphone_sessions (
    token_hash text PRIMARY KEY,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    scopes text[] NOT NULL,
    expires_at bigint NOT NULL CHECK (expires_at > 0),
    revoked_at bigint
);
CREATE INDEX IF NOT EXISTS iphone_sessions_account ON iphone_sessions (account_id);
CREATE INDEX IF NOT EXISTS iphone_sessions_expiry ON iphone_sessions (expires_at);
REVOKE ALL ON iphone_login_requests, iphone_sessions FROM PUBLIC;
ALTER TABLE pack_versions ADD COLUMN IF NOT EXISTS tags text[] NOT NULL DEFAULT '{}'::text[];

ALTER TABLE team_trip_courses
    ADD COLUMN IF NOT EXISTS priority smallint CHECK (priority BETWEEN 1 AND 10);
CREATE TABLE IF NOT EXISTS pack_course_covers (
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL,
    image bytea NOT NULL CHECK (octet_length(image) BETWEEN 1 AND 524288),
    PRIMARY KEY (pack_id, version),
    FOREIGN KEY (pack_id, version) REFERENCES pack_versions(pack_id, version) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS team_trip_messages (
    trip_id char(32) NOT NULL REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    sender_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    message_id text NOT NULL CHECK (message_id ~ '^[0-9a-f]{32}$'),
    protected bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (trip_id, sender_id, message_id)
);
CREATE INDEX IF NOT EXISTS team_trip_messages_timeline
    ON team_trip_messages (trip_id, created_at DESC, sender_id, message_id);
CREATE INDEX IF NOT EXISTS team_trip_messages_sender
    ON team_trip_messages (sender_id);
REVOKE ALL ON team_trip_messages FROM PUBLIC;
ALTER TABLE team_trip_courses ADD COLUMN IF NOT EXISTS waypoints bytea;

CREATE TABLE IF NOT EXISTS team_trip_route_plans (
    trip_id char(32) PRIMARY KEY REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    protected bytea NOT NULL
);

CREATE TABLE IF NOT EXISTS team_trip_driving_versus (
    trip_id char(32) PRIMARY KEY REFERENCES team_trips(trip_id) ON DELETE CASCADE,
    protected bytea NOT NULL
);

CREATE TABLE IF NOT EXISTS team_course_tag_follows (
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    tag_key varchar(96) NOT NULL,
    tag varchar(24) NOT NULL,
    followed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(account_id,tag_key)
);
CREATE TABLE IF NOT EXISTS team_course_discovery_reads (
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    event_id bigint NOT NULL REFERENCES pack_review_events(event_id) ON DELETE CASCADE,
    PRIMARY KEY(account_id,event_id)
);
CREATE TABLE IF NOT EXISTS team_course_hidden (
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL,
    PRIMARY KEY(account_id,pack_id,version),
    FOREIGN KEY(pack_id,version) REFERENCES pack_versions(pack_id,version) ON DELETE CASCADE
);
ALTER TABLE team_remix_drafts ALTER COLUMN history_id DROP NOT NULL;

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

CREATE TABLE IF NOT EXISTS iphone_push_installations (
    installation_id uuid PRIMARY KEY,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    session_hash text NOT NULL REFERENCES iphone_sessions(token_hash) ON DELETE CASCADE,
    environment text NOT NULL CHECK (environment IN ('sandbox', 'production')),
    token_digest text NOT NULL,
    protected bytea NOT NULL,
    registered_ms bigint NOT NULL,
    binding uuid NOT NULL,
    UNIQUE (environment,token_digest)
);
CREATE INDEX IF NOT EXISTS iphone_push_installations_session ON iphone_push_installations(session_hash);
CREATE INDEX IF NOT EXISTS iphone_push_installations_account ON iphone_push_installations(account_id);

CREATE TABLE IF NOT EXISTS iphone_push_outbox (
    event_id uuid NOT NULL,
    installation_id uuid NOT NULL REFERENCES iphone_push_installations(installation_id) ON DELETE CASCADE,
    binding uuid NOT NULL,
    recipient_id text NOT NULL,
    protected bytea NOT NULL,
    created_at bigint NOT NULL,
    expires_at bigint NOT NULL,
    next_attempt bigint NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    PRIMARY KEY(event_id,installation_id)
);
CREATE INDEX IF NOT EXISTS iphone_push_outbox_due ON iphone_push_outbox(next_attempt,expires_at);
REVOKE ALL ON iphone_push_installations,iphone_push_outbox FROM PUBLIC;
-- Existing saves receive the migration time; new saves record their own time.
ALTER TABLE team_course_stars ADD COLUMN IF NOT EXISTS starred_at timestamptz NOT NULL DEFAULT now();
