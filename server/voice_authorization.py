"""Current Voice authorization without constructing a room display projection.

Every call owns one synchronous transaction. Each socket reuses its dedicated
connection, with no transaction or authorization snapshot across a network await.
"""
import re
import hashlib
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

import psycopg
from fastapi import HTTPException
from private_records import PrivateRecordError, VisitCipher
from team_friends import blocked
from team_trip_context import resolve_trip_context


class VoiceDatabase:
    def __init__(self, dsn):
        self.dsn = dsn
        self.connection = None
        self.lock = threading.Lock()
        self.closed = False

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.closed:
                raise HTTPException(403, 'Voice connection closed')
            if self.connection is None:
                self.connection = psycopg.connect(self.dsn)
            with self.connection.transaction():
                yield self.connection

    def close(self):
        with self.lock:
            self.closed = True
            if self.connection is not None:
                self.connection.close()
                self.connection = None


def voice_database(service, socket):
    database = getattr(socket.state, 'voice_database', None)
    if database is None:
        database = VoiceDatabase(service.dsn)
        socket.state.voice_database = database
    return database


def close_voice_database(socket):
    for name in ('voice_database', 'voice_delivery_database'):
        database = getattr(socket.state, name, None)
        if database is not None:
            database.close()


def _precondition(socket,name,*,zero=False):
    from native_functional_policy import MAX_REVISION
    values=socket.headers.getlist(name)
    if len(values)!=1 or not re.fullmatch(r'0|[1-9][0-9]{0,9}' if zero else r'[1-9][0-9]{0,9}',values[0]):
        raise HTTPException(403,'Invalid voice precondition')
    value=int(values[0])
    if value>MAX_REVISION:raise HTTPException(403,'Invalid voice precondition')
    return value


def voice_context(service, conn, socket, room, account):
    trip = getattr(socket.state, 'voice_trip', None)
    if trip is not None:
        context = resolve_trip_context(service.auth, conn, trip, account, states=('active',))
        return context['roomId'], trip
    if conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL', (room,)).fetchone():
        service.rooms.access(conn, room, account)
    return room, None


@dataclass
class _DeliveryContext:
    trip: dict | None = None
    checked_room: str | None = None


def _authorize_native_voice(service, socket, room, conn, *, delivery=None, read_only=False):
    from native_functional_identity import revalidate_socket
    from native_functional_policy import FunctionalError
    if not service.enabled:raise HTTPException(403)
    if not isinstance(room,str)or not re.fullmatch(r'[a-f0-9]{32}',room):raise HTTPException(404,'Room unavailable')
    functional_revision=_precondition(socket,'x-wegoh-functional-revision')
    room_revision=_precondition(socket,'x-wegoh-room-voice-revision',zero=True)
    access=getattr(service.auth,'room_voice_access',None)
    if access is None:raise HTTPException(403)
    try:
        graph_locked = read_only or (delivery is not None and delivery.trip is not None)
        if not graph_locked and getattr(service.auth,'room_service',None) is not service.rooms:
            service.rooms.graph_lock(conn)
        principal,functional=revalidate_socket(service.auth,socket,conn,functional_revision=functional_revision,
                                                graph_locked=graph_locked,read_only=read_only)
        trip=getattr(socket.state,'voice_trip',None)
        if trip is not None:
            resolved_trip = delivery.trip if delivery is not None else None
            if resolved_trip is not None and resolved_trip['tripId'] == trip:
                service.auth.trip_service.require_member(
                    conn, principal['id'], resolved_trip['ownerId'], resolved_trip['members'])
            else:
                resolved_trip = resolve_trip_context(service.auth, conn, trip, principal['id'],
                                                     states=('active',), locked_for_read=read_only)
                if delivery is not None:
                    delivery.trip = resolved_trip
            room=resolved_trip['roomId']
            value=access.resolved_trip_snapshot(conn,principal,functional,resolved_trip)
        else:
            room,trip=voice_context(service,conn,socket,room,principal['id'])
            grant,current,joined,expiry=access.context(conn,principal['id'],principal['deviceId'],room,principal['grantId'])
            value=access.snapshot(conn,grant,current,room,joined,expiry)
        if value['revision']!=room_revision:raise HTTPException(403,'Voice permission changed')
        flags=value['permissions']
        if trip is not None:
            flags=dict(receiveVoice=flags['receiveVoice'] and 'rooms:read' in functional['approvedPurposes'],
                       transmitVoice=flags['transmitVoice'] and 'rooms:interact' in functional['approvedPurposes'])
        if not any(flags.values()):raise HTTPException(403,'Voice permission required')
        check_room_members = trip is None or delivery is None or delivery.checked_room != room
        with conn.pipeline():
            if check_room_members:
                member_rows=conn.execute('SELECT account_id,protected FROM team_room_members WHERE room_id=%s AND left_at IS NULL',(room,))
            filter_rows=conn.execute('SELECT speaker_id,protected FROM team_voice_filters WHERE room_id=%s AND account_id=%s',(room,principal['id']))
        if check_room_members:
            peers=[]
            for account,raw in member_rows.fetchall():
                service.rooms.member_payload(account,room,raw)
                peers.append(account)
            if trip is None and any(blocked(conn,principal['id'],peer)for peer in peers if peer!=principal['id']):raise HTTPException(404,'Room unavailable')
            if trip is not None and delivery is not None:
                delivery.checked_room = room
        muted=set()
        for speaker,raw in filter_rows.fetchall():
            if service.rooms.restore('voice-filter:'+principal['id'],room+':'+speaker,raw)['muted']:muted.add(speaker)
        suspended=bool(conn.execute(
            'SELECT 1 FROM team_voice_reports WHERE room_id=%s AND speaker_id=%s '
            'AND resolved_at IS NULL LIMIT 1', (room, principal['id'])).fetchone())
        stamp=(principal['deviceId'],principal['grantId'],principal['credentialEpoch'],principal['slotRevision'],functional_revision,room_revision,value['memberJoinedAt'],value['expiresAt'])
        return dict(principal,voiceRoomId=room,voiceTripId=trip,voiceTransport='native',voiceStamp=stamp,voiceCanReceive=flags['receiveVoice'],voiceCanTransmit=flags['transmitVoice'],voiceMuted=muted,voiceSuspended=suspended)
    except FunctionalError as error:raise HTTPException(error.status,error.code)from None


