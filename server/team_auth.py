from native_access_policy import is_retired_authorization_path
from native_principal import is_native_principal
"""Private team-demo identity and device authorization; never an external IdP substitute.

Cloudflare JWTs authenticate the browser boundary. Individual opaque sessions and
revocable device tokens authorize WegoH resources. Local Studio remains separate.
"""
import hashlib
from contextlib import nullcontext
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
import unicodedata
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import tuple_row
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import VisitCipher
from place_map_config import public_map_config
from team_data import changed
from access_identity import AccessVerifier, AccessIdentityError, origin_url
from account_handles import create_account, normalize_handle
from iphone_sessions import API_PREFIX as IPHONE_API_PREFIX, BROWSER_PREFIX as IPHONE_BROWSER_PREFIX

COOKIE = '__Host-wegoh_team'
CODE = re.compile(r'[A-HJ-NP-Z2-9]{8}')
VERIFIER = re.compile(r'[A-Za-z0-9._~-]{43,128}')
CHALLENGE = re.compile(r'[A-Za-z0-9_-]{43}')
SESSION_SECONDS = 14400
ACCESS_SECONDS = 900
DEVICE_SECONDS = 604800
NATIVE_CERT_HEADER = 'cf-cert-sha256'
NATIVE_CERT_STATUS = {'cf-cert-presented':'true', 'cf-cert-verified':'true', 'cf-cert-revoked':'false'}
CERTIFICATE_FINGERPRINT = re.compile(r'[a-f0-9]{64}')
SELF_ENROLLED_MEMBER = dict(name='WegoH 팀원', role='admin')
REVIEWER_MEMBER = dict(name='WegoH 심사자', role='creator')


def reviewer_domain(email):
    # Exact domain only; subdomains of an allowed domain are not reviewers.
    allowed = {d.strip().lower() for d in os.environ.get('WEGOH_REVIEWER_EMAIL_DOMAINS', '').split(',') if d.strip()}
    return email.rpartition('@')[2].lower() in allowed


