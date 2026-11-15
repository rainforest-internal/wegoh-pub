"""Participant-only text history. The voice relay never writes to this table."""
from fastapi import HTTPException

from private_records import PrivateRecordError, VisitCipher
from team_event_versions import trip_changed
from team_friends import blocked
from team_trip_context import trip_state

HISTORY_LIMIT = 50


def visible_people(trips, conn, trip, actor):
    _, _, members = trips.access(conn, trip, actor)
    people = {}
    for peer, member in members.items():
        if member['state'] != 'accepted' or (peer != actor and blocked(conn, actor, peer)):
            continue
        person = trips.person(peer, connection=conn)
        if person:
            people[peer] = person['name']
    return people


def record(cipher, trip, message, sender, protected):
    value = cipher.restore(f'team-trip-message:{trip}:{sender}', message, protected)
    if not isinstance(value, dict) or set(value) != {'text'} or not isinstance(value['text'], str):
        raise PrivateRecordError('Trip message integrity failed')
    return value['text']


def history(trips, conn, trip, actor):
    people = visible_people(trips, conn, trip, actor)
    if trip_state(conn, trip)['deletedAt'] is not None:
        raise HTTPException(404, 'Trip unavailable')
    rows = conn.execute(
        'SELECT message_id,sender_id,created_at,protected FROM team_trip_messages '
        'WHERE trip_id=%s AND sender_id=ANY(%s) ORDER BY created_at DESC,sender_id,message_id LIMIT %s',
        (trip, list(people), HISTORY_LIMIT)).fetchall()
    cipher = VisitCipher() if rows else None
    return dict(messages=[dict(id=message, senderId=sender, senderName=people[sender],
        createdAt=created.isoformat(), text=record(cipher, trip, message, sender, protected))
        for message, sender, created, protected in reversed(rows)])


def send(trips, conn, trip, actor, message, text):
    trips.access(conn, trip, actor, mutable=True)
    cipher = VisitCipher()
    protected = cipher.protect(f'team-trip-message:{trip}:{actor}', message, dict(text=text))
    row = conn.execute('INSERT INTO team_trip_messages(trip_id,sender_id,message_id,protected) '
        'VALUES(%s,%s,%s,%s) ON CONFLICT(trip_id,sender_id,message_id) DO NOTHING RETURNING created_at',
        (trip, actor, message, protected)).fetchone()
    if row:
        conn.execute('DELETE FROM team_trip_messages WHERE trip_id=%s AND (sender_id,message_id) IN '
            '(SELECT sender_id,message_id FROM team_trip_messages WHERE trip_id=%s '
            'ORDER BY created_at DESC,sender_id,message_id OFFSET %s)', (trip, trip, HISTORY_LIMIT))
        trip_changed(conn, trip, ('chat',))
    else:
        existing, created = conn.execute('SELECT protected,created_at FROM team_trip_messages '
            'WHERE trip_id=%s AND sender_id=%s AND message_id=%s', (trip, actor, message)).fetchone()
        if record(cipher, trip, message, actor, existing) != text:
            raise HTTPException(409, 'Trip message ID already in use')
        row = (created,)
    return dict(id=message, createdAt=row[0].isoformat())
