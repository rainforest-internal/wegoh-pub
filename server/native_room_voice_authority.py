"""Native grant/device/room voice consent with independent directions.

A device row for the current membership always decides. A trip room without one
starts on: the member's own trip voice setting and the device's approved voice
purposes decide. Other rooms stay off until the owner turns them on.
"""
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from psycopg.rows import dict_row, tuple_row
from private_records import VisitCipher
from native_access_codec import decode_json, CodecError
from native_functional_policy import WIRE, MAX_REVISION, FunctionalError, identifier, revision
from team_data import changed
from team_friends import blocked
from team_trip_context import resolve_trip_context

CONTRACT = WIRE['roomVoice']
PERMISSIONS = frozenset(CONTRACT['permissions'])
def fail(status, code):
    raise FunctionalError(status, code)
def connection(value):
    return getattr(value, 'connection', value)

class NativeRoomVoiceAuthority:
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
                if trip_context and access['state'] != 'active':
                    fail(409, 'TRIP_STATE_CONFLICT')
            joined = cursor.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s ' + ('' if withdrawal else 'AND left_at IS NULL'), (room, owner)).fetchone()
        if not joined:
            fail(404, 'ROOM_UNAVAILABLE')
        expiry = min(grant['expires_at'], functional['expiresAt'])
        if access['expiresAt'] is not None:
            expiry = min(expiry, int(access['expiresAt'].timestamp()))
        return grant, functional, joined[0], expiry

    def resolved_trip_snapshot(self, conn, principal, functional, context):
        db = connection(conn)
        if db.autocommit: fail(503, 'FUNCTIONAL_TRANSACTION_REQUIRED')
        room, account, trip = context['roomId'], principal['id'], context['tripId']
        if 'voice' not in self.rooms.available_consents():
            fail(403, 'TRIP_VOICE_UNAVAILABLE')
        with db.cursor(row_factory=tuple_row) as cursor:
            row = cursor.execute('SELECT protected FROM team_rooms WHERE room_id=%s AND trip_id=%s AND owner_id=%s',
                (room, trip, context['ownerId'])).fetchone()
            if not row: fail(409, 'TRIP_MEMBERSHIP_INCONSISTENT')
            self.rooms.restore('owner:' + context['ownerId'], room, row[0])
            if any(peer != account and membership['state'] == 'accepted' and blocked(cursor, account, peer)
                   for peer, membership in context['members'].items()):
                fail(404, 'ROOM_UNAVAILABLE')
            _, membership = self.auth.trip_service.voice_membership(cursor, trip, room, account)
        enabled = membership['participating']
        return dict(authorizationVersion=1, contractVersion=1, deviceId=principal['deviceId'], grantId=principal['grantId'],
            tripId=trip, revision=membership['revision'], functionalRevision=functional['revision'],
            memberJoinedAt=membership['memberJoinedAt'], expiresAt=functional['expiresAt'],
            permissions=dict(receiveVoice=enabled, transmitVoice=enabled),
            roomVoiceDisclosureVersion=CONTRACT['disclosureVersion'], roomVoiceDisclosureSha256=CONTRACT['disclosureSha256'])

    def row(self, conn, grant, room, lock=False):
        with connection(conn).cursor(row_factory=dict_row) as cursor:
            return cursor.execute('SELECT * FROM native_room_voice_authorizations WHERE grant_id=%s AND room_id=%s' + (' FOR UPDATE' if lock else ' FOR SHARE'), (grant, room)).fetchone()

    @staticmethod
    def payload(row):
        value = VisitCipher().restore('native-room-voice', row['grant_id'] + ':' + row['room_id'], row['protected'])
        if type(value) is not dict or set(value) != {'permissions', 'roomVoiceDisclosureVersion', 'roomVoiceDisclosureSha256', 'disclosureSnapshot'}:
            fail(503, 'ROOM_VOICE_STATE_INVALID')
        flags = value['permissions']
        if type(flags) is not dict or set(flags) != PERMISSIONS or any(type(x) is not bool for x in flags.values()):
            fail(503, 'ROOM_VOICE_STATE_INVALID')
        return value

    def trip_default(self, conn, grant, room, joined):
        with connection(conn).cursor(row_factory=tuple_row) as cursor:
            member = cursor.execute('SELECT m.protected FROM team_room_members m JOIN team_rooms r USING(room_id) '
                'WHERE m.room_id=%s AND m.account_id=%s AND m.joined_at=%s AND m.left_at IS NULL AND r.trip_id IS NOT NULL',
                (room, grant['account_id'], joined)).fetchone()
        return bool(member) and self.rooms.member_payload(grant['account_id'], room, member[0])['consents']['voice']

    def snapshot(self, conn, grant, functional, room, joined, expiry):
        row = self.row(conn, grant['grant_id'], room)
        flags = dict(receiveVoice=False, transmitVoice=False)
        if row and row['device_id'] != grant['device_id']:
            fail(503, 'ROOM_VOICE_STATE_INVALID')
        decided = bool(row) and row['member_joined_at'] == joined
        defaulted = not decided and expiry > self.base.now() and self.trip_default(conn, grant, room, joined)
        if defaulted:
            flags = dict(receiveVoice=True, transmitVoice=True)
        elif decided and row['state'] == 'ACTIVE' and min(expiry, row['expires_at']) > self.base.now():
            flags = self.payload(row)['permissions'].copy()
        if 'room-voice:receive' not in functional['approvedPurposes']: flags['receiveVoice'] = False
        if 'room-voice:transmit' not in functional['approvedPurposes']: flags['transmitVoice'] = False
        return dict(authorizationVersion=1, deviceId=grant['device_id'], grantId=grant['grant_id'], roomId=room,
            revision=row['revision'] if row else 0, functionalRevision=functional['revision'],
            memberJoinedAt=joined.isoformat(), expiresAt=min(expiry, row['expires_at']) if row and not defaulted else expiry,
            permissions=flags, roomVoiceDisclosureVersion=CONTRACT['disclosureVersion'], roomVoiceDisclosureSha256=CONTRACT['disclosureSha256'])

    def require(self, conn, owner, device, grant_id, room, permission, expected=None, *, trip_context=False):
        grant, functional, joined, expiry = self.context(conn, owner, device, room, grant_id, trip_context=trip_context)
        value = self.snapshot(conn, grant, functional, room, joined, expiry)
        if permission not in PERMISSIONS or not value['permissions'][permission]:
            fail(403, 'ROOM_VOICE_PERMISSION_REQUIRED')
        if expected is not None and (type(expected) is not int or expected != value['revision']):
            fail(409, 'ROOM_VOICE_REVISION_CHANGED')
        return value

    def data_stamp(self, conn, principal):
        # Private current-grant comparison only; never expose room IDs/flags in events.
        rows=connection(conn).execute('SELECT a.room_id,a.revision,a.state,a.expires_at,a.member_joined_at,m.joined_at,m.left_at '
            'FROM native_room_voice_authorizations a JOIN native_v2_grants g ON g.grant_id=a.grant_id '
            'LEFT JOIN team_room_members m ON m.room_id=a.room_id AND m.account_id=g.account_id '
            'WHERE a.grant_id=%s AND a.device_id=%s AND g.account_id=%s ORDER BY a.room_id',
            (principal['grantId'],principal['deviceId'],principal['id'])).fetchall()
        stamp=[]
        for room,revision_value,state,expiry,joined,current_joined,left in rows:
            accessible=False
            if left is None and joined==current_joined:
                try:self.rooms.access(conn,room,principal['id'],trip_context=True);accessible=True
                except HTTPException as error:
                    if error.status_code not in(403,404,409):raise
            stamp.append((room,revision_value,state,expiry>self.base.now(),accessible))
        return tuple(stamp)

    def listing(self, request):
        """A name-safe selection reference, never a new permission or room roster."""
        from native_functional_identity import transaction_actor
        from native_principal import is_native_principal
        from native_functional_query import native_query_allowed
        self.functional.require_enabled()
        if not is_native_principal(getattr(request.state, 'device_identity', None)):
            fail(404, 'ROUTE_NOT_FOUND')
        if not native_query_allowed(request): fail(400, 'INVALID_VOICE_ROOM_CURSOR')
        after = request.query_params.get('cursor', '')
        with self.base.db() as db:
            identity = transaction_actor(self.auth, request, db)
            grant, _ = self.functional.owner_grant(db, identity['id'], identity['deviceId'])
            if grant['grant_id'] != identity['grantId']: fail(401, 'INVALID_CREDENTIAL')
            with db.cursor(row_factory=dict_row) as cursor:
                functional = self.functional.snapshot(cursor, grant)
            with db.cursor(row_factory=tuple_row) as cursor:
                credential_expiry = cursor.execute('SELECT LEAST(c.access_expires_at,x.expires_at) '
                    'FROM native_v2_credentials c JOIN native_v2_grants g USING(grant_id) '
                    'JOIN native_v2_installations i USING(installation_key_id) '
                    'JOIN native_v2_certificates x ON x.installation_key_id=i.installation_key_id AND x.generation=i.current_generation '
                    'WHERE c.grant_id=%s', (grant['grant_id'],)).fetchone()
            if not credential_expiry or credential_expiry[0] <= self.base.now(): fail(401, 'INVALID_CREDENTIAL')
            items = []
            with db.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute("SELECT * FROM native_room_voice_authorizations WHERE grant_id=%s "
                    "AND device_id=%s AND room_id>%s AND state='ACTIVE' AND expires_at>%s ORDER BY room_id FOR SHARE",
                    (grant['grant_id'], grant['device_id'], after, self.base.now()))
                for row in rows:
                    payload = self.payload(row)
                    # Older audio-only consent remains unchanged, but cannot expose a new room-name projection.
                    if (payload['roomVoiceDisclosureVersion'] != CONTRACT['disclosureVersion'] or
                        payload['roomVoiceDisclosureSha256'] != CONTRACT['disclosureSha256']): continue
                    directions = [name for name, flag, purpose in (
                        ('receive', 'receiveVoice', 'room-voice:receive'), ('transmit', 'transmitVoice', 'room-voice:transmit'))
                        if payload['permissions'][flag] and purpose in functional['approvedPurposes']]
                    if not directions: continue
                    with db.cursor(row_factory=tuple_row) as domain:
                        try: access = self.rooms.access(domain, row['room_id'], identity['id'])
                        except HTTPException as error:
                            if error.status_code in (403, 404, 409): continue
                            raise
                        member = domain.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s '
                            'AND account_id=%s AND left_at IS NULL', (row['room_id'], identity['id'])).fetchone()
                    if not member or row['member_joined_at'] != member[0]: continue
                    expiry = min(grant['expires_at'], functional['expiresAt'], row['expires_at'],
                        credential_expiry[0], int(access['expiresAt'].timestamp()))
                    if expiry <= self.base.now(): continue
                    items.append(dict(roomId=row['room_id'], name=access['name'], availableDirections=directions,
                        revision=row['revision'], memberJoinedAt=member[0].isoformat(), expiresAt=expiry))
                    if len(items) == 21: break
            more = len(items) > 20; items = items[:20]
            return dict(authorizationVersion=1, deviceId=grant['device_id'], grantId=grant['grant_id'],
                functionalRevision=functional['revision'], items=items, nextCursor=items[-1]['roomId'] if more else None)

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
                        resolve_trip_context(self.auth, cursor, trip, owner, states=('active',))
                    except HTTPException as error:
                        if error.status_code not in (403,404,409):
                            raise
                        value['permissions'] = {key:False for key in PERMISSIONS}
            return self.trip_snapshot(value, trip)

    def owned_put(self, owner, device, room, raw, request, *, trip=None):
        try: value = decode_json(raw, maximum_bytes=12288)
        except CodecError: fail(400, 'INVALID_ROOM_VOICE_REQUEST')
        if trip is not None:
            if type(value) is not dict or value.get('tripId') != trip or type(value.get('contractVersion')) is not int or value['contractVersion'] != 1:
                fail(400, 'INVALID_TRIP_PERMISSION_REQUEST')
            value = {key:item for key,item in value.items() if key not in ('tripId','contractVersion')}
        if type(value) is not dict or set(value) != set(CONTRACT['ownerPutFields']): fail(400, 'INVALID_ROOM_VOICE_REQUEST')
        if type(value['authorizationVersion']) is not int or value['authorizationVersion'] != 1: fail(400, 'INVALID_ROOM_VOICE_REQUEST')
        identifier(value['grantId']); revision(value['revision']); revision(value['functionalRevision'], zero=False)
        flags = value['permissions']
        if type(flags) is not dict or set(flags) != PERMISSIONS or any(type(x) is not bool for x in flags.values()): fail(400, 'INVALID_ROOM_VOICE_REQUEST')
        if value['roomVoiceDisclosureVersion'] != CONTRACT['disclosureVersion'] or type(value['roomVoiceDisclosureVersion']) is not int or value['roomVoiceDisclosureSha256'] != CONTRACT['disclosureSha256']: fail(409, 'ROOM_VOICE_DISCLOSURE_CHANGED')
        with self.base.db() as conn:
            if self.auth.browser(request, mutate=True, connection=conn)['id'] != owner: fail(401, 'AUTHENTICATION_CHANGED')
            withdrawal = trip is not None and not any(flags.values())
            if trip is not None:
                room = self.trip_room(conn, trip, owner, withdrawal=withdrawal)
            grant, functional, joined, expiry = self.context(conn, owner, device, room, value['grantId'], trip_context=trip is not None, withdrawal=withdrawal)
            if value['functionalRevision'] != functional['revision'] or value['memberJoinedAt'] != joined.isoformat(): fail(409, 'ROOM_VOICE_CONTEXT_CHANGED')
            current = self.row(conn, grant['grant_id'], room, True)
            if trip is not None and current and current['state'] == 'ACTIVE' and current['member_joined_at'] == joined and current['expires_at'] > self.base.now():
                expiry = min(expiry, current['expires_at'])
            old_revision = current['revision'] if current else 0
            if old_revision != value['revision']: fail(409, 'ROOM_VOICE_REVISION_CHANGED')
            if old_revision >= MAX_REVISION: fail(409, 'ROOM_VOICE_REVISION_EXHAUSTED')
            purposes = set(functional['approvedPurposes'])
            required = set()
            if flags['receiveVoice']: required.add('room-voice:receive')
            if flags['transmitVoice']: required.add('room-voice:transmit')
            if not required <= purposes: fail(403, 'FUNCTIONAL_PURPOSE_REQUIRED')
            previous = self.payload(current)['permissions'] if current and current['protected'] is not None else dict(receiveVoice=False, transmitVoice=False)
            active = any(flags.values())
            payload = dict(permissions=flags, roomVoiceDisclosureVersion=CONTRACT['disclosureVersion'], roomVoiceDisclosureSha256=CONTRACT['disclosureSha256'], disclosureSnapshot=CONTRACT['disclosure'])
            protected = VisitCipher().protect('native-room-voice', grant['grant_id'] + ':' + room, payload) if active else None
            conn.execute("INSERT INTO native_room_voice_authorizations(grant_id,room_id,device_id,revision,state,protected,member_joined_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(grant_id,room_id) DO UPDATE SET device_id=excluded.device_id,revision=excluded.revision,state=excluded.state,protected=excluded.protected,member_joined_at=excluded.member_joined_at,expires_at=excluded.expires_at", (grant['grant_id'],room,device,old_revision+1,'ACTIVE' if active else 'WITHDRAWN',protected,joined,expiry))
            voice=getattr(self.auth,'voice_service',None)
            if voice:voice.invalidate_native(owner,device,room)
            changed(conn, owner, 'devices')
            return self.trip_snapshot(self.snapshot(conn, grant, functional, room, joined, expiry), trip)

    def withdraw(self, conn, owner, device, removed, room=None):
        keys = set()
        if removed & {'room-voice:receive'}: keys.add('receiveVoice')
        if removed & {'room-voice:transmit'}: keys.add('transmitVoice')
        if not keys: return
        db = connection(conn)
        with db.cursor(row_factory=dict_row) as cursor:
            query = 'SELECT r.* FROM native_room_voice_authorizations r JOIN native_v2_grants g ON g.grant_id=r.grant_id WHERE g.account_id=%s AND r.device_id=%s'
            args = [owner, device]
            if room is not None: query += ' AND r.room_id=%s'; args.append(room)
            rows = cursor.execute(query + ' ORDER BY r.room_id FOR UPDATE OF r', args).fetchall()
            for row in rows:
                if row['protected'] is None: continue
                payload = self.payload(row); flags = payload['permissions']; edited = any(flags[k] for k in keys)
                if not edited: continue
                for key in keys: flags[key] = False
                active = any(flags.values()); protected = VisitCipher().protect('native-room-voice', row['grant_id']+':'+row['room_id'], payload) if active else None
                cursor.execute('UPDATE native_room_voice_authorizations SET revision=%s,state=%s,protected=%s WHERE grant_id=%s AND room_id=%s', (min(MAX_REVISION,row['revision']+1),'ACTIVE' if active else 'WITHDRAWN',protected,row['grant_id'],row['room_id']))
            voice=getattr(self.auth,'voice_service',None)
            if voice:voice.invalidate_native(owner,device,room)
            changed(cursor, owner, 'devices')

    def withdraw_room_context(self, conn, room, owner=None, *, share_only=False):
        voice = getattr(self.auth, 'voice_service', None)
        if voice:
            voice.invalidate_context(room, accounts=None if owner is None else {owner})
        # Membership/role lineage, separate from the Browser account voice flag.
        db = connection(conn)
        with db.cursor(row_factory=tuple_row) as cursor:
            query = ('SELECT DISTINCT g.account_id,a.device_id FROM native_room_voice_authorizations a '
                     'JOIN native_v2_grants g ON g.grant_id=a.grant_id WHERE a.room_id=%s')
            args = [room]
            if owner is not None: query += ' AND g.account_id=%s'; args.append(owner)
            targets = cursor.execute(query + ' ORDER BY g.account_id,a.device_id', args).fetchall()
        removed = frozenset({'room-voice:receive','room-voice:transmit'})
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
            self.withdraw(conn, owner, device, frozenset({'room-voice:receive','room-voice:transmit'}), room)
            current = self.row(conn, grant['grant_id'], room, True)
            if not current or current['member_joined_at'] != joined:
                old_revision = current['revision'] if current else 0
                if old_revision >= MAX_REVISION: fail(409, 'ROOM_VOICE_REVISION_EXHAUSTED')
                conn.execute("INSERT INTO native_room_voice_authorizations(grant_id,room_id,device_id,revision,state,protected,member_joined_at,expires_at) VALUES(%s,%s,%s,%s,'WITHDRAWN',NULL,%s,%s) ON CONFLICT(grant_id,room_id) DO UPDATE SET device_id=excluded.device_id,revision=excluded.revision,state=excluded.state,protected=excluded.protected,member_joined_at=excluded.member_joined_at,expires_at=excluded.expires_at", (grant['grant_id'],room,device,old_revision+1,joined,expiry))
                voice=getattr(self.auth,'voice_service',None)
                if voice:voice.invalidate_native(owner,device,room)
                changed(conn, owner, 'devices')
            return self.trip_snapshot(self.snapshot(conn, grant, functional, room, joined, expiry), trip)

    def trip_router(self):
        router = APIRouter()
        def output(call):
            try:
                return JSONResponse(call(), headers={'Cache-Control':'private, no-store'})
            except FunctionalError as error:
                return JSONResponse(dict(authorizationVersion=1, contractVersion=1, error=error.code), status_code=error.status, headers={'Cache-Control':'no-store'})
        @router.get('/v1/devices/{device}/trips/{trip}/voice-permissions')
        def get(device: str, trip: str, request: Request):
            return output(lambda: self.owned_get(self.auth.browser(request)['id'], device, None, trip=trip))
        @router.put('/v1/devices/{device}/trips/{trip}/voice-permissions')
        async def put(device: str, trip: str, request: Request):
            from native_authorization import read_body
            owner = self.auth.browser(request, mutate=True)['id']
            raw = await read_body(request)
            return await run_in_threadpool(output, lambda: self.owned_put(owner, device, None, raw, request, trip=trip))
        @router.delete('/v1/devices/{device}/trips/{trip}/voice-permissions')
        def delete(device: str, trip: str, request: Request):
            owner = self.auth.browser(request, mutate=True)['id']
            return output(lambda: self.owned_delete(owner, device, trip, request))
        @router.get('/v1/native/trips/{trip}/voice-permissions')
        def own(trip: str, request: Request):
            from native_functional_identity import transaction_actor
            def perform():
                with self.base.db() as conn:
                    identity = transaction_actor(self.auth, request, conn)
                    with conn.cursor(row_factory=tuple_row) as cursor:
                        context = resolve_trip_context(self.auth, cursor, trip, identity['id'], states=('active',))
                    return self.resolved_trip_snapshot(conn, identity, request.state.functional_snapshot, context)
            return output(perform)
        return router

    def router(self):
        router = APIRouter(); service = self
        def output(call):
            try: return JSONResponse(call(), headers={'Cache-Control':'private, no-store'})
            except FunctionalError as error: return JSONResponse(dict(authorizationVersion=1,error=error.code), status_code=error.status, headers={'Cache-Control':'no-store'})
        @router.get('/v1/native/voice-rooms')
        def rooms(request: Request):
            return output(lambda: service.listing(request))
        @router.get('/v1/devices/{device}/rooms/{room}/voice-permissions')
        def get(device: str, room: str, request: Request):
            return output(lambda: service.owned_get(service.auth.browser(request)['id'], device, room))
        @router.put('/v1/devices/{device}/rooms/{room}/voice-permissions')
        async def put(device: str, room: str, request: Request):
            from native_authorization import read_body
            owner = service.auth.browser(request, mutate=True)['id']; raw = await read_body(request)
            return await run_in_threadpool(output, lambda: service.owned_put(owner,device,room,raw,request))
        @router.delete('/v1/devices/{device}/rooms/{room}/voice-permissions')
        def delete(device: str, room: str, request: Request):
            def perform():
                owner = service.auth.browser(request, mutate=True)['id']
                with service.base.db() as conn:
                    if service.auth.browser(request,mutate=True,connection=conn)['id'] != owner: fail(401,'AUTHENTICATION_CHANGED')
                    grant, functional, joined, expiry = service.context(conn,owner,device,room)
                    service.withdraw(conn,owner,device,frozenset({'room-voice:receive','room-voice:transmit'}),room)
                    return service.snapshot(conn,grant,functional,room,joined,expiry)
            return output(perform)
        @router.get('/v1/native/rooms/{room}/voice-permissions')
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