class VoiceDeliverySourceDenied(Exception):
    """The receiver is eligible but the sender lost current authority."""


def _native_transaction(service, socket, check, *, trip_read, database=None):
    from native_functional_identity import VoiceDefaultRequired

    database = database or voice_database(service, socket)
    if trip_read:
        try:
            with database.transaction() as conn:
                # Parallel readers still exclude existing graph writers.
                conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('social-membership',0))")
                return check(conn, read_only=True)
        except VoiceDefaultRequired:
            # Leave the read transaction before taking the exclusive graph lock.
            pass
    with database.transaction() as conn:
        return check(conn, read_only=False)


def authorize_native_delivery(service, target, source):
    def check(conn, *, read_only):
        # Trip, linked room and membership graph stay locked for this frame.
        # The second actor still checks their own membership and live authority.
        delivery = _DeliveryContext()
        fresh=_authorize_native_voice(service,target.socket,target.room,conn,delivery=delivery,read_only=read_only)
        if not service.current_peer(target,fresh) or not fresh['voiceCanReceive'] or source.actor in fresh['voiceMuted']:
            return fresh,None
        try:
            sender=_authorize_native_voice(service,source.socket,source.room,conn,delivery=delivery,read_only=read_only)
        except(HTTPException,PrivateRecordError) as error:
            raise VoiceDeliverySourceDenied from error
        return fresh,sender

    trip = getattr(target.socket.state, 'voice_trip', None)
    return _native_transaction(service, target.socket, check,
                               trip_read=trip is not None and trip == getattr(source.socket.state, 'voice_trip', None))


