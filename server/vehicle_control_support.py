"""Short-lived input hints; observations never grant control authority."""
import copy
import datetime as dt
import math

from psycopg.rows import dict_row, tuple_row

from device_command_registry import DRIVER_AREA, ProductionCommandRegistry, SEATS, WINDOWS
from native_access_codec import CodecError, decode_json
from native_functional_policy import FunctionalError, identifier, revision
from private_records import VisitCipher

TTL_SECONDS = 90
MAX_BYTES = 12288
RECEIVE = 'device-commands:receive'
REGISTRY = ProductionCommandRegistry()


def fail(status=400, code='INVALID_CONTROL_SUPPORT'):
    raise FunctionalError(status, code)


def number(value):
    if type(value) not in (int, float):
        fail()
    try:
        if not math.isfinite(value):
            fail()
    except (OverflowError, ValueError):
        fail()
    return value


def support_zones(value, action, identifiers):
    """Seats one SDK area changes together. Each group has 2+ reported seats and no seat is in two groups."""
    if type(value) is not list or len(value) > 4 or value and action.area_key != 'seat':
        fail()
    result, used = [], set()
    for zone in value:
        if (type(zone) is not list or len(zone) < 2 or any(type(seat) is not str or seat not in identifiers for seat in zone)
                or len(set(zone)) != len(zone) or used & set(zone)):
            fail()
        used |= set(zone)
        result.append(sorted(zone, key=SEATS.index))
    return sorted(result, key=lambda zone: SEATS.index(zone[0]))


def support_actions(value):
    if type(value) is not list or len(value) > 11:
        fail()
    result, seen = [], set()
    for item in value:
        if type(item) is not dict or set(item) != {'id', 'revision', 'status', 'available', 'areas', 'zones'}:
            fail()
        action = REGISTRY.lookup(item['id'], item['revision'])
        if action is None or item['id'] in seen or item['status'] not in ('known', 'unknown') or type(item['available']) is not bool:
            fail()
        seen.add(item['id'])
        areas = item['areas']
        if type(areas) is not list or len(areas) > 8:
            fail()
        available = item['available']
        if item['status'] == 'unknown' and available:
            fail()
        if not available and areas or action.area_key is None and areas or available and action.area_key is not None and not areas:
            fail()
        normalized, identifiers = [], set()
        for area in areas:
            if type(area) is not dict or set(area) != {'id', 'min', 'max', 'step'}:
                fail()
            # The driver seat/window is never remotely controlled, so a report naming it (e.g. from a
            # vehicle app older than that rule) is rejected rather than shown on iPhone. Zones may only
            # name reported areas, so a zone containing the driver seat is rejected too.
            if (type(area['id']) is not str or area['id'] not in (WINDOWS if action.area_key == 'window' else SEATS)
                    or area['id'] == DRIVER_AREA or area['id'] in identifiers):
                fail()
            identifiers.add(area['id'])
            low, high, step = area['min'], area['max'], area['step']
            if action.argument_kind == 'seat-switch':
                if any(v is not None for v in (low, high, step)):
                    fail()
            else:
                number(low); number(high)
                maximum = 50 if action.argument_kind == 'hvac-celsius' else 10 if action.argument_kind == 'seat-level' else 100
                if not 0 <= low <= high <= maximum:
                    fail()
                if action.argument_kind == 'hvac-celsius':
                    if step is not None and (number(step) <= 0 or step > maximum or high > low and step > high - low):
                        fail()
                elif any(number(v) != int(v) for v in (low, high)) or type(step) not in (int, float) or number(step) != 1:
                    fail()
                else:
                    low, high, step = int(low), int(high), 1
                    if action.argument_kind == 'window-position' and (low != 0 or high != 100):
                        fail()
            normalized.append(dict(id=area['id'], min=low, max=high, step=step))
        result.append(dict(id=item['id'], revision=1, status=item['status'], available=available,
                           areas=sorted(normalized, key=lambda a: a['id']), zones=support_zones(item['zones'], action, identifiers)))
    return sorted(result, key=lambda a: a['id'])


def report_body(raw):
    if type(raw) in (bytes, bytearray) and len(raw) > MAX_BYTES:
        fail(413, 'CONTROL_SUPPORT_TOO_LARGE')
    try:
        value = decode_json(raw, maximum_bytes=MAX_BYTES)
    except CodecError:
        fail()
    if type(value) is not dict or set(value) != {'functionalRevision', 'receiverRevision', 'actions'}:
        fail()
    revision(value['functionalRevision'], zero=False)
    revision(value['receiverRevision'], zero=False)
    return dict(value, actions=support_actions(value['actions']))


def timestamp(value):
    if type(value) is not str or len(value) > 64:
        fail()
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            fail()
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        fail()


