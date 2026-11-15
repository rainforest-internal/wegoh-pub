"""Browser-authorized iPhone sessions, separate from vehicle credentials."""
import asyncio
from contextlib import nullcontext
from html import escape
import hashlib
import hmac
import os
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg.rows import dict_row
from starlette.concurrency import run_in_threadpool

from access_identity import origin_url
from enrollment_crypto import challenge
from native_access_codec import CodecError, decode_json

API_PREFIX = '/v1/iphone/'
BROWSER_PREFIX = API_PREFIX + 'browser/'
LOGIN_PAGE = '/iphone-login'
DECISION_PATH = BROWSER_PREFIX + 'login/decision'
CALLBACK = 'io.wegoh.iphone://login/callback'
REQUEST_SECONDS = 300
SESSION_SECONDS = 604800
CURRENT_CONSENT_VERSION = 'v4'
# Keep the scopes for each disclosed consent immutable. The code hash domain
# records the approved version using the existing one-time receipt column.
CONSENT_VERSIONS = {
    'v4': ('code:consent-v4', ('account:read', 'account:write', 'maps:read', 'vehicles:manage',
                              'courses:read', 'courses:write', 'friends:read', 'friends:manage',
                              'trips:read', 'trips:manage')),
    'v1': ('code', ('account:read', 'maps:read', 'vehicles:manage')),
    'v3': ('code:consent-v3', ('account:read', 'account:write', 'maps:read', 'vehicles:manage',
                              'courses:read', 'courses:write', 'friends:read', 'friends:manage')),
    'v2': ('code:consent-v2', ('account:read', 'account:write', 'maps:read', 'vehicles:manage',
                              'courses:read', 'courses:write')),
}
SCOPES = CONSENT_VERSIONS[CURRENT_CONSENT_VERSION][1]
REQUEST_ID = re.compile(r'[a-f0-9]{32}')
NONCE = re.compile(r'[A-Za-z0-9_-]{43}')
VERIFIER = re.compile(r'[A-Za-z0-9._~-]{43,128}')


def fail(status, code):
    raise HTTPException(status, 'IPHONE_' + code)


def digest(purpose, value):
    return hashlib.sha256(('WegoH iPhone ' + purpose + '\n' + value).encode('ascii')).hexdigest()


async def body(request, content_type, *, maximum_bytes=2048):
    if request.headers.get('content-type', '').split(';', 1)[0].strip() != content_type:
        fail(400, 'INVALID_REQUEST')
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > maximum_bytes:
                    fail(413, 'REQUEST_TOO_LARGE')
    except TimeoutError:
        fail(408, 'REQUEST_TIMEOUT')
    return bytes(raw)


async def json_fields(request, **fields):
    try:
        value = decode_json(await body(request, 'application/json'), maximum_bytes=2048)
    except CodecError:
        fail(400, 'INVALID_REQUEST')
    if type(value) is not dict or value.keys() != fields.keys() or any(
            not isinstance(value[key], str) or not pattern.fullmatch(value[key])
            for key, pattern in fields.items()):
        fail(400, 'INVALID_REQUEST')
    return value


