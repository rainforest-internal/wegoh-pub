"""Individual team friendships. No rooms, history, messages or vehicle execution.

Only pseudonymous ownership indexes are relational plaintext. Request direction,
relationship state and each person's block choice are authenticated ciphertext.
"""
import json
import re
import hashlib
import secrets

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import VisitCipher, PrivateRecordError
from team_data import changed
from account_handles import account_person, normalize_handle
from native_access_codec import CodecError, decode_json

ACCOUNT = re.compile(r'team-[a-f0-9]{40}')


def pair_ids(owner, target):
    if not isinstance(target, str) or not ACCOUNT.fullmatch(target) or owner == target:
        raise HTTPException(400, 'Choose another account')
    return tuple(sorted((owner, target)))


def read_pair(conn, a, b):
    row = conn.execute('SELECT protected FROM team_friend_pairs WHERE account_a=%s AND account_b=%s', (a, b)).fetchone()
    if not row:
        return dict(state='none', requestedBy=None, blockedBy=[]), False
    return restore_pair(a, b, row[0]), True


def restore_pair(a, b, protected):
    value = VisitCipher().restore('team-friend-pair', a + ':' + b, protected)
    if (not isinstance(value, dict) or set(value) != {'state', 'requestedBy', 'blockedBy'}
            or value['state'] not in ('none', 'pending', 'accepted')
            or not isinstance(value['blockedBy'], list)
            or any(x not in (a, b) for x in value['blockedBy'])
            or len(set(value['blockedBy'])) != len(value['blockedBy'])
            or (value['state'] == 'none' and value['requestedBy'] is not None)
            or (value['state'] != 'none' and value['requestedBy'] not in (a, b))
            or (value['blockedBy'] and value['state'] != 'none')):
        raise PrivateRecordError('Friend relationship integrity check failed')
    return value


def save_pair(conn, a, b, value):
    protected = None
    if value['state'] == 'none' and not value['blockedBy']:
        conn.execute('DELETE FROM team_friend_pairs WHERE account_a=%s AND account_b=%s', (a, b))
    else:
        protected = VisitCipher().protect('team-friend-pair', a + ':' + b, value)
        conn.execute('INSERT INTO team_friend_pairs(account_a,account_b,protected) VALUES(%s,%s,%s) '
            'ON CONFLICT(account_a,account_b) DO UPDATE SET protected=excluded.protected,updated_at=now()',
            (a, b, protected))
    changed(conn, a, 'friends')
    changed(conn, b, 'friends')
    return protected


def blocked(conn, owner, target):
    a, b = pair_ids(owner, target)
    return bool(read_pair(conn, a, b)[0]['blockedBy'])


def linked(conn, owner, target):
    a, b = pair_ids(owner, target)
    value, _ = read_pair(conn, a, b)
    return value['state'] == 'accepted' and not value['blockedBy']


def has_vehicle(conn, account):
    row = conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s', (account,)).fetchone()
    if not row:
        return False
    saved = VisitCipher().restore('team-account:' + account, 'identity', row[0])
    profiles = saved.get('vehicleProfiles', {})
    for key, in conn.execute('SELECT g.installation_key_id FROM native_v2_grants g '
            'JOIN native_v2_installations i USING(installation_key_id) '
            "WHERE g.account_id=%s AND g.state='TOKEN_ISSUED' AND g.revoked_at IS NULL "
            'AND g.expires_at>extract(epoch FROM clock_timestamp()) '
            'AND i.revoked_at IS NULL AND i.active_grant_id=g.grant_id', (account,)):
        plate = profiles.get(key, {}).get('plateNumber', '')
        if isinstance(plate, str) and plate.strip():
            return True
    return False


