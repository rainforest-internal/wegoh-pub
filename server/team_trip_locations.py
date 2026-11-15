"""Latest current-device fixes for members of one active trip."""
import math
import re
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response

from native_functional_identity import business_json, resolve_current_device, transaction_actor
from native_functional_policy import FunctionalError
from native_principal import is_native_principal
from team_friends import blocked
from team_rooms import TeamRooms
from team_trip_context import resolve_trip_context
from team_trips import TeamTrips

FRESH_SECONDS = 60
CLOCK_SKEW_SECONDS = 10


def _valid_number(value, minimum, maximum):
    return type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value)


def _capture_time(value):
    if isinstance(value, str) and 1 <= len(value) <= 40:
        try:
            captured = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if captured.utcoffset() is not None:
                return captured.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    raise HTTPException(400, 'Invalid location capture time')


def _fresh(captured, now):
    return -CLOCK_SKEW_SECONDS <= (now - captured).total_seconds() <= FRESH_SECONDS


def _member_fix(member, key, now):
    saved = member.get(key)
    if (member['state'] != 'accepted' or member.get('locationConsent') is not True or not saved
            or saved['shareId'] != member.get('locationShareId')):
        return None
    captured = _capture_time(saved['capturedAt'])
    if not _fresh(captured, now):
        return None
    return dict(lat=saved['latitude'], lng=saved['longitude'], accuracyMeters=saved['accuracyMeters'],
                capturedAt=captured)


def _vehicle_fix(auth, conn, account, member, now):
    fix = _member_fix(member, 'vehicleLocation', now)
    if not fix:
        return None
    saved = member['vehicleLocation']
    try:
        reference = resolve_current_device(auth, conn, account, saved['deviceId'])
    except FunctionalError as error:
        if error.status in (401, 403, 404):
            return None
        raise
    return fix if reference.grant_id == saved['grantId'] else None


def latest_member_location(auth, conn, room, account):
    row = conn.execute("SELECT t.trip_id, m.protected, clock_timestamp() FROM team_rooms r "
        "JOIN team_trips t USING(trip_id) JOIN team_trip_members m USING(trip_id) "
        "WHERE r.room_id=%s AND m.account_id=%s AND t.state='active' AND t.deleted_at IS NULL",
        (room, account)).fetchone()
    if row:
        member = TeamTrips.restore('member:' + account, row[0], row[1])
        fixes = (_member_fix(member, 'phoneLocation', row[2]), _vehicle_fix(auth, conn, account, member, row[2]))
        return max((fix for fix in fixes if fix), key=lambda fix: fix['capturedAt'], default=None)
    return None


def _save_member(conn, trip, account, member):
    conn.execute('UPDATE team_trip_members SET protected=%s WHERE trip_id=%s AND account_id=%s',
                 (TeamTrips.protect('member:' + account, trip, member), trip, account))


def clear_trip_locations(conn, trip, account=None):
    query = 'SELECT account_id,protected FROM team_trip_members WHERE trip_id=%s'
    args = [trip]
    if account is not None:
        query += ' AND account_id=%s'
        args.append(account)
    for peer, raw in conn.execute(query + ' FOR UPDATE', args).fetchall():
        member = TeamTrips.restore('member:' + peer, trip, raw)
        phone = member.pop('phoneLocation', None)
        vehicle = member.pop('vehicleLocation', None)
        if phone is not None or vehicle is not None:
            _save_member(conn, trip, peer, member)


def _record(conn, trip, account, data, device=None):
    row = conn.execute('SELECT protected,clock_timestamp() FROM team_trip_members '
                       'WHERE trip_id=%s AND account_id=%s FOR UPDATE', (trip, account)).fetchone()
    member = TeamTrips.restore('member:' + account, trip, row[0])
    if member['state'] != 'accepted' or member.get('locationConsent') is not True:
        raise HTTPException(403, 'TRIP_LOCATION_SHARING_OFF')
    if data['shareId'] != member.get('locationShareId'):
        raise HTTPException(409, 'TRIP_LOCATION_SHARING_CHANGED')
    captured = _capture_time(data['capturedAt'])
    if not _fresh(captured, row[1]):
        raise HTTPException(400, 'Location capture is outside the allowed time')
    fix = dict(data, capturedAt=captured.isoformat())
    key = 'vehicleLocation' if device else 'phoneLocation'
    if device:
        fix.update(deviceId=device['deviceId'], grantId=device['grantId'])
    old = member.get(key)
    if old == fix:
        return
    if old and old['shareId'] == fix['shareId'] and captured <= _capture_time(old['capturedAt']):
        raise HTTPException(409, 'A newer location is already available')
    member[key] = fix
    _save_member(conn, trip, account, member)
    from team_event_versions import trip_changed
    trip_changed(conn, trip, ('location',))


