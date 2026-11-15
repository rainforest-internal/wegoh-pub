
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