def stored_support(value):
    fields = {'deviceId', 'grantId', 'credentialEpoch', 'functionalRevision', 'receiverRevision',
              'observedAt', 'expiresAt', 'actions'}
    if type(value) is not dict or set(value) != fields:
        fail()
    identifier(value['deviceId']); identifier(value['grantId'])
    revision(value['functionalRevision'], zero=False); revision(value['receiverRevision'], zero=False)
    if type(value['credentialEpoch']) is not int or value['credentialEpoch'] < 0:
        fail()
    start, end = timestamp(value['observedAt']), timestamp(value['expiresAt'])
    if not start < end <= start + TTL_SECONDS:
        fail()
    support_actions(value['actions'])
    return value


def report_support(service, request, raw):
    from native_functional_identity import _revalidate_principal
    from native_principal import is_native_principal
    from team_trips import TeamTrips
    service.require_enabled()
    if not is_native_principal(getattr(request.state, 'device_identity', None)):
        fail(401, 'INVALID_CREDENTIAL')
    data = report_body(raw)
    with service.base.db() as conn:
        service.auth.room_service.graph_lock(conn)
        principal, snapshot, grant = _revalidate_principal(service.auth, request, conn, include_grant=True)
        if RECEIVE not in snapshot['approvedPurposes']:
            fail(403, 'FUNCTIONAL_PURPOSE_REQUIRED')
        with conn.cursor(row_factory=tuple_row) as cursor:
            if TeamTrips(service.auth).category(cursor, principal['id']) != 'vehicle':
                fail(403, 'VEHICLE_OWNER_REQUIRED')
        row = service.row(conn, grant, lock=True)
        now = service.base.now()
        if row is None or row['state'] != 'ACTIVE' or row['expires_at'] <= now:
            fail(403, 'FUNCTIONAL_CONSENT_INACTIVE')
        payload = service.payload(row)
        if data['functionalRevision'] != row['revision']:
            fail(409, 'FUNCTIONAL_REVISION_CHANGED')
        if data['receiverRevision'] != payload.get('receiverRevision', 1):
            fail(409, 'RECEIVER_CHANGED')
        observed = dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat()
        expires = dt.datetime.fromtimestamp(min(now + TTL_SECONDS, row['expires_at'], grant['expires_at']), dt.timezone.utc).isoformat()
        payload['receiverSupport'] = dict(deviceId=grant['device_id'], grantId=grant['grant_id'],
            credentialEpoch=principal['credentialEpoch'], functionalRevision=row['revision'],
            receiverRevision=data['receiverRevision'], observedAt=observed, expiresAt=expires, actions=data['actions'])
        protected = VisitCipher().protect('native-functional', grant['grant_id'], payload)
        conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s', (protected, grant['grant_id']))
        return dict(status='accepted', observedAt=observed, expiresAt=expires)


def current_support(conn, auth, reference):
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute('SELECT f.*,g.credential_epoch FROM native_functional_authorizations f '
            'JOIN native_v2_grants g USING(grant_id) WHERE f.grant_id=%s AND f.device_id=%s',
            (reference.grant_id, reference.device_id)).fetchone()
    if not row or row['state'] != 'ACTIVE':
        return None
    payload = auth.functional_access.payload(row)
    value = payload.get('receiverSupport')
    now = auth.native_authorization.now()
    if (not value or RECEIVE not in payload['approvedPurposes'] or row['expires_at'] <= now
            or value['deviceId'] != reference.device_id or value['grantId'] != reference.grant_id
            or value['credentialEpoch'] != row['credential_epoch'] or value['functionalRevision'] != row['revision']
            or value['receiverRevision'] != payload.get('receiverRevision', 1)
            or not timestamp(value['observedAt']) <= now < timestamp(value['expiresAt'])):
        return None
    return value


def public_support(snapshot, action):
    found = next((a for a in snapshot['actions'] if a['id'] == action['id'] and a['revision'] == action['revision']), None) if snapshot else None
    if found is None:
        return dict(status='unknown', available=False, areas=[], zones=[], observedAt=None, expiresAt=None)
    return dict(status=found['status'], available=found['available'], areas=copy.deepcopy(found['areas']),
                zones=copy.deepcopy(found['zones']), observedAt=snapshot['observedAt'], expiresAt=snapshot['expiresAt'])


def command_problem(snapshot, action, arguments):
    support = public_support(snapshot, action)
    if support['status'] != 'known':
        return None
    if not support['available']:
        return 'VEHICLE_CONTROL_UNSUPPORTED'
    selected = REGISTRY.lookup(action['id'], action['revision'])
    if selected.area_key is None:
        return None
    area = next((a for a in support['areas'] if a['id'] == arguments[selected.area_key]), None)
    if area is None:
        return 'VEHICLE_CONTROL_AREA_UNSUPPORTED'
    if area['min'] is None:
        return None
    value = arguments['value']
    if not area['min'] <= value <= area['max']:
        return 'VEHICLE_CONTROL_VALUE_UNSUPPORTED'
    if area['step'] is not None:
        count = (value - area['min']) / area['step']
        if not math.isfinite(count) or abs(count - round(count)) > .001:
            return 'VEHICLE_CONTROL_VALUE_UNSUPPORTED'
    return None
