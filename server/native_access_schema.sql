-- Native authorization v2. Additive and inert until exact v2 handlers are enabled.
-- Run as the existing application schema owner inside the startup transaction.
-- No existing table, key, account, token or travel record is rewritten/deleted.
-- No public/issuer GRANT is implied by these owner-only tables and views.

CREATE TABLE IF NOT EXISTS native_v2_installations (
    installation_key_id text PRIMARY KEY CHECK (installation_key_id ~ '^[a-f0-9]{64}$'),
    revision bigint NOT NULL DEFAULT 1 CHECK (revision BETWEEN 1 AND 9007199254740991),
    current_generation integer NOT NULL DEFAULT 0 CHECK (current_generation >= 0),
    slot_revision bigint NOT NULL DEFAULT 1 CHECK (slot_revision BETWEEN 1 AND 9007199254740991),
    active_grant_id text CHECK (active_grant_id ~ '^[a-f0-9]{32}$'),
    revoked_at bigint CHECK (revoked_at BETWEEN 0 AND 253402300799),
    created_at bigint NOT NULL CHECK (created_at BETWEEN 0 AND 253402300799)
);

-- Public bootstrap metadata contains no personal grant/token/capability.
-- protected_request is AES-GCM VisitCipher data: exact begin snapshot + CSR/name.
-- The issuer writes outcome only; approval remains a separate main-owned record.
CREATE TABLE IF NOT EXISTS native_v2_connections (
    connection_id text PRIMARY KEY CHECK (connection_id ~ '^[a-f0-9]{32}$'),
    operation_id text NOT NULL UNIQUE CHECK (operation_id ~ '^[a-f0-9]{32}$'),
    installation_key_id text NOT NULL CHECK (installation_key_id ~ '^[a-f0-9]{64}$'),
    kind text NOT NULL CHECK (kind IN ('INSTALL','ACCOUNT','RENEW')),
    user_code text NOT NULL UNIQUE CHECK (user_code ~ '^[A-HJ-NP-Z2-9]{8}$'),
    original_begin_hash text NOT NULL CHECK (original_begin_hash ~ '^[a-f0-9]{64}$'),
    code_challenge text NOT NULL CHECK (code_challenge ~ '^[A-Za-z0-9_-]{43}$'),
    proof_nonce text NOT NULL CHECK (proof_nonce ~ '^[A-Za-z0-9_-]{43}$'),
    state text NOT NULL CHECK (state IN ('PENDING','ISSUING','UNCERTAIN','ISSUED','EXPIRED_NOT_ISSUED')),
    expires_at bigint NOT NULL CHECK (expires_at BETWEEN 0 AND 253402300799),
    next_poll bigint NOT NULL DEFAULT 0 CHECK (next_poll BETWEEN 0 AND 253402300799),
    created_at bigint NOT NULL CHECK (created_at BETWEEN 0 AND 253402300799),
    protected_request bytea NOT NULL CHECK (octet_length(protected_request) >= 32),
    protected_certificate bytea CHECK (octet_length(protected_certificate) >= 32),
    restart_hash text CHECK (restart_hash ~ '^[a-f0-9]{64}$'),
    restart_expires_at bigint CHECK (restart_expires_at BETWEEN 0 AND 253402300799),
    restart_consumed_at bigint CHECK (restart_consumed_at BETWEEN 0 AND 253402300799),
    previous_connection_id text REFERENCES native_v2_connections(connection_id),
    CHECK (expires_at > created_at),
    CHECK ((restart_hash IS NULL) = (restart_expires_at IS NULL)),
    CHECK (state <> 'ISSUED' OR protected_certificate IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS native_v2_connections_key ON native_v2_connections(installation_key_id,state);

-- Only the main API owns explicit user approval. The issuer sees a narrow view
-- for membership revalidation and issuance eligibility, not grant scopes/tokens.
-- protected_owner contains the cert approver audit identity, not authority over
-- future account users. Its purpose withdrawal/deletion is an explicit mutation.
CREATE TABLE IF NOT EXISTS native_v2_approvals (
    connection_id text PRIMARY KEY REFERENCES native_v2_connections(connection_id),
    grant_id text UNIQUE CHECK (grant_id ~ '^[a-f0-9]{32}$'),
    state text NOT NULL CHECK (state IN ('APPROVED','DENIED','REVOKED')),
    protected_owner bytea CHECK (octet_length(protected_owner) >= 32),
    approved_at bigint NOT NULL CHECK (approved_at BETWEEN 0 AND 253402300799),
    exchange_expires_at bigint CHECK (exchange_expires_at BETWEEN 0 AND 253402300799),
    CHECK (state <> 'APPROVED' OR (grant_id IS NOT NULL AND protected_owner IS NOT NULL
        AND exchange_expires_at > approved_at))
);
CREATE OR REPLACE VIEW native_v2_issuer_approvals WITH (security_barrier=true) AS
    SELECT connection_id,grant_id,state,protected_owner,exchange_expires_at
    FROM native_v2_approvals;

-- Encrypted consent snapshot includes name, approved scopes, retention/purpose
-- registry version/hash, keepSignedIn, original request and immutable expiry.
-- device_id is assigned only in successful account exchange, once per grant.
CREATE TABLE IF NOT EXISTS native_v2_grants (
    grant_id text PRIMARY KEY CHECK (grant_id ~ '^[a-f0-9]{32}$'),
    connection_id text NOT NULL UNIQUE REFERENCES native_v2_connections(connection_id),
    installation_key_id text NOT NULL REFERENCES native_v2_installations(installation_key_id),
    account_id text CHECK (account_id ~ '^team-[a-f0-9]{40}$'),
    device_id text UNIQUE CHECK (device_id ~ '^[a-f0-9]{32}$'),
    state text NOT NULL CHECK (state IN ('APPROVED','TOKEN_ISSUED','REVOKED','EXPIRED')),
    credential_epoch bigint NOT NULL DEFAULT 1 CHECK (credential_epoch BETWEEN 1 AND 9007199254740991),
    consent_version integer NOT NULL CHECK (consent_version > 0),
    expires_at bigint NOT NULL CHECK (expires_at BETWEEN 0 AND 253402300799),
    revoked_at bigint CHECK (revoked_at BETWEEN 0 AND 253402300799),
    recovery_hash text CHECK (recovery_hash ~ '^[a-f0-9]{64}$'),
    revoke_hash text CHECK (revoke_hash ~ '^[a-f0-9]{64}$'),
    protected_consent bytea CHECK (octet_length(protected_consent) >= 32),
    device_revision bigint NOT NULL DEFAULT 1 CHECK (device_revision BETWEEN 1 AND 9007199254740991),
    CHECK (state NOT IN ('APPROVED','TOKEN_ISSUED') OR
        (account_id IS NOT NULL AND protected_consent IS NOT NULL)),
    CHECK (state <> 'TOKEN_ISSUED' OR
        (device_id IS NOT NULL AND recovery_hash IS NOT NULL AND revoke_hash IS NOT NULL)),
    CHECK (state <> 'REVOKED' OR revoked_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS native_v2_grants_account ON native_v2_grants(account_id,state);

CREATE TABLE IF NOT EXISTS native_v2_certificates (
    installation_key_id text NOT NULL REFERENCES native_v2_installations(installation_key_id),
    generation integer NOT NULL CHECK (generation > 0),
    generation_operation_id text NOT NULL UNIQUE CHECK (generation_operation_id ~ '^[a-f0-9]{32}$'),
    certificate_sha256 text NOT NULL UNIQUE CHECK (certificate_sha256 ~ '^[a-f0-9]{64}$'),
    code_challenge text NOT NULL CHECK (code_challenge ~ '^[A-Za-z0-9_-]{43}$'),
    proof_nonce text NOT NULL CHECK (proof_nonce ~ '^[A-Za-z0-9_-]{43}$'),
    expires_at bigint NOT NULL CHECK (expires_at BETWEEN 0 AND 253402300799),
    protected_receipt bytea NOT NULL CHECK (octet_length(protected_receipt) >= 32),
    PRIMARY KEY (installation_key_id,generation)
);
-- Public-receipt recovery deliberately has no account/scopes/personal tokens.
CREATE OR REPLACE VIEW native_v2_certificate_recovery WITH (security_barrier=true) AS
    SELECT c.installation_key_id,c.generation,c.generation_operation_id,
        c.certificate_sha256,c.code_challenge,c.proof_nonce,c.expires_at,
        c.protected_receipt,i.current_generation,i.revoked_at
    FROM native_v2_certificates c JOIN native_v2_installations i USING (installation_key_id);

CREATE TABLE IF NOT EXISTS native_v2_credentials (
    grant_id text PRIMARY KEY REFERENCES native_v2_grants(grant_id),
    device_id text NOT NULL UNIQUE CHECK (device_id ~ '^[a-f0-9]{32}$'),
    access_hash text NOT NULL UNIQUE CHECK (access_hash ~ '^[a-f0-9]{64}$'),
    refresh_hash text NOT NULL UNIQUE CHECK (refresh_hash ~ '^[a-f0-9]{64}$'),
    certificate_sha256 text NOT NULL CHECK (certificate_sha256 ~ '^[a-f0-9]{64}$'),
    generation integer NOT NULL CHECK (generation > 0),
    slot_revision bigint NOT NULL CHECK (slot_revision BETWEEN 1 AND 9007199254740991),
    credential_epoch bigint NOT NULL CHECK (credential_epoch BETWEEN 1 AND 9007199254740991),
    access_expires_at bigint NOT NULL CHECK (access_expires_at BETWEEN 0 AND 253402300799)
);

-- Exact request hashes and encrypted responses permit same-operation retry;
-- no plaintext token, verifier or purpose capability is kept in indexed columns.
CREATE TABLE IF NOT EXISTS native_v2_operations (
    operation_id text PRIMARY KEY CHECK (operation_id ~ '^[a-f0-9]{32}$'),
    action text NOT NULL CHECK (action IN ('SESSION_EXCHANGE','SESSION_RECOVER','SESSION_REFRESH',
        'SESSION_REVOKE','CREDENTIAL_REBIND','SCOPE_REDUCTION','INSTALLATION_REVOKE')),
    request_hash text NOT NULL CHECK (request_hash ~ '^[a-f0-9]{64}$'),
    grant_id text NOT NULL REFERENCES native_v2_grants(grant_id),
    installation_key_id text NOT NULL REFERENCES native_v2_installations(installation_key_id),
    credential_epoch bigint NOT NULL CHECK (credential_epoch BETWEEN 1 AND 9007199254740991),
    slot_revision bigint NOT NULL CHECK (slot_revision BETWEEN 1 AND 9007199254740991),
    expires_at bigint NOT NULL CHECK (expires_at BETWEEN 0 AND 253402300799),
    protected_receipt bytea NOT NULL CHECK (octet_length(protected_receipt) >= 32)
);
CREATE INDEX IF NOT EXISTS native_v2_operations_grant ON native_v2_operations(grant_id);

-- Authenticated certificate/SPKI mapping for explicit v1 cohort migration.
-- An absent mapping never grants permission or proves a sibling key is absent.
CREATE TABLE IF NOT EXISTS native_v2_legacy_certificates (
    certificate_sha256 text PRIMARY KEY CHECK (certificate_sha256 ~ '^[a-f0-9]{64}$'),
    installation_key_id text NOT NULL CHECK (installation_key_id ~ '^[a-f0-9]{64}$'),
    expires_at bigint NOT NULL CHECK (expires_at BETWEEN 0 AND 253402300799),
    protected_provenance bytea NOT NULL CHECK (octet_length(protected_provenance) >= 32)
);


-- Main-only authority snapshot; issuer gets only the eligibility projection.
CREATE TABLE IF NOT EXISTS native_v2_renewals (
    connection_id text PRIMARY KEY REFERENCES native_v2_connections(connection_id),
    installation_key_id text NOT NULL REFERENCES native_v2_installations(installation_key_id),
    grant_id text NOT NULL REFERENCES native_v2_grants(grant_id),
    device_id text NOT NULL CHECK (device_id ~ '^[a-f0-9]{32}$'),
    installation_revision bigint NOT NULL CHECK (installation_revision BETWEEN 1 AND 9007199254740991),
    expected_generation integer NOT NULL CHECK (expected_generation > 0),
    slot_revision bigint NOT NULL CHECK (slot_revision BETWEEN 1 AND 9007199254740991),
    credential_epoch bigint NOT NULL CHECK (credential_epoch BETWEEN 1 AND 9007199254740991),
    consent_version integer NOT NULL CHECK (consent_version > 0),
    consent_hash text NOT NULL CHECK (consent_hash ~ '^[a-f0-9]{64}$'),
    protected_owner bytea NOT NULL CHECK (octet_length(protected_owner) >= 32),
    grant_expires_at bigint NOT NULL,
    expires_at bigint NOT NULL,
    CHECK (expires_at <= grant_expires_at)
);
CREATE OR REPLACE VIEW native_v2_issuer_approvals WITH (security_barrier=true) AS
    SELECT connection_id,grant_id,state,protected_owner,exchange_expires_at FROM native_v2_approvals
    UNION ALL
    SELECT r.connection_id,r.grant_id,'APPROVED'::text,r.protected_owner,r.expires_at
    FROM native_v2_renewals r
    JOIN native_v2_grants g ON g.grant_id=r.grant_id
    JOIN native_v2_installations i ON i.installation_key_id=r.installation_key_id
    JOIN native_v2_approvals a ON a.connection_id=g.connection_id
    WHERE g.state='TOKEN_ISSUED' AND a.state='APPROVED'
      AND i.revoked_at IS NULL AND i.active_grant_id=g.grant_id
      AND i.revision=r.installation_revision AND i.current_generation=r.expected_generation
      AND i.slot_revision=r.slot_revision AND g.credential_epoch=r.credential_epoch
      AND g.consent_version=r.consent_version AND g.device_id=r.device_id
      AND g.expires_at=r.grant_expires_at;