class IPhoneSessions:
    def __init__(self, auth, *, clock=time.time):
        self.auth = auth
        self.clock = clock
        configured = os.environ.get('WEGOH_IPHONE_API_ORIGIN', '') if auth.enabled else ''
        self.origin = origin_url(configured) if configured else ''
        self.host = urlsplit(self.origin).hostname
        enrollment_origin = auth.native_authorization.origin
        if self.origin and (self.origin in (auth.public_origin, auth.native_origin, enrollment_origin)
                            or self.host in ('localhost', '127.0.0.1', '::1')):
            raise RuntimeError('iPhone API requires a separate public hostname')

    def now(self):
        return int(self.clock())

    def db(self):
        return psycopg.connect(self.auth.dsn, row_factory=dict_row)

    def api_boundary(self, request):
        path = request.url.path
        if (not self.host or request.url.hostname != self.host or request.url.port not in (None, 443)
                or not path.startswith(API_PREFIX) or path.startswith(BROWSER_PREFIX)
                or not request.client or request.client.host not in ('127.0.0.1', '::1')):
            fail(404, 'ROUTE_NOT_FOUND')
        if any(name in request.headers for name in ('cookie', 'origin')):
            fail(400, 'INVALID_REQUEST')

    def browser_identity(self, request):
        if (not self.origin or request.url.hostname != urlsplit(self.auth.public_origin).hostname
                or request.url.port not in (None, 443)):
            fail(404, 'ROUTE_NOT_FOUND')
        actor = getattr(request.state, 'team_identity', None)
        if actor is None:
            fail(401, 'LOGIN_REQUIRED')
        return actor

    @staticmethod
    def lock_account(conn, account_id):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                     ('iphone-session:' + account_id,))

    def start(self, code_challenge, state):
        self.auth.rate('iphone-login-start', limit=120)
        request_id, now = secrets.token_hex(16), self.now()
        expires = now + REQUEST_SECONDS
        with self.db() as conn:
            conn.execute('DELETE FROM iphone_login_requests WHERE expires_at<=%s', (now - 3600,))
            conn.execute('DELETE FROM iphone_sessions WHERE expires_at<=%s', (now - 86400,))
            conn.execute(
                "INSERT INTO iphone_login_requests(request_id,callback_state,code_challenge,status,expires_at) "
                "VALUES(%s,%s,%s,'PENDING',%s)", (request_id, state, code_challenge, expires))
        return dict(requestId=request_id, expiresAt=expires,
                    authorizationUrl=f'{self.auth.public_origin}{LOGIN_PAGE}?request_id={request_id}')

    def login_request(self, conn, request_id, *, lock=False):
        row = conn.execute('SELECT * FROM iphone_login_requests WHERE request_id=%s'
                           + (' FOR UPDATE' if lock else ''), (request_id,)).fetchone()
        if not row:
            fail(404, 'LOGIN_NOT_FOUND')
        if row['expires_at'] <= self.now():
            fail(410, 'LOGIN_EXPIRED')
        return row

    def csrf(self, request_id, account_id, version):
        message = f'wegoh-iphone-login-{version}:{request_id}:{account_id}'.encode('ascii')
        return hmac.new(self.auth.secret, message, hashlib.sha256).hexdigest()

    def consent_page(self, request_id, actor):
        self.auth.rate('iphone-login-page:' + actor['id'], limit=30)
        with self.db() as conn:
            row = self.login_request(conn, request_id)
            if row['status'] != 'PENDING':
                fail(409, 'LOGIN_USED')
            try:
                account = self.auth.current_account(actor['id'], connection=conn)
            except HTTPException as error:
                if error.status_code != 401:
                    raise
                account = actor
        display_name = escape(account['displayName'])
        csrf = self.csrf(request_id, actor['id'], CURRENT_CONSENT_VERSION)
        return HTMLResponse(f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>iPhone 로그인 - WegoH</title>
  <link rel="stylesheet" href="/pleos-tokens.css">
  <link rel="stylesheet" href="/studio.css">
  <link rel="stylesheet" href="/enroll.css">
</head>
<body>
<main id="enrollment-main">
  <h1>WegoH iPhone 로그인</h1>
  <form action="{DECISION_PATH}" method="post" class="pairing-card">
    <p><strong>{display_name}</strong> 계정으로 iPhone 앱을 연결합니다.</p>
    <p>앱에서 내 프로필 확인·수정, 코스 조회·만들기·수정, 차량 연결, 장소 검색, 자동차 경로 조회, 친구 코드 검색·친구 요청·수락·거절·연결 해제·차단 관리, 여행 조회·만들기·초대·참여·차량 그룹 및 탑승 선택·픽업 및 드랍 장소 관리·위치 공유 설정·코스 추가·여행 시작을 사용할 수 있습니다. 로그인은 7일간 유지됩니다.</p>
    <input type="hidden" name="request_id" value="{request_id}">
    <input type="hidden" name="csrf" value="{csrf}">
    <div class="enrollment-actions">
      <button name="decision" value="approve" type="submit">로그인</button>
      <button name="decision" value="deny" type="submit" class="secondary">거절</button>
    </div>
  </form>
</main>
</body>
</html>""", headers={'Referrer-Policy': 'strict-origin'})

    def decide(self, request_id, actor, approved, consent_version):
        account_id = actor['id']
        self.auth.rate('iphone-login-decision:' + account_id, limit=15)
        with self.db() as conn:
            self.lock_account(conn, account_id)
            row = self.login_request(conn, request_id, lock=True)
            if row['status'] != 'PENDING':
                fail(409, 'LOGIN_USED')
            values = {'state': row['callback_state']}
            if approved:
                try:
                    self.auth.ensure_account(conn, actor)
                except HTTPException as error:
                    if error.status_code == 403:
                        fail(403, 'LOGIN_DENIED')
                    raise
                code = secrets.token_urlsafe(32)
                purpose, _ = CONSENT_VERSIONS[consent_version]
                conn.execute(
                    "UPDATE iphone_login_requests SET status='APPROVED',account_id=%s,code_hash=%s "
                    "WHERE request_id=%s", (account_id, digest(purpose, code), request_id))
                values['code'] = code
            else:
                conn.execute("UPDATE iphone_login_requests SET status='DENIED' WHERE request_id=%s",
                             (request_id,))
                values['error'] = 'access_denied'
        return RedirectResponse(CALLBACK + '?' + urlencode(values), status_code=303,
                                headers={'Referrer-Policy': 'no-referrer'})

    @staticmethod
    def verify(row, verifier):
        if not hmac.compare_digest(row['code_challenge'], challenge(verifier)):
            fail(401, 'INVALID_PROOF')

    def exchange(self, request_id, code, verifier):
        self.auth.rate('iphone-login-exchange', limit=120)
        with self.db() as conn:
            initial = self.login_request(conn, request_id)
            self.verify(initial, verifier)
            if initial['status'] == 'PENDING':
                fail(409, 'LOGIN_PENDING')
            if initial['account_id']:
                self.lock_account(conn, initial['account_id'])
            row = self.login_request(conn, request_id, lock=True)
            if row['status'] in ('DENIED', 'CANCELLED'):
                fail(403, 'LOGIN_DENIED')
            if row['status'] != 'APPROVED':
                fail(409, 'LOGIN_USED')
            for purpose, scopes in CONSENT_VERSIONS.values():
                if hmac.compare_digest(row['code_hash'] or '', digest(purpose, code)):
                    break
            else:
                fail(401, 'INVALID_PROOF')
            try:
                account = self.auth.current_account(row['account_id'], connection=conn)
            except HTTPException as error:
                if error.status_code in (401, 403):
                    fail(403, 'LOGIN_DENIED')
                raise
            token = secrets.token_urlsafe(32)
            expires = self.now() + SESSION_SECONDS
            conn.execute('INSERT INTO iphone_sessions(token_hash,account_id,scopes,expires_at) '
                         'VALUES(%s,%s,%s,%s)', (digest('session', token), account['id'], list(scopes), expires))
            conn.execute("UPDATE iphone_login_requests SET status='USED',code_hash=NULL WHERE request_id=%s",
                         (request_id,))
        return dict(self.session_view(account, scopes, expires), accessToken=token, tokenType='Bearer')

    def cancel(self, request_id, verifier):
        self.auth.rate('iphone-login-cancel', limit=120)
        with self.db() as conn:
            row = self.login_request(conn, request_id, lock=True)
            self.verify(row, verifier)
            if row['status'] == 'USED':
                fail(409, 'LOGIN_USED')
            if row['status'] in ('PENDING', 'APPROVED'):
                conn.execute("UPDATE iphone_login_requests SET status='CANCELLED',code_hash=NULL WHERE request_id=%s",
                             (request_id,))

    @staticmethod
    def session_view(account, scopes, expires):
        return dict(user={key: account[key] for key in ('id', 'displayName')},
                    scopes=list(scopes), expiresAt=expires)

    def token_hash(self, request):
        self.api_boundary(request)
        values = request.headers.getlist('authorization')
        if len(values) != 1 or not values[0].startswith('Bearer ') or not NONCE.fullmatch(values[0][7:]):
            fail(401, 'SESSION_REQUIRED')
        return digest('session', values[0][7:])

    def authenticate(self, request, scope, *, connection=None, lock=False):
        token_hash = self.token_hash(request)
        with (self.db() if connection is None else nullcontext(connection)) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.execute('SELECT account_id,scopes,expires_at,revoked_at FROM iphone_sessions '
                                     'WHERE token_hash=%s' + (' FOR UPDATE' if lock else ''),
                                     (token_hash,)).fetchone()
            if not row:
                fail(401, 'SESSION_REQUIRED')
            if row['revoked_at'] is not None:
                fail(401, 'SESSION_REVOKED')
            if row['expires_at'] <= self.now():
                fail(401, 'SESSION_EXPIRED')
            try:
                account = self.auth.current_account(row['account_id'], connection=conn)
            except HTTPException as error:
                if error.status_code not in (401, 403):
                    raise
                self.revoke_token(conn, token_hash)
            else:
                if scope not in SCOPES or scope not in row['scopes']:
                    fail(403, 'SCOPE_DENIED')
                return dict(account, scopes=row['scopes'], expiresAt=row['expires_at'])
        fail(401, 'SESSION_REVOKED')

    def revoke_token(self, conn, token_hash):
        conn.execute('UPDATE iphone_sessions SET revoked_at=%s WHERE token_hash=%s AND revoked_at IS NULL',
                     (self.now(), token_hash))

    def logout(self, request):
        token_hash = self.token_hash(request)
        self.authenticate(request, 'account:read')
        with self.db() as conn:
            self.revoke_token(conn, token_hash)

    def revoke_owned(self, request):
        self.browser_identity(request)
        actor = self.auth.browser(request, mutate=True)
        self.auth.rate('iphone-session-revoke:' + actor['id'], limit=15)
        with self.db() as conn:
            self.lock_account(conn, actor['id'])
            self.auth.browser(request, mutate=True, connection=conn)
            conn.execute('UPDATE iphone_sessions SET revoked_at=%s WHERE account_id=%s AND revoked_at IS NULL',
                         (self.now(), actor['id']))
            conn.execute("UPDATE iphone_login_requests SET status='CANCELLED',code_hash=NULL "
                         "WHERE account_id=%s AND status='APPROVED'", (actor['id'],))

    def router(self):
        router = APIRouter(include_in_schema=False)
        if not self.origin:
            return router

        def app_request(request):
            self.api_boundary(request)
            if request.url.query:
                fail(400, 'INVALID_REQUEST')

        @router.post(API_PREFIX + 'login/requests', status_code=201)
        async def start(request: Request):
            app_request(request)
            value = await json_fields(request, codeChallenge=NONCE, state=NONCE)
            return await run_in_threadpool(self.start, value['codeChallenge'], value['state'])

        @router.get(LOGIN_PAGE)
        def consent(request: Request):
            actor = self.browser_identity(request)
            pairs = list(request.query_params.multi_items())
            if len(pairs) != 1 or pairs[0][0] != 'request_id' or not REQUEST_ID.fullmatch(pairs[0][1]):
                fail(400, 'INVALID_REQUEST')
            return self.consent_page(pairs[0][1], actor)

        @router.post(DECISION_PATH)
        async def decide(request: Request):
            actor = self.browser_identity(request)
            self.auth.check_origin(request)
            raw = await body(request, 'application/x-www-form-urlencoded')
            try:
                form = parse_qs(raw.decode('ascii'), strict_parsing=True, max_num_fields=3)
            except (UnicodeError, ValueError):
                fail(400, 'INVALID_REQUEST')
            if request.url.query or set(form) != {'request_id', 'csrf', 'decision'} or any(
                    len(values) != 1 for values in form.values()):
                fail(400, 'INVALID_REQUEST')
            request_id, csrf, decision = (form[key][0] for key in ('request_id', 'csrf', 'decision'))
            if not REQUEST_ID.fullmatch(request_id) or decision not in ('approve', 'deny'):
                fail(400, 'INVALID_REQUEST')
            if not re.fullmatch(r'[a-f0-9]{64}', csrf):
                fail(403, 'LOGIN_CSRF')
            for version in CONSENT_VERSIONS:
                if hmac.compare_digest(csrf, self.csrf(request_id, actor['id'], version)):
                    break
            else:
                fail(403, 'LOGIN_CSRF')
            return await run_in_threadpool(self.decide, request_id, actor, decision == 'approve', version)

        @router.post(API_PREFIX + 'login/exchange')
        async def exchange(request: Request):
            app_request(request)
            value = await json_fields(request, requestId=REQUEST_ID, code=NONCE, codeVerifier=VERIFIER)
            return await run_in_threadpool(self.exchange, value['requestId'], value['code'], value['codeVerifier'])

        @router.post(API_PREFIX + 'login/cancel', status_code=204)
        async def cancel(request: Request):
            app_request(request)
            value = await json_fields(request, requestId=REQUEST_ID, codeVerifier=VERIFIER)
            await run_in_threadpool(self.cancel, value['requestId'], value['codeVerifier'])
            return Response(status_code=204)

        @router.get(API_PREFIX + 'session')
        def session(request: Request):
            app_request(request)
            account = self.authenticate(request, 'account:read')
            return self.session_view(account, account['scopes'], account['expiresAt'])

        @router.delete(API_PREFIX + 'session', status_code=204)
        def logout(request: Request):
            app_request(request)
            self.logout(request)
            return Response(status_code=204)

        @router.delete(BROWSER_PREFIX + 'sessions', status_code=204)
        def revoke_owned(request: Request):
            self.revoke_owned(request)
            return Response(status_code=204)

        return router
