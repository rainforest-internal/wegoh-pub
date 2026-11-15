"""Explicit Native report writes and bilateral room delivery. No vehicle control."""
from course_publication import COURSE_AVAILABLE, available
import hashlib
import json
import math
import re
import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import VisitCipher, PrivateRecordError
from team_data import changed
from team_friends import blocked, linked
from native_principal import is_native_principal
from native_functional_identity import resolve_current_device,revalidate_native,business_json
from native_functional_policy import FunctionalError

KINDS = ('location', 'visits')
HOURS = (1, 4, 12, 24)
ID = re.compile(r'[a-f0-9]{32}')


def fail(status=404, message='Report unavailable'):
    raise HTTPException(status, message)


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail(400, 'Invalid report identifier')
    return value


def integer(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        fail(400, 'Invalid report revision')
    return value


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        fail(400, 'Report time requires a timezone')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except ValueError:
        fail(400, 'Report time requires a timezone')


class TeamVehicle:
    def __init__(self, auth, rooms):
        self.auth, self.rooms, self.dsn = auth, rooms, auth.dsn
        self.enabled = auth.enabled and rooms.enabled
        auth.vehicle_service = self

    @staticmethod
    def protect(kind, account, key, value):
        return VisitCipher().protect('team-vehicle:' + kind + ':' + account, key, value)

    @staticmethod
    def restore(kind, account, key, raw):
        return VisitCipher().restore('team-vehicle:' + kind + ':' + account, key, raw)

    @staticmethod
    def now(conn):
        return conn.execute('SELECT clock_timestamp()').fetchone()[0]

    def member(self, conn, room, account, *, trip_context=False):
        access = self.rooms.access(conn, room, account, trip_context=trip_context)
        row = conn.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s '
                           'AND account_id=%s AND left_at IS NULL', (room, account)).fetchone()
        if not row or (access['expiresAt'] is not None and access['expiresAt'] <= self.now(conn)):
            fail()
        return access, row[0].isoformat()

    def purposes(self, conn, account, device, lock=False):
        # The typed current grant is the sole device authority. The old purpose
        # table is historical encrypted data, never a second consent source.
        try:
            self.auth.functional_access.require_enabled()
            current=resolve_current_device(self.auth,conn,account,identifier(device))
        except FunctionalError as error:fail(error.status,error.code)
        return current,dict(location='vehicle-location:report' in current.approved_purposes,
            visits='vehicle-visits:report' in current.approved_purposes),current.functional_revision,current.expires_at

    def room_grants(self, conn, room, account, lock=False, *, trip_context=False):
        access, joined = self.member(conn, room, account, trip_context=trip_context)
        row = conn.execute('SELECT protected,revision,expires_at FROM team_vehicle_room_grants '
                           'WHERE room_id=%s AND account_id=%s' + (' FOR UPDATE' if lock else ''),
                           (room, account)).fetchone()
        empty = dict(joinedAt=joined, receiveLocation=False, receiveVisits=False, webExpiresAt=None, receiverDeviceId=None, devices={})
        if not row:
            return access, empty, 0, None
        value = self.restore('room-grant', account, room, row[0])
        if (set(value) != set(empty) or type(value['receiveLocation']) is not bool
                or type(value['receiveVisits']) is not bool or not isinstance(value['devices'], dict)
                or len(value['devices']) > 100):
            raise PrivateRecordError('Room report grant integrity failed')
        if row[2] <= self.now(conn) or value['joinedAt'] != joined:
            value = empty
        return access, value, row[1], row[2]

    def store_room(self, conn, room, account, value, expiry):
        row = conn.execute('INSERT INTO team_vehicle_room_grants(room_id,account_id,protected,expires_at) '
            'VALUES(%s,%s,%s,%s) ON CONFLICT(room_id,account_id) DO UPDATE SET protected=excluded.protected,'
            'expires_at=excluded.expires_at,revision=team_vehicle_room_grants.revision+1 RETURNING revision',
            (room, account, self.protect('room-grant', account, room, value), expiry)).fetchone()
        self.rooms.notify(conn, room)
        changed(conn, account, 'vehicle')
        return row[0]

    def withdraw_room(self, conn, room, account=None):
        # Called under the existing membership graph lock, including block/leave.
        query = 'SELECT account_id,protected,expires_at FROM team_vehicle_room_grants WHERE room_id=%s'
        args = [room]
        if account is not None:
            query += ' AND account_id=%s'
            args.append(account)
        for owner, raw, expiry in conn.execute(query + ' FOR UPDATE', args).fetchall():
            value = self.restore('room-grant', owner, room, raw)
            value.update(receiveLocation=False, receiveVisits=False, webExpiresAt=None, receiverDeviceId=None, devices={})
            if value != self.restore('room-grant', owner, room, raw):
                self.store_room(conn, room, owner, value, expiry)
        query = 'DELETE FROM team_vehicle_latest_reports WHERE room_id=%s'
        if account is not None:
            query += ' AND account_id=%s'
        conn.execute(query, args)

    def reset_trip_location_reports(self, conn, room, account):
        conn.execute("DELETE FROM team_vehicle_latest_reports WHERE room_id=%s AND account_id=%s AND kind='location'",
                     (room, account))
        conn.execute('UPDATE team_vehicle_room_grants SET revision=revision+1 WHERE room_id=%s AND account_id=%s',
                     (room, account))

    def withdraw_trip_context(self, conn, trip, room, account=None):
        from team_trip_locations import clear_trip_locations
        clear_trip_locations(conn, trip, account)
        self.withdraw_room(conn, room, account)
        content = getattr(self.auth, 'content_service', None)
        if content:content.withdraw_trip_context(conn, trip, room, account)

    def friendship_changed(self, conn, a, b):
        # Existing friend mutations already hold the same membership graph lock.
        rooms = conn.execute('SELECT x.room_id FROM team_room_members x JOIN team_room_members y USING(room_id) '
            'JOIN team_rooms r USING(room_id) WHERE r.trip_id IS NULL '
            'AND x.account_id=%s AND y.account_id=%s AND x.left_at IS NULL AND y.left_at IS NULL', (a, b)).fetchall()
        for (room,) in rooms:
            self.rooms.notify(conn, room)
        changed(conn, a, 'vehicle')
        changed(conn, b, 'vehicle')

    def lock_device_change(self, conn):
        self.rooms.graph_lock(conn)

    def withdraw_device(self, conn, account, device):
        # Device revocation takes graph lock before the existing device UPDATE.
        rooms = [x[0] for x in conn.execute('SELECT DISTINCT room_id FROM team_vehicle_latest_reports '
                                          'WHERE device_id=%s AND account_id=%s', (device, account))]
        conn.execute('DELETE FROM team_vehicle_latest_reports WHERE device_id=%s AND account_id=%s', (device, account))
        for room in rooms:
            self.rooms.notify(conn, room)
        changed(conn, account, 'vehicle')

    def update_purposes(self, conn, account, device, data, revoke=None):
        self.rooms.graph_lock(conn)
        self.purposes(conn,account,device,True) # Exact current owner/slot, no legacy fallback.
        fail(409,'Use current functional permissions')

    @staticmethod
    def may_send(access, kind):
        if kind == 'location' and access.get('tripId'):
            return access['tripLocationConsent']
        return access['consents']['status'] and access['consents']['location']

    def update_room(self, conn, room, account, data, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access, value, revision, previous_expiry = self.room_grants(conn, room, account, True, trip_context=trip_context)
        device = identifier(data['deviceId'])
        native, purposes, device_revision, device_expiry = self.purposes(conn, account, device, True)
        flags = ('shareLocation', 'shareVisits', 'receiveLocation', 'receiveVisits')
        if any(type(data[k]) is not bool for k in flags):
            fail(400, 'Choose each room report purpose')
        integer(data['revision'])
        timestamp(data['joinedAt'])
        permitting = any(data[k] for k in flags)
        if permitting and (integer(data['revision']) != revision or data['joinedAt'] != value['joinedAt']):
            fail(409, 'Room membership or report purposes changed')
        integer(data['devicePermissionRevision'])
        if (data['shareLocation'] or data['shareVisits']) and data['devicePermissionRevision'] != device_revision:
            fail(409, 'Device report purposes changed')
        for kind, fields in (('location', ('shareLocation',)), ('visits', ('shareVisits', 'receiveVisits'))):
            if any(data[field] for field in fields) and not self.may_send(access, kind):
                fail(403, 'Current sharing consent required')
        if data['receiveLocation'] and not trip_context and not self.may_send(access, 'location'):
            fail(403, 'Current sharing consent required')
        if data['shareLocation'] and not purposes['location'] or data['shareVisits'] and not purposes['visits']:
            fail(403, 'Explicit device reporting required')
        if type(data['expiresInHours']) is not int or data['expiresInHours'] not in HOURS:
            fail(400, 'Choose a room report period')
        old = value['devices'].get(device, {})
        flags_changed = any(old.get(k, False) != data[k] for k in ('shareLocation', 'shareVisits'))
        nonce = secrets.token_hex(16) if flags_changed or old.get('permissionRevision') != device_revision else old.get('nonce')
        expiry = min(value for value in (access['expiresAt'], native.expires_at, self.now(conn) + timedelta(hours=data['expiresInHours'])) if value is not None)
        value['devices'][device] = dict(shareLocation=data['shareLocation'], shareVisits=data['shareVisits'],
            permissionRevision=device_revision, nonce=nonce, receiveLocation=data['receiveLocation'],
            receiveVisits=data['receiveVisits'], expiresAt=expiry.isoformat())
        value['receiverDeviceId'] = device if data['receiveLocation'] or data['receiveVisits'] else None
        self.store_room(conn, room, account, value, max(expiry, previous_expiry or expiry))

    def receiving_snapshot(self, conn, room, account, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access, value, revision, _ = self.room_grants(conn, room, account, trip_context=trip_context)
        live = (bool(value.get('webExpiresAt')) and timestamp(value['webExpiresAt']) > self.now(conn)
                and access['consents']['status'] and access['consents']['location'])
        return dict(roomId=room, revision=revision, joinedAt=value['joinedAt'],
            expiresAt=value.get('webExpiresAt'), serverNow=self.now(conn),
            receiveLocation=bool(live and value['receiveLocation']), receiveVisits=bool(live and value['receiveVisits']))

    def update_receiving(self, conn, room, account, data=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access, value, revision, previous_expiry = self.room_grants(conn, room, account, True, trip_context=trip_context)
        if data is None:
            value.update(receiveLocation=False, receiveVisits=False, webExpiresAt=None)
            expiry = previous_expiry or self.now(conn)
        else:
            integer(data['revision']);timestamp(data['joinedAt'])
            if any(type(data[key]) is not bool for key in ('receiveLocation', 'receiveVisits')):
                fail(400, 'Choose each browser receiving purpose')
            permitting = data['receiveLocation'] or data['receiveVisits']
            if permitting and (data['revision'] != revision or data['joinedAt'] != value['joinedAt']):
                fail(409, 'Room membership or receiving purposes changed')
            if permitting and (not access['consents']['status'] or not access['consents']['location']):
                fail(403, 'Current room status and location consent required')
            if type(data['expiresInHours']) is not int or data['expiresInHours'] not in HOURS:
                fail(400, 'Choose a browser receiving period')
            web_expiry = min(value for value in (access['expiresAt'], self.now(conn) + timedelta(hours=data['expiresInHours'])) if value is not None)
            value.update(receiveLocation=data['receiveLocation'], receiveVisits=data['receiveVisits'], webExpiresAt=web_expiry.isoformat())
            expiry = max(web_expiry, previous_expiry or web_expiry)
        # Browser-only receiving never looks up/creates a device or changes its purposes/grant.
        self.store_room(conn, room, account, value, expiry)
        return self.receiving_snapshot(conn, room, account, trip_context=trip_context)

    def sender(self, conn, room, account, device, kind, *, trip_context=False):
        native, purposes, revision, expiry = self.purposes(conn, account, device, True)
        access, grants, room_revision, room_expiry = self.room_grants(conn, room, account, True, trip_context=trip_context)
        if access.get('tripId') and access['state'] != 'active':
            fail(409, 'TRIP_STATE_CONFLICT')
        grant = grants['devices'].get(device, {})
        key = 'shareLocation' if kind == 'location' else 'shareVisits'
        if (not purposes[kind] or not grant.get(key)
                or not grant.get('expiresAt') or timestamp(grant['expiresAt']) <= self.now(conn)
                or not self.may_send(access, kind)):
            fail(403, 'Explicit current room reporting required')
        return native, access, grants, grant, revision, room_revision

    def latest(self, conn, room, account, device, kind, *, trip_context=False):
        try:
            _, access, grants, grant, revision, _ = self.sender(conn, room, account, device, kind, trip_context=trip_context)
        except HTTPException as error:
            if error.status_code in (403, 404, 409):
                return None
            raise
        row = conn.execute('SELECT protected,received_at FROM team_vehicle_latest_reports '
            'WHERE room_id=%s AND device_id=%s AND account_id=%s AND kind=%s', (room, device, account, kind)).fetchone()
        if not row:
            return None
        value = self.restore('latest', account, room + ':' + device + ':' + kind, row[0])
        if value['roomJoinedAt'] != grants['joinedAt'] or value['grantNonce'] != grant['nonce']:
            return None
        if kind == 'visits':
            report = value['report']
            if not access['course'] or (report['courseId'], report['courseVersion']) != (access['courseId'], access['courseVersion']):
                return None
            approved = conn.execute("SELECT p.checksum FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) "
                f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE} FOR SHARE OF p",
                (report['courseId'], report['courseVersion'])).fetchone()
            if not approved or approved[0] != report['checksum'] or not available(conn, approved[0], lock=True):
                return None
        captured = timestamp(value['capturedAt'])
        age = (self.now(conn) - captured).total_seconds()
        return dict(value['report'], eventId=value['eventId'], capturedAt=value['capturedAt'], receivedAt=row[1],
                    stale=age > 60, source='device-reported' if kind == 'location' else 'user-confirmed',
                    accuracyVerified=False, physicalArrivalVerified=False)

    def snapshot(self, conn, account, device, room=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        native, purposes, revision, expiry = self.purposes(conn, account, device)
        result = dict(authorizationVersion=1,authority='native-functional',functionalRevision=revision,
            deviceId=device, name=native.name, revision=revision, expiresAt=native.expires_at,
            serverNow=self.now(conn), reporting=purposes, reportingExpiresAt=expiry,
            roomReporting=None, latestLocation=None, latestVisit=None, supportedControlActions=[], requests=[])
        if room:
            access, grants, room_revision, room_expiry = self.room_grants(conn, room, account, trip_context=trip_context)
            grant = grants['devices'].get(device, {})
            active = (bool(grant.get('expiresAt'))
                      and timestamp(grant['expiresAt']) > self.now(conn))
            result['roomReporting'] = dict(roomId=room, deviceId=device, revision=room_revision,
                joinedAt=grants['joinedAt'], expiresAt=grant.get('expiresAt'), receiverDeviceId=grants['receiverDeviceId'],
                shareLocation=active and purposes['location'] and self.may_send(access, 'location') and bool(grant.get('shareLocation')),
                shareVisits=active and purposes['visits'] and bool(grant.get('shareVisits')),
                receiveLocation='vehicle-reports:read' in native.approved_purposes and bool(grant.get('expiresAt')) and timestamp(grant['expiresAt']) > self.now(conn) and grants['receiverDeviceId'] == device and bool(grant.get('receiveLocation')),
                receiveVisits='vehicle-reports:read' in native.approved_purposes and bool(grant.get('expiresAt')) and timestamp(grant['expiresAt']) > self.now(conn) and grants['receiverDeviceId'] == device and bool(grant.get('receiveVisits')))
            result['latestLocation'] = self.latest(conn, room, account, device, 'location', trip_context=trip_context)
            result['latestVisit'] = self.latest(conn, room, account, device, 'visits', trip_context=trip_context)
        return result

    def reports(self, conn, room, viewer, device=None, *, trip_context=False, allow_visits=True):
        self.rooms.graph_lock(conn)
        access, grants, _, _ = self.room_grants(conn, room, viewer, trip_context=trip_context)
        if access.get('tripId') and access['state'] != 'active':
            fail(409, 'TRIP_STATE_CONFLICT')
        result = []
        if device:
            own = grants['devices'].get(device, {}) if grants['receiverDeviceId'] == device else {}
            live = bool(own.get('expiresAt')) and timestamp(own['expiresAt']) > self.now(conn)
            grants = dict(grants, receiveLocation=live and bool(own.get('receiveLocation')),
                          receiveVisits=live and bool(own.get('receiveVisits')))
        elif not grants.get('webExpiresAt') or timestamp(grants['webExpiresAt']) <= self.now(conn):
            grants = dict(grants, receiveLocation=False, receiveVisits=False)
        room_consent = access['consents']['status'] and access['consents']['location']
        receive_locations = trip_context or (room_consent and grants['receiveLocation'])
        receive_visits = allow_visits and room_consent and grants['receiveVisits']
        if receive_locations or receive_visits:
            for account, peer in self.rooms.active_members(conn, room).items():
                if account == viewer or blocked(conn, viewer, account):
                    continue
                friend = linked(conn, viewer, account) if receive_visits or not trip_context else False
                read_location = receive_locations and (trip_context or friend)
                read_visit = receive_visits and friend
                if not read_location and not read_visit:
                    continue
                for (source_device,) in conn.execute("SELECT g.device_id FROM native_v2_grants g JOIN native_v2_installations i USING(installation_key_id) JOIN native_device_refs r ON r.device_id=g.device_id AND r.kind='native' WHERE g.account_id=%s AND g.state='TOKEN_ISSUED' AND i.active_grant_id=g.grant_id AND i.revoked_at IS NULL AND g.expires_at>%s ORDER BY g.device_id LIMIT 100",(account,self.auth.functional_access.base.now())):
                    location = self.latest(conn, room, account, source_device, 'location', trip_context=trip_context) if read_location else None
                    if trip_context and location and location['stale']:
                        location = None
                    visit = self.latest(conn, room, account, source_device, 'visits', trip_context=trip_context) if read_visit else None
                    if location or visit:
                        result.append(dict(accountId=account, name=peer['name'], deviceId=source_device, location=location, visit=visit))
        return dict(roomId=room, serverNow=self.now(conn), reports=result)

    def current_native(self, conn, actor, credential, rooms_read=False, loaded=None):
        request=credential.get('request')
        if not is_native_principal(actor) or request is None:fail(401,'INVALID_CREDENTIAL')
        try:
            current,snapshot=revalidate_native(self.auth,request,conn,functional_revision=getattr(request.state,'functional_revision',None))
        except FunctionalError as error:fail(error.status,error.code)
        if (current['grantId'],current['deviceId'],current['id'])!=(actor['grantId'],actor['deviceId'],actor['id']):fail(401,'INVALID_CREDENTIAL')
        request.state.functional_snapshot=snapshot

    def ingest(self, conn, room, actor, credential, kind, data, *, trip_context=False):
        self.rooms.graph_lock(conn)
        account, device = actor['id'], actor['deviceId']
        native, access, grants, grant, revision, room_revision = self.sender(conn, room, account, device, kind, trip_context=trip_context)
        self.current_native(conn, actor, credential, loaded=native)
        if integer(data['devicePermissionRevision']) != revision or integer(data['roomRevision']) != room_revision:
            fail(409, 'Report purposes changed')
        event = identifier(data['eventId'])
        captured = timestamp(data['capturedAt'])
        if kind == 'location':
            for key, low, high in [('latitude', -90, 90), ('longitude', -180, 180)]:
                v = data[key]
                if type(v) not in (int, float) or not low <= v <= high or not math.isfinite(v):
                    fail(400, 'Invalid report coordinates')
            accuracy = data['accuracyMeters']
            if accuracy is not None and (type(accuracy) not in (int, float) or not 0 <= accuracy <= 10000 or not math.isfinite(accuracy)):
                fail(400, 'Invalid reported accuracy')
            report = {k: data[k] for k in ('latitude', 'longitude', 'accuracyMeters')}
        else:
            if (not isinstance(data['courseId'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', data['courseId'])
                    or type(data['courseVersion']) is not int or not 1 <= data['courseVersion'] <= 2147483647):
                fail(400, 'Invalid course version')
            if not access['course'] or (data['courseId'], data['courseVersion']) != (access['courseId'], access['courseVersion']):
                fail(409, 'Current room course required')
            course = conn.execute("SELECT p.checksum,p.stop_count FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) "
                f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE} FOR SHARE OF p",
                (data['courseId'], data['courseVersion'])).fetchone()
            if not course or not available(conn, course[0], lock=True) or type(data['checkpoint']) is not int or not 1 <= data['checkpoint'] <= course[1]:
                fail(400, 'Invalid course checkpoint')
            report = dict(courseId=data['courseId'], courseVersion=data['courseVersion'], checkpoint=data['checkpoint'], checksum=course[0])
        digest = hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        receipt = conn.execute('SELECT protected,received_at FROM team_vehicle_report_receipts WHERE device_id=%s AND event_id=%s',
                               (device, event)).fetchone()
        if receipt:
            old = self.restore('receipt', account, device + ':' + event, receipt[0])
            if old != dict(roomId=room, kind=kind, digest=digest, nonce=grant['nonce']):
                fail(409, 'Report event already used')
            latest = self.latest(conn, room, account, device, kind, trip_context=trip_context)
            return dict(eventId=event,status='duplicate',receivedAt=receipt[1],latest=bool(latest and latest['eventId']==event))
        now = self.now(conn)
        if not -30 <= (now - captured).total_seconds() <= 300:
            fail(400, 'Report capture time is outside the allowed window')
        latest = self.latest(conn, room, account, device, kind, trip_context=trip_context)
        if latest and captured <= timestamp(latest['capturedAt']):
            fail(409, 'An equal or newer report is already stored')
        value = dict(eventId=event,capturedAt=data['capturedAt'],roomJoinedAt=grants['joinedAt'],
                     grantNonce=grant['nonce'],devicePermissionRevision=revision,report=report)
        conn.execute('INSERT INTO team_vehicle_latest_reports(room_id,device_id,kind,account_id,protected,received_at) '
            'VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(room_id,device_id,kind) DO UPDATE SET protected=excluded.protected,received_at=excluded.received_at',
            (room,device,kind,account,self.protect('latest',account,room+':'+device+':'+kind,value),now))
        conn.execute('INSERT INTO team_vehicle_report_receipts(device_id,event_id,account_id,protected,received_at) VALUES(%s,%s,%s,%s,%s)',
            (device,event,account,self.protect('receipt',account,device+':'+event,dict(roomId=room,kind=kind,digest=digest,nonce=grant['nonce'])),now))
        self.rooms.notify(conn,room)
        changed(conn,account,'vehicle')
        return dict(eventId=event,status='accepted',receivedAt=now,latest=True)


    def visible_to_device(self, actor):
        with psycopg.connect(self.dsn) as conn:
            self.rooms.graph_lock(conn)
            _, purposes, _, _ = self.purposes(conn, actor['id'], actor['deviceId'])
            if any(purposes.values()):
                return True
            for (room,) in conn.execute('SELECT room_id FROM team_vehicle_room_grants WHERE account_id=%s AND expires_at>now()', (actor['id'],)):
                try:
                    access, grants, _, _ = self.room_grants(conn, room, actor['id'], trip_context=True)
                except HTTPException as error:
                    if error.status_code in (403, 404, 409):
                        continue
                    raise
                own = grants['devices'].get(actor['deviceId'], {}) if grants['receiverDeviceId'] == actor['deviceId'] else {}
                if (access['consents']['status'] and access['consents']['location']
                        and own.get('expiresAt') and timestamp(own['expiresAt']) > self.now(conn)
                        and any(own.get(key) for key in ('receiveLocation', 'receiveVisits'))):
                    return True
        return False

    @staticmethod
    def trip_result(value, trip):
        result = dict(value)
        result.pop('roomId', None)
        result['tripId'] = trip
        if 'roomReporting' in result:
            reporting = result.pop('roomReporting')
            result['tripReporting'] = None if reporting is None else dict(
                (key, item) for key, item in reporting.items() if key != 'roomId')
        return result

    def trip_router(self):
        from team_device_commands import body, trip_withdrawal_room
        from team_trip_context import resolve_trip_context
        router = APIRouter()
        if not self.enabled:
            return router

        def browser(conn, request, mutate=False):
            if getattr(request.state, 'device_identity', None):fail()
            self.rooms.graph_lock(conn)
            return self.auth.browser(request, mutate=mutate, connection=conn)['id']

        def native(conn, request):
            actor = self.auth.device(request)
            self.rooms.graph_lock(conn)
            self.current_native(conn, actor, dict(request=request), rooms_read=True)
            return actor

        @router.get('/v1/devices/{device}/trips/{trip}/vehicle-domain')
        def snapshot(trip: str, device: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                account = browser(conn, request)
                context = resolve_trip_context(self.auth, conn, trip, account)
                result = self.snapshot(conn, account, device, context['roomId'], trip_context=True)
            response.headers['Cache-Control'] = 'private, no-store'
            return self.trip_result(result, trip)

        @router.get('/v1/native/trips/{trip}/vehicle-domain')
        def native_snapshot(trip: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                actor = native(conn, request)
                context = resolve_trip_context(self.auth, conn, trip, actor['id'])
                result = self.snapshot(conn, actor['id'], actor['deviceId'], context['roomId'], trip_context=True)
            response.headers['Cache-Control'] = 'private, no-store'
            return self.trip_result(result, trip)

        @router.put('/v1/social/trips/{trip}/device-reporting')
        async def grant(trip: str, request: Request, response: Response):
            data = await body(request, ('deviceId', 'revision', 'joinedAt', 'devicePermissionRevision',
                'shareLocation', 'shareVisits', 'receiveLocation', 'receiveVisits', 'expiresInHours'))
            with psycopg.connect(self.dsn) as conn:
                account = browser(conn, request, True)
                self.auth.rate('room-report-purpose:' + account, limit=30)
                context = resolve_trip_context(self.auth, conn, trip, account)
                self.update_room(conn, context['roomId'], account, data, trip_context=True)
                result = self.snapshot(conn, account, data['deviceId'], context['roomId'], trip_context=True)
            response.headers['Cache-Control'] = 'private, no-store'
            return self.trip_result(result, trip)

        @router.delete('/v1/social/trips/{trip}/device-reporting')
        def withdraw(trip: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                account = browser(conn, request, True)
                room = trip_withdrawal_room(self.auth, conn, trip, account)
                self.withdraw_room(conn, room, account)
            response.headers['Cache-Control'] = 'private, no-store'
            return dict(tripId=trip, status='revoked')

        @router.get('/v1/social/trips/{trip}/report-receiving')
        def receiving(trip: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                account = browser(conn, request)
                context = resolve_trip_context(self.auth, conn, trip, account)
                result = self.receiving_snapshot(conn, context['roomId'], account, trip_context=True)
            response.headers['Cache-Control'] = 'private, no-store'
            return self.trip_result(result, trip)

        @router.put('/v1/social/trips/{trip}/report-receiving')
        async def set_receiving(trip: str, request: Request, response: Response):
            data = await body(request, ('revision', 'joinedAt', 'receiveLocation', 'receiveVisits', 'expiresInHours'))
            with psycopg.connect(self.dsn) as conn:
                account = browser(conn, request, True)
                self.auth.rate('browser-report-receiving:' + account, limit=30)
                context = resolve_trip_context(self.auth, conn, trip, account)
                result = self.update_receiving(conn, context['roomId'], account, data, trip_context=True)
            response.headers['Cache-Control'] = 'private, no-store'
            return self.trip_result(result, trip)

        @router.delete('/v1/social/trips/{trip}/report-receiving')
        def withdraw_receiving(trip: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                account = browser(conn, request, True)
                room = trip_withdrawal_room(self.auth, conn, trip, account)
                row = conn.execute('SELECT protected,expires_at FROM team_vehicle_room_grants '
                    'WHERE room_id=%s AND account_id=%s FOR UPDATE', (room, account)).fetchone()
                if row:
                    value = self.restore('room-grant', account, room, row[0])
                    value.update(receiveLocation=False, receiveVisits=False, webExpiresAt=None)
                    self.store_room(conn, room, account, value, row[1])
            response.headers['Cache-Control'] = 'private, no-store'
            return dict(tripId=trip, status='revoked')

        @router.get('/v1/social/trips/{trip}/device-reports')
        def reports(trip: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                account = browser(conn, request)
                context = resolve_trip_context(self.auth, conn, trip, account, states=('active',))
                result = self.reports(conn, context['roomId'], account, trip_context=True)
            response.headers['Cache-Control'] = 'private, no-store'
            return self.trip_result(result, trip)

        @router.get('/v1/native/trips/{trip}/device-reports')
        def native_reports(trip: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                actor = native(conn, request)
                context = resolve_trip_context(self.auth, conn, trip, actor['id'], states=('active',))
                purposes = request.state.functional_snapshot['approvedPurposes']
                result = self.reports(conn, context['roomId'], actor['id'], actor['deviceId'],
                                      trip_context=True, allow_visits='vehicle-reports:read' in purposes)
            response.headers['Cache-Control'] = 'private, no-store'
            return self.trip_result(result, trip)

        async def report(trip, request, kind):
            common = ('eventId', 'devicePermissionRevision', 'reportingRevision', 'capturedAt')
            extra = ('latitude', 'longitude', 'accuracyMeters') if kind == 'location' else ('courseId', 'courseVersion', 'checkpoint')
            data = await body(request, common + extra)
            data['roomRevision'] = data.pop('reportingRevision')
            with psycopg.connect(self.dsn) as conn:
                actor = native(conn, request)
                self.auth.rate('device-report-write:' + actor['deviceId'], limit=120)
                context = resolve_trip_context(self.auth, conn, trip, actor['id'], states=('active',))
                return self.ingest(conn, context['roomId'], actor, dict(request=request), kind, data, trip_context=True)

        @router.post('/v1/native/trips/{trip}/reports/location')
        async def location(trip: str, request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            return await report(trip, request, 'location')

        @router.post('/v1/native/trips/{trip}/reports/visits')
        async def visits(trip: str, request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            return await report(trip, request, 'visits')

        from team_trip_locations import trip_location_router
        router.include_router(trip_location_router(self.auth))
        return router

    def router(self):
        router = APIRouter()
        if not self.enabled:
            return router

        async def body(request, fields):
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4096:
                    fail(413, 'Report request too large')
            value=business_json(request,raw,maximum=4096)
            if not isinstance(value, dict) or set(value) != set(fields):
                fail(400, 'Invalid report fields')
            return value

        def browser(request, conn, mutate=False):
            if getattr(request.state, 'device_identity', None):
                fail()
            return self.auth.browser(request, mutate=mutate, connection=conn)['id']

        def native(request):
            if not getattr(request.state, 'device_identity', None):
                fail()
            return self.auth.device(request)

        def credential(request):
            return dict(request=request)

        def room_parameter(request):
            if set(request.query_params) - {'roomId'} or len(request.query_params.getlist('roomId')) > 1:
                fail(400, 'Invalid room selection')
            value = request.query_params.get('roomId')
            return identifier(value) if value is not None else None

        @router.get('/v1/devices/{device}/vehicle-domain')
        def device_snapshot(device: str, request: Request, response: Response, roomId: str | None = None):
            with psycopg.connect(self.dsn) as conn:
                who = browser(request, conn)
                result = self.snapshot(conn, who, device, room_parameter(request))
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.put('/v1/devices/{device}/reporting-permissions')
        async def update_purposes(device: str, request: Request, response: Response):
            data = await body(request, ('revision', 'purposes', 'expiresInHours'))
            with psycopg.connect(self.dsn) as conn:
                who = browser(request, conn, True)
                self.auth.rate('device-report-purpose:' + who, limit=30)
                self.update_purposes(conn, who, device, data)
                result = self.snapshot(conn, who, device)
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.delete('/v1/devices/{device}/reporting-permissions/{purpose}')
        def revoke_purpose(device: str, purpose: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                who = browser(request, conn, True)
                self.update_purposes(conn, who, device, {}, revoke=purpose)
                result = self.snapshot(conn, who, device)
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.put('/v1/social/rooms/{room}/device-reporting')
        async def room_grant(room: str, request: Request, response: Response):
            data = await body(request, ('deviceId', 'revision', 'joinedAt', 'devicePermissionRevision',
                'shareLocation', 'shareVisits', 'receiveLocation', 'receiveVisits', 'expiresInHours'))
            with psycopg.connect(self.dsn) as conn:
                who = browser(request, conn, True)
                self.auth.rate('room-report-purpose:' + who, limit=30)
                self.update_room(conn, room, who, data)
                result = self.snapshot(conn, who, data['deviceId'], room)
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.delete('/v1/social/rooms/{room}/device-reporting')
        def revoke_room(room: str, request: Request):
            with psycopg.connect(self.dsn) as conn:
                who = browser(request, conn, True)
                self.rooms.graph_lock(conn)
                self.member(conn, room, who)
                self.withdraw_room(conn, room, who)
            return dict(status='revoked')

        @router.get('/v1/social/rooms/{room}/report-receiving')
        def receiving(room: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                result = self.receiving_snapshot(conn, room, browser(request, conn))
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.put('/v1/social/rooms/{room}/report-receiving')
        async def update_receiving(room: str, request: Request, response: Response):
            data = await body(request, ('revision', 'joinedAt', 'receiveLocation', 'receiveVisits', 'expiresInHours'))
            with psycopg.connect(self.dsn) as conn:
                who = browser(request, conn, True)
                self.auth.rate('browser-report-receiving:' + who, limit=30)
                result = self.update_receiving(conn, room, who, data)
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.delete('/v1/social/rooms/{room}/report-receiving')
        def revoke_receiving(room: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                result = self.update_receiving(conn, room, browser(request, conn, True))
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.get('/v1/social/rooms/{room}/device-reports')
        def browser_reports(room: str, request: Request, response: Response):
            with psycopg.connect(self.dsn) as conn:
                result = self.reports(conn, room, browser(request, conn))
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.get('/v1/device/vehicle-domain')
        def native_snapshot(request: Request, response: Response, roomId: str | None = None):
            who = native(request)
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn)
                self.current_native(conn, who, credential(request))
                result = self.snapshot(conn, who['id'], who['deviceId'], room_parameter(request))
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        @router.get('/v1/native/rooms/{room}/device-reports')
        def native_reports(room: str, request: Request, response: Response):
            who = native(request)
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn)
                self.current_native(conn, who, credential(request), rooms_read=True)
                result = self.reports(conn, room, who['id'], who['deviceId'])
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        async def report(request, room, kind):
            common = ('eventId', 'devicePermissionRevision', 'roomRevision', 'capturedAt')
            extra = ('latitude', 'longitude', 'accuracyMeters') if kind == 'location' else ('courseId', 'courseVersion', 'checkpoint')
            data = await body(request, common + extra)
            who = native(request)  # Re-authenticate after the complete body arrives.
            self.auth.rate('device-report-write:' + who['deviceId'], limit=120)
            current = credential(request)
            with psycopg.connect(self.dsn) as conn:
                return self.ingest(conn, room, who, current, kind, data)

        @router.post('/v1/native/rooms/{room}/reports/location')
        async def location(room: str, request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            return await report(request, room, 'location')

        @router.post('/v1/native/rooms/{room}/reports/visits')
        async def visit(room: str, request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            return await report(request, room, 'visits')

        return router