def _authorize_iphone_trip(service, socket, database):
    from team_trips import MAX_VOICE_REVISION, trip_fields, voice_counter_key
    from team_friends import restore_pair

    auth, rooms = service.auth, service.rooms
    trip = socket.state.voice_trip
    if not isinstance(trip, str) or not re.fullmatch(r'[a-f0-9]{32}', trip):
        raise HTTPException(404, 'Trip unavailable')
    with database.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('social-membership',0))")
        actor = auth.iphone_sessions.authenticate(socket, 'trips:read', connection=conn)
        row = conn.execute(
            'SELECT t.owner_id,t.protected,t.state,r.room_id,r.owner_id,r.protected,r.closed_at '
            'FROM team_trips t JOIN team_rooms r USING(trip_id) WHERE t.trip_id=%s FOR SHARE OF t,r',
            (trip,)).fetchone()
        if not row:
            raise HTTPException(404, 'Trip unavailable')
        owner, trip_raw, state, room, room_owner, room_raw, closed = row
        if owner != room_owner:
            raise PrivateRecordError('Trip owner integrity failed')
        value = auth.trip_service.restore('owner:' + owner, trip, trip_raw)
        try:
            if not isinstance(value, dict) or set(value) != {'title', 'description'} or trip_fields(value) != value:
                raise PrivateRecordError('Trip integrity failed')
        except HTTPException:
            raise PrivateRecordError('Trip integrity failed') from None
        rooms.restore('owner:' + owner, room, room_raw)
        if state != 'active':
            raise HTTPException(409, 'TRIP_STATE_CONFLICT')
        if closed is not None:
            raise HTTPException(404, 'Room unavailable')
        rows = conn.execute(
            'WITH t AS (SELECT account_id,protected FROM team_trip_members WHERE trip_id=%s), '
            'm AS (SELECT account_id,protected,joined_at FROM team_room_members WHERE room_id=%s AND left_at IS NULL) '
            'SELECT COALESCE(t.account_id,m.account_id),t.protected,m.protected,m.joined_at,a.protected,a.account_status,'
            '(SELECT 1+LEAST(%s,COALESCE((SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource=\'rooms\'),0))),'
            'EXISTS(SELECT 1 FROM team_voice_reports WHERE room_id=%s AND speaker_id=%s AND resolved_at IS NULL) '
            'FROM t FULL JOIN m USING(account_id) LEFT JOIN team_accounts a ON a.account_id=COALESCE(t.account_id,m.account_id)',
            (trip, room, MAX_VOICE_REVISION-1, voice_counter_key(trip, actor['id']), room, actor['id'])).fetchall()
        memberships, active, peers = {}, set(), []
        roster = auth.members()
        own = None
        for account, trip_member, room_member, joined, identity, status, revision, suspended in rows:
            if trip_member is not None:
                memberships[account] = auth.trip_service.member_payload(trip, account, trip_member)
            if room_member is None:
                continue
            active.add(account)
            member = rooms.member_payload(account, room, room_member)
            if status != 'active' or identity is None:
                continue
            saved = VisitCipher().restore('team-account:' + account, 'identity', identity)
            if not isinstance(saved, dict) or not isinstance(saved.get('email'), str):
                raise PrivateRecordError('Account identity integrity failed')
            if auth.stored_member(saved, members=roster) is None:
                continue
            peers.append(account)
            if account == actor['id']:
                own = member, joined, revision, suspended
        if active != {account for account, member in memberships.items() if member['state'] == 'accepted'}:
            raise HTTPException(409, 'TRIP_MEMBERSHIP_INCONSISTENT')
        if (memberships.get(actor['id'], {}).get('state') != 'accepted'
                or owner not in peers or actor['id'] not in peers or own is None):
            raise HTTPException(404, 'Trip unavailable')
        for a, b, raw in conn.execute(
                'SELECT account_a,account_b,protected FROM team_friend_pairs '
                'WHERE (account_a=%s AND account_b=ANY(%s)) OR (account_b=%s AND account_a=ANY(%s))',
                (actor['id'], peers, actor['id'], peers)):
            if restore_pair(a, b, raw)['blockedBy']:
                raise HTTPException(404, 'Room unavailable')
        member, joined, revision, suspended = own
        if not member['consents']['voice']:
            raise HTTPException(403, 'Sharing permission required')
        muted = set()
        for speaker, raw in conn.execute('SELECT speaker_id,protected FROM team_voice_filters WHERE room_id=%s AND account_id=%s',
                                          (room, actor['id'])):
            if rooms.restore('voice-filter:' + actor['id'], room + ':' + speaker, raw)['muted']:
                muted.add(speaker)
        return dict(actor, voiceRoomId=room, voiceTripId=trip, voiceTransport='iphone',
                    voiceStamp=(joined.isoformat(), revision, auth.iphone_sessions.token_hash(socket)),
                    voiceCanReceive=True, voiceCanTransmit='trips:manage' in actor['scopes'],
                    voiceMuted=muted, voiceSuspended=suspended)


def authorize_delivery_source(service, target, source):
    database = getattr(target.socket.state, 'voice_delivery_database', None)
    if database is None:
        database = VoiceDatabase(service.dsn)
        target.socket.state.voice_delivery_database = database
    return authorize_voice(service, source.socket, source.room, database=database)


