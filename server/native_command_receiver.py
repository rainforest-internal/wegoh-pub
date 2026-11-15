"""Read and change the authenticated vehicle's command receiver."""
from psycopg.rows import tuple_row

from native_access_codec import CodecError, decode_json
from native_functional_identity import _revalidate_principal
from native_functional_policy import FunctionalError, MAX_REVISION, identifier, revision
from native_principal import is_native_principal
from private_records import VisitCipher
from team_data import changed

RECEIVE = 'device-commands:receive'


def receiver_change(raw):
    try:
        value = decode_json(raw, maximum_bytes=12288)
    except CodecError:
        raise FunctionalError(400, 'INVALID_FUNCTIONAL_REQUEST') from None
    if type(value) is not dict or set(value) != {'grantId', 'revision', 'enabled'} or type(value['enabled']) is not bool:
        raise FunctionalError(400, 'INVALID_FUNCTIONAL_REQUEST')
    identifier(value['grantId'])
    revision(value['revision'], zero=False)
    return value


def command_receiver(service, request, raw=None):
    service.require_enabled()
    principal = getattr(request.state, 'device_identity', None)
    if not is_native_principal(principal):
        raise FunctionalError(401, 'INVALID_CREDENTIAL')
    change = receiver_change(raw) if raw is not None else None
    with service.base.db() as conn:
        grant, _ = service.owner_grant(conn, principal['id'], principal['deviceId'])
        _revalidate_principal(service.auth, request, conn)
        row = service.row(conn, grant, lock=True)
        if row['state'] != 'ACTIVE' or row['expires_at'] <= service.base.now():
            raise FunctionalError(403, 'FUNCTIONAL_CONSENT_INACTIVE')
        payload = service.payload(row)
        purposes = set(payload['approvedPurposes'])
        current = dict(deviceId=grant['device_id'], grantId=grant['grant_id'],
                       revision=payload.get('receiverRevision', 1), enabled=RECEIVE in purposes)
        if change is None:
            return current
        if change['grantId'] != current['grantId'] or change['revision'] != current['revision']:
            raise FunctionalError(409, 'RECEIVER_CHANGED')
        if change['enabled'] == current['enabled']:
            return current
        if current['revision'] >= MAX_REVISION:
            raise FunctionalError(409, 'RECEIVER_REVISION_EXHAUSTED')

        commands = getattr(service.auth, 'device_command_service', None)
        if commands is None:
            raise FunctionalError(503, 'RECEIVER_UNAVAILABLE')
        if change['enabled']:
            purposes.add(RECEIVE)
        else:
            purposes.remove(RECEIVE)
            where = 'device_id=%s AND owner_id=%s'
            target = (current['deviceId'], principal['id'])
            with conn.cursor(row_factory=tuple_row) as cursor:
                commands.revoke_rows(cursor, where, target, 'receiver-paused')
                commands.friend_controls.cancel(cursor, where, target, 'receiver-paused')

        current.update(revision=current['revision'] + 1, enabled=change['enabled'])
        payload.pop('receiverSupport', None)
        payload.update(receiverRevision=current['revision'], approvedPurposes=sorted(purposes))
        protected = VisitCipher().protect('native-functional', current['grantId'], payload)
        conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s',
                     (protected, current['grantId']))
        commands.invalidate_receiver(conn, current['deviceId'])
        changed(conn, principal['id'], 'devices')
        for peer in conn.execute('SELECT DISTINCT requester_id FROM team_trip_remote_grants '
                                 'WHERE driver_id=%s AND device_id=%s', (principal['id'], current['deviceId'])):
            changed(conn, peer['requester_id'], 'rooms')
        return current
