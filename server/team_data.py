from native_access_policy import AUTHORIZATION_VERSION
from native_principal import is_native_principal
"""Individual preparation metadata and bounded authenticated change notifications.

REST is authoritative. WebSockets only invalidate named resources, never send
locations, tokens, names, or playlist contents. Reconnection always snapshots.
"""
import asyncio
import json
import re
import secrets
import time
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from private_records import VisitCipher
from starlette.concurrency import run_in_threadpool
from native_events import visible_resources as native_visible_resources
from native_access_policy import event_resources, ScopeDenied


async def close_socket(socket, code=1008):
    # A disconnected transport may fail even while rejecting/closing a socket.
    # This only contains cleanup errors; authentication and DB failures stay outside.
    try:
        await socket.close(code=code)
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass


def changed(conn, account, resource, *, legacy_only=False):
    if resource not in ('courses', 'playlists', 'devices', 'friends', 'rooms', 'history', 'vehicle', 'content', 'recommendations', 'cautions'):
        raise ValueError('Unknown change resource')
    conn.execute('INSERT INTO team_resource_versions(account_id,resource,revision) VALUES(%s,%s,1) '
        'ON CONFLICT(account_id,resource) DO UPDATE SET revision=team_resource_versions.revision+1',
        (account, resource))

    if not legacy_only and (account == '*' or re.fullmatch(r'team-[a-f0-9]{40}', account)):
        from team_event_versions import bump
        bump(conn, 'event-account:' + account, resource)


