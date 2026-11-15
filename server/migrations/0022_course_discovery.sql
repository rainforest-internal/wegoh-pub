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
