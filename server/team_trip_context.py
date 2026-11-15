import re

from fastapi import HTTPException
from private_records import PrivateRecordError

LIVE_STATES = ('planned', 'active')
CLOSED_STATES = ('completed', 'cancelled')


def trip_state(conn, trip, *, locked_for_read=False):
    if not isinstance(trip, str) or not re.fullmatch(r'[a-f0-9]{32}', trip):
        raise HTTPException(404, 'Trip unavailable')
    if not locked_for_read:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('social-membership',0))")
    row_lock = 'FOR SHARE' if locked_for_read else 'FOR UPDATE'
    row = conn.execute('SELECT state,revision,started_at,ended_at,deleted_at,source_kind '
        'FROM team_trips WHERE trip_id=%s ' + row_lock, (trip,)).fetchone()
    if not row:
        raise HTTPException(404, 'Trip unavailable')
    return dict(zip(('state', 'revision', 'startedAt', 'endedAt', 'deletedAt', 'sourceKind'), row))


def linked_room(conn, trip, *, locked_for_read=False):
    row_lock = 'FOR SHARE' if locked_for_read else 'FOR UPDATE'
    row = conn.execute('SELECT room_id,owner_id FROM team_rooms WHERE trip_id=%s ' + row_lock, (trip,)).fetchone()
    if not row:
        raise HTTPException(409, 'TRIP_CONTEXT_NOT_READY')
    return row


def check_members(conn, trip, room, memberships):
    active = {row[0] for row in conn.execute('SELECT account_id FROM team_room_members '
        'WHERE room_id=%s AND left_at IS NULL', (room,))}
    accepted = {account for account, member in memberships.items() if member['state'] == 'accepted'}
    if active != accepted:
        raise HTTPException(409, 'TRIP_MEMBERSHIP_INCONSISTENT')


def resolve_trip_context(auth, conn, trip, account, *, states=LIVE_STATES, permission=None, locked_for_read=False):
    # Voice readers already hold the shared social-membership transaction lock.
    from team_trips import TeamTrips
    trips = getattr(auth, 'trip_service', None) or TeamTrips(auth)
    state = trip_state(conn, trip, locked_for_read=locked_for_read)
    owner, value, memberships = trips.access(conn, trip, account, permission=permission)
    if states is not None and state['state'] not in states:
        raise HTTPException(409, 'TRIP_STATE_CONFLICT')
    room, room_owner = linked_room(conn, trip, locked_for_read=locked_for_read)
    if owner != room_owner:
        raise PrivateRecordError('Trip owner integrity failed')
    check_members(conn, trip, room, memberships)
    return dict(tripId=trip, roomId=room, ownerId=owner, **state, **value, members=memberships)


def create_internal_room(conn, trip, owner, title):
    import secrets
    from team_rooms import TeamRooms
    room = secrets.token_hex(16)
    payload = dict(name=title, code=None, courseId=None, courseVersion=None, preference='balanced')
    conn.execute('INSERT INTO team_rooms(room_id,owner_id,trip_id,code_hash,protected,expires_at) '
        'VALUES(%s,%s,%s,NULL,%s,NULL)',
        (room, owner, trip, TeamRooms.protect('owner:' + owner, room, payload)))
    return room


def activate_member(conn, room, account, *, location_consent=False, voice_enabled=True):
    from team_rooms import TeamRooms, CONSENTS
    row = conn.execute('SELECT left_at FROM team_room_members WHERE room_id=%s AND account_id=%s FOR UPDATE',
        (room, account)).fetchone()
    if row and row[0] is None:
        return False
    choices = {key: key == 'voice' and voice_enabled for key in CONSENTS}
    choices['location'] = location_consent
    value = dict(role='member', consents=choices)
    conn.execute('INSERT INTO team_room_members(room_id,account_id,protected,joined_at) '
        'VALUES(%s,%s,%s,clock_timestamp()) ON CONFLICT(room_id,account_id) DO UPDATE '
        'SET protected=excluded.protected,left_at=NULL,joined_at=GREATEST(clock_timestamp(),team_room_members.joined_at+interval \'1 microsecond\')',
        (room, account, TeamRooms.protect('member:' + account, room, value)))
    return True


def bump_revision(conn, trip):
    return conn.execute('UPDATE team_trips SET revision=revision+1 WHERE trip_id=%s RETURNING revision', (trip,)).fetchone()[0]
