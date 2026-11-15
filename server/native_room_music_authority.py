"""Explicit Native grant/device/room music consent; Web account flags never grant it."""
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from psycopg.rows import dict_row, tuple_row
from private_records import VisitCipher
from native_access_codec import decode_json, CodecError
from native_functional_policy import WIRE, MAX_REVISION, FunctionalError, identifier, revision
from team_data import changed
from team_trip_context import resolve_trip_context

CONTRACT = WIRE['roomMusic']
PERMISSIONS = frozenset(CONTRACT['permissions'])
def fail(status, code):
    raise FunctionalError(status, code)
def connection(value):
    return getattr(value, 'connection', value)

class NativeRoomMusicAuthority:
    def __init__(self, functional, rooms):
        self.functional, self.rooms = functional, rooms
        self.base, self.auth = functional.base, functional.auth

    def context(self, conn, owner, device, room, grant_id=None, *, trip_context=False, withdrawal=False):
        self.functional.require_enabled()
        identifier(room)
        db = connection(conn)
        if db.autocommit: fail(503, "FUNCTIONAL_TRANSACTION_REQUIRED")
        self.rooms.graph_lock(db)
        grant, _ = self.functional.owner_grant(db, owner, device)
        if grant_id is not None and grant['grant_id'] != grant_id:
            fail(401, 'INVALID_CREDENTIAL')
        with db.cursor(row_factory=dict_row) as cursor:
            functional = self.functional.snapshot(cursor, grant)
        with db.cursor(row_factory=tuple_row) as cursor:
            if withdrawal:
                access = dict(expiresAt=None)
            else:
                access = self.rooms.access(cursor, room, owner, trip_context=trip_context)
            joined = cursor.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s ' + ('' if withdrawal else 'AND left_at IS NULL'), (room, owner)).fetchone()
        if not joined:
            fail(404, 'ROOM_UNAVAILABLE')
        expiry = min(grant['expires_at'], functional['expiresAt'])
        if access['expiresAt'] is not None:
            expiry = min(expiry, int(access['expiresAt'].timestamp()))
        return grant, functional, joined[0], expiry

    def row(self, conn, grant, room, lock=False):
        with connection(conn).cursor(row_factory=dict_row) as cursor:
            return cursor.execute('SELECT * FROM native_room_music_authorizations WHERE grant_id=%s AND room_id=%s' + (' FOR UPDATE' if lock else ' FOR SHARE'), (grant, room)).fetchone()

    @staticmethod
    def payload(row):
        value = VisitCipher().restore('native-room-music', row['grant_id'] + ':' + row['room_id'], row['protected'])
        if type(value) is not dict or set(value) != {'permissions', 'roomMusicDisclosureVersion', 'roomMusicDisclosureSha256', 'disclosureSnapshot'}:
            fail(503, 'ROOM_MUSIC_STATE_INVALID')
        flags = value['permissions']
        if type(flags) is not dict or set(flags) != PERMISSIONS or any(type(x) is not bool for x in flags.values()):
            fail(503, 'ROOM_MUSIC_STATE_INVALID')
        return value

    def snapshot(self, conn, grant, functional, room, joined, expiry):
        row = self.row(conn, grant['grant_id'], room)
        flags = dict(receiveMusic=False, shareMusic=False)
        if row and row['device_id'] != grant['device_id']:
            fail(503, 'ROOM_MUSIC_STATE_INVALID')
        if row and row['state'] == 'ACTIVE' and row['member_joined_at'] == joined and min(expiry, row['expires_at']) > self.base.now():
            flags = self.payload(row)['permissions'].copy()
            if 'rooms:read' not in functional['approvedPurposes']:
                flags = dict(receiveMusic=False, shareMusic=False)
            else:
                if 'room-music:read' not in functional['approvedPurposes']: flags['receiveMusic'] = False
                if 'room-music:control' not in functional['approvedPurposes']: flags['shareMusic'] = False
        return dict(authorizationVersion=1, deviceId=grant['device_id'], grantId=grant['grant_id'], roomId=room,
            revision=row['revision'] if row else 0, functionalRevision=functional['revision'],
            memberJoinedAt=joined.isoformat(), expiresAt=min(expiry, row['expires_at']) if row else expiry,
            permissions=flags, roomMusicDisclosureVersion=CONTRACT['disclosureVersion'], roomMusicDisclosureSha256=CONTRACT['disclosureSha256'])

    def require(self, conn, owner, device, grant_id, room, permission, expected=None, *, trip_context=False):
        grant, functional, joined, expiry = self.context(conn, owner, device, room, grant_id, trip_context=trip_context)
        value = self.snapshot(conn, grant, functional, room, joined, expiry)
        if permission not in PERMISSIONS or not value['permissions'][permission]:
            fail(403, 'ROOM_MUSIC_PERMISSION_REQUIRED')
        if expected is not None and (type(expected) is not int or expected != value['revision']):
            fail(409, 'ROOM_MUSIC_REVISION_CHANGED')
        return value

    def data_stamp(self, conn, principal):
        # Internal comparison only: room identifiers/revisions never enter the
        # public devices frame and other installations' rows are not queried.
        rows = conn.execute('SELECT a.room_id,a.revision,a.state,a.expires_at,a.member_joined_at,'
            'm.joined_at,m.left_at,COALESCE(s.revision,0) FROM native_room_music_authorizations a '
            'JOIN native_v2_grants g ON g.grant_id=a.grant_id '
            'LEFT JOIN team_room_members m ON m.room_id=a.room_id AND m.account_id=g.account_id '
            'LEFT JOIN team_room_music s ON s.room_id=a.room_id '
            'WHERE a.grant_id=%s AND a.device_id=%s AND g.account_id=%s ORDER BY a.room_id',
            (principal['grantId'],principal['deviceId'],principal['id'])).fetchall()
        stamp = []
        for room, revision_value, state, expiry, joined, current_joined, left, selection_revision in rows:
            accessible = False; role = None
            if left is None and joined == current_joined:
                try:
                    access = self.rooms.access(conn, room, principal['id'], trip_context=True)
                    accessible = True; role = access['role']
                except HTTPException as error:
                    if error.status_code not in (403,404,409): raise
            stamp.append((room,revision_value,state,expiry>self.base.now(),accessible,role,selection_revision))
        return tuple(stamp)

    def trip_room(self, conn, trip, owner, *, withdrawal=False):
        with connection(conn).cursor(row_factory=tuple_row) as cursor:
            if not withdrawal:
                return resolve_trip_context(self.auth, cursor, trip, owner)['roomId']
            identifier(trip)
            self.rooms.graph_lock(cursor)
            row = cursor.execute('SELECT r.room_id FROM team_rooms r JOIN team_room_members m USING(room_id) '
                'WHERE r.trip_id=%s AND m.account_id=%s', (trip, owner)).fetchone()
            if not row:
                fail(404, 'TRIP_UNAVAILABLE')
            return row[0]

    @staticmethod
    def trip_snapshot(value, trip):
        if trip is None:
            return value
        value = dict(value, tripId=trip, contractVersion=1)
        value.pop('roomId', None)
        return value

    def owned_get(self, owner, device, room, *, trip=None):
        with self.base.db() as conn:
            if trip is not None:
                room = self.trip_room(conn, trip, owner, withdrawal=True)
            grant, functional, joined, expiry = self.context(conn, owner, device, room, trip_context=trip is not None, withdrawal=trip is not None)
            value = self.snapshot(conn, grant, functional, room, joined, expiry)
            if trip is not None:
                with connection(conn).cursor(row_factory=tuple_row) as cursor:
                    try:
                        resolve_trip_context(self.auth, cursor, trip, owner)
                    except HTTPException as error:
                        if error.status_code not in (403,404,409):
                            raise
                        value['permissions'] = {key:False for key in PERMISSIONS}
            return self.trip_snapshot(value, trip)

    def owned_put(self, owner, device, room, raw, request, *, trip=None):
        try: value = decode_json(raw, maximum_bytes=12288)
        except CodecError: fail(400, 'INVALID_ROOM_MUSIC_REQUEST')
        if trip is not None:
            if type(value) is not dict or value.get('tripId') != trip or type(value.get('contractVersion')) is not int or value['contractVersion'] != 1:
                fail(400, 'INVALID_TRIP_PERMISSION_REQUEST')
            value = {key:item for key,item in value.items() if key not in ('tripId','contractVersion')}
        if type(value) is not dict or set(value) != set(CONTRACT['ownerPutFields']): fail(400, 'INVALID_ROOM_MUSIC_REQUEST')
        if type(value['authorizationVersion']) is not int or value['authorizationVersion'] != 1: fail(400, 'INVALID_ROOM_MUSIC_REQUEST')
        identifier(value['grantId']); revision(value['revision']); revision(value['functionalRevision'], zero=False)
        flags = value['permissions']
        if type(flags) is not dict or set(flags) != PERMISSIONS or any(type(x) is not bool for x in flags.values()): fail(400, 'INVALID_ROOM_MUSIC_REQUEST')
        if value['roomMusicDisclosureVersion'] != CONTRACT['disclosureVersion'] or type(value['roomMusicDisclosureVersion']) is not int or value['roomMusicDisclosureSha256'] != CONTRACT['disclosureSha256']: fail(409, 'ROOM_MUSIC_DISCLOSURE_CHANGED')
        with self.base.db() as conn:
            if self.auth.browser(request, mutate=True, connection=conn)['id'] != owner: fail(401, 'AUTHENTICATION_CHANGED')
            withdrawal = trip is not None and not any(flags.values())
            if trip is not None:
                room = self.trip_room(conn, trip, owner, withdrawal=withdrawal)
            grant, functional, joined, expiry = self.context(conn, owner, device, room, value['grantId'], trip_context=trip is not None, withdrawal=withdrawal)
            if value['functionalRevision'] != functional['revision'] or value['memberJoinedAt'] != joined.isoformat(): fail(409, 'ROOM_MUSIC_CONTEXT_CHANGED')
            current = self.row(conn, grant['grant_id'], room, True)
            if trip is not None and current and current['state'] == 'ACTIVE' and current['member_joined_at'] == joined and current['expires_at'] > self.base.now():
                expiry = min(expiry, current['expires_at'])
            old_revision = current['revision'] if current else 0
            if old_revision != value['revision']: fail(409, 'ROOM_MUSIC_REVISION_CHANGED')
            if old_revision >= MAX_REVISION: fail(409, 'ROOM_MUSIC_REVISION_EXHAUSTED')
            purposes = set(functional['approvedPurposes'])
            required = {'rooms:read'} if any(flags.values()) else set()
            if flags['receiveMusic']: required.add('room-music:read')
            if flags['shareMusic']: required.add('room-music:control')
            if not required <= purposes: fail(403, 'FUNCTIONAL_PURPOSE_REQUIRED')
            previous = self.payload(current)['permissions'] if current and current['protected'] is not None else dict(receiveMusic=False, shareMusic=False)
            active = any(flags.values())
            payload = dict(permissions=flags, roomMusicDisclosureVersion=CONTRACT['disclosureVersion'], roomMusicDisclosureSha256=CONTRACT['disclosureSha256'], disclosureSnapshot=CONTRACT['disclosure'])
            protected = VisitCipher().protect('native-room-music', grant['grant_id'] + ':' + room, payload) if active else None
            conn.execute("INSERT INTO native_room_music_authorizations(grant_id,room_id,device_id,revision,state,protected,member_joined_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(grant_id,room_id) DO UPDATE SET device_id=excluded.device_id,revision=excluded.revision,state=excluded.state,protected=excluded.protected,member_joined_at=excluded.member_joined_at,expires_at=excluded.expires_at", (grant['grant_id'],room,device,old_revision+1,'ACTIVE' if active else 'WITHDRAWN',protected,joined,expiry))
            if previous['shareMusic'] and not flags['shareMusic']:
                with conn.cursor(row_factory=tuple_row) as cursor: self.auth.room_music_service.withdraw_native_source(cursor, owner, device, room=room)
            changed(conn, owner, 'devices')
            return self.trip_snapshot(self.snapshot(conn, grant, functional, room, joined, expiry), trip)

    def withdraw(self, conn, owner, device, removed, room=None):
        keys = set()
        if removed & {'rooms:read', 'room-music:read'}: keys.add('receiveMusic')
        if removed & {'rooms:read', 'room-music:control'}: keys.add('shareMusic')
        if not keys: return
        db = connection(conn)
        with db.cursor(row_factory=dict_row) as cursor:
            query = 'SELECT r.* FROM native_room_music_authorizations r JOIN native_v2_grants g ON g.grant_id=r.grant_id WHERE g.account_id=%s AND r.device_id=%s'
            args = [owner, device]
            if room is not None: query += ' AND r.room_id=%s'; args.append(room)
            rows = cursor.execute(query + ' ORDER BY r.room_id FOR UPDATE OF r', args).fetchall()
            for row in rows:
                if row['protected'] is None: continue
                payload = self.payload(row); flags = payload['permissions']; edited = any(flags[k] for k in keys)
                if not edited: continue
                for key in keys: flags[key] = False
                active = any(flags.values()); protected = VisitCipher().protect('native-room-music', row['grant_id']+':'+row['room_id'], payload) if active else None
                cursor.execute('UPDATE native_room_music_authorizations SET revision=%s,state=%s,protected=%s WHERE grant_id=%s AND room_id=%s', (min(MAX_REVISION,row['revision']+1),'ACTIVE' if active else 'WITHDRAWN',protected,row['grant_id'],row['room_id']))
            changed(cursor, owner, 'devices')

    def withdraw_room_context(self, conn, room, owner=None, *, share_only=False):
        # Membership/role lineage, separate from the Browser account music flag.
        db = connection(conn)
        with db.cursor(row_factory=tuple_row) as cursor:
            query = ('SELECT DISTINCT g.account_id,a.device_id FROM native_room_music_authorizations a '
                     'JOIN native_v2_grants g ON g.grant_id=a.grant_id WHERE a.room_id=%s AND g.account_id IS NOT NULL')
            args = [room]
            if owner is not None: query += ' AND g.account_id=%s'; args.append(owner)
            targets = cursor.execute(query + ' ORDER BY g.account_id,a.device_id', args).fetchall()
        removed = frozenset({'room-music:control'} if share_only else {'rooms:read'})
        for account, device in targets:
            self.withdraw(db, account, device, removed, room)

    def withdraw_trip_context(self, conn, trip, room, account=None):
        self.withdraw_room_context(conn, room, account)

    def owned_delete(self, owner, device, trip, request):
        with self.base.db() as conn:
            if self.auth.browser(request, mutate=True, connection=conn)['id'] != owner:
                fail(401, 'AUTHENTICATION_CHANGED')
            room = self.trip_room(conn, trip, owner, withdrawal=True)
            grant, functional, joined, expiry = self.context(conn, owner, device, room, trip_context=True, withdrawal=True)
            self.withdraw(conn, owner, device, frozenset({'rooms:read'}), room)
            with conn.cursor(row_factory=tuple_row) as cursor:
                self.auth.room_music_service.withdraw_native_source(cursor, owner, device, room=room)
            return self.trip_snapshot(self.snapshot(conn, grant, functional, room, joined, expiry), trip)

    def trip_router(self):
        router = APIRouter()
        def output(call):
            try:
                return JSONResponse(call(), headers={'Cache-Control':'private, no-store'})
            except FunctionalError as error:
                return JSONResponse(dict(authorizationVersion=1, contractVersion=1, error=error.code), status_code=error.status, headers={'Cache-Control':'no-store'})
        @router.get('/v1/devices/{device}/trips/{trip}/music-permissions')
        def get(device: str, trip: str, request: Request):
            return output(lambda: self.owned_get(self.auth.browser(request)['id'], device, None, trip=trip))
        @router.put('/v1/devices/{device}/trips/{trip}/music-permissions')
        async def put(device: str, trip: str, request: Request):
            from native_authorization import read_body
            owner = self.auth.browser(request, mutate=True)['id']
            raw = await read_body(request)
            return await run_in_threadpool(output, lambda: self.owned_put(owner, device, None, raw, request, trip=trip))
        @router.delete('/v1/devices/{device}/trips/{trip}/music-permissions')
        def delete(device: str, trip: str, request: Request):
            owner = self.auth.browser(request, mutate=True)['id']
            return output(lambda: self.owned_delete(owner, device, trip, request))
        @router.get('/v1/native/trips/{trip}/music-permissions')
        def own(trip: str, request: Request):
            from native_functional_identity import transaction_actor
            def perform():
                with self.base.db() as conn:
                    identity = transaction_actor(self.auth, request, conn)
                    room = self.trip_room(conn, trip, identity['id'])
                    grant, functional, joined, expiry = self.context(conn, identity['id'], identity['deviceId'], room, identity['grantId'], trip_context=True)
                    return self.trip_snapshot(self.snapshot(conn, grant, functional, room, joined, expiry), trip)
            return output(perform)
        return router

    def router(self):
        router = APIRouter(); service = self
        def output(call):
            try: return JSONResponse(call(), headers={'Cache-Control':'private, no-store'})
            except FunctionalError as error: return JSONResponse(dict(authorizationVersion=1,error=error.code), status_code=error.status, headers={'Cache-Control':'no-store'})
        @router.get('/v1/devices/{device}/rooms/{room}/music-permissions')
        def get(device: str, room: str, request: Request):
            return output(lambda: service.owned_get(service.auth.browser(request)['id'], device, room))
        @router.put('/v1/devices/{device}/rooms/{room}/music-permissions')
        async def put(device: str, room: str, request: Request):
            from native_authorization import read_body
            owner = service.auth.browser(request, mutate=True)['id']; raw = await read_body(request)
            return await run_in_threadpool(output, lambda: service.owned_put(owner,device,room,raw,request))
        @router.delete('/v1/devices/{device}/rooms/{room}/music-permissions')
        def delete(device: str, room: str, request: Request):
            def perform():
                owner = service.auth.browser(request, mutate=True)['id']
                with service.base.db() as conn:
                    if service.auth.browser(request,mutate=True,connection=conn)['id'] != owner: fail(401,'AUTHENTICATION_CHANGED')
                    grant, functional, joined, expiry = service.context(conn,owner,device,room)
                    service.withdraw(conn,owner,device,frozenset({'rooms:read'}),room)
                    with conn.cursor(row_factory=tuple_row) as cursor: service.auth.room_music_service.withdraw_native_source(cursor,owner,device,room=room)
                    return service.snapshot(conn,grant,functional,room,joined,expiry)
            return output(perform)
        @router.get('/v1/native/rooms/{room}/music-permissions')
        def own(room: str, request: Request):
            from native_functional_identity import transaction_actor
            def perform():
                service.functional.require_enabled()
                with service.base.db() as conn:
                    identity = transaction_actor(service.auth,request,conn)
                    grant,functional,joined,expiry = service.context(conn,identity['id'],identity['deviceId'],room,identity['grantId'])
                    return service.snapshot(conn,grant,functional,room,joined,expiry)
            return output(perform)
        return router
