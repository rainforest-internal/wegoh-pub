"""Session-bound APNs installations and transactional delivery for iPhone."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import logging
import re
import time
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, HTTPException, Request
from psycopg.rows import dict_row, tuple_row
from starlette.concurrency import run_in_threadpool

from deployment_gate import DeploymentGate
from iphone_sessions import json_fields
from private_records import PrivateRecordError, VisitCipher

INSTALLATION = re.compile(r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}')
DEVICE_TOKEN = re.compile(r'(?:[0-9a-f]{2}){32,256}')
ENVIRONMENT = re.compile(r'sandbox|production')
TTL = {'friend_request': 86400, 'friend_accepted': 86400, 'trip_invitation': 86400,
       'hand_raise': 60, 'hand_raise_reaction': 60}
SCOPE = {kind: 'friends:read' if kind.startswith('friend_') else 'trips:read' for kind in TTL}
logger = logging.getLogger(__name__)


def event_context(installation, binding, event):
    return f'{installation.hex}/{binding.hex}/{event.hex}'


def enqueue_push(conn, *, kind, actor, recipients, resource_id, trip_id=None):
    now = int(time.time())
    cipher = None
    for recipient in sorted(set(recipients) - {actor}):
        with conn.cursor(row_factory=tuple_row) as cursor:
            installations = cursor.execute(
                'SELECT i.installation_id,i.binding FROM iphone_push_installations i '
                'JOIN iphone_sessions s ON s.token_hash=i.session_hash AND s.account_id=i.account_id '
                'WHERE i.account_id=%s AND s.revoked_at IS NULL AND s.expires_at>%s AND %s=ANY(s.scopes) '
                'ORDER BY i.installation_id FOR KEY SHARE OF i', (recipient, now, SCOPE[kind])).fetchall()
        if not installations:
            continue
        if cipher is None:
            cipher = VisitCipher()
        event = uuid4()
        record = dict(kind=kind, actor_id=actor, recipient_id=recipient, resource_id=resource_id, trip_id=trip_id)
        for installation, binding in installations:
            protected = cipher.protect('iphone-push-event:' + recipient, event_context(installation, binding, event), record)
            conn.execute(
                'INSERT INTO iphone_push_outbox(event_id,installation_id,binding,recipient_id,'
                'protected,created_at,expires_at,next_attempt) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                (event, installation, binding, recipient, protected, now, now + TTL[kind], now))


class IPhonePush:
    def __init__(self, sessions):
        self.sessions = sessions

    def register(self, request, value):
        installation = UUID(value['installationId'])
        token = value['deviceToken']
        environment = value['environment']
        token_digest = hashlib.sha256(bytes.fromhex(token)).hexdigest()
        with self.sessions.db() as conn:
            account = self.sessions.authenticate(request, 'account:read', connection=conn, lock=True)['id']
            session_hash = self.sessions.token_hash(request)
            # Token rotation and account switches can change both unique keys in a single transaction.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('iphone-push-registration',0))")
            conn.execute('DELETE FROM iphone_push_installations WHERE environment=%s AND token_digest=%s '
                         'AND installation_id<>%s', (environment, token_digest, installation))
            current = conn.execute('SELECT session_hash,account_id,environment,token_digest,binding '
                                   'FROM iphone_push_installations WHERE installation_id=%s FOR UPDATE',
                                   (installation,)).fetchone()
            if current and (current['session_hash'], current['account_id'], current['environment'],
                            current['token_digest']) == (session_hash, account, environment, token_digest):
                conn.execute('UPDATE iphone_push_installations SET registered_ms=%s WHERE installation_id=%s',
                             (time.time_ns() // 1_000_000, installation))
            else:
                binding = uuid4()
                protected = VisitCipher().protect('iphone-push:' + account, binding.hex, token)
                conn.execute('DELETE FROM iphone_push_installations WHERE installation_id=%s', (installation,))
                conn.execute('INSERT INTO iphone_push_installations(installation_id,account_id,session_hash,'
                             'environment,token_digest,protected,registered_ms,binding) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                             (installation, account, session_hash, environment, token_digest, protected,
                              time.time_ns() // 1_000_000, binding))
        return {'registered': True}

    def unregister(self, request, value):
        with self.sessions.db() as conn:
            account = self.sessions.authenticate(request, 'account:read', connection=conn, lock=True)['id']
            conn.execute('DELETE FROM iphone_push_installations WHERE installation_id=%s AND account_id=%s '
                         'AND session_hash=%s', (UUID(value['installationId']), account, self.sessions.token_hash(request)))
        return {'registered': False}

    def router(self):
        router = APIRouter(include_in_schema=False)
        if not self.sessions.origin:
            return router

        async def fields(request, **patterns):
            self.sessions.api_boundary(request)
            if request.url.query:
                raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
            # Reject unsigned traffic before looking at its payload.
            account = await run_in_threadpool(self.sessions.authenticate, request, 'account:read')
            await run_in_threadpool(self.sessions.auth.rate, 'iphone-push:' + account['id'], limit=60)
            return await json_fields(request, installationId=INSTALLATION, **patterns)

        @router.put('/v1/iphone/push/installation')
        async def register(request: Request):
            value = await fields(request, deviceToken=DEVICE_TOKEN, environment=ENVIRONMENT)
            return await run_in_threadpool(self.register, request, value)

        @router.delete('/v1/iphone/push/installation')
        async def unregister(request: Request):
            value = await fields(request)
            return await run_in_threadpool(self.unregister, request, value)

        return router


class PushWorker:
    def __init__(self, auth, provider, *, clock=time.time):
        self.auth = auth
        self.provider = provider
        self.clock = clock

    def deliver_one(self):
        from iphone_push_events import push_event_visible
        now = int(self.clock())
        with psycopg.connect(self.auth.dsn) as conn:
            candidate = conn.execute('SELECT event_id,installation_id FROM iphone_push_outbox '
                                     'WHERE next_attempt<=%s ORDER BY next_attempt,event_id LIMIT 1', (now,)).fetchone()
            if candidate is None:
                return False
            # Domain writers take the exclusive membership lock before their session and relationship rows.
            conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended('social-membership',0))")
            with conn.cursor(row_factory=dict_row) as cursor:
                item = cursor.execute(
                    'SELECT o.*,i.account_id,i.environment,i.protected AS protected_token,i.registered_ms,s.revoked_at,'
                    's.expires_at AS session_expires,s.scopes FROM iphone_push_outbox o '
                    'JOIN iphone_push_installations i ON i.installation_id=o.installation_id AND i.binding=o.binding '
                    'JOIN iphone_sessions s ON s.token_hash=i.session_hash AND s.account_id=i.account_id '
                    'WHERE o.event_id=%s AND o.installation_id=%s AND o.next_attempt<=%s '
                    'FOR SHARE OF s,i SKIP LOCKED FOR UPDATE OF o SKIP LOCKED', (*candidate, now)).fetchone()
            if item is None:
                return False
            now = int(self.clock())
            if (item['account_id'] == item['recipient_id'] and item['revoked_at'] is None
                    and min(item['session_expires'], item['expires_at']) > now):
                cipher = VisitCipher()
                try:
                    event = cipher.restore('iphone-push-event:' + item['recipient_id'],
                                           event_context(item['installation_id'], item['binding'], item['event_id']),
                                           item['protected'])
                    if (event['recipient_id'] == item['recipient_id'] and SCOPE[event['kind']] in item['scopes']
                            and push_event_visible(conn, event, self.auth, now)):
                        token = cipher.restore('iphone-push:' + item['account_id'], item['binding'].hex, item['protected_token'])
                        if self._send(conn, item, event, token, now):
                            return True
                except PrivateRecordError:
                    logger.warning('iPhone notification record could not be verified')
            conn.execute('DELETE FROM iphone_push_outbox WHERE event_id=%s AND installation_id=%s', candidate)
        return True

    def _send(self, conn, item, event, token, now):
        try:
            status, reason, timestamp, retry = self.provider.send(
                token, item['environment'], event_id=item['event_id'].hex, kind=event['kind'],
                trip_id=event['trip_id'], recipient_id=item['recipient_id'],
                expires_at=min(item['expires_at'], item['session_expires']))
        except OSError:
            status, reason, timestamp, retry = 0, '', None, None
        if (status == 410 and reason in ('Unregistered', 'ExpiredToken') and timestamp is not None
                and timestamp >= item['registered_ms']):
            conn.execute('DELETE FROM iphone_push_installations WHERE installation_id=%s AND binding=%s '
                         'AND registered_ms<=%s', (item['installation_id'], item['binding'], timestamp))
        elif status == 0 or status == 429 or status >= 500 or status == 403:
            wait = max(retry or 0, min(900, 2 ** min(10, item['attempts'] + 1)), 900 if status >= 500 else 0)
            if now + wait < min(item['session_expires'], item['expires_at']):
                conn.execute('UPDATE iphone_push_outbox SET attempts=attempts+1,next_attempt=%s '
                             'WHERE event_id=%s AND installation_id=%s',
                             (now + wait, item['event_id'], item['installation_id']))
                return True
        return False


def push_lifespan(auth, revision):
    @asynccontextmanager
    async def lifespan(app):
        from iphone_apns import APNsProvider
        provider = APNsProvider.from_environment() if auth.iphone_sessions.origin else None
        if provider is None:
            yield
            return
        worker = PushWorker(auth, provider)
        gate = DeploymentGate(app, source_revision=revision())
        stopped = asyncio.Event()

        async def run():
            while not stopped.is_set():
                try:
                    if (not gate.path or gate.allowed(gate.state())) and await asyncio.to_thread(worker.deliver_one):
                        continue
                except Exception:
                    logger.warning('iPhone notification delivery temporarily unavailable')
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=1)
                except TimeoutError:
                    pass

        task = asyncio.create_task(run())
        try:
            yield
        finally:
            stopped.set()
            await task
            provider.close()
    return lifespan
