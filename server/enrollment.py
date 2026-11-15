"""Isolated initial certificate registration, never a native API mTLS exception."""
import asyncio
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from access_identity import origin_url
from private_records import VisitCipher
from enrollment_crypto import (B64, CODE, ID, EnrollmentError, IssuanceUncertain,
    challenge, digest, proof_message, public_bytes, validate_csr, verify_proof)

TTL = 300
INTERVAL = 5
MAX_BODY = 12288
MAX_RETAINED = 1000


def fail(status, code, retry=None):
    return HTTPException(status, code, headers={'Retry-After': str(retry)} if retry else None)


async def body(request, fields):
    if request.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/json':
        raise fail(415, 'JSON_REQUIRED')
    raw = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_BODY:
                    raise fail(413, 'REQUEST_TOO_LARGE')
    except TimeoutError:
        raise fail(408, 'REQUEST_TIMEOUT') from None
    try:
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError()
                value[key] = item
            return value
        value = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(value, dict) or set(value) != set(fields):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise fail(400, 'INVALID_REQUEST') from None


class EnrollmentService:
    def __init__(self, auth, *, origin=None, issuer=None, clock=time.time):
        self.auth, self.issuer, self.clock = auth, issuer, clock
        configured = origin if origin is not None else os.environ.get('WEGOH_ENROLLMENT_ORIGIN', '')
        self.origin = origin_url(configured) if configured else ''
        if self.origin and self.origin in (auth.public_origin, auth.native_origin):
            raise EnrollmentError('ENROLLMENT_REQUIRES_SEPARATE_HOST')

    def available(self, *, issue=False):
        if not self.auth.enabled or not self.origin or (issue and self.issuer is None):
            raise fail(503, 'ENROLLMENT_UNAVAILABLE')

    def public_boundary(self, request):
        self.available(issue=True)
        if (request.url.hostname != urlsplit(self.origin).hostname
                or request.url.port not in (None, 443)
                or not request.client or request.client.host not in ('127.0.0.1', '::1')
                or any(name in request.headers for name in ('origin', 'cookie', 'authorization'))
                or request.url.query):
            raise fail(404, 'NOT_FOUND')
        allowed = request.method == 'POST' and (request.url.path == '/v1/enrollments'
            or re.fullmatch(r'/v1/enrollments/[a-f0-9]{32}/claim', request.url.path))
        if not allowed:
            raise fail(404, 'NOT_FOUND')
        self.auth.rate('enrollment-public-total', limit=120)

    def _record(self, row):
        return VisitCipher().restore('enrollment', row[0], row[4])

    def _save(self, conn, key, record, state=None):
        protected = VisitCipher().protect('enrollment', key, record)
        if state is None:
            conn.execute('UPDATE vehicle_enrollments SET protected=%s WHERE enrollment_id=%s', (protected, key))
        else:
            conn.execute('UPDATE vehicle_enrollments SET protected=%s,state=%s WHERE enrollment_id=%s',
                (protected, state, key))

    def _load(self, conn, key, *, code=False, allow_expired=False):
        field = 'user_code' if code else 'enrollment_id'
        row = conn.execute('SELECT enrollment_id,user_code,state,expires_at,protected,next_poll FROM '
            'vehicle_enrollments WHERE ' + field + '=%s FOR UPDATE', (key,)).fetchone()
        if row is None:
            raise fail(404, 'ENROLLMENT_NOT_FOUND')
        if not allow_expired and row[3] <= int(self.clock()):
            raise fail(410, 'ENROLLMENT_EXPIRED')
        return row

    def begin(self, value):
        self.available(issue=True)
        policy=getattr(self.auth,'legacy_transition',None)
        if policy:policy.require_creation(self.clock())
        self.auth.rate('enrollment-begin-total', limit=20)
        name, code_challenge = value.get('name'), value.get('codeChallenge')
        if (not isinstance(name, str) or not 1 <= len(name) <= 60 or name != name.strip()
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or not isinstance(code_challenge, str) or not B64.fullmatch(code_challenge)):
            raise fail(400, 'INVALID_REQUEST')
        try:
            csr = validate_csr(value.get('csrPem'))
        except EnrollmentError as error:
            raise fail(400, str(error)) from None
        key, nonce = secrets.token_hex(16), secrets.token_urlsafe(32)
        code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
        expires = int(self.clock()) + TTL
        value = dict(name=name, csrPem=value['csrPem'], publicKeySha256=digest(public_bytes(csr.public_key())),
            codeChallenge=code_challenge, proofNonce=nonce, owner=None)
        with psycopg.connect(self.auth.dsn) as conn:
            # Bound anonymous storage and serialize SPKI de-duplication across workers.
            conn.execute('SELECT pg_advisory_xact_lock(715019221)')
            retained, active = conn.execute('SELECT count(*),count(*) FILTER (WHERE expires_at>%s) '
                'FROM vehicle_enrollments', (int(self.clock()),)).fetchone()
            if retained >= MAX_RETAINED:
                # Preserve all existing records, but never allow anonymous storage to grow forever.
                raise fail(429, 'ENROLLMENT_STORAGE_LIMIT', 3600)
            if active >= 100:
                raise fail(429, 'ENROLLMENT_CAPACITY_REACHED', 60)
            spki = value['publicKeySha256']
            duplicate = conn.execute('SELECT 1 FROM vehicle_enrollments WHERE public_key_hash=%s '
                'AND expires_at>%s', (spki, int(self.clock()))).fetchone()
            if duplicate:
                raise fail(409, 'ENROLLMENT_ALREADY_PENDING')
            conn.execute('INSERT INTO vehicle_enrollments '
                '(enrollment_id,user_code,public_key_hash,state,expires_at,protected,next_poll) '
                "VALUES(%s,%s,%s,'pending',%s,%s,0)",
                (key, code, spki, expires, VisitCipher().protect('enrollment', key, value)))
        return dict(enrollmentId=key, userCode=code, verificationUri=self.auth.public_origin + '/enroll.html#' + code,
            proofNonce=nonce, expiresIn=TTL, interval=INTERVAL)

    def detail(self, code, owner):
        self.available()
        if not CODE.fullmatch(code):
            raise fail(404, 'ENROLLMENT_NOT_FOUND')
        self.auth.rate('enrollment-details:' + owner, limit=30)
        with psycopg.connect(self.auth.dsn) as conn:
            row = self._load(conn, code, code=True)
            record = self._record(row)
            if record['owner'] not in (None, owner):
                raise fail(404, 'ENROLLMENT_NOT_FOUND')
            if row[2] == 'denied':
                raise fail(410, 'ENROLLMENT_CANCELLED')
            return dict(userCode=row[1], name=record['name'], publicKeySha256=record['publicKeySha256'],
                state=row[2], expiresAt=row[3], grantsPersonalAccess=False)

    def approve(self, code, owner):
        self.available()
        self.auth.current_account(owner)
        self.auth.rate('enrollment-approve:' + owner, limit=5)
        with psycopg.connect(self.auth.dsn) as conn:
            row = self._load(conn, code, code=True)
            record = self._record(row)
            if row[2] == 'approved' and record['owner'] == owner:
                return dict(status='approved')
            if row[2] != 'pending' or record['owner'] is not None:
                raise fail(409, 'ENROLLMENT_NOT_PENDING')
            # Per-account issuance ceiling; certificate quotas are not an authz model.
            owner_key = digest(owner.encode())
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('enrollment-owner:' + owner,))
            count = conn.execute('SELECT count(*) FROM vehicle_enrollments WHERE owner_hash=%s '
                "AND state IN ('approved','issuing','issued','uncertain') AND created_at>now()-interval '1 day'",
                (owner_key,)).fetchone()[0]
            if count >= 5:
                raise fail(429, 'ENROLLMENT_ACCOUNT_LIMIT', 3600)
            record['owner'] = owner
            self._save(conn, row[0], record, 'approved')
            conn.execute('UPDATE vehicle_enrollments SET owner_hash=%s WHERE enrollment_id=%s', (owner_key, row[0]))
        return dict(status='approved')

    def cancel(self, code, owner):
        self.available()
        with psycopg.connect(self.auth.dsn) as conn:
            row = self._load(conn, code, code=True)
            record = self._record(row)
            if record['owner'] not in (None, owner):
                raise fail(404, 'ENROLLMENT_NOT_FOUND')
            if row[2] not in ('pending', 'approved', 'denied'):
                raise fail(409, 'ISSUANCE_ALREADY_STARTED')
            record['owner'] = owner
            self._save(conn, row[0], record, 'denied')
        return dict(status='cancelled')

    def claim(self, key, value):
        self.available(issue=True)
        if not ID.fullmatch(key):
            raise fail(404, 'ENROLLMENT_NOT_FOUND')
        now = int(self.clock())
        with psycopg.connect(self.auth.dsn) as conn:
            row = self._load(conn, key)
            record = self._record(row)
            try:
                if not hmac.compare_digest(challenge(value.get('codeVerifier')), record['codeChallenge']):
                    raise EnrollmentError('INVALID_PROOF')
                verify_proof(validate_csr(record['csrPem']), proof_message(key, record['proofNonce'],
                    record['codeChallenge']), value.get('signature'))
            except EnrollmentError:
                raise fail(403, 'ENROLLMENT_PROOF_REQUIRED') from None
            if row[5] > now:
                raise fail(429, 'SLOW_DOWN', row[5] - now)
            conn.execute('UPDATE vehicle_enrollments SET next_poll=%s WHERE enrollment_id=%s', (now + INTERVAL, key))
            state = row[2]
            if state == 'pending':
                return dict(status='authorization_pending', retryAfter=INTERVAL)
            if state == 'denied':
                raise fail(403, 'ENROLLMENT_CANCELLED')
            self.auth.current_account(record['owner'])
            if state == 'issued':
                return dict(status='issued', **record['receipt'])
            if state == 'uncertain':
                raise fail(409, 'ISSUANCE_UNCERTAIN')
            if state == 'issuing':
                # A lost worker cannot repeat a non-idempotent Cloudflare POST.
                return dict(status='issuance_pending', retryAfter=INTERVAL)
            if state != 'approved':
                raise fail(409, 'ENROLLMENT_STATE_INVALID')
            policy=getattr(self.auth,'legacy_transition',None)
            if policy:policy.require_creation(self.clock())
            self._save(conn, key, record, 'issuing')
        # 'issuing' has committed before external IO. No automatic retry on any failure.
        try:
            receipt = self.issuer.issue(record['csrPem'])
        except Exception:
            with psycopg.connect(self.auth.dsn) as conn:
                conn.execute("UPDATE vehicle_enrollments SET state='uncertain' WHERE enrollment_id=%s AND state='issuing'", (key,))
            raise fail(409, 'ISSUANCE_UNCERTAIN') from None
        with psycopg.connect(self.auth.dsn) as conn:
            current = self._load(conn, key, allow_expired=True)
            fresh = self._record(current)
            if current[2] != 'issuing' or fresh['owner'] != record['owner']:
                raise fail(409, 'ISSUANCE_UNCERTAIN')
            fresh['receipt'] = receipt
            self._save(conn, key, fresh, 'issued')
        # Re-check current membership after external IO, before disclosing the receipt.
        self.auth.current_account(record['owner'])
        if current[3] <= int(self.clock()):
            raise fail(410, 'ENROLLMENT_EXPIRED')
        return dict(status='issued', **receipt)

    def bootstrap_router(self):
        router = APIRouter()
        @router.post('/v1/enrollments', status_code=201)
        async def begin(request: Request):
            value = await body(request, ('name', 'csrPem', 'codeChallenge'))
            return await run_in_threadpool(self.begin, value)
        @router.post('/v1/enrollments/{enrollment_id}/claim')
        async def claim(enrollment_id: str, request: Request):
            value = await body(request, ('codeVerifier', 'signature'))
            return await run_in_threadpool(self.claim, enrollment_id, value)
        return router

    def browser_router(self):
        router = APIRouter()
        @router.get('/v1/enrollments/{user_code}')
        def detail(user_code: str, request: Request):
            return self.detail(user_code, self.auth.browser(request)['id'])
        @router.post('/v1/enrollments/{user_code}/approve')
        async def approve(user_code: str, request: Request):
            owner = await run_in_threadpool(self.auth.browser, request, mutate=True)
            await body(request, ())
            return await run_in_threadpool(self.approve, user_code, owner['id'])
        @router.delete('/v1/enrollments/{user_code}')
        def cancel(user_code: str, request: Request):
            return self.cancel(user_code, self.auth.browser(request, mutate=True)['id'])
        return router