def _locations(auth, conn, context, viewer):
    from team_trip_hand_raise import latest_vehicle_location

    trip, room = context['tripId'], context['roomId']
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    vehicles = {row[0] for row in conn.execute(
        "SELECT DISTINCT account_id FROM team_vehicle_latest_reports WHERE room_id=%s AND kind='location' "
        "AND received_at >= %s - interval '70 seconds'", (room, now))}
    rows = conn.execute('SELECT account_id,protected FROM team_trip_members WHERE trip_id=%s ORDER BY account_id',
                        (trip,)).fetchall()
    locations = []
    for account, raw in rows:
        if context['members'].get(account, {}).get('locationConsent') is not True:
            continue
        member = TeamTrips.restore('member:' + account, trip, raw)
        if member['state'] != 'accepted' or (viewer != account and blocked(conn, viewer, account)):
            continue
        source, fix = 'phone', _member_fix(member, 'phoneLocation', now)
        vehicle = _vehicle_fix(auth, conn, account, member, now)
        reported = latest_vehicle_location(auth, conn, room, account) if account in vehicles else None
        if reported and (not vehicle or reported['capturedAt'] > vehicle['capturedAt']):
            vehicle = reported
        if vehicle and _fresh(vehicle['capturedAt'], now) and (not fix or vehicle['capturedAt'] > fix['capturedAt']):
            source, fix = 'vehicle', vehicle
        if fix:
            person = auth.trip_service.person(account)
            if person:
                locations.append(dict(accountId=account, name=person['name'], source=source, latitude=fix['lat'],
                    longitude=fix['lng'], accuracyMeters=fix.get('accuracyMeters'), capturedAt=fix['capturedAt']))
    mine = context['members'][viewer]
    return dict(tripId=trip, serverNow=now, shareId=mine.get('locationShareId') if mine.get('locationConsent') else None,
                locations=locations, cars=_car_locations(auth, conn, trip, viewer, locations))


def _car_locations(auth, conn, trip, viewer, locations):
    # A car is where its occupants are: use the newest shared fix among its driver and riders.
    # Only fixes already visible to the viewer are used, so consent, blocking and freshness carry over.
    visible = {row['accountId']: row for row in locations}
    service = auth.trip_service
    riders = service.riders(conn, trip)
    cars = []
    for car, value in service.cars(conn, trip).items():
        driver = value['driverId']
        if driver != viewer and blocked(conn, viewer, driver):
            continue
        occupants = [driver] + [peer for peer, assigned in riders.items() if assigned == car]
        fixes = [visible[peer] for peer in occupants if peer in visible]
        if fixes:
            best = max(fixes, key=lambda row: row['capturedAt'])
            cars.append(dict(carId=car, source=best['source'], latitude=best['latitude'], longitude=best['longitude'],
                accuracyMeters=best['accuracyMeters'], capturedAt=best['capturedAt']))
    return cars


def trip_location_router(auth):
    router = APIRouter()

    def account_context(conn, request, trip, mutate=False):
        principal = getattr(request.state, 'device_identity', None)
        native = request.url.path.startswith('/v1/native/')
        if native != is_native_principal(principal):
            raise HTTPException(404, 'Trip unavailable')
        iphone = request.url.path.startswith('/v1/iphone/')
        if iphone and request.url.query:
            raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
        TeamRooms.graph_lock(conn)
        actor = (auth.iphone_sessions.authenticate(request, 'trips:manage' if mutate else 'trips:read',
            connection=conn, lock=mutate) if iphone else transaction_actor(auth, request, conn, mutate=mutate))
        account = actor['id']
        auth.rate('trip-member-location-' + ('write:' if mutate else 'read:') + account, limit=24 if mutate else 60)
        context = resolve_trip_context(auth, conn, trip, account, states=('active',))
        return actor, context

    @router.get('/v1/iphone/trips/{trip}/locations', include_in_schema=False)
    @router.get('/v1/social/trips/{trip}/locations')
    @router.get('/v1/native/trips/{trip}/locations')
    def locations(trip: str, request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        with psycopg.connect(auth.dsn) as conn:
            viewer, context = account_context(conn, request, trip)
            return _locations(auth, conn, context, viewer['id'])

    @router.post('/v1/social/trips/{trip}/locations/me')
    @router.post('/v1/native/trips/{trip}/locations/me')
    async def report(trip: str, request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 2048:
                raise HTTPException(413, 'Location request too large')
            raw.extend(chunk)
        data = business_json(request, raw, maximum=2048)
        if (not isinstance(data, dict) or set(data) != {'shareId','capturedAt','latitude','longitude','accuracyMeters'}
                or not isinstance(data['shareId'], str) or not re.fullmatch(r'[0-9a-f]{32}', data['shareId'])
                or not _valid_number(data['latitude'], -90, 90) or not _valid_number(data['longitude'], -180, 180)
                or data['accuracyMeters'] is not None and not _valid_number(data['accuracyMeters'], 0, 10000)):
            raise HTTPException(400, 'Invalid phone location')
        with psycopg.connect(auth.dsn) as conn:
            account, _ = account_context(conn, request, trip, mutate=True)
            _record(conn, trip, account['id'], data, account if is_native_principal(account) else None)
        return dict(status='accepted')

    return router