def issue_link(conn, account, *, trip=None):
    from team_device_commands import iso
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    if trip is None:
        row = conn.execute("INSERT INTO team_friend_links(account_id,token_sha256,expires_at) "
            "VALUES(%s,%s,clock_timestamp()+interval '7 days') ON CONFLICT(account_id) "
            "DO UPDATE SET token_sha256=excluded.token_sha256,expires_at=excluded.expires_at RETURNING expires_at",
            (account, digest)).fetchone()
    else:
        row = conn.execute("INSERT INTO team_trip_links(trip_id,token_sha256,created_by,expires_at) "
            "VALUES(%s,%s,%s,clock_timestamp()+interval '7 days') ON CONFLICT(trip_id) "
            "DO UPDATE SET token_sha256=excluded.token_sha256,created_by=excluded.created_by,expires_at=excluded.expires_at RETURNING expires_at",
            (trip, digest, account)).fetchone()
    return dict(token=token, expiresAt=iso(row[0]))


def resolve_link(conn, token, *, trip=False):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(404, 'Link unavailable')
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    if trip:
        row = conn.execute('SELECT l.trip_id,t.owner_id,l.expires_at FROM team_trip_links l '
            'JOIN team_trips t USING(trip_id) WHERE l.token_sha256=%s AND l.expires_at>clock_timestamp()', (digest,)).fetchone()
    else:
        row = conn.execute('SELECT account_id,expires_at FROM team_friend_links '
            'WHERE token_sha256=%s AND expires_at>clock_timestamp()', (digest,)).fetchone()
    if not row:
        raise HTTPException(404, 'Link unavailable')
    return row


from native_access import read_actor, native_resource
from native_functional_identity import request_actor,transaction_actor,business_json

