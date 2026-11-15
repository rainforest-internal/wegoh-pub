
CREATE TABLE IF NOT EXISTS team_course_stars (
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL,
    account_id text NOT NULL REFERENCES team_accounts(account_id) ON DELETE CASCADE,
    PRIMARY KEY(pack_id,version,account_id),
    FOREIGN KEY(pack_id,version) REFERENCES pack_versions(pack_id,version) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS team_course_stars_account ON team_course_stars(account_id);
