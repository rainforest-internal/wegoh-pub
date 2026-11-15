CREATE TABLE IF NOT EXISTS pack_course_covers (
    pack_id varchar(80) NOT NULL,
    version integer NOT NULL,
    image bytea NOT NULL CHECK (octet_length(image) BETWEEN 1 AND 524288),
    PRIMARY KEY (pack_id, version),
    FOREIGN KEY (pack_id, version) REFERENCES pack_versions(pack_id, version) ON DELETE CASCADE
);
