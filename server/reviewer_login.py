"""Reviewer sign-in under /reviewer only.

An address whose domain exactly matches WEGOH_REVIEWER_EMAIL_DOMAINS starts a
reviewer session. The cookie is scoped to /reviewer, the account is a creator
reviewer account and the session reaches nothing but vehicle connection
approval. Rate limited.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from private_records import VisitCipher

PREFIX = '/reviewer'
COOKIE = '__Secure-wegoh_reviewer'
SESSION_SECONDS = 604800
SUBJECT_PREFIX = 'reviewer:'
# RFC 5322 dot-atom local part; quoted local parts are not accepted.
ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
LOCAL = re.compile(ATOM + r'(?:\.' + ATOM + r')*')
DOMAIN = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}')
TOKEN = re.compile(r'v1\.(team-[a-f0-9]{40})\.([0-9]{10})\.([a-f0-9]{64})')
ASSETS = {'reviewer.js': 'text/javascript', 'pleos-tokens.css': 'text/css', 'studio.css': 'text/css',
          'enroll.css': 'text/css', 'favicon.svg': 'image/svg+xml', 'native-access-wire.json': 'application/json'}
CONNECTION = re.compile(PREFIX + r'/v1/connections/[^/]{1,16}')


def domains():
    return {d.strip().lower() for d in os.environ.get('WEGOH_REVIEWER_EMAIL_DOMAINS', '').split(',') if d.strip()}


def reviewer_email(value):
    """Return the normalized reviewer address, or None. Exact domain only, no subdomains."""
    if type(value) is not str or not 3 <= len(value) <= 254 or value.count('@') != 1:
        return None
    local, domain = value.split('@')
    domain = domain.lower()
    if not 1 <= len(local) <= 64 or not LOCAL.fullmatch(local) or not DOMAIN.fullmatch(domain):
        return None
    if domain not in domains():
        return None
    return (local + '@' + domain).casefold()


class ReviewerLogin:
    def __init__(self, auth):
        self.auth = auth
        self.key = hmac.new(auth.secret, b'wegoh-reviewer-session-v1', hashlib.sha256).digest()
        self.web = Path(os.environ.get('WEGOH_WEB_DIR', str(Path(__file__).parent / 'web')))

    @property
    def enabled(self):
        return bool(domains())

    # ------------------------------------------------------------------ boundary
    def boundary(self, request):
        """Exact /reviewer routes only; every other path under it is 404."""
        path, method = request.url.path, request.method
        if not self.enabled:
            raise HTTPException(404, 'Not found')
        allowed = ((method == 'GET' and (path == PREFIX or path in {PREFIX + '/assets/' + n for n in ASSETS}
                                         or path == PREFIX + '/v1/session'))
                   or (method == 'POST' and path == PREFIX + '/v1/login')
                   or (method == 'DELETE' and path == PREFIX + '/v1/session')
                   or (method in ('GET', 'POST', 'DELETE') and CONNECTION.fullmatch(path)))
        if not allowed:
            raise HTTPException(404, 'Not found')
        if request.url.query and path != PREFIX:
            raise HTTPException(400, 'Invalid request')
        self.auth.rate('reviewer-total', limit=600)

    def client_address(self, request):
        # Loopback origin behind the tunnel: Cloudflare overwrites CF-Connecting-IP.
        host = request.client.host if request.client else ''
        if host in ('127.0.0.1', '::1'):
            return request.headers.get('cf-connecting-ip', host)[:64]
        return host

    def check_mutation(self, request, token=None):
        self.auth.check_origin(request)
        if request.headers.get('sec-fetch-site', 'same-origin') not in ('same-origin', 'none'):
            raise HTTPException(403, 'Origin denied')
        if token is not None and not hmac.compare_digest(
                request.headers.get('x-wegoh-csrf', '').encode(), self.csrf(token).encode()):
            raise HTTPException(403, 'CSRF verification failed')

    # ------------------------------------------------------------------- session
    def account_id(self, email):
        subject = SUBJECT_PREFIX + email
        return 'team-' + hashlib.sha256((self.auth.issuer + '\0' + subject).encode()).hexdigest()[:40], subject

    def sign(self, account, expires):
        return hmac.new(self.key, ('session:' + account + ':' + str(expires)).encode(), hashlib.sha256).hexdigest()

    def token(self, account, expires):
        return 'v1.' + account + '.' + str(expires) + '.' + self.sign(account, expires)

    def csrf(self, token):
        return hmac.new(self.key, ('csrf:' + token).encode(), hashlib.sha256).hexdigest()

    def identity(self, request, *, optional=False):
        token = request.cookies.get(COOKIE, '')
        match = TOKEN.fullmatch(token) if len(token) <= 200 else None
        if (not match or not hmac.compare_digest(match[3], self.sign(match[1], int(match[2])))
                or int(match[2]) <= time.time()):
            if optional:
                return None, None
            raise HTTPException(401, 'Reviewer sign-in required')
        account = match[1]
        with psycopg.connect(self.auth.dsn) as conn:
            row = conn.execute("SELECT protected FROM team_accounts WHERE account_id=%s AND account_status='active'",
                               (account,)).fetchone()
        if not row:
            if optional:
                return None, None
            raise HTTPException(401, 'Reviewer sign-in required')
        saved = VisitCipher().restore('team-account:' + account, 'identity', row[0])
        email = saved.get('email', '')
        if (saved.get('accessSelfEnrolled') is not True or saved.get('subject') != SUBJECT_PREFIX + email
                or reviewer_email(email) != email or email in self.auth.members()
                or self.account_id(email)[0] != account):
            raise HTTPException(403, 'Team access denied')
        owner = dict(id=account, email=email, subject=saved['subject'])
        current = self.auth.current_account(account, vehicle=True, identity=owner)
        if current['role'] != 'creator':
            raise HTTPException(403, 'Action not permitted')
        from api_observability import note_identity
        note_identity(account)
        return dict(owner, displayName=current['displayName'], role=current['role']), token

    def view(self, identity, token):
        if not identity:
            return dict(authenticated=False, user=None, csrfToken=None)
        return dict(authenticated=True, user=dict(displayName=identity['displayName'], role=identity['role']),
                    csrfToken=self.csrf(token))

    def login(self, request, raw):
        self.check_mutation(request)
        self.auth.rate('reviewer-login-total', limit=60)
        self.auth.rate('reviewer-login-ip:' + self.client_address(request), limit=10)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid JSON') from None
        if type(data) is not dict or set(data) != {'email'}:
            raise HTTPException(400, 'Invalid request fields')
        email = reviewer_email(data['email'])
        if email is None:
            raise HTTPException(403, 'REVIEWER_EMAIL_DENIED')
        # Roster members keep their Access sign-in and roster role.
        if email in self.auth.members():
            raise HTTPException(403, 'REVIEWER_EMAIL_DENIED')
        account, subject = self.account_id(email)
        from team_auth import REVIEWER_MEMBER
        with psycopg.connect(self.auth.dsn) as conn:
            identity = self.auth.ensure_account(conn, dict(id=account, email=email, subject=subject,
                displayName=REVIEWER_MEMBER['name'], role=REVIEWER_MEMBER['role'], accessSelfEnrolled=True))
        if identity['role'] != 'creator':
            raise HTTPException(403, 'Team access denied')
        from api_observability import note_identity
        note_identity(account)
        token = self.token(account, int(time.time()) + SESSION_SECONDS)
        return identity, token

    # -------------------------------------------------------------------- router
    def router(self):
        router = APIRouter()

        def cookie(response, token):
            response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=True,
                                samesite='strict', path=PREFIX)
            response.headers['Cache-Control'] = 'private, no-store'

        async def body(request):
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 1024:
                    raise HTTPException(413, 'Request too large')
            return bytes(raw)

        @router.get(PREFIX, include_in_schema=False)
        def page():
            return FileResponse(self.web / 'reviewer.html', media_type='text/html',
                                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})

        @router.get(PREFIX + '/assets/{name}', include_in_schema=False)
        def asset(name: str):
            if name not in ASSETS:
                raise HTTPException(404, 'Not found')
            return FileResponse(self.web / name, media_type=ASSETS[name], headers={'Cache-Control': 'no-store'})

        @router.get(PREFIX + '/v1/session', include_in_schema=False)
        def session(request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            return self.view(*self.identity(request, optional=True))

        @router.post(PREFIX + '/v1/login', include_in_schema=False)
        async def login(request: Request, response: Response):
            identity, token = await run_in_threadpool(self.login, request, await body(request))
            cookie(response, token)
            return dict(authenticated=True, user=dict(displayName=identity['displayName'], role=identity['role']),
                        csrfToken=self.csrf(token))

        @router.delete(PREFIX + '/v1/session', include_in_schema=False)
        def logout(request: Request, response: Response):
            self.check_mutation(request)
            response.delete_cookie(COOKIE, path=PREFIX, secure=True, httponly=True, samesite='strict')
            response.headers['Cache-Control'] = 'private, no-store'
            return self.view(None, None)

        from native_authorization import NativeAuthorizationError, error_response, http_error_response, read_body

        def service():
            authorization = getattr(self.auth, 'native_authorization', None)
            if authorization is None or not authorization.enabled:
                raise HTTPException(404, 'Not found')
            return authorization

        @router.get(PREFIX + '/v1/connections/{user_code}', include_in_schema=False)
        def detail(user_code: str, request: Request):
            try:
                identity, _ = self.identity(request)
                self.auth.rate('reviewer-connection-read:' + identity['id'], limit=60)
                return service().detail(user_code, identity)
            except NativeAuthorizationError as error:
                return error_response(error)
            except HTTPException as error:
                return http_error_response(error)

        async def decide(user_code, request, deny):
            try:
                identity, token = await run_in_threadpool(self.identity, request)
                self.check_mutation(request, token)
                await run_in_threadpool(self.auth.rate, 'reviewer-connection-decision:' + identity['id'], limit=30)
                return await run_in_threadpool(service().approve, user_code, await read_body(request), identity, deny=deny)
            except NativeAuthorizationError as error:
                return error_response(error)
            except HTTPException as error:
                return http_error_response(error)

        @router.post(PREFIX + '/v1/connections/{user_code}', include_in_schema=False)
        async def approve(user_code: str, request: Request):
            return await decide(user_code, request, False)

        @router.delete(PREFIX + '/v1/connections/{user_code}', include_in_schema=False)
        async def deny(user_code: str, request: Request):
            return await decide(user_code, request, True)

        return router