def create_router(auth):
    router = APIRouter()
    if not auth.enabled:
        return router

    def iphone(request):
        return request.url.path.startswith('/v1/iphone/')

    def identity(request, *, mutate=False, connection=None):
        if iphone(request):
            if request.query_params:
                raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
            return auth.iphone_sessions.authenticate(request, 'account:write' if mutate else 'account:read',
                connection=connection, lock=mutate and connection is not None)
        device = getattr(request.state, 'device_identity', None)
        if device and not mutate:
            return device
        return auth.browser(request, mutate=mutate)

    def revalidate(request, owner, conn, *, mutate=False):
        if iphone(request) and identity(request, mutate=mutate, connection=conn)['id'] != owner:
            raise HTTPException(401, 'AUTHENTICATION_CHANGED')

    def row_value(owner, row):
        value = VisitCipher().restore('team-playlist:' + owner, row[0], row[1])
        return dict(id=row[0], name=value['name'], tracks=value['tracks'], revision=row[2], updatedAt=row[3])

    async def read_value(request, *, update=False):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 262144:
                raise HTTPException(413, 'Playlist request too large')
        try:
            if iphone(request):
                from native_functional_identity import business_json
                value = business_json(request, bytes(raw), maximum=262144)
            else:
                value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid JSON') from None
        fields = {'name', 'tracks', 'revision'} if update else {'name', 'tracks'}
        if not isinstance(value, dict) or set(value) != fields:
            raise HTTPException(400, 'Invalid playlist fields')
        def text(item, limit):
            return (isinstance(item, str) and 1 <= len(item.strip()) <= limit
                    and not any(ord(char) < 32 for char in item))
        if not text(value['name'], 80) or not isinstance(value['tracks'], list) or len(value['tracks']) > 100:
            raise HTTPException(400, 'Invalid playlist')
        if update and (type(value['revision']) is not int or not 1 <= value['revision'] <= 2147483647):
            raise HTTPException(400, 'Invalid playlist revision')
        tracks, ids = [], set()
        for track in value['tracks']:
            if (not isinstance(track, dict) or set(track) not in ({'title', 'url'}, {'id', 'title', 'url'})
                    or not text(track['title'], 120) or not text(track['url'], 2048)):
                raise HTTPException(400, 'Invalid playlist track')
            try:
                url = urlsplit(track['url'])
                if (url.scheme != 'https' or not url.hostname or url.username or url.password
                        or url.port not in (None, 443) or any(c.isspace() for c in track['url'])):
                    raise ValueError('Unsafe track URL')
            except ValueError:
                raise HTTPException(400, 'Use an HTTPS track link') from None
            track_id = track.get('id', secrets.token_hex(16))
            if not isinstance(track_id, str) or not re.fullmatch(r'[a-f0-9]{32}', track_id) or track_id in ids:
                raise HTTPException(400, 'Invalid or duplicate track ID')
            ids.add(track_id)
            tracks.append(dict(id=track_id, title=track['title'].strip(), url=track['url']))
        return dict(name=value['name'].strip(), tracks=tracks), value.get('revision')

    @router.get('/v1/playlists')
    @router.get('/v1/iphone/playlists', include_in_schema=False)
    def playlists(request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        owner = identity(request)['id']
        with psycopg.connect(auth.dsn) as conn:
            revalidate(request, owner, conn, mutate=request.method not in ('GET', 'HEAD'))
            rows = conn.execute('SELECT playlist_id,protected,revision,updated_at FROM team_playlists '
                'WHERE account_id=%s ORDER BY updated_at DESC,playlist_id LIMIT 100', (owner,)).fetchall()
        return dict(playlists=[row_value(owner, row) for row in rows])

    @router.get('/v1/playlists/{playlist_id}')
    @router.get('/v1/iphone/playlists/{playlist_id}', include_in_schema=False)
    def playlist(playlist_id: str, request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        owner = identity(request)['id']
        with psycopg.connect(auth.dsn) as conn:
            revalidate(request, owner, conn, mutate=request.method not in ('GET', 'HEAD'))
            row = conn.execute('SELECT playlist_id,protected,revision,updated_at FROM team_playlists '
                'WHERE playlist_id=%s AND account_id=%s', (playlist_id, owner)).fetchone()
        if not row:
            raise HTTPException(404, 'Playlist unavailable')
        return row_value(owner, row)

    @router.post('/v1/playlists', status_code=201)
    @router.post('/v1/iphone/playlists', include_in_schema=False, status_code=201)
    async def create(request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        owner = identity(request, mutate=True)['id']
        auth.rate('playlist-write:' + owner, limit=30)
        value, _ = await read_value(request)
        playlist_id = secrets.token_hex(16)
        protected = VisitCipher().protect('team-playlist:' + owner, playlist_id, value)
        with psycopg.connect(auth.dsn) as conn:
            revalidate(request, owner, conn, mutate=request.method not in ('GET', 'HEAD'))
            # Serialize per-owner capacity with no hidden truncation/deletion.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('playlists:' + owner,))
            if conn.execute('SELECT count(*) FROM team_playlists WHERE account_id=%s', (owner,)).fetchone()[0] >= 100:
                raise HTTPException(409, 'Playlist limit reached; manage existing lists')
            row = conn.execute('INSERT INTO team_playlists(playlist_id,account_id,protected) VALUES(%s,%s,%s) '
                'RETURNING playlist_id,protected,revision,updated_at', (playlist_id, owner, protected)).fetchone()
            changed(conn, owner, 'playlists')
        return row_value(owner, row)

    @router.put('/v1/playlists/{playlist_id}')
    @router.put('/v1/iphone/playlists/{playlist_id}', include_in_schema=False)
    async def update(playlist_id: str, request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        owner = identity(request, mutate=True)['id']
        auth.rate('playlist-write:' + owner, limit=30)
        value, revision = await read_value(request, update=True)
        protected = VisitCipher().protect('team-playlist:' + owner, playlist_id, value)
        with psycopg.connect(auth.dsn) as conn:
            music=getattr(auth,'room_music_service',None)
            if music:music.rooms.graph_lock(conn)
            revalidate(request, owner, conn, mutate=True)
            row = conn.execute('SELECT revision FROM team_playlists WHERE playlist_id=%s AND account_id=%s FOR UPDATE',
                (playlist_id, owner)).fetchone()
            if not row:
                raise HTTPException(404, 'Playlist unavailable')
            if row[0] != revision:
                raise HTTPException(409, 'Playlist changed; reload before editing')
            row = conn.execute('UPDATE team_playlists SET protected=%s,revision=revision+1,updated_at=now() '
                'WHERE playlist_id=%s AND account_id=%s RETURNING playlist_id,protected,revision,updated_at',
                (protected, playlist_id, owner)).fetchone()
            if music:music.invalidate_playlist(conn,owner,playlist_id)
            changed(conn, owner, 'playlists')
        return row_value(owner, row)

    @router.delete('/v1/playlists/{playlist_id}')
    @router.delete('/v1/iphone/playlists/{playlist_id}', include_in_schema=False)
    async def delete(playlist_id: str, request: Request, response: Response):
        response.headers['Cache-Control'] = 'private, no-store'
        owner = identity(request, mutate=True)['id']
        auth.rate('playlist-write:' + owner, limit=30)
        expected_revision = None
        if iphone(request):
            from iphone_sessions import body
            from native_functional_identity import business_json
            data = business_json(request, await body(request, 'application/json', maximum_bytes=4096), maximum=4096)
            if set(data) != {'revision'} or type(data['revision']) is not int or not 1 <= data['revision'] <= 2147483647:
                raise HTTPException(400, 'Invalid playlist revision')
            expected_revision = data['revision']
        with psycopg.connect(auth.dsn) as conn:
            music=getattr(auth,'room_music_service',None)
            if music:music.rooms.graph_lock(conn)
            revalidate(request, owner, conn, mutate=True)
            if expected_revision is not None:
                current = conn.execute('SELECT revision FROM team_playlists WHERE playlist_id=%s AND account_id=%s FOR UPDATE',
                    (playlist_id, owner)).fetchone()
                if not current:
                    raise HTTPException(404, 'Playlist unavailable')
                if current[0] != expected_revision:
                    raise HTTPException(409, 'Playlist changed; reload before deleting')
            row = conn.execute('DELETE FROM team_playlists WHERE playlist_id=%s AND account_id=%s RETURNING playlist_id',
                (playlist_id, owner)).fetchone()
            if not row:
                raise HTTPException(404, 'Playlist unavailable')
            if music:music.invalidate_playlist(conn,owner,playlist_id)
            changed(conn, owner, 'playlists')
        return dict(status='deleted')

    def authenticate_socket(socket):
        # Browser credentials are never accepted in URL/subprotocols. Native
        # clients use the standard Authorization header and their own hostname.
        from team_event_versions import CHAT_PROTOCOL, PROTOCOL
        protocols = socket.headers.getlist('sec-websocket-protocol')
        if socket.url.query or protocols not in ([], [PROTOCOL], [CHAT_PROTOCOL]):
            raise HTTPException(403, 'WebSocket credentials must not use URLs or subprotocols')
        host = socket.url.hostname
        if host == urlsplit(auth.public_origin).hostname:
            auth.check_origin(socket)
            socket.state.team_identity = auth.edge_identity(socket)
            return auth.browser(socket)
        if auth.native_origin and host == urlsplit(auth.native_origin).hostname:
            if socket.headers.get('origin') or protocols == [CHAT_PROTOCOL]:
                raise HTTPException(403, 'Native WebSocket must not use browser credentials')
            return auth.device(socket)
        raise HTTPException(403, 'WebSocket host denied')

    def visible_resources(account):
        if is_native_principal(account):
            return frozenset(event_resources(AUTHORIZATION_VERSION, 'GET', '/v1/events', frozenset(account['scopes'])))
        return native_visible_resources(auth, account)

    def versions(account,resources, fine=False, chat=False):
        owner = account['id']
        with psycopg.connect(auth.dsn) as conn:
            rooms = getattr(auth, 'room_service', None)
            if rooms and rooms.enabled: rooms.notify_expired(conn)
            if fine:
                from team_event_versions import versions as fine_versions
                return fine_versions(auth, conn, account, resources, chat=chat)
            all_versions = {(a, r): v for a, r, v in conn.execute('SELECT account_id,resource,revision '
                'FROM team_resource_versions WHERE account_id IN (%s,%s)', (owner, '*')).fetchall()}
            result = {key:v for key,v in all_versions.items() if key[1] in resources and not (is_native_principal(account) and key[1] == 'devices')}
            if is_native_principal(account) and 'devices' in resources:
                # Only this installation's base and functional authority invalidates
                # its devices feed. No other device's private consent is disclosed.
                own = conn.execute('SELECT g.device_revision,COALESCE(f.revision,0),'
                    "COALESCE(f.state='ACTIVE' AND f.expires_at>extract(epoch FROM now()),false) "
                    'FROM native_v2_grants g LEFT JOIN native_functional_authorizations f '
                    'ON f.grant_id=g.grant_id AND f.device_id=g.device_id '
                    'AND f.installation_key_id=g.installation_key_id '
                    "WHERE g.grant_id=%s AND g.device_id=%s AND g.account_id=%s AND g.state='TOKEN_ISSUED'",
                    (account['grantId'], account['deviceId'], owner)).fetchone()
                if own:
                    room_music = getattr(auth, 'room_music_access', None)
                    room_stamp = room_music.data_stamp(conn, account) if room_music else ()
                    room_voice = getattr(auth, 'room_voice_access', None)
                    voice_stamp = room_voice.data_stamp(conn, account) if room_voice else ()
                    command_stamp=conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='devices'",('command-device:'+account['deviceId'],)).fetchone()
                    profile_stamp=conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='devices'",('profile-account:'+owner,)).fetchone()
                    from psycopg.rows import dict_row
                    with conn.cursor(row_factory=dict_row)as cursor:
                        functional=cursor.execute("SELECT * FROM native_functional_authorizations WHERE grant_id=%s AND device_id=%s AND state='ACTIVE' AND expires_at>extract(epoch FROM now())",(account['grantId'],account['deviceId'])).fetchone()
                    service=getattr(auth,'functional_access',None)
                    from native_functional_defaults import account_purposes
                    purposes=account_purposes(service.payload(functional)['approvedPurposes'])if service and service.enabled and functional else frozenset()
                    trip_stamp = conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='rooms'",
                        ('trip-account:' + owner,)).fetchone() if 'rooms:read' in purposes else None
                    domains={'friends':'friends:read','rooms':'rooms:read','history':'history:read','recommendations':'recommendations:use','cautions':'cautions:read','vehicle':'vehicle-reports:read'}
                    social_stamp=tuple((resource,all_versions.get((owner,resource),0),all_versions.get(('*',resource),0))for resource,purpose in domains.items()if purpose in purposes)
                    result[(owner, 'devices')] = tuple(own) + (room_stamp,voice_stamp,command_stamp[0]if command_stamp else 0,profile_stamp[0]if profile_stamp else 0,social_stamp,trip_stamp[0] if trip_stamp else 0)
            return result

    def acquire(owner):
        # DB leases bound memory and work across workers; expiry handles crashes.
        lease = secrets.token_hex(16)
        with psycopg.connect(auth.dsn) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('sockets:' + owner,))
            conn.execute('DELETE FROM team_socket_leases WHERE expires_at<=now()')
            if conn.execute('SELECT count(*) FROM team_socket_leases WHERE account_id=%s', (owner,)).fetchone()[0] >= 16:
                raise HTTPException(429, 'Too many active connections')
            conn.execute("INSERT INTO team_socket_leases VALUES(%s,%s,now()+interval '30 seconds')", (lease, owner))
        return lease

    def renew(lease):
        with psycopg.connect(auth.dsn) as conn:
            if not conn.execute("UPDATE team_socket_leases SET expires_at=now()+interval '30 seconds' "
                                'WHERE lease_id=%s RETURNING lease_id', (lease,)).fetchone():
                raise HTTPException(401, 'Connection lease expired')

    def release(lease):
        with psycopg.connect(auth.dsn) as conn:
            conn.execute('DELETE FROM team_socket_leases WHERE lease_id=%s', (lease,))

    @router.websocket('/v1/events')
    async def events(socket: WebSocket):
        lease = None
        accepted = False
        try:
            account = await run_in_threadpool(authenticate_socket, socket)
            await run_in_threadpool(auth.rate, 'socket-open:' + account['id'], limit=30)
            allowed = await run_in_threadpool(visible_resources, account)
            lease = await run_in_threadpool(acquire, account['id'])
            from team_event_versions import CHAT_PROTOCOL, PROTOCOL
            protocol = socket.headers.get('sec-websocket-protocol')
            fine = protocol in (PROTOCOL, CHAT_PROTOCOL)
            chat = protocol == CHAT_PROTOCOL
            await socket.accept(subprotocol=protocol if fine else None)
            accepted = True
            previous = await run_in_threadpool(versions, account, allowed, fine, chat)
            seq, epoch = 0, secrets.token_hex(8)
            await asyncio.wait_for(socket.send_json(dict(type='snapshot', epoch=epoch, seq=seq,
                **(dict(versions=previous) if fine else dict(resources=sorted(allowed))))), timeout=3)
            heartbeat = renewed = opened = time.monotonic()
            while True:
                # No unbounded producer queue: coalesce the fixed allowed resource
                # versions and revalidate identity/session/device every second.
                try:
                    message = await asyncio.wait_for(socket.receive(), timeout=1)
                except asyncio.TimeoutError:
                    message = None
                if message:
                    if message['type'] == 'websocket.disconnect':
                        break
                    await close_socket(socket)
                    break  # This feed does not accept commands/client payloads.
                fresh = await run_in_threadpool(authenticate_socket, socket)
                current_allowed = await run_in_threadpool(visible_resources, fresh)
                if (current_allowed != allowed or fresh['id'] != account['id'] or fresh['role'] != account['role']
                    or any(fresh.get(k) != account.get(k) for k in ('grantId', 'credentialEpoch', 'slotRevision'))):
                    await close_socket(socket, 4003)
                    break
                current = await run_in_threadpool(versions, account, allowed, fine, chat)
                resources = sorted({key if fine else key[1] for key in set(current) | set(previous) if current.get(key) != previous.get(key)})
                if resources:
                    seq += 1
                    await asyncio.wait_for(socket.send_json(dict(type='invalidate', epoch=epoch, seq=seq,
                        **(dict(versions={key: current.get(key) for key in resources}) if fine else dict(resources=resources)))), timeout=3)
                    previous = current
                now = time.monotonic()
                if account.get('deviceId') and now - opened >= auth.native_socket_seconds:
                    # Reconnect through the edge so certificate revocation can be
                    # evaluated again. Existing header values cannot attest it.
                    await close_socket(socket)
                    break
                if now - renewed >= 10:
                    await run_in_threadpool(renew, lease)
                    renewed = now
                if now - heartbeat >= 20:
                    await asyncio.wait_for(socket.send_json(dict(type='heartbeat', epoch=epoch, seq=seq)), timeout=3)
                    heartbeat = now
        except (HTTPException, ScopeDenied):
            await close_socket(socket, 4003 if accepted else 1008)
        except (RuntimeError, psycopg.Error, OSError, asyncio.TimeoutError):
            await close_socket(socket, 1011 if accepted else 1008)
        except WebSocketDisconnect:
            pass
        finally:
            if lease:
                try:
                    await run_in_threadpool(release, lease)
                except (psycopg.Error, OSError):
                    pass  # The 30-second DB lease still expires after failures.

    return router