def create_router(auth, rooms=None):
    router = APIRouter()
    if not auth.enabled:
        return router

    def persist_pair(conn,a,b,value):
        protected = save_pair(conn,a,b,value)
        trips=getattr(auth,'trip_service',None)
        if trips and trips.enabled:trips.friendship_changed(conn,a,b,value['state']=='accepted' and not value['blockedBy'])
        commands=getattr(auth,'device_command_service',None)
        if commands and (value['state']!='accepted' or value['blockedBy']):
            commands.revoke_pair(conn,a,b)
        vehicle=getattr(auth,'vehicle_service',None)
        if vehicle:vehicle.friendship_changed(conn,a,b)
        history=getattr(auth,'history_service',None)
        if history and history.enabled and(value['state']!='accepted' or value['blockedBy']):history.revoke_pair(conn,a,b)
        cautions=getattr(auth,'cautions_service',None)
        if cautions and cautions.enabled and(value['state']!='accepted' or value['blockedBy']):cautions.revoke_pair(conn,a,b)
        if value['state'] in ('pending', 'accepted'):
            from iphone_push import enqueue_push
            requester = value['requestedBy']
            other = b if requester == a else a
            if value['state'] == 'pending':
                kind, actor, recipient = 'friend_request', requester, other
            else:
                kind, actor, recipient = 'friend_accepted', other, requester
            enqueue_push(conn, kind=kind, actor=actor, recipients=[recipient],
                         resource_id=hashlib.sha256(protected).hexdigest())

    def iphone(request):
        return request.url.path.startswith('/v1/iphone/')

    def iphone_actor(request, *, connection=None, mutate=False):
        if request.url.query and not request.url.path.endswith('/search'):
            raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
        return auth.iphone_sessions.authenticate(request, 'friends:manage' if mutate else 'friends:read',
                                                  connection=connection, lock=mutate and connection is not None)

    def transaction(request, conn, *, mutate=False):
        if iphone(request):
            if mutate and rooms and rooms.enabled:
                rooms.graph_lock(conn)
            return iphone_actor(request, connection=conn, mutate=mutate)
        return transaction_actor(auth, request, conn, mutate=mutate)

    def actor(request, mutate=False):
        if iphone(request):
            return iphone_actor(request, mutate=mutate)
        # One current identity for native reads/writes; each domain transaction
        # rechecks its exact functional purpose and explicit mutation revision.
        return request_actor(auth,request,mutate=mutate)

    async def body(request, fields):
        raw = bytearray()
        if iphone(request):
            from iphone_sessions import body as iphone_body
            raw.extend(await iphone_body(request, 'application/json'))
        else:
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4096:
                    raise HTTPException(413, 'Request too large')
        try:
            data = business_json(request,raw,maximum=4096)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid JSON') from None
        if not isinstance(data, dict) or set(data) != set(fields):
            raise HTTPException(400, 'Invalid friend request fields')
        return data

    def person(conn, account, *, lock=False):
        current = account_person(conn, account, lock=lock)
        return dict(id=current['id'], name=current['name']) if current else None

    def lock_pair(conn, owner, target, *, available=False):
        # All graph changes serialize with history grants before pair/history locks.
        if rooms and rooms.enabled: rooms.graph_lock(conn)
        a, b = pair_ids(owner, target)
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('friends:' + a + ':' + b,))
        if not conn.execute('SELECT 1 FROM team_accounts WHERE account_id=%s', (target,)).fetchone():
            raise HTTPException(404, 'Account unavailable')
        if available and person(conn, target, lock=True) is None:
            raise HTTPException(404, 'Account unavailable')
        return a, b

    @router.get('/v1/iphone/friends/search', include_in_schema=False)
    @router.get('/v1/social/friends/search')
    def search(request: Request, response: Response):
        owner = (iphone_actor(request) if iphone(request) else auth.browser(request))['id']
        response.headers['Cache-Control'] = 'private, no-store'
        auth.rate('friend-search-ip:' + (request.client.host if request.client else 'unknown'), limit=60)
        auth.rate('friend-search-account:' + owner, limit=20)
        if set(request.query_params) != {'handle'} or len(request.query_params.getlist('handle')) != 1:
            raise HTTPException(400, 'INVALID_HANDLE')
        handle = normalize_handle(request.query_params['handle'])
        with psycopg.connect(auth.dsn) as conn:
            if iphone(request):
                iphone_actor(request, connection=conn)
            else:
                auth.browser(request, connection=conn)
            row = conn.execute("SELECT account_id FROM team_accounts WHERE lower(handle)=%s AND account_status='active'", (handle,)).fetchone()
            result = account_person(conn, row[0]) if row else None
            if result:
                relationship = 'self'
                if result['id'] != owner:
                    value, _ = read_pair(conn, *pair_ids(owner, result['id']))
                    if value['blockedBy']:
                        return dict(person=None)
                    relationship = ('friend' if value['state'] == 'accepted' else
                        ('outgoing' if value['requestedBy'] == owner else 'incoming') if value['state'] == 'pending' else 'none')
                result['relationship'] = relationship
        return dict(person=result)

    @router.get('/v1/iphone/friends', include_in_schema=False)
    @router.get('/v1/social/overview')
    def overview(request: Request, response: Response):
        owner = actor(request)['id']
        response.headers['Cache-Control'] = 'private, no-store'
        people, friends, requests, blocks = [], [], [], []
        with psycopg.connect(auth.dsn) as conn:
            transaction(request,conn,mutate=request.method!='GET')
            allowed=getattr(request.state,'functional_snapshot',{}).get('approvedPurposes',frozenset())
            native=native_resource(request)
            accounts = []if native and 'friends:read'not in allowed else conn.execute(
                'SELECT CASE WHEN account_a=%s THEN account_b ELSE account_a END FROM team_friend_pairs '
                'WHERE account_a=%s OR account_b=%s ORDER BY 1', (owner, owner, owner)).fetchall()
            for (target,) in accounts:
                a, b = pair_ids(owner, target)
                value, _ = read_pair(conn, a, b)
                target_person = account_person(conn, target) if iphone(request) else person(conn, target)
                if owner in value['blockedBy']:
                    blocks.append(dict(target_person or dict(id=target, name=None), available=bool(target_person)))
                if value['blockedBy'] or target_person is None:
                    continue
                if value['state'] == 'accepted':
                    friends.append(dict(target_person, hasVehicle=has_vehicle(conn, target)))
                elif value['state'] == 'pending':
                    requests.append(dict(target_person, direction='outgoing' if value['requestedBy'] == owner else 'incoming'))
            room_rows = [] if iphone(request) else rooms.list_rooms(conn, owner) if rooms and rooms.enabled and(not native or 'rooms:read'in allowed)else []
        if iphone(request):
            return dict(friends=friends, requests=requests, blocks=blocks)
        if native_resource(request):
            manage={'friends:read','friends:manage'}<=allowed
            return dict(people=people if manage else[],friends=friends if 'friends:read'in allowed else[],requests=requests if manage else[],blocks=blocks if manage else[],rooms=room_rows,history=[],
                        capabilities=dict(friends='friends:read'in allowed,rooms='rooms:read'in allowed,history='history:read'in allowed,nativeReadOnly=not manage))
        return dict(people=people, friends=friends, requests=requests, blocks=blocks,
            rooms=room_rows, history=[], capabilities=auth.capabilities())

    @router.post('/v1/iphone/friends/requests', status_code=201, include_in_schema=False)
    @router.post('/v1/social/friends/requests', status_code=201)
    async def request_friend(request: Request, response: Response):
        owner = actor(request, True)['id']
        target = (await body(request, ('targetId',)))['targetId']
        auth.rate('friend-mutate:' + owner, limit=60)
        with psycopg.connect(auth.dsn) as conn:
            transaction(request,conn,mutate=request.method!='GET')
            a, b = lock_pair(conn, owner, target, available=True)
            value, _ = read_pair(conn, a, b)
            if value['blockedBy']:
                raise HTTPException(404, 'Account unavailable')
            if value['state'] == 'pending' and value['requestedBy'] != owner:
                raise HTTPException(409, 'Respond to the existing request')
            if value['state'] in ('pending', 'accepted'):
                response.status_code = 200
            else:
                value.update(state='pending', requestedBy=owner)
                persist_pair(conn, a, b, value)
        return dict(status=value['state'])

    @router.post('/v1/iphone/friends/requests/{target}/respond', include_in_schema=False)
    @router.post('/v1/social/friends/requests/{target}/respond')
    async def respond(target: str, request: Request):
        owner = actor(request, True)['id']
        data = await body(request, ('accept',))
        if type(data['accept']) is not bool:
            raise HTTPException(400, 'Choose a response')
        auth.rate('friend-mutate:' + owner, limit=60)
        with psycopg.connect(auth.dsn) as conn:
            transaction(request,conn,mutate=request.method!='GET')
            a, b = lock_pair(conn, owner, target, available=True)
            value, _ = read_pair(conn, a, b)
            if value['blockedBy'] or value['state'] != 'pending' or value['requestedBy'] != target:
                raise HTTPException(404, 'Friend request unavailable')
            value.update(state='accepted' if data['accept'] else 'none',
                         requestedBy=target if data['accept'] else None)
            persist_pair(conn, a, b, value)
        return dict(status='accepted' if data['accept'] else 'declined')

    @router.delete('/v1/iphone/friends/{target}', include_in_schema=False)
    @router.delete('/v1/social/friends/{target}')
    async def remove(target: str, request: Request):
        owner = actor(request, True)['id']
        if native_resource(request) or iphone(request):await body(request,())
        auth.rate('friend-mutate:' + owner, limit=60)
        with psycopg.connect(auth.dsn) as conn:
            transaction(request,conn,mutate=request.method!='GET')
            a, b = lock_pair(conn, owner, target)
            value, _ = read_pair(conn, a, b)
            if value['state'] == 'pending' and value['requestedBy'] != owner:
                raise HTTPException(403, 'Only the sender may cancel a request')
            if value['state'] != 'none':
                value.update(state='none', requestedBy=None)
                persist_pair(conn, a, b, value)
        return dict(status='removed')

    @router.post('/v1/iphone/blocks', status_code=201, include_in_schema=False)
    @router.post('/v1/social/blocks', status_code=201)
    async def block_account(request: Request, response: Response):
        owner = actor(request, True)['id']
        target = (await body(request, ('targetId',)))['targetId']
        auth.rate('friend-mutate:' + owner, limit=60)
        with psycopg.connect(auth.dsn) as conn:
            transaction(request,conn,mutate=request.method!='GET')
            a, b = lock_pair(conn, owner, target)
            value, _ = read_pair(conn, a, b)
            if owner in value['blockedBy']:
                response.status_code = 200
            else:
                value.update(state='none', requestedBy=None, blockedBy=sorted(value['blockedBy'] + [owner]))
                persist_pair(conn, a, b, value)
                trips=getattr(auth,'trip_service',None)
                if trips and trips.enabled: trips.on_block(conn, owner, target)
                if rooms and rooms.enabled: rooms.on_block(conn, owner, target)
        return dict(status='blocked')

    @router.delete('/v1/iphone/blocks/{target}', include_in_schema=False)
    @router.delete('/v1/social/blocks/{target}')
    async def unblock_account(target: str, request: Request):
        owner = actor(request, True)['id']
        if native_resource(request) or iphone(request):await body(request,())
        auth.rate('friend-mutate:' + owner, limit=60)
        with psycopg.connect(auth.dsn) as conn:
            transaction(request,conn,mutate=request.method!='GET')
            a, b = lock_pair(conn, owner, target)
            value, _ = read_pair(conn, a, b)
            if owner in value['blockedBy']:
                value['blockedBy'].remove(owner)
                persist_pair(conn, a, b, value)
        return dict(status='unblocked')

    def link_actor(request, response, *, mutate=False):
        response.headers['Cache-Control'] = 'private, no-store'
        account = auth.browser(request, mutate=mutate)['id']
        if mutate:
            auth.rate('friend-mutate:' + account, limit=60)
        return account

    def link_transaction(request, conn, *, mutate=False):
        from team_rooms import TeamRooms
        TeamRooms.graph_lock(conn)
        auth.browser(request, mutate=mutate, connection=conn)

    async def link_body(request, *, token=False):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                raise HTTPException(413, 'Request too large')
        if not raw and not token:
            return {}
        try:
            value = decode_json(bytes(raw), maximum_bytes=4096)
        except CodecError:
            raise HTTPException(400, 'Invalid JSON') from None
        if not isinstance(value, dict) or set(value) != ({'token'} if token else set()):
            raise HTTPException(400, 'Invalid friend request fields')
        return value

    def friend_link(conn, token, account, *, accepting=False):
        owner, expires = resolve_link(conn, token)
        target = person(conn, owner)
        if not target or (owner == account and accepting) or (owner != account and blocked(conn, account, owner)):
            raise HTTPException(404, 'Link unavailable')
        return owner, expires, target

    @router.post('/v1/social/friend-link', status_code=201)
    async def create_friend_link(request: Request, response: Response):
        account = link_actor(request, response, mutate=True)
        await link_body(request)
        with psycopg.connect(auth.dsn) as conn:
            link_transaction(request, conn, mutate=True)
            value = issue_link(conn, account)
            changed(conn, account, 'friends')
        return value

    @router.delete('/v1/social/friend-link')
    async def revoke_friend_link(request: Request, response: Response):
        account = link_actor(request, response, mutate=True)
        await link_body(request)
        with psycopg.connect(auth.dsn) as conn:
            link_transaction(request, conn, mutate=True)
            conn.execute('DELETE FROM team_friend_links WHERE account_id=%s', (account,))
            changed(conn, account, 'friends')
        return dict(status='revoked')

    @router.post('/v1/social/friend-links/preview')
    async def preview_friend_link(request: Request, response: Response):
        from team_device_commands import iso
        account = link_actor(request, response, mutate=True)
        token = (await link_body(request, token=True))['token']
        with psycopg.connect(auth.dsn) as conn:
            link_transaction(request, conn, mutate=True)
            owner, expires, target = friend_link(conn, token, account)
            return dict(ownerName=target['name'], expiresAt=iso(expires), alreadyFriends=owner != account and linked(conn, account, owner))

    @router.post('/v1/social/friend-links/accept')
    async def accept_friend_link(request: Request, response: Response):
        account = link_actor(request, response, mutate=True)
        token = (await link_body(request, token=True))['token']
        with psycopg.connect(auth.dsn) as conn:
            link_transaction(request, conn, mutate=True)
            owner, _, _ = friend_link(conn, token, account, accepting=True)
            a, b = lock_pair(conn, account, owner, available=True)
            value, _ = read_pair(conn, a, b)
            if value['state'] != 'accepted':
                value.update(state='accepted', requestedBy=owner)
                persist_pair(conn, a, b, value)
        return dict(status='accepted')

    return router
