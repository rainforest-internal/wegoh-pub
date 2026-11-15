import hashlib
import json

from fastapi import HTTPException
from native_principal import is_native_principal

PROTOCOL = 'wegoh.events.v1'
CHAT_PROTOCOL = 'wegoh.events.v1.chat'
SECTIONS = ('detail', 'route', 'signals', 'music', 'location', 'voice')
WEB_SECTIONS = (*SECTIONS, 'chat')


def stamp(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()[:32]


def bump(conn, key, resource='rooms'):
    conn.execute('INSERT INTO team_resource_versions(account_id,resource,revision) VALUES(%s,%s,1) '
        'ON CONFLICT(account_id,resource) DO UPDATE SET revision=team_resource_versions.revision+1', (key, resource))


def trip_changed(conn, trip, sections=SECTIONS):
    if not set(sections) <= set(WEB_SECTIONS):
        raise ValueError('Unknown trip section')
    for section in sections:
        bump(conn, 'event-trip:' + trip + ':' + section)


def versions(auth, conn, actor, allowed, *, chat=False):
    from psycopg.rows import dict_row
    from native_functional_defaults import account_purposes

    owner = actor['id']
    native = is_native_principal(actor)
    rows = {(a, r): v for a, r, v in conn.execute('SELECT account_id,resource,revision FROM '
        'team_resource_versions WHERE account_id=ANY(%s)', (['event-account:' + owner, 'event-account:*'],))}
    domains = set(allowed)
    authority = ()
    if native:
        with conn.cursor(row_factory=dict_row) as cursor:
            functional = cursor.execute("SELECT * FROM native_functional_authorizations WHERE grant_id=%s "
                "AND device_id=%s AND state='ACTIVE' AND expires_at>extract(epoch FROM now())",
                (actor['grantId'], actor['deviceId'])).fetchone()
        service = getattr(auth, 'functional_access', None)
        purposes = account_purposes(service.payload(functional)['approvedPurposes']) if service and functional else frozenset()
        own = conn.execute('SELECT device_revision FROM native_v2_grants WHERE grant_id=%s AND device_id=%s '
            "AND account_id=%s AND state='TOKEN_ISSUED'", (actor['grantId'], actor['deviceId'], owner)).fetchone()
        authority = (own, functional['revision'] if functional else 0)
        for domain, purpose in {'friends': 'friends:read', 'rooms': 'rooms:read', 'history': 'history:read',
                'recommendations': 'recommendations:use', 'cautions': 'cautions:read', 'vehicle': 'vehicle-reports:read'}.items():
            if purpose in purposes:
                domains.add(domain)
        if 'device-commands:receive' in purposes:
            domains.add('commands')
        domains.add('profile')
    result = {}
    if native and 'rooms' in domains:
        for domain, table in (('music', 'native_room_music_authorizations'), ('voice', 'native_room_voice_authorizations')):
            state = conn.execute('SELECT room_id,revision,state,expires_at>extract(epoch FROM now()) FROM ' + table +
                ' WHERE grant_id=%s AND device_id=%s ORDER BY room_id', (actor['grantId'], actor['deviceId'])).fetchall()
            result[domain] = stamp(state)
    for domain in domains:
        if domain == 'devices' and native:
            value = authority
        elif domain == 'commands':
            value = conn.execute("SELECT account_id,revision FROM team_resource_versions "
                "WHERE account_id=ANY(%s) AND resource='devices' ORDER BY account_id",
                (['command-device:' + actor['deviceId'], 'command-status-device:' + actor['deviceId']],)).fetchall()
        elif domain == 'profile':
            value = conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='devices'",
                ('profile-account:' + owner,)).fetchone()
        else:
            value = (rows.get(('event-account:' + owner, domain), 0), rows.get(('event-account:*', domain), 0))
        result[domain] = stamp(value)
    if 'rooms' not in domains:
        return result
    trips = conn.execute('SELECT t.trip_id,m.protected,t.owner_id FROM team_trips t JOIN team_trip_members m USING(trip_id) '
        "WHERE m.account_id=%s AND t.deleted_at IS NULL AND t.state IN ('planned','active') ORDER BY t.trip_id", (owner,)).fetchall()
    if len(trips) > 100:
        raise HTTPException(409, 'Event projection limit exceeded')
    trip_service = auth.trip_service
    from team_friends import blocked
    sections = WEB_SECTIONS if chat and not native else SECTIONS
    section_keys = ['event-trip:' + trip + ':' + section for trip, _, _ in trips for section in sections]
    section_rows = dict(conn.execute("SELECT account_id,revision FROM team_resource_versions WHERE account_id=ANY(%s) AND resource='rooms'", (section_keys,)))
    hosts = {}
    for trip, raw, host in trips:
        member = trip_service.member_payload(trip, owner, raw)
        if member['state'] != 'accepted':
            continue
        if host not in hosts:
            hosts[host] = bool(trip_service.person(host, connection=conn)) and (host == owner or not blocked(conn, host, owner))
        if not hosts[host]:
            continue
        for section in sections:
            result['trip.' + trip + '.' + section] = stamp(section_rows.get('event-trip:' + trip + ':' + section, 0))
    return result
