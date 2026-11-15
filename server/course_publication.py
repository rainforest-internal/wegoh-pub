COURSE_AVAILABLE = """NOT EXISTS (
    SELECT 1 FROM pack_reviews course_moderation
    WHERE course_moderation.checksum=p.checksum AND (
        course_moderation.state='quarantined' AND EXISTS (
            SELECT 1 FROM content_reports course_report WHERE course_report.checksum=p.checksum
        ) OR course_moderation.state='rejected' AND (
            EXISTS (SELECT 1 FROM content_reports course_report WHERE course_report.checksum=p.checksum)
            OR EXISTS (SELECT 1 FROM pack_review_events course_event
                WHERE course_event.checksum=p.checksum AND course_event.state='rejected')
        )
    )
)"""
COURSE_STATE = f"CASE WHEN {COURSE_AVAILABLE} THEN 'approved' ELSE r.state END"


def available(conn, checksum, *, lock=False):
    if lock:
        conn.execute('SELECT state FROM pack_reviews WHERE checksum=%s FOR SHARE', (checksum,)).fetchone()
    return bool(conn.execute(f'SELECT 1 FROM pack_versions p WHERE p.checksum=%s AND {COURSE_AVAILABLE} LIMIT 1',
                            (checksum,)).fetchone())


def presentation_state(conn, checksum):
    if available(conn, checksum):
        return 'approved'
    return conn.execute('SELECT state FROM pack_reviews WHERE checksum=%s', (checksum,)).fetchone()[0]
