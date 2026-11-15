"""Explicit room-scoped device command delivery and fixed HVAC contracts.

Read permissions, client capability JSON and an ACK do not confer execution
support or physical verification. All sensitive payloads use VisitCipher.
"""
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response
from private_records import VisitCipher, PrivateRecordError
from team_auth import COOKIE, hashed
from team_data import changed
from team_event_versions import bump
from device_command_registry import ProductionCommandRegistry
from native_functional_identity import request_actor,transaction_actor,business_json,resolve_current_device
from native_functional_policy import FunctionalError
from native_principal import is_native_principal

ID = re.compile(r'[a-f0-9]{32}')
ACCOUNT = re.compile(r'team-[a-f0-9]{40}')
EVENT = re.compile(r'[A-Za-z0-9_-]{16,96}')
STAGES = ('queued', 'delivered', 'received', 'sdk-accepted', 'state-confirmed')
TERMINAL = ('rejected', 'unknown', 'cancelled', 'expired', 'state-confirmed')
HOURS = (1, 4, 12, 24)


def fail(code=404, message='Device request unavailable'):
    raise HTTPException(code, message)


def instant(value):
    if not isinstance(value, str):
        fail(400, 'A timezone-aware time is required')
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        fail(400, 'Invalid time')
    if result.tzinfo is None or result.utcoffset() is None:
        fail(400, 'A timezone-aware time is required')
    return result.astimezone(dt.timezone.utc)


def iso(value):
    return value.astimezone(dt.timezone.utc).isoformat()