def authorize_voice(service, socket, room, *, database=None):
    auth, rooms = service.auth, service.rooms
    if not service.enabled:
        raise HTTPException(403)
    if socket.url.path.startswith('/v1/iphone/'):
        auth.iphone_sessions.api_boundary(socket)
    if socket.url.hostname == urlsplit(auth.native_origin).hostname:
        if socket.url.query or socket.headers.get('sec-websocket-protocol'):
            raise HTTPException(403)
        def check(conn, *, read_only):
            return _authorize_native_voice(service, socket, room, conn, read_only=read_only)
        return _native_transaction(service, socket, check, trip_read=getattr(socket.state, 'voice_trip', None) is not None, database=database)
    iphone = socket.url.path.startswith('/v1/iphone/')
    if (socket.url.query or socket.headers.get('sec-websocket-protocol')
            or (not iphone and socket.url.hostname != urlsplit(auth.public_origin).hostname)):
        raise HTTPException(403)
    if not iphone:
        auth.check_origin(socket)
        socket.state.team_identity = auth.edge_identity(socket)
    if not isinstance(room, str) or not re.fullmatch(r'[a-f0-9]{32}', room):
        raise HTTPException(404, 'Room unavailable')

    if iphone and getattr(socket.state, 'voice_trip', None) is not None:
        return _authorize_iphone_trip(service, socket, database or voice_database(service, socket))

    with (database or voice_database(service, socket)).transaction() as conn:
        actor = (auth.iphone_sessions.authenticate(socket, 'trips:read', connection=conn)
                 if iphone else auth.browser(socket, connection=conn))
        room, trip = voice_context(service, conn, socket, room, actor['id'])
        row = conn.execute(
            'SELECT r.owner_id,m.protected,r.protected,m.joined_at FROM team_rooms r '
            'JOIN team_room_members m USING(room_id) WHERE r.room_id=%s '
            'AND m.account_id=%s AND m.left_at IS NULL AND r.closed_at IS NULL '
            'AND (r.expires_at>now() OR r.trip_id IS NOT NULL)', (room, actor['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Room unavailable')
        # Preserve authenticated room-record integrity without building its UI DTO.
        rooms.restore('owner:' + row[0], room, row[2])
        if trip is not None:
            _, member = auth.trip_service.voice_membership(conn, trip, room, actor['id'])
            enabled = member['participating']
            stamp = (member['memberJoinedAt'], member['revision'])
            if iphone:
                stamp += (auth.iphone_sessions.token_hash(socket),)
        else:
            enabled = rooms.member_payload(actor['id'], room, row[1])['consents']['voice']
            stamp = (row[3].isoformat(), hashlib.sha256(bytes(row[1])).hexdigest())
        if not enabled:
            raise HTTPException(403, 'Sharing permission required')

        # Same current-account/allowlist and membership-integrity semantics as
        # rooms.active_members, read on this connection instead of one per peer.
        members = auth.members()
        peers = []
        for account, member_raw, account_raw in conn.execute(
                'SELECT m.account_id,m.protected,a.protected FROM team_room_members m '
                'JOIN team_accounts a ON a.account_id=m.account_id '
                "WHERE m.room_id=%s AND m.left_at IS NULL AND a.account_status='active' "
                'ORDER BY m.joined_at,m.account_id', (room,)):
            saved = VisitCipher().restore('team-account:' + account, 'identity', account_raw)
            if not isinstance(saved, dict) or not isinstance(saved.get('email'), str):
                raise PrivateRecordError('Account identity integrity failed')
            if auth.stored_member(saved, members=members) is None:
                continue
            rooms.member_payload(account, room, member_raw)
            peers.append(account)
        if actor['id'] not in peers:
            raise HTTPException(403, 'Team access denied')
        # The owner case matches rooms.access: graph mutations remove a blocked
        # peer from an owner's room; other members also check all active pairs.
        if (trip is not None or actor['id'] != row[0]) and any(blocked(conn, actor['id'], peer)
                for peer in peers if peer != actor['id']):
            raise HTTPException(404, 'Room unavailable')

        muted = set()
        for speaker, raw in conn.execute(
                'SELECT speaker_id,protected FROM team_voice_filters '
                'WHERE room_id=%s AND account_id=%s', (room, actor['id'])):
            if rooms.restore('voice-filter:' + actor['id'], room + ':' + speaker, raw)['muted']:
                muted.add(speaker)
        suspended = bool(conn.execute(
            'SELECT 1 FROM team_voice_reports WHERE room_id=%s AND speaker_id=%s '
            'AND resolved_at IS NULL LIMIT 1', (room, actor['id'])).fetchone())
    return dict(actor, voiceRoomId=room,voiceTripId=trip,voiceStamp=stamp,voiceTransport='iphone' if iphone else 'browser',voiceCanReceive=True,voiceCanTransmit=not iphone or 'trips:manage' in actor['scopes'],voiceMuted=muted,voiceSuspended=suspended)