def self_enrolled_member(email):
    return REVIEWER_MEMBER if reviewer_domain(email) else SELF_ENROLLED_MEMBER


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class TeamAuth:
    # Edge revocation is checked at new HTTP requests/upgrades, not inside an old WSS.
    native_socket_seconds = 60

    def __init__(self, dsn, secret, *, enrollment_only=False):
        self.dsn = dsn
        self.secret = secret.encode()
        self.enrollment_only = enrollment_only
        mode = os.environ.get('WEGOH_AUTH_MODE', 'local')
        if mode not in ('local', 'cloudflare'):
            raise RuntimeError('Unknown authentication mode')
        self.enabled = mode == 'cloudflare'
        self.native_relay_key=None
        if self.enabled and os.environ.get('WEGOH_NATIVE_ACCESS_ENABLED')=='1':
            from native_relay_credentials import load_relay_key
            self.native_relay_key=load_relay_key()
        self.public_origin = self.native_origin = self.issuer = self.audience = ''
        self.members_file = None
        self.verifier = None
        if not self.enabled:
            return
        if os.environ.get('WEGOH_LOCAL_STUDIO') == '1':
            raise RuntimeError('Shared demo cannot use the local common creator')
        self.public_origin = origin_url(os.environ.get('WEGOH_PUBLIC_ORIGIN', ''))
        self.issuer = origin_url(os.environ.get('WEGOH_ACCESS_ISSUER', ''), issuer=True)
        self.audience = os.environ.get('WEGOH_ACCESS_AUD', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{16,256}', self.audience):
            raise RuntimeError('An exact Access application audience is required')
        native = os.environ.get('WEGOH_NATIVE_API_ORIGIN', '')
        self.native_origin = origin_url(native) if native else ''
        if self.native_origin == self.public_origin:
            raise RuntimeError('Native API requires its own hostname')
        self.members_file = Path(os.environ.get('WEGOH_TEAM_MEMBERS_FILE', ''))
        self.verifier = AccessVerifier(self.issuer, self.audience, self.members_file)
        from reviewer_login import ReviewerLogin
        self.reviewer = ReviewerLogin(self)

    @property
    def hosts(self):
        iphone = getattr(self, 'iphone_sessions', None)
        return ['localhost', '127.0.0.1'] + [urlsplit(v).hostname for v in
            (self.public_origin, self.native_origin, getattr(iphone, 'origin', ''),
             getattr(getattr(self,'native_authorization',None),'origin','') if getattr(getattr(self,'native_authorization',None),'enabled',False) else '') if v]

    @property
    def jwks(self):
        return self.verifier.jwks if self.verifier else None

    @jwks.setter
    def jwks(self, value):
        self.verifier.jwks = value

    def members(self):
        return self.verifier.members()

    def edge_identity(self, request):
        try:
            return self.verifier.identity(request.headers, unlisted_member=(
                None if self.enrollment_only else self.unlisted_member))
        except AccessIdentityError as error:
            raise HTTPException(error.status_code, error.detail) from None

    @staticmethod
    def matches_self_enrollment(saved, email, subject):
        return (saved.get('accessSelfEnrolled') is True
                and saved['email'] == email and saved['subject'] == subject)

    def unlisted_member(self, account, email, subject):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT protected,account_status FROM team_accounts WHERE account_id=%s',
                               (account,)).fetchone()
        if row:
            if row[1] != 'active':
                raise AccessIdentityError(403, 'Team access denied')
            saved = VisitCipher().restore('team-account:' + account, 'identity', row[0])
            if not self.matches_self_enrollment(saved, email, subject):
                raise AccessIdentityError(403, 'Team access denied')
        return self_enrolled_member(email)

    def stored_member(self, saved, *, members=None, require_roster=False):
        if members is None:
            members = self.members()
        member = members.get(saved['email'])
        if member is None and not (self.enrollment_only or require_roster) and saved.get('accessSelfEnrolled') is True:
            return self_enrolled_member(saved['email'])
        return member

    def vehicle_member(self, saved, identity=None):
        # Vehicle connection keeps the explicit roster, plus self-enrolled reviewer domains.
        member = self.stored_member(saved, require_roster=True)
        if member is None and reviewer_domain(saved['email']):
            email, subject = (identity['email'], identity['subject']) if identity else (saved['email'], saved['subject'])
            if self.matches_self_enrollment(saved, email, subject):
                return REVIEWER_MEMBER
        return member

    def check_origin(self, request):
        if request.headers.get('origin') != self.public_origin:
            raise HTTPException(403, 'Origin denied')

    def csrf(self, token):
        return hmac.new(self.secret, ('wegoh-csrf-v1:' + token).encode(), hashlib.sha256).hexdigest()

    def browser(self, request, *, mutate=False, roles=None, optional=False, connection=None):
        identity = getattr(request.state, 'team_identity', None)
        token = request.cookies.get(COOKIE, '')
        if not identity or not token or len(token) > 100:
            if optional:
                return None
            raise HTTPException(401, 'Start a team session first')
        with (nullcontext(connection) if connection is not None else psycopg.connect(self.dsn)) as conn:
            row = conn.execute('SELECT creator_id FROM studio_sessions WHERE token_hash=%s '
                               'AND expires_at>now()', (hashed(token),)).fetchone()
        if not row or (row['creator_id'] if isinstance(row,dict) else row[0]) != identity['id']:
            if optional:
                return None
            raise HTTPException(401, 'Team session expired')
        if mutate:
            self.check_origin(request)
            if not hmac.compare_digest(request.headers.get('x-wegoh-csrf', '').encode(),
                                       self.csrf(token).encode()):
                raise HTTPException(403, 'CSRF verification failed')
        account = (self.current_account(identity['id'], connection=connection) if connection is not None
                   else self.current_account(identity['id']))
        if identity['role'] != account['role'] or (roles and account['role'] not in roles):
            raise HTTPException(403, 'Action not permitted')
        return dict(identity, displayName=account['displayName'], role=account['role'], handle=account['handle'])

    def capabilities(self):
        history=bool(getattr(self,'history_service',None)and self.history_service.enabled)
        return dict(drivingData=False,cautions=bool(getattr(self,'cautions_service',None)and self.cautions_service.enabled),friends=self.enabled, playlists=self.enabled,
                    pairing=bool(self.native_origin), vehicles=False,
                    vehicleReports=bool(getattr(self,'vehicle_service',None)and self.vehicle_service.enabled),
                    deviceCommandProtocol=bool(getattr(self,'device_command_service',None) and self.device_command_service.enabled),
                    roomMissions=bool(getattr(self,'mission_service',None)and self.mission_service.enabled), rooms=bool(getattr(self, 'room_service', None) and self.room_service.enabled), roomVoice=bool(getattr(self,'voice_service',None)and self.voice_service.enabled), roomMusic=bool(getattr(self,'room_music_service',None)and self.room_music_service.enabled), history=history,
                    historyVisits=history,historyRemix=bool(getattr(self,'history_remix_service',None)and self.history_remix_service.enabled),historyTraceIngest=history,historyTraceCapture=False,
                    historyPhotos=bool(getattr(self,'photos_service',None)and self.photos_service.enabled),historyPhotoUpload=bool(getattr(self,'photos_service',None)and self.photos_service.can_upload),historyReplay=False,historyExport=False)

    def status(self, request):
        identity = self.browser(request, optional=True)
        return dict(mode='team-demo', authenticated=bool(identity),
            user={key: identity[key] for key in ('id', 'displayName', 'role', 'handle')} if identity else None,
            csrfToken=self.csrf(request.cookies[COOKIE]) if identity else None,
            nativeApiEnabled=bool(self.native_origin), capabilities=self.capabilities(), placeMap=public_map_config())

    def rate(self, scope, *, limit=60):
        # Persistent atomic buckets: one worker/restart cannot reset the limit.
        # Do not trust CF-Connecting-IP/X-Forwarded-For from arbitrary callers.
        bucket = int(time.time()) // 60
        key = hashed(scope)
        with psycopg.connect(self.dsn) as conn:
            # Only expired rate metadata is pruned, never user records/history.
            conn.execute('DELETE FROM team_rate_limits WHERE bucket<%s', (bucket - 2,))
            hits = conn.execute('INSERT INTO team_rate_limits(scope_hash,bucket,hits) VALUES(%s,%s,1) '
                'ON CONFLICT(scope_hash) DO UPDATE SET bucket=excluded.bucket,hits=CASE '
                'WHEN team_rate_limits.bucket=excluded.bucket THEN team_rate_limits.hits+1 ELSE 1 END '
                'RETURNING hits', (key, bucket)).fetchone()[0]
        if hits > limit:
            raise HTTPException(429, 'Request limit exceeded', headers={'Retry-After': '60'})

    def current_account(self, account, *, connection=None, require_roster=False, vehicle=False, identity=None):
        database = getattr(connection, 'connection', connection)
        with (nullcontext(database) if database is not None else psycopg.connect(self.dsn)) as conn:
            with conn.cursor(row_factory=tuple_row) as cursor:
                if self.enrollment_only:
                    row = cursor.execute('SELECT protected FROM team_accounts WHERE account_id=%s', (account,)).fetchone()
                else:
                    row = cursor.execute("SELECT protected,handle FROM team_accounts WHERE account_id=%s AND account_status='active'", (account,)).fetchone()
        if not row:
            raise HTTPException(401, 'Account unavailable')
        saved = VisitCipher().restore('team-account:' + account, 'identity', row[0])
        member = (self.vehicle_member(saved, identity) if vehicle
                  else self.stored_member(saved, require_roster=require_roster))
        if not member:
            raise HTTPException(403, 'Team access denied')
        return dict(id=account, displayName=saved.get('displayName',member['name']), role=member['role'], handle=None if self.enrollment_only else row[1])

    def ensure_account(self, connection, identity):
        account_id = identity['id']
        with connection.cursor(row_factory=tuple_row) as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', (int(hashed('profile:' + account_id)[:15], 16),))
            old = cursor.execute('SELECT protected,account_status FROM team_accounts WHERE account_id=%s FOR UPDATE',
                                 (account_id,)).fetchone()
            if old and old[1] != 'active':
                raise HTTPException(403, 'Account unavailable')
            value = {key: identity[key] for key in ('email', 'subject', 'displayName')}
            member = self.members().get(value['email'])
            cipher = VisitCipher()
            if old:
                previous = cipher.restore('team-account:' + account_id, 'identity', old[0])
                auto_enrolled = previous.get('accessSelfEnrolled') is True
                if (auto_enrolled or member is None) and not self.matches_self_enrollment(
                        previous, value['email'], value['subject']):
                    raise HTTPException(403, 'Team access denied')
                if auto_enrolled:
                    value['accessSelfEnrolled'] = True
                for field in ('displayName', 'vehicleProfiles'):
                    if field in previous:
                        value[field] = previous[field]
            elif member is None:
                if identity.get('accessSelfEnrolled') is not True or self.enrollment_only:
                    raise HTTPException(403, 'Team access denied')
                value['accessSelfEnrolled'] = True
                value['displayName'] = self_enrolled_member(value['email'])['name']
            member = member or self_enrolled_member(value['email'])
            protected = cipher.protect('team-account:' + account_id, 'identity', value)
            if old:
                handle = cursor.execute('UPDATE team_accounts SET protected=%s WHERE account_id=%s RETURNING handle',
                                        (protected, account_id)).fetchone()[0]
            else:
                handle = create_account(cursor, account_id, protected)
        return dict(identity, displayName=value['displayName'], role=member['role'], handle=handle)

    def iphone(self, request, scope):
        service = getattr(self, 'iphone_sessions', None)
        if not service or not service.origin:
            raise HTTPException(404, 'IPHONE_ROUTE_NOT_FOUND')
        return service.authenticate(request, scope)

    def native_certificate(self, request):
        # This is trusted edge metadata, not an origin-side TLS verification.
        # The origin must stay loopback-only. Cloudflare Managed Transform
        # Add TLS client auth headers must overwrite all four fields, and
        # WAF must block unverified/revoked certificates on the native host.
        # Deploy only after observing forged-input overwrite at this origin.
        if (not self.native_origin
                or request.url.hostname != urlsplit(self.native_origin).hostname
                or not request.client or request.client.host not in ('127.0.0.1', '::1')):
            raise HTTPException(401, 'Native certificate required')
        for name, expected in NATIVE_CERT_STATUS.items():
            if request.headers.getlist(name) != [expected]:
                raise HTTPException(401, 'Native certificate required')
        values = request.headers.getlist(NATIVE_CERT_HEADER)
        if len(values) != 1 or not CERTIFICATE_FINGERPRINT.fullmatch(values[0]):
            raise HTTPException(401, 'Native certificate required')
        return values[0]

    @staticmethod
    def certificate_matches(value, certificate):
        stored = value.get('nativeCertificateSha256')
        return (isinstance(stored, str) and bool(CERTIFICATE_FINGERPRINT.fullmatch(stored))
                and hmac.compare_digest(stored, certificate))

    def device(self, request, *, connection=None):
        service = getattr(self, 'native_authorization', None)
        if service is None or not service.enabled:
            raise HTTPException(401, 'Device authentication required')
        from native_authorization import NativeAuthorizationError
        try:
            options = dict(enforce_route=request.scope.get('type') != 'websocket')
            if connection is not None:
                options['connection'] = connection
            identity = service.authenticate(request, **options)
        except NativeAuthorizationError as error:
            raise HTTPException(error.status, error.code) from None
        if not is_native_principal(identity):
            raise HTTPException(401, 'Device authentication required')
        return identity

    def boundary(self, request):
        """Every host/path is explicitly classified; no CORS/Access catch-all bypass."""
        if not self.enabled:
            return
        host = request.url.hostname
        path, method = request.url.path, request.method
        if is_retired_authorization_path(path):raise HTTPException(404, 'Not found')
        iphone = getattr(self, 'iphone_sessions', None)
        if iphone and iphone.host and host == iphone.host:
            iphone.api_boundary(request)
            return
        if path.startswith(IPHONE_API_PREFIX) and not path.startswith(IPHONE_BROWSER_PREFIX):
            raise HTTPException(404, 'IPHONE_ROUTE_NOT_FOUND')
        authorization=getattr(self,'native_authorization',None)
        if authorization and authorization.enabled and host==urlsplit(authorization.origin).hostname:
            authorization.renew_relay_boundary(request)
            return
        if host in ('127.0.0.1', 'localhost'):
            if (not request.client or request.client.host not in ('127.0.0.1', '::1')
                    or not ((method == 'GET' and path in ('/health/live', '/health/ready')) or path.startswith('/v1/moderation/'))):
                raise HTTPException(404, 'Not found')
            # Moderation still requires its server-only operator key below.
            return
        if host == urlsplit(self.public_origin).hostname:
            # Only /reviewer bypasses Access at the edge; it has its own cookie identity.
            if path == '/reviewer' or path.startswith('/reviewer/'):
                self.reviewer.boundary(request)
                return
            request.state.team_identity = self.edge_identity(request)
            if path.startswith('/v1/devices/token') or path.startswith('/v1/device-') or path.startswith('/v1/device/') or path in ('/v1/account', '/v1/device'):
                raise HTTPException(404, 'Not found')
            return
        if self.native_origin and host == urlsplit(self.native_origin).hostname:
            self.native_certificate(request)
            authorization_request = method == 'POST' and (path in ('/v1/device-authorizations', '/v1/device-sessions/exchange', '/v1/device-sessions/recover', '/v1/device-sessions/refresh', '/v1/device-sessions/rebind', '/v1/device-sessions/revoke') or re.fullmatch(r'/v1/device-sessions/[a-f0-9]{32}/revoke', path))
            if authorization_request:
                if request.url.query or any(name in request.headers for name in ('origin','cookie')):
                    raise HTTPException(403,'Native API requires a nonbrowser request')
                self.rate('native-v2-bootstrap-total', limit=120)
                return
            # Surface classification is exact policy membership, never authorization.
            from native_access_policy import required_scope,RouteDenied
            from native_functional_policy import is_functional_route
            try:required_scope(method,path)
            except RouteDenied:
                if not is_functional_route(method,path):
                    if path in ('/v1/social/trips','/v1/social/trip-links') or path.startswith(('/v1/social/trips/','/v1/social/trip-links/')):
                        raise HTTPException(403,'차량에서 사용할 수 없는 경로입니다.')
                    raise HTTPException(404,'Not found')
            self.rate('native-auth-total', limit=600)
            request.state.device_identity = self.device(request)
            return
        raise HTTPException(404, 'Not found')

    def router(self):
        router = APIRouter()
        if not self.enabled:
            return router

        async def body(request, fields):
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4096:
                    raise HTTPException(413, 'Request too large')
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                raise HTTPException(400, 'Invalid JSON') from None
            if not isinstance(data, dict) or set(data) != set(fields):
                raise HTTPException(400, 'Invalid request fields')
            return data

        @router.get('/v1/auth/session')
        def session(request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            return self.status(request)

        @router.post('/v1/auth/session')
        def login(request: Request, response: Response):
            self.check_origin(request)
            identity = request.state.team_identity
            self.rate('login:' + identity['id'], limit=15)
            token = secrets.token_urlsafe(32)
            with psycopg.connect(self.dsn) as conn:
                identity = self.ensure_account(conn, identity)
                old = request.cookies.get(COOKIE, '')
                if old:
                    conn.execute('DELETE FROM studio_sessions WHERE token_hash=%s AND creator_id=%s',
                                 (hashed(old), identity['id']))
                conn.execute("INSERT INTO studio_sessions(token_hash,creator_id,expires_at) VALUES(%s,%s,now()+interval '4 hours')",
                             (hashed(token), identity['id']))
            response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                                secure=True, samesite='strict', path='/')
            response.headers['Cache-Control'] = 'private, no-store'
            return dict(mode='team-demo', authenticated=True,
                user={k: identity[k] for k in ('id', 'displayName', 'role', 'handle')},
                csrfToken=self.csrf(token), nativeApiEnabled=bool(self.native_origin), capabilities=self.capabilities(), placeMap=public_map_config())

        @router.delete('/v1/auth/session')
        def logout(request: Request, response: Response):
            identity = self.browser(request, mutate=True)
            with psycopg.connect(self.dsn) as conn:
                conn.execute('DELETE FROM studio_sessions WHERE token_hash=%s AND creator_id=%s',
                             (hashed(request.cookies[COOKIE]), identity['id']))
            response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
            response.headers['Cache-Control'] = 'no-store'
            return dict(mode='team-demo', authenticated=False, user=None, csrfToken=None,
                        nativeApiEnabled=bool(self.native_origin), capabilities=self.capabilities(), placeMap=public_map_config())

        def iphone_profile(request, scope, *, connection=None, lock=False):
            if request.url.query:
                raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
            return self.iphone_sessions.authenticate(request, scope, connection=connection, lock=lock)

        @router.get('/v1/iphone/profile', include_in_schema=False)
        def iphone_get_profile(request: Request, response: Response):
            actor = iphone_profile(request, 'account:read')
            self.rate('iphone-profile:' + actor['id'], limit=60)
            response.headers['Cache-Control'] = 'private, no-store'
            return dict(user={key: actor[key] for key in ('id', 'displayName', 'handle')})

        @router.put('/v1/profile/handle')
        @router.put('/v1/iphone/profile/handle', include_in_schema=False)
        async def update_handle(request: Request, response: Response):
            iphone = request.url.path == '/v1/iphone/profile/handle'
            actor = iphone_profile(request, 'account:write') if iphone else self.browser(request, mutate=True)
            self.rate('handle-change:' + actor['id'], limit=5)
            data = await body(request, ('handle', 'expectedHandle'))
            handle = normalize_handle(data['handle'])
            expected = normalize_handle(data['expectedHandle'])
            try:
                with psycopg.connect(self.dsn) as conn:
                    current = (iphone_profile(request, 'account:write', connection=conn, lock=True)
                               if iphone else self.browser(request, mutate=True, connection=conn))
                    if current['id'] != actor['id']: raise HTTPException(401, 'Account changed')
                    conn.execute('SELECT pg_advisory_xact_lock(%s)', (int(hashed('profile:' + actor['id'])[:15], 16),))
                    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('account-handle-allocation',))
                    row = conn.execute('SELECT handle,handle_changed_at IS NOT NULL AND '
                        "handle_changed_at>now()-interval '24 hours' FROM team_accounts "
                        "WHERE account_id=%s AND account_status='active' FOR UPDATE", (actor['id'],)).fetchone()
                    if not row:
                        raise HTTPException(403, 'Account unavailable')
                    if row[0] != expected:
                        raise HTTPException(409, 'HANDLE_CHANGED')
                    if row[0] != handle:
                        if row[1]:
                            raise HTTPException(429, 'HANDLE_CHANGE_LIMIT', headers={'Retry-After': '86400'})
                        conn.execute('UPDATE team_accounts SET handle=%s,handle_changed_at=now() WHERE account_id=%s', (handle, actor['id']))
            except psycopg.errors.UniqueViolation:
                raise HTTPException(409, 'HANDLE_UNAVAILABLE') from None
            response.headers['Cache-Control'] = 'private, no-store'
            return dict(handle=handle)

        @router.put('/v1/iphone/profile', include_in_schema=False)
        @router.put('/v1/profile')
        @router.put('/v1/account')
        async def update_profile(request: Request, response: Response):
            from native_access_codec import decode_json,CodecError
            from native_authorization import read_body,NativeAuthorizationError
            native=is_native_principal(getattr(request.state,'device_identity',None))
            iphone=request.url.path=='/v1/iphone/profile'
            actor=(iphone_profile(request,'account:write') if iphone else
                   self.device(request) if native else self.browser(request,mutate=True))
            try:data=decode_json(await read_body(request),maximum_bytes=1024)
            except CodecError:raise HTTPException(400,'INVALID_PROFILE') from None
            except NativeAuthorizationError as error:raise HTTPException(error.status,error.code) from None
            if type(data)is not dict or set(data)!={'displayName','expectedDisplayName'}:raise HTTPException(400,'INVALID_PROFILE')
            name=data['displayName'];expected=data['expectedDisplayName']
            if (type(name)is not str or not 1<=len(name)<=30 or name!=name.strip()
                or any(unicodedata.category(c).startswith('C') for c in name)
                or type(expected)is not str or not 1<=len(expected)<=64):raise HTTPException(400,'INVALID_PROFILE')
            self.rate('profile:'+actor['id'],limit=15)
            from psycopg.rows import dict_row
            with psycopg.connect(self.dsn,row_factory=dict_row) as conn:
                if native:
                    service=self.native_authorization
                    initial=conn.execute('SELECT installation_key_id FROM native_v2_grants WHERE grant_id=%s',(actor['grantId'],)).fetchone()
                    if not initial:raise HTTPException(401,'INVALID_CREDENTIAL')
                    service.lock(conn,initial['installation_key_id'])
                    try:current=service.authenticate(request,connection=conn)
                    except NativeAuthorizationError as error:raise HTTPException(error.status,error.code) from None
                    if current['grantId']!=actor['grantId'] or current['credentialEpoch']!=actor['credentialEpoch']:raise HTTPException(401,'INVALID_CREDENTIAL')
                elif iphone:
                    current=iphone_profile(request,'account:write',connection=conn,lock=True)
                    if current['id']!=actor['id']:raise HTTPException(401,'Account changed')
                else:self.browser(request,mutate=True,connection=conn)
                conn.execute('SELECT pg_advisory_xact_lock(%s)',(int(hashed('profile:'+actor['id'])[:15],16),))
                row=conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s FOR UPDATE',(actor['id'],)).fetchone()
                if not row:raise HTTPException(401,'INVALID_CREDENTIAL')
                saved=VisitCipher().restore('team-account:'+actor['id'],'identity',row['protected'])
                member=self.stored_member(saved)
                if not member:raise HTTPException(403,'Team access denied')
                if saved.get('displayName',member['name'])!=expected:raise HTTPException(409,'PROFILE_CHANGED')
                saved['displayName']=name
                protected=VisitCipher().protect('team-account:'+actor['id'],'identity',saved)
                conn.execute('UPDATE team_accounts SET protected=%s WHERE account_id=%s',(protected,actor['id']))
                changed(conn,actor['id'],'devices')
                changed(conn,'profile-account:'+actor['id'],'devices')
            response.headers['Cache-Control']='private, no-store'
            return dict(user=dict(id=actor['id'],displayName=name))

        router.include_router(self.reviewer.router())

        from vehicle_profile import register_vehicle_profile
        register_vehicle_profile(router,self)

        @router.get('/v1/account')
        def account(request: Request):
            identity = request.state.device_identity
            return dict(user={k: identity[k] for k in (('id', 'displayName') if is_native_principal(identity) else ('id', 'displayName', 'role'))},
                        deviceId=identity['deviceId'])







        @router.get('/v1/devices')
        def devices(request: Request, response: Response):
            identity = self.browser(request)
            response.headers['Cache-Control'] = 'private, no-store'
            service = getattr(self, 'native_authorization', None)
            return dict(devices=service.list_owned_devices(identity['id']) if service and service.enabled else [])

        @router.delete('/v1/devices/{device_id}')
        def revoke(device_id: str, request: Request):
            identity = self.browser(request, mutate=True)
            service = getattr(self, 'native_authorization', None)
            if service and service.enabled and service.revoke_owned_device(identity['id'], device_id):
                return dict(status='revoked')
            raise HTTPException(404, 'Device unavailable')

        @router.delete('/v1/device')
        def revoke_self(request: Request):
            identity = request.state.device_identity
            if not is_native_principal(identity):
                raise HTTPException(401, 'Device authentication required')
            return self.native_authorization.revoke_authenticated(identity)

        return router
