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
