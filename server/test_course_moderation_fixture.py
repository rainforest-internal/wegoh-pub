import secrets


def restrict_course(conn, checksum, *, state='rejected'):
    if state not in ('quarantined', 'rejected'):
        raise ValueError('A post-publication restriction is required')
    if state == 'quarantined':
        pack, version, creator = conn.execute(
            'SELECT pack_id,version,creator_id FROM pack_versions WHERE checksum=%s LIMIT 1',
            (checksum,)).fetchone()
        conn.execute('INSERT INTO content_reports(report_id,pack_id,version,checksum,creator_id,reason) '
            "VALUES(%s,%s,%s,%s,%s,'other') ON CONFLICT(checksum,creator_id,reason) DO NOTHING",
            (secrets.token_hex(16), pack, version, checksum, creator))
    conn.execute('INSERT INTO pack_reviews(checksum,state,reviewer,review_note) VALUES(%s,%s,%s,%s) '
        'ON CONFLICT(checksum) DO UPDATE SET state=excluded.state,reviewer=excluded.reviewer,review_note=excluded.review_note',
        (checksum, state, 'synthetic-operator', 'Explicit post-publication restriction in an isolated fixture'))
    conn.execute('INSERT INTO pack_review_events(checksum,state,reviewer,review_note) VALUES(%s,%s,%s,%s)',
        (checksum, state, 'synthetic-operator', 'Explicit post-publication restriction in an isolated fixture'))