def revision(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        fail(400, 'Invalid revision')
    return value


def event(value):
    if not isinstance(value, str) or not EVENT.fullmatch(value):
        fail(400, 'Invalid event identifier')
    return value


async def body(request, required, optional=()):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 4096:
            fail(413, 'Request too large')
    try:
        value = business_json(request,raw,maximum=4096)
    except (ValueError, UnicodeError, RecursionError):
        fail(400, 'Invalid JSON')
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or not set(required) <= set(value):
        fail(400, 'Invalid request fields')
    return value


def trip_withdrawal_room(auth, conn, trip, account):
    from team_trip_context import trip_state
    trip_state(conn, trip)
    auth.current_account(account)
    row = conn.execute('SELECT r.room_id FROM team_rooms r JOIN team_room_members m USING(room_id) '
        'WHERE r.trip_id=%s AND m.account_id=%s FOR UPDATE OF r', (trip, account)).fetchone()
    if not row:fail()
    return row[0]


class TeamDeviceCommands:
    def __init__(self, auth, rooms, *, fixture_registry=None):
        self.auth, self.rooms, self.dsn = auth, rooms, auth.dsn
        self.enabled = auth.enabled
        # Internal, explicit fixture injection only. app.py never supplies one;
        # there is no environment, HTTP, certificate or capability-JSON switch.
        self.registry = fixture_registry if fixture_registry is not None else ProductionCommandRegistry()

    def display_actions(self):
        """Response-only options from trusted server action objects, never client JSON."""
        result=[]
        for descriptor in self.registry.describe():
            action=self.registry.lookup(descriptor['id'],descriptor['revision'])
            if action is None:continue
            label=getattr(action,'display_label',None)
            kind=getattr(action,'argument_kind',None)
            if (not isinstance(label,str) or not 1<=len(label)<=80 or label!=label.strip()
                    or any(ord(c)<32 for c in label) or kind not in ('empty-object','hvac-celsius','hvac-fan',
                        'seat-switch','seat-level','window-position','switch')):
                # Unknown display/argument contracts aren't guessed into a UI.
                continue
            result.append(dict(id=descriptor['id'],revision=descriptor['revision'],label=label,argumentKind=kind))
        return sorted(result,key=lambda x:(x['id'],x['revision']))

    def received_grants(self,conn,room,requester,participation,joined,*,trip_context=False):
        now=self.now(conn)
        if not self.live(participation,now) or participation.get('joinedAt')!=joined:return []
        options=self.display_actions()
        if not options:return []
        result=[]
        for device,owner in conn.execute('SELECT device_id,owner_id FROM team_device_command_grants '
                'WHERE room_id=%s AND requester_id=%s AND owner_id=requester_id ORDER BY device_id LIMIT 100',(room,requester)):
            try:
                _,expiry=self.context(conn,room,device,requester,owner,trip_context=trip_context)
                access=self.access(conn,device,owner);_,grant=self.grant(conn,room,device,requester)
                allowed=[dict(x)for x in options if all(dict(id=x['id'],revision=x['revision'])in value.get('actions',[])
                    for value in (participation,access,grant))]
                if not allowed:continue
                person=self.rooms.person(owner)
                if person is None:continue
                try:reference=resolve_current_device(self.auth,conn,owner,device,required=frozenset({'device-commands:receive'}))
                except FunctionalError as error:fail(error.status,error.code)
                expiry=min(expiry,reference.expires_at)
                if expiry<=self.now(conn):continue
                result.append(dict(targetDeviceId=device,ownerId=owner,ownerName=person['name'],deviceName=reference.name,
                    grantRevision=grant['revision'],expiresAt=iso(expiry),actions=allowed))
            except HTTPException as error:
                if error.status_code not in (401,403,404,409):raise
                # No target identifiers/names/old grant metadata in this field.
                continue
            except RuntimeError as error:
                # Missing/corrupt encrypted state must not become an empty success.
                raise PrivateRecordError('Device command metadata unavailable') from error
        return result

    @staticmethod
    def now(conn):
        return conn.execute('SELECT clock_timestamp()').fetchone()[0]

    def protect(self, kind, key, value):
        return VisitCipher().protect('device-command-' + kind, key, value)

    def restore(self, kind, key, raw):
        value = VisitCipher().restore('device-command-' + kind, key, raw)
        if not isinstance(value, dict):
            raise PrivateRecordError('Device command integrity failed')
        return value

    def digest(self, domain, value):
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return hmac.new(self.auth.secret, domain.encode() + b':' + raw, hashlib.sha256).hexdigest()

    def notify(self, conn, *accounts):
        for account in set(accounts):
            changed(conn, account, 'devices')
            changed(conn, account, 'rooms')

    def invalidate_receiver(self, conn, device):
        changed(conn,"command-device:"+device,"devices")

    def notify_progress(self, conn, *accounts):
        for account in set(accounts):changed(conn,account,'devices')

    def notify_request_progress(self, conn, value):
        self.notify_progress(conn,value['requesterId'])
        if value['roomId'] is None:
            self.notify_progress(conn,value['ownerId'])
            bump(conn,'command-status-device:'+value['targetDeviceId'],'devices')

    def browser(self, conn, request, mutate=False):
        actor = transaction_actor(self.auth,request,conn,mutate=mutate)
        if mutate:
            self.auth.rate('device-command-write:' + actor['id'], limit=60)
            if is_native_principal(actor):return actor
            row = conn.execute('SELECT creator_id,expires_at FROM studio_sessions WHERE token_hash=%s FOR UPDATE',
                (hashed(request.cookies.get(COOKIE, '')),)).fetchone()
            if not row or row[0] != actor['id'] or row[1] <= self.now(conn):
                fail(401, 'Team session expired')
        return actor

    def device(self, conn, owner, device):
        try:return resolve_current_device(self.auth,conn,owner,device).expires_at
        except FunctionalError as error:fail(error.status,error.code)

    def native(self, conn, request, device=None):
        actor=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
        if not is_native_principal(actor) or device is not None and actor['deviceId']!=device:
            fail(401,'Device authentication changed')
        self.device(conn,actor['id'],actor['deviceId'])
        return actor

    def membership(self, conn, room, account, *, trip_context=False, active=False):
        if not isinstance(room, str) or not ID.fullmatch(room):
            fail()
        access = self.rooms.access(conn, room, account, trip_context=trip_context)
        if active and access.get('tripId') and access['state'] != 'active':
            fail(409, 'TRIP_STATE_CONFLICT')
        row = conn.execute('SELECT joined_at FROM team_room_members '
            'WHERE room_id=%s AND account_id=%s AND left_at IS NULL', (room, account)).fetchone()
        if not row:fail()
        self.auth.current_account(account)
        return iso(row[0]), access['expiresAt']

    def access(self, conn, device, owner):
        try:reference=resolve_current_device(self.auth,conn,owner,device)
        except FunctionalError as error:fail(error.status,error.code)
        row=conn.execute('SELECT protected FROM team_device_command_access WHERE device_id=%s FOR UPDATE',(device,)).fetchone()
        value=self.restore('access',device,row[0])if row else dict(revision=0,consent=False,expiresAt=None,actions=[])
        binding=value.pop('nativeBinding',None)
        if (binding!=dict(grantId=reference.grant_id,functionalRevision=reference.functional_revision)
            or 'device-commands:receive'not in reference.approved_purposes):value['consent']=False
        return value

    def participation(self, conn, room, actor, *, trip_context=False, active=False):
        joined, expiry = self.membership(conn, room, actor, trip_context=trip_context, active=active)
        key = room + ':' + actor
        row = conn.execute('SELECT protected FROM team_device_command_members WHERE room_id=%s AND account_id=%s FOR UPDATE',
            (room, actor)).fetchone()
        value = self.restore('member', key, row[0]) if row else dict(revision=0, consent=False, expiresAt=None, joinedAt=joined, actions=[])
        return value, joined, expiry

    def grant(self, conn, room, device, requester):
        row = conn.execute('SELECT owner_id,protected FROM team_device_command_grants '
            'WHERE room_id=%s AND device_id=%s AND requester_id=%s FOR UPDATE', (room, device, requester)).fetchone()
        if not row:
            return None, dict(revision=0, consent=False, expiresAt=None, actions=[])
        return row[0], self.restore('grant', room + ':' + device + ':' + requester, row[1])

    def live(self, value, now):
        return value.get('consent') is True and value.get('expiresAt') is not None and instant(value['expiresAt']) > now

    def actions(self, value):
        if not isinstance(value, list) or len(value) > 16:
            fail(400, 'Choose explicit registered actions')
        result = []
        for item in value:
            if not isinstance(item, dict) or set(item) != {'id', 'revision'} or not isinstance(item['id'], str) or not 1 <= len(item['id']) <= 80:
                fail(400, 'Invalid action selection')
            revision(item['revision'])
            if self.registry.lookup(item['id'], item['revision']) is None:
                fail(503, 'Registered action unavailable')
            if item in result:
                fail(400, 'Duplicate action selection')
            result.append(dict(item))
        return sorted(result, key=lambda x: (x['id'], x['revision']))

    def context(self, conn, room, device, requester, owner, *, expected=None, action=None, trip_context=False):
        if action is not None and self.registry.lookup(action['id'], action['revision']) is None:
            fail(403, 'Registered action unavailable')
        if room is None:
            return self.friend_controls.context(conn,device,requester,owner,expected=expected,action=action)
        if requester != owner:
            fail(403, 'Use the current trip remote')
        a, joined_requester, room_expiry = self.participation(conn, room, requester, trip_context=trip_context, active=True)
        access = self.access(conn, device, owner)
        saved_owner, grant = self.grant(conn, room, device, requester)
        now = self.now(conn)
        if (saved_owner != owner or not all(self.live(x, now) for x in (a, access, grant))
            or a.get('joinedAt') != joined_requester or grant.get('requesterJoinedAt') != joined_requester
            or grant.get('ownerJoinedAt') != joined_requester or grant.get('deviceRevision') != access['revision']
            or grant.get('participationRevision') != a['revision']):
            fail(403, 'Current explicit command permissions required')
        if action is not None and any(action not in x.get('actions', []) for x in (a, access, grant)):
            fail(403, 'This registered action was not explicitly permitted')
        trip_snapshot = {}
        if room_expiry is None:
            trip = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s', (room,)).fetchone()[0]
            trip_snapshot['tripId'] = trip
        snapshot = dict(grantRevision=grant['revision'], deviceRevision=access['revision'],
            participationRevision=a['revision'], requesterJoinedAt=joined_requester, ownerJoinedAt=joined_requester, **trip_snapshot)
        if expected is not None and snapshot != expected:
            fail(409, 'Command permissions changed')
        return snapshot, min(expiry for expiry in (room_expiry, self.device(conn, owner, device),
            *(instant(x['expiresAt']) for x in (a, access, grant))) if expiry is not None)

    def save_request(self, conn, key, value):
        conn.execute(('UPDATE friend_vehicle_commands SET protected=%s,updated_at=clock_timestamp() WHERE request_id=%s'if value.get('roomId')is None else 'UPDATE team_device_commands SET protected=%s,updated_at=clock_timestamp() WHERE request_id=%s'),
            (self.protect('request', key, value), key))

    def terminalize(self, value, reason):
        if value['stage'] not in TERMINAL:
            value['stage'] = 'unknown' if value['mayHaveExecuted'] else ('expired' if reason == 'expired' else 'cancelled')
            value['reason'] = reason
            value['leaseHash'] = None
        return value

    def revoke_rows(self, conn, where, args, reason):
        for key, raw in conn.execute('SELECT request_id,protected FROM team_device_commands WHERE ' + where + ' FOR UPDATE', args).fetchall():
            value = self.restore('request', key, raw)
            if value['stage'] in TERMINAL:continue
            self.terminalize(value, reason)
            self.save_request(conn, key, value)
            self.invalidate_receiver(conn,value['targetDeviceId'])
            self.notify(conn, value['requesterId'], value['ownerId'])

    def revoke_context(self, conn, room, account=None):
        # Called inside the existing social graph transaction before any rejoin.
        query = 'room_id=%s';args = [room]
        if account is not None:
            query += ' AND (requester_id=%s OR owner_id=%s)';args += [account, account]
        self.revoke_rows(conn, query, args, 'context-withdrawn')
        for device, requester, raw in conn.execute('SELECT device_id,requester_id,protected FROM team_device_command_grants WHERE ' + query + ' FOR UPDATE', args).fetchall():
            key = room + ':' + device + ':' + requester;value = self.restore('grant', key, raw)
            if not value.get('consent'):continue
            value.update(consent=False, revision=value['revision'] + 1)
            conn.execute('UPDATE team_device_command_grants SET protected=%s WHERE room_id=%s AND device_id=%s AND requester_id=%s',
                (self.protect('grant', key, value), room, device, requester))

    def withdraw_trip_context(self, conn, trip, room, account=None):
        self.revoke_context(conn, room, account)
        query = 'SELECT account_id,protected FROM team_device_command_members WHERE room_id=%s'
        args = [room]
        if account is not None:
            query += ' AND account_id=%s'
            args.append(account)
        for peer, raw in conn.execute(query + ' FOR UPDATE', args).fetchall():
            key = room + ':' + peer
            value = self.restore('member', key, raw)
            if not value.get('consent'):continue
            value.update(consent=False, revision=value['revision'] + 1)
            conn.execute('UPDATE team_device_command_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                (self.protect('member', key, value), room, peer))
            self.notify(conn, peer)
        controls = getattr(self, 'friend_controls', None)
        if controls:controls.withdraw_trip_context(conn, trip, room, account)

    def revoke_device(self, conn, device, owner):
        self.friend_controls.revoke_device(conn,device,owner)
        self.revoke_rows(conn,'device_id=%s AND owner_id=%s',(device,owner),'device-revoked')
        for room, requester, raw in conn.execute('SELECT room_id,requester_id,protected FROM team_device_command_grants WHERE device_id=%s AND owner_id=%s FOR UPDATE',(device,owner)).fetchall():
            key=room+':'+device+':'+requester;value=self.restore('grant',key,raw);value.update(consent=False,revision=value['revision']+1)
            conn.execute('UPDATE team_device_command_grants SET protected=%s WHERE room_id=%s AND device_id=%s AND requester_id=%s',(self.protect('grant',key,value),room,device,requester))
        self.notify(conn,owner)

    def revoke_native_requester(self,conn,device,owner):
        # Only this installation's Native-origin requests, never Browser/other devices.
        rows=[]
        for table in ('team_device_commands', 'friend_vehicle_commands'):
            rows.extend(conn.execute('SELECT request_id,protected FROM ' + table + ' WHERE requester_id=%s FOR UPDATE',(owner,)).fetchall())
        for key,raw in rows:
            value=self.restore('request',key,raw);origin=value.get('nativeOrigin')
            if origin is None or origin.get('deviceId')!=device or value['stage']in TERMINAL:continue
            self.terminalize(value,'source-permission-withdrawn');self.save_request(conn,key,value);self.invalidate_receiver(conn,value['targetDeviceId'])
            self.notify(conn,value['requesterId'],value['ownerId'])

    def revoke_pair(self, conn, a, b):
        self.friend_controls.revoke_pair(conn,a,b)
        for room, in conn.execute('SELECT DISTINCT room_id FROM team_device_command_grants WHERE '
                '(owner_id=%s AND requester_id=%s) OR (owner_id=%s AND requester_id=%s)', (a, b, b, a)):
            self.revoke_context(conn, room, a)

    def load_request(self, conn, identifier):
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            fail()
        row = conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s FOR UPDATE', (identifier,)).fetchone()
        if not row:
            row=conn.execute('SELECT protected FROM friend_vehicle_commands WHERE request_id=%s FOR UPDATE',(identifier,)).fetchone()
        if not row:fail()
        value = self.restore('request', identifier, row[0])
        origin=value.get('nativeOrigin')
        if origin is not None:
            if (type(origin)is not dict or set(origin)!={'deviceId','grantId','functionalRevision'}
                or any(type(origin[k])is not str or ID.fullmatch(origin[k])is None for k in('deviceId','grantId'))
                or type(origin['functionalRevision'])is not int or not 1<=origin['functionalRevision']<=2147483647):
                raise PrivateRecordError('Device request source integrity failed')
            if value['stage']not in TERMINAL:
                try:
                    reference=resolve_current_device(self.auth,conn,value['requesterId'],origin['deviceId'],required=frozenset({'device-commands:request'}))
                    active=reference.grant_id==origin['grantId']and reference.functional_revision==origin['functionalRevision']
                except FunctionalError as error:
                    if error.status not in(401,403,404,410):fail(error.status,error.code)
                    active=False
                if not active:
                    self.terminalize(value,'source-permission-withdrawn');self.save_request(conn,identifier,value);self.invalidate_receiver(conn,value['targetDeviceId']);self.notify(conn,value['ownerId'],value['requesterId'])
        now=self.now(conn)
        reason='expired' if instant(value['expiresAt'])<=now else ('lease-expired' if value.get('leaseExpiresAt') and instant(value['leaseExpiresAt'])<=now else None)
        if reason and value['stage'] not in TERMINAL:
            self.terminalize(value,reason);self.save_request(conn,identifier,value);self.invalidate_receiver(conn,value['targetDeviceId']);self.notify(conn,value['ownerId'],value['requesterId'])
        return value

    @staticmethod
    def public(identifier, value, *, payload=False):
        result = {key:value[key] for key in ('roomId', 'targetDeviceId', 'requesterId', 'ownerId', 'capabilityId',
            'capabilityRevision', 'stage', 'lastAcknowledgedStage', 'mayHaveExecuted', 'expiresAt', 'createdAt', 'reason')}
        result.update(id=identifier, physicalExecutionVerified=False)
        if payload:
            result['arguments'] = value['arguments']
        return result

    def trip_router(self):
        router = self.router(trip_context=True)
        controls = getattr(self, 'friend_controls', None)
        if controls:router.include_router(controls.trip_router())
        return router

    def router(self, *, trip_context=False):
        from fastapi import Depends, Response
        def private_response(response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
        router = APIRouter(dependencies=[Depends(private_response)] if trip_context else [])
        if not self.enabled:
            return router

        prefix = '/v1/social/trips/{room}' if trip_context else '/v1/social/rooms/{room}'

        def room_context(conn, selector, account, *, withdrawing=False):
            if not trip_context:
                if withdrawing:
                    link = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL', (selector,)).fetchone()
                    if link:self.rooms.access(conn, selector, account)
                else:self.membership(conn, selector, account)
                return selector
            from team_trip_context import resolve_trip_context
            if withdrawing:
                return trip_withdrawal_room(self.auth, conn, selector, account)
            return resolve_trip_context(self.auth, conn, selector, account)['roomId']

        def public_context(value, selector):
            if not trip_context:return value
            value = dict(value)
            value.pop('roomId', None)
            value['tripId'] = selector
            for field in ('grants', 'requests'):
                if field in value:
                    value[field] = [public_context(item, selector) for item in value[field]]
            return value

        @router.get('/v1/devices/{device}/command-access')
        def get_access(device: str, request: Request):
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request)
                value = self.access(conn, device, actor['id']);now = self.now(conn)
                return dict(deviceId=device, **value, active=self.live(value, now), serverNow=now,
                    supportedControlActions=self.display_actions(), physicalExecutionSupported=False)

        @router.put('/v1/devices/{device}/command-access')
        async def put_access(device: str, request: Request):
            data = await body(request, ('revision', 'consent', 'expiresInHours', 'actions'))
            revision(data['revision']);actions=self.actions(data['actions'])
            if type(data['consent']) is not bool or type(data['expiresInHours']) is not int or data['expiresInHours'] not in HOURS:
                fail(400, 'Choose an explicit command permission and expiry')
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request, True)
                value = self.access(conn, device, actor['id'])
                if value['revision'] != data['revision']:
                    fail(409, 'Command permission changed')
                expires = min(self.device(conn, actor['id'], device), self.now(conn) + dt.timedelta(hours=data['expiresInHours']))
                try:reference=resolve_current_device(self.auth,conn,actor['id'],device,required=frozenset({'device-commands:receive'})if data['consent']else frozenset())
                except FunctionalError as error:fail(error.status,error.code)
                value.update(revision=value['revision'] + 1, consent=data['consent'], actions=actions, expiresAt=iso(expires),nativeBinding=dict(grantId=reference.grant_id,functionalRevision=reference.functional_revision))
                conn.execute('INSERT INTO team_device_command_access(device_id,protected) VALUES(%s,%s) '
                    'ON CONFLICT(device_id) DO UPDATE SET protected=excluded.protected', (device, self.protect('access', device, value)))
                value.pop('nativeBinding')
                self.revoke_rows(conn, 'device_id=%s', (device,), 'device-permission-changed');self.notify(conn, actor['id'])
            return dict(deviceId=device, **value, supportedControlActions=self.display_actions())

        @router.delete('/v1/devices/{device}/command-access')
        def delete_access(device: str, request: Request):
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request, True);value = self.access(conn, device, actor['id'])
                value.update(revision=value['revision'] + 1, consent=False)
                conn.execute('INSERT INTO team_device_command_access(device_id,protected) VALUES(%s,%s) ON CONFLICT(device_id) '
                    'DO UPDATE SET protected=excluded.protected', (device, self.protect('access', device, value)))
                self.revoke_rows(conn, 'device_id=%s', (device,), 'device-permission-withdrawn');self.notify(conn, actor['id'])
            return dict(deviceId=device, **value,supportedControlActions=self.display_actions())

        @router.get(prefix + '/device-command-access')
        def get_member(room: str, request: Request):
            selector = room
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request);room = room_context(conn, selector, actor['id']);value, joined, expiry = self.participation(conn,room,actor['id'],trip_context=trip_context)
                now = self.now(conn);owned = []
                active = self.live(value,now) and value['joinedAt'] == joined
                participants = [dict(accountId=actor['id'], revision=value['revision'], joinedAt=joined,
                    actions=value.get('actions', []), active=active)]
                for device, requester, raw in conn.execute('SELECT device_id,requester_id,protected FROM team_device_command_grants '
                        'WHERE room_id=%s AND owner_id=%s AND requester_id=owner_id', (room, actor['id'])):
                    grant = self.restore('grant', room + ':' + device + ':' + requester, raw)
                    owned.append(dict(roomId=room,deviceId=device, requesterId=requester, **grant))
                received=self.received_grants(conn,room,actor['id'],value,joined,trip_context=trip_context)
                return public_context(dict(roomId=room, **value, currentJoinedAt=joined, active=active,
                    grants=owned, receivedGrants=received, participants=participants, serverNow=self.now(conn), supportedControlActions=self.display_actions()), selector)

        @router.put(prefix + '/device-command-access')
        async def put_member(room: str, request: Request):
            selector = room
            data = await body(request, ('revision', 'joinedAt', 'consent', 'expiresInHours', 'actions'))
            revision(data['revision']);instant(data['joinedAt']);actions=self.actions(data['actions'])
            if type(data['consent']) is not bool or type(data['expiresInHours']) is not int or data['expiresInHours'] not in HOURS:
                fail(400, 'Choose an explicit room command permission and expiry')
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request, True);room = room_context(conn, selector, actor['id']);value, joined, expiry = self.participation(conn,room,actor['id'],trip_context=trip_context)
                if value['revision'] != data['revision'] or data['joinedAt'] != joined:
                    fail(409, 'Room command permission changed')
                value.update(revision=value['revision'] + 1, consent=data['consent'], actions=actions, joinedAt=joined,
                    expiresAt=iso(min(item for item in (expiry, self.now(conn) + dt.timedelta(hours=data['expiresInHours'])) if item is not None)))
                key = room + ':' + actor['id'];conn.execute('INSERT INTO team_device_command_members(room_id,account_id,protected) '
                    'VALUES(%s,%s,%s) ON CONFLICT(room_id,account_id) DO UPDATE SET protected=excluded.protected',
                    (room, actor['id'], self.protect('member', key, value)))
                self.revoke_context(conn, room, actor['id']);self.notify(conn, actor['id'])
            return public_context(dict(roomId=room, **value), selector)

        @router.delete(prefix + '/device-command-access')
        def withdraw_member(room: str, request: Request):
            selector = room
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request, True)
                room = room_context(conn, selector, actor['id'], withdrawing=True)
                if trip_context:self.withdraw_trip_context(conn, selector, room, actor['id'])
                else:
                    self.membership(conn, room, actor['id'])
                    self.withdraw_trip_context(conn, '', room, actor['id'])
            return public_context(dict(status='withdrawn'), selector)

        @router.put(prefix + '/device-command-grants/{device}/{peer}')
        async def put_grant(room: str, device: str, peer: str, request: Request):
            selector = room
            data = await body(request, ('revision', 'deviceRevision', 'participationRevision', 'ownerJoinedAt', 'requesterJoinedAt', 'consent', 'expiresInHours', 'actions'))
            for key in ('revision', 'deviceRevision', 'participationRevision'):revision(data[key])
            actions=self.actions(data['actions'])
            if not ACCOUNT.fullmatch(peer) or type(data['consent']) is not bool or type(data['expiresInHours']) is not int or data['expiresInHours'] not in HOURS:
                fail(400, 'Invalid command grant')
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request, True);room = room_context(conn, selector, actor['id']);owner = actor['id']
                if peer != owner:fail(403, 'Use the current trip remote')
                access = self.access(conn, device, owner)
                member, joined_peer, room_expiry = self.participation(conn,room,peer,trip_context=trip_context);joined_owner, _ = self.membership(conn,room,owner,trip_context=trip_context)
                saved_owner, value = self.grant(conn, room, device, peer)
                if (saved_owner not in (None, owner) or value['revision'] != data['revision'] or data['deviceRevision'] != access['revision']
                    or data['participationRevision'] != member['revision'] or data['ownerJoinedAt'] != joined_owner or data['requesterJoinedAt'] != joined_peer):
                    fail(409, 'Command grant context changed')
                now = self.now(conn)
                if data['consent'] and (not self.live(access, now) or not self.live(member, now) or member['joinedAt'] != joined_peer):
                    fail(403, 'Separate current device and requester permissions required')
                if data['consent'] and any(x not in access.get('actions',[]) or x not in member.get('actions',[]) for x in actions):
                    fail(403,'Action must be separately permitted by both parties')
                value.update(revision=value['revision']+1, consent=data['consent'], actions=actions, deviceRevision=access['revision'],
                    participationRevision=member['revision'], ownerJoinedAt=joined_owner, requesterJoinedAt=joined_peer,
                    expiresAt=iso(min(item for item in (room_expiry, self.device(conn, owner, device), instant(access['expiresAt']) if access['expiresAt'] else now,
                        instant(member['expiresAt']) if member['expiresAt'] else now, now+dt.timedelta(hours=data['expiresInHours'])) if item is not None)))
                key = room + ':' + device + ':' + peer
                conn.execute('INSERT INTO team_device_command_grants(room_id,device_id,requester_id,owner_id,protected) VALUES(%s,%s,%s,%s,%s) '
                    'ON CONFLICT(room_id,device_id,requester_id) DO UPDATE SET protected=excluded.protected',
                    (room, device, peer, owner, self.protect('grant', key, value)))
                self.revoke_rows(conn, 'room_id=%s AND device_id=%s AND requester_id=%s', (room, device, peer), 'grant-changed')
                self.notify(conn, owner, peer)
            return public_context(dict(roomId=room, deviceId=device, requesterId=peer, **value), selector)

        @router.delete(prefix + '/device-command-grants/{device}/{peer}')
        def delete_grant(room: str, device: str, peer: str, request: Request):
            selector = room
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor = self.browser(conn, request, True);room = room_context(conn, selector, actor['id'], withdrawing=True)
                row = conn.execute('SELECT owner_id,protected FROM team_device_command_grants WHERE room_id=%s AND device_id=%s '
                    'AND requester_id=%s FOR UPDATE', (room, device, peer)).fetchone()
                if not row or row[0] != actor['id']:fail()
                key=room+':'+device+':'+peer;value=self.restore('grant',key,row[1]);value.update(consent=False,revision=value['revision']+1)
                conn.execute('UPDATE team_device_command_grants SET protected=%s WHERE room_id=%s AND device_id=%s AND requester_id=%s',
                    (self.protect('grant',key,value),room,device,peer))
                self.revoke_rows(conn,'room_id=%s AND device_id=%s AND requester_id=%s',(room,device,peer),'grant-withdrawn');self.invalidate_receiver(conn,device);self.notify(conn,actor['id'],peer)
            return dict(status='withdrawn',revision=value['revision'])

        @router.post(prefix + '/device-requests',status_code=201)
        async def create(room: str, request: Request):
            selector = room
            data=await body(request,('eventId','targetDeviceId','grantRevision','capabilityId','capabilityRevision','arguments','expiresInSeconds'))
            event(data['eventId']);revision(data['grantRevision']);revision(data['capabilityRevision'])
            if (not isinstance(data['targetDeviceId'],str) or not ID.fullmatch(data['targetDeviceId']) or not isinstance(data['capabilityId'],str)
                or len(data['capabilityId'])>80 or not isinstance(data['arguments'],dict) or type(data['expiresInSeconds']) is not int or not 5<=data['expiresInSeconds']<=300):
                fail(400,'Invalid device request')
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor=self.browser(conn,request,True);room=room_context(conn,selector,actor['id']);owner,grant=self.grant(conn,room,data['targetDeviceId'],actor['id'])
                if owner is None:fail(403,'Explicit target owner grant required')
                context,expiry=self.context(conn,room,data['targetDeviceId'],actor['id'],owner,trip_context=trip_context)
                if grant['revision']!=data['grantRevision']:fail(409,'Command grant changed')
                action=self.registry.lookup(data['capabilityId'],data['capabilityRevision'])
                if action is None:fail(503,'No validated execution adapter is available')
                if not action.validate_arguments(data['arguments']):fail(400,'Invalid registered action arguments')
                self.context(conn,room,data['targetDeviceId'],actor['id'],owner,action=dict(id=data['capabilityId'],revision=data['capabilityRevision']),trip_context=trip_context)
                origin=dict(deviceId=actor['deviceId'],grantId=actor['grantId'],functionalRevision=request.state.functional_snapshot['revision'])if is_native_principal(actor)else None
                digest=self.digest('request-body',[room,data,origin]if origin else[room,data])
                event_hash=self.digest('request-event',[actor['id'],origin['deviceId'],origin['grantId'],data['eventId']]if origin else[actor['id'],data['eventId']])
                old=conn.execute('SELECT request_id,protected FROM team_device_commands WHERE requester_id=%s AND event_hash=%s FOR UPDATE',(actor['id'],event_hash)).fetchone()
                if old:
                    value=self.load_request(conn,old[0])
                    if value['roomId']!=room or value['bodyHash']!=digest:fail(409,'Event identifier was already used with another body')
                    return public_context(self.public(old[0],value), selector)
                if conn.execute('SELECT count(*) FROM team_device_commands WHERE requester_id=%s',(actor['id'],)).fetchone()[0]>=1000:fail(409,'Manage existing device requests first')
                now=self.now(conn);identifier=secrets.token_hex(16)
                value=dict(roomId=room,targetDeviceId=data['targetDeviceId'],requesterId=actor['id'],ownerId=owner,
                    capabilityId=data['capabilityId'],capabilityRevision=data['capabilityRevision'],arguments=data['arguments'],bodyHash=digest,
                    context=context,createdAt=iso(now),expiresAt=iso(min(expiry,now+dt.timedelta(seconds=data['expiresInSeconds']))),
                    stage='queued',lastAcknowledgedStage=None,mayHaveExecuted=False,reason=None,leaseHash=None,leaseExpiresAt=None,
                    claimIdHash=None,leaseId=None,acks={})
                if origin is not None:value['nativeOrigin']=origin
                conn.execute('INSERT INTO team_device_commands(request_id,room_id,device_id,requester_id,owner_id,event_hash,protected) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                    (identifier,room,data['targetDeviceId'],actor['id'],owner,event_hash,self.protect('request',identifier,value)))
                self.notify_progress(conn,actor['id'],owner)
                return public_context(self.public(identifier,value), selector)

        @router.get(prefix + '/device-requests')
        def listing(room: str, request: Request):
            selector = room
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor=self.browser(conn,request);room=room_context(conn,selector,actor['id']);self.membership(conn,room,actor['id'],trip_context=trip_context);items=[]
                for key, in conn.execute('SELECT request_id FROM team_device_commands WHERE room_id=%s AND (requester_id=%s OR owner_id=%s) '
                        'ORDER BY created_at DESC LIMIT 100',(room,actor['id'],actor['id'])):
                    value=self.load_request(conn,key)
                    try:self.context(conn,room,value['targetDeviceId'],value['requesterId'],value['ownerId'],expected=value['context'],action=dict(id=value['capabilityId'],revision=value['capabilityRevision']),trip_context=trip_context)
                    except HTTPException:continue
                    items.append(self.public(key,value))
                return public_context(dict(roomId=room,requests=items,serverNow=self.now(conn),supportedControlActions=self.display_actions()), selector)

        @router.delete(prefix + '/device-requests/{identifier}')
        def cancel(room: str, identifier: str, request: Request):
            selector = room
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor=self.browser(conn,request,True);room=room_context(conn,selector,actor['id'],withdrawing=True);value=self.load_request(conn,identifier)
                if value['roomId']!=room or actor['id'] not in (value['requesterId'],value['ownerId']):fail()
                self.terminalize(value,'explicit-cancellation');self.save_request(conn,identifier,value);self.invalidate_receiver(conn,value['targetDeviceId']);self.notify(conn,value['ownerId'],value['requesterId'])
                return dict(id=identifier,stage=value['stage'],mayHaveExecuted=value['mayHaveExecuted'],physicalExecutionVerified=False)

        @router.get('/v1/device/command-inbox')
        def inbox(request: Request, response: Response, view: Literal['active', 'status']=Query('active',
                description='status는 현재 여행 허용 범위의 종료된 요청도 포함합니다. active는 미종료 요청만 반환합니다.')):
            response.headers['Cache-Control'] = 'private, no-store'
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor=self.native(conn,request);items=[]
                for key, in conn.execute('SELECT request_id FROM (SELECT request_id,created_at FROM team_device_commands WHERE device_id=%s AND owner_id=%s UNION ALL SELECT request_id,created_at FROM friend_vehicle_commands WHERE device_id=%s AND owner_id=%s) requests ORDER BY created_at DESC,request_id DESC LIMIT 100',
                        (actor['deviceId'],actor['id'],actor['deviceId'],actor['id'])):
                    value=self.load_request(conn,key)
                    if value['stage'] not in STAGES[:-1] and (view!='status' or value['roomId'] is not None):continue
                    try:self.context(conn,value['roomId'],actor['deviceId'],value['requesterId'],actor['id'],expected=value['context'],action=dict(id=value['capabilityId'],revision=value['capabilityRevision']),trip_context=True)
                    except HTTPException:continue
                    items.append(self.public(key,value))
                return dict(requests=items,supportedControlActions=self.display_actions(),serverNow=self.now(conn))

        @router.post('/v1/device/requests/{identifier}/claim')
        async def claim(identifier: str, request: Request):
            data=await body(request,('claimId',));event(data['claimId'])
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor=self.native(conn,request);value=self.load_request(conn,identifier)
                if value['targetDeviceId']!=actor['deviceId'] or value['ownerId']!=actor['id']:fail()
                self.context(conn,value['roomId'],actor['deviceId'],value['requesterId'],actor['id'],expected=value['context'],action=dict(id=value['capabilityId'],revision=value['capabilityRevision']),trip_context=True)
                if self.registry.lookup(value['capabilityId'],value['capabilityRevision']) is None:fail(503,'Registered adapter unavailable')
                claim_hash=self.digest('claim',[actor['deviceId'],data['claimId']]);now=self.now(conn)
                if value['claimIdHash'] is not None:
                    if value['leaseExpiresAt'] is None or instant(value['leaseExpiresAt'])<=now or value['leaseHash'] is None:fail(410,'Command lease expired')
                    if value['claimIdHash']!=claim_hash:fail(409,'Request has already been claimed')
                else:
                    if value['stage']!='queued':fail(409,'Request is not deliverable')
                    lease=secrets.token_urlsafe(32);value.update(stage='delivered',mayHaveExecuted=True,claimIdHash=claim_hash,leaseId=lease,
                        leaseHash=self.digest('lease',lease),leaseExpiresAt=iso(min(instant(value['expiresAt']),now+dt.timedelta(seconds=30))))
                    self.save_request(conn,identifier,value);self.notify_request_progress(conn,value)
                return dict(self.public(identifier,value,payload=True),leaseId=value['leaseId'],leaseExpiresAt=value['leaseExpiresAt'],serverNow=iso(self.now(conn)))

        @router.post('/v1/device/requests/{identifier}/ack')
        async def ack(identifier: str, request: Request):
            data=await body(request,('ackId','leaseId','stage','evidence'));event(data['ackId'])
            if not isinstance(data['leaseId'],str) or len(data['leaseId'])>100 or data['stage'] not in STAGES[2:]+('rejected','unknown') or not isinstance(data['evidence'],dict):fail(400,'Invalid command acknowledgement')
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn);actor=self.native(conn,request);value=self.load_request(conn,identifier)
                if value['targetDeviceId']!=actor['deviceId'] or value['ownerId']!=actor['id']:fail()
                self.context(conn,value['roomId'],actor['deviceId'],value['requesterId'],actor['id'],expected=value['context'],action=dict(id=value['capabilityId'],revision=value['capabilityRevision']),trip_context=True)
                action=self.registry.lookup(value['capabilityId'],value['capabilityRevision'])
                if action is None:fail(503,'Registered adapter unavailable')
                if value['leaseHash'] is None or not hmac.compare_digest(value['leaseHash'],self.digest('lease',data['leaseId'])):fail(409,'Command lease mismatch')
                if instant(value['leaseExpiresAt'])<=self.now(conn):self.terminalize(value,'lease-expired');self.save_request(conn,identifier,value);fail(410,'Command lease expired')
                key=self.digest('ack-id',data['ackId']);digest=self.digest('ack-body',data)
                if key in value['acks']:
                    if value['acks'][key]!=digest:fail(409,'Acknowledgement identifier reused with another body')
                    return self.public(identifier,value)
                stage=data['stage'];current=value['stage']
                if current in TERMINAL or (stage in STAGES and STAGES.index(stage)!=STAGES.index(current)+1):fail(409,'Invalid acknowledgement transition')
                if not action.validate_ack(stage,data['evidence'],dict(requestId=identifier,leaseHash=value['leaseHash'],createdAt=value['createdAt'],arguments=value['arguments'])):fail(400,'Registered acknowledgement evidence is required')
                if len(value['acks'])>=8:fail(409,'Acknowledgement limit reached')
                value['acks'][key]=digest;value.update(stage=stage,lastAcknowledgedStage=stage)
                if stage=='rejected':value['reason']=data['evidence'].get('reason')
                self.save_request(conn,identifier,value);self.notify_request_progress(conn,value)
                return self.public(identifier,value)

        if trip_context:
            router.routes[:] = [route for route in router.routes if route.path.startswith('/v1/social/trips/')]
        return router
