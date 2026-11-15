
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
