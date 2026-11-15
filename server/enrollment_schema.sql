-- Additive, dedicated bootstrap state; existing user data is never changed.
CREATE TABLE IF NOT EXISTS vehicle_enrollments (
    enrollment_id char(32) PRIMARY KEY CHECK (enrollment_id ~ '^[a-f0-9]{32}$'),
    user_code char(8) NOT NULL UNIQUE CHECK (user_code ~ '^[A-HJ-NP-Z2-9]{8}$'),
    public_key_hash char(64) NOT NULL CHECK (public_key_hash ~ '^[a-f0-9]{64}$'),
    owner_hash char(64),
    state text NOT NULL CHECK (state IN ('pending','approved','issuing','issued','uncertain','denied')),
    expires_at bigint NOT NULL,
    protected bytea NOT NULL,
    next_poll bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS vehicle_enrollments_spki ON vehicle_enrollments(public_key_hash,expires_at);
CREATE INDEX IF NOT EXISTS vehicle_enrollments_owner ON vehicle_enrollments(owner_hash,created_at);

-- Isolated public-bootstrap throttling; no access to main API rate metadata.
CREATE TABLE IF NOT EXISTS vehicle_enrollment_rate_limits (
    scope_hash char(64) PRIMARY KEY CHECK (scope_hash ~ '^[a-f0-9]{64}$'),
    bucket bigint NOT NULL,
    hits integer NOT NULL CHECK (hits > 0)
);
