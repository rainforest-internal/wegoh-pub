"""Bounded, process-local complete voice messages; no audio files or DB payloads."""
import base64
import binascii
import hashlib
import json
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from iphone_sessions import body
from native_authorization import NativeAuthorizationError, hash_secret
from native_functional_identity import _scope_check, functional_body, transaction_actor
from native_functional_policy import FunctionalError
from native_principal import is_native_principal
from team_friends import blocked
from team_trip_context import resolve_trip_context

ID = re.compile(r'[a-f0-9]{32}')
CURSOR = re.compile(r'([a-f0-9]{32}):(0|[1-9][0-9]{0,15})')
MAX_PCM = 480000
MAX_BODY = 700000


def fail(status, code):
    raise HTTPException(status, 'VOICE_CLIP_' + code)


@dataclass(repr=False)
class Clip:
    id: str
    trip: str
    room: str
    speaker: str
    sequence: int
    pcm: bytes
    created: float
    source: dict
    audience: dict
    delivered: dict = field(default_factory=dict)

    def metadata(self):
        return dict(id=self.id, speakerId=self.speaker, sequence=self.sequence, durationMs=len(self.pcm) // 32)


@dataclass(repr=False)
class ClipReceipt:
    id: str
    speaker: str
    sequence: int
    duration_ms: int
    pcm_digest: bytes
    created: float

    def metadata(self):
        return dict(id=self.id, speakerId=self.speaker, sequence=self.sequence, durationMs=self.duration_ms)


class VoiceClipMemory:
    def __init__(self, *, clock=time.monotonic, ttl=90, max_bytes=32*1024*1024, max_count=64, trip_limit=20, max_receipts=2048):
        self.clock, self.ttl, self.max_bytes, self.max_count, self.trip_limit = clock, ttl, max_bytes, max_count, trip_limit
        self.boot = secrets.token_hex(16)
        self.sequence = 0
        self.clips = OrderedDict()
        self.receipts = OrderedDict()
        self.max_receipts = max_receipts
        self.lock = threading.RLock()
        self.timer = None

    def _prune(self):
        now = self.clock()
        for key, clip in tuple(self.clips.items()):
            if now - clip.created >= self.ttl:
                self.clips.pop(key)
        for key, receipt in tuple(self.receipts.items()):
            if now - receipt.created >= self.ttl:
                self.receipts.pop(key)

    def _expire(self):
        with self.lock:
            self.timer = None
            self._prune()
            self._schedule_expiry()

    def _schedule_expiry(self):
        if self.receipts and self.timer is None:
            delay = max(0.01, min(value.created for value in self.receipts.values()) + self.ttl - self.clock())
            self.timer = threading.Timer(delay, self._expire)
            self.timer.daemon = True
            self.timer.start()

    def publish(self, trip, room, source, audience, client_id, pcm):
        with self.lock:
            self._prune()
            receipt_key = (trip, source['account'], client_id)
            digest = hashlib.sha256(pcm).digest()
            previous = self.receipts.get(receipt_key)
            if previous is not None:
                if previous.pcm_digest != digest:
                    fail(409, 'MESSAGE_CONFLICT')
                return previous
            if len(self.receipts) >= self.max_receipts:
                fail(429, 'CAPACITY')
            if len(pcm) > self.max_bytes:
                fail(413, 'TOO_LARGE')
            for key, clip in tuple(self.clips.items()):
                if clip.trip == trip and sum(value.trip == trip for value in self.clips.values()) >= self.trip_limit:
                    self.clips.pop(key)
            while self.clips and (len(self.clips) >= self.max_count or
                    sum(len(value.pcm) for value in self.clips.values()) + len(pcm) > self.max_bytes):
                self.clips.popitem(last=False)
            self.sequence += 1
            clip = Clip(secrets.token_hex(16), trip, room, source['account'], self.sequence,
                        pcm, self.clock(), dict(source), dict(audience))
            receipt = ClipReceipt(clip.id, clip.speaker, clip.sequence, len(pcm)//32, digest, clip.created)
            self.clips[clip.id] = clip
            self.receipts[receipt_key] = receipt
            self._schedule_expiry()
            return receipt

    def feed(self, trip, cursor):
        with self.lock:
            self._prune()
            latest = self.boot + ':' + str(self.sequence)
            if not cursor:
                return latest, []
            match = CURSOR.fullmatch(cursor)
            if not match:
                fail(400, 'INVALID_CURSOR')
            if match[1] != self.boot or int(match[2]) > self.sequence:
                return latest, []
            return latest, [clip for clip in self.clips.values()
                            if clip.trip == trip and clip.sequence > int(match[2])]

    def get(self, identifier):
        with self.lock:
            self._prune()
            value = self.clips.get(identifier)
            if value is None:
                fail(404, 'UNAVAILABLE')
            return value

    def delivered(self, clip, actor, stamp):
        with self.lock:
            if self.clips.get(clip.id) is not clip:
                fail(404, 'UNAVAILABLE')
            clip.delivered[actor] = stamp

    def clear(self):
        with self.lock:
            self.clips.clear()
            self.receipts.clear()
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None

    def withdraw(self, trip, account=None):
        with self.lock:
            for key, clip in tuple(self.clips.items()):
                if clip.trip == trip and (account is None or clip.speaker == account):
                    self.clips.pop(key)


class TeamVoiceClips:
    def __init__(self, voice, *, memory=None):
        self.voice, self.auth = voice, voice.auth
        self.memory = memory or VoiceClipMemory()

    def _context(self, conn, trip, actor):
        context = resolve_trip_context(self.auth, conn, trip, actor, states=('active',))
        self.voice.rooms.access(conn, context['roomId'], actor, trip_context=True)
        if any(peer != actor and membership['state'] == 'accepted' and blocked(conn, actor, peer)
               for peer, membership in context['members'].items()):
            fail(404, 'UNAVAILABLE')
        _, member = self.auth.trip_service.voice_membership(conn, trip, context['roomId'], actor)
        if not member['participating']:
            fail(403, 'PARTICIPATION_REQUIRED')
        return context, (member['memberJoinedAt'], member['revision'])

    def _native_direction(self, conn, principal, functional, context, *, transmit):
        try:
            value = self.auth.room_voice_access.resolved_trip_snapshot(conn, principal, functional, context)
        except FunctionalError as error:
            raise HTTPException(error.status, error.code) from None
        purpose = 'rooms:interact' if transmit else 'rooms:read'
        if purpose not in functional['approvedPurposes'] or not value['permissions']['transmitVoice' if transmit else 'receiveVoice']:
            fail(403, 'DIRECTION_REQUIRED')

    def _actor(self, request, conn, trip, *, transmit=False):
        if not self.voice.enabled:
            fail(404, 'UNAVAILABLE')
        self.voice.rooms.graph_lock(conn)
        phone = request.url.path.startswith('/v1/iphone/')
        if phone:
            self.auth.iphone_sessions.api_boundary(request)
            actor = self.auth.iphone_sessions.authenticate(request, 'trips:manage' if transmit else 'trips:read',
                                                           connection=conn, lock=transmit)
            reference = dict(kind='iphone', account=actor['id'], tokenHash=self.auth.iphone_sessions.token_hash(request))
        else:
            if (request.url.hostname != urlsplit(self.auth.native_origin).hostname or
                    not is_native_principal(getattr(request.state, 'device_identity', None))):
                fail(404, 'UNAVAILABLE')
            actor = transaction_actor(self.auth, request, conn, mutate=transmit)
            reference = dict(kind='native', account=actor['id'], grant=actor['grantId'], device=actor['deviceId'],
                epoch=actor['credentialEpoch'], slot=actor['slotRevision'],
                functional=request.state.functional_snapshot['revision'], certificate=self.auth.native_certificate(request),
                accessHash=hash_secret('access', request.headers['authorization'][7:]))
        context, stamp = self._context(conn, trip, actor['id'])
        if not phone:
            self._native_direction(conn, actor, request.state.functional_snapshot, context, transmit=transmit)
        reference['stamp'] = stamp
        if transmit and self._suspended(conn, context['roomId'], actor['id']):
            fail(403, 'SPEAKER_SUSPENDED')
        return actor, context, reference

    @staticmethod
    def _suspended(conn, room, actor):
        return bool(conn.execute('SELECT 1 FROM team_voice_reports WHERE room_id=%s AND speaker_id=%s '
                                'AND resolved_at IS NULL LIMIT 1', (room, actor)).fetchone())

    def _source_current(self, conn, clip):
        ref = clip.source
        if ref['kind'] == 'iphone':
            row = conn.execute('SELECT account_id,scopes,expires_at,revoked_at FROM iphone_sessions WHERE token_hash=%s',
                               (ref['tokenHash'],)).fetchone()
            if not row or row[0] != ref['account'] or row[3] is not None or row[2] <= self.auth.iphone_sessions.now() or 'trips:manage' not in row[1]:
                fail(403, 'SOURCE_UNAVAILABLE')
            self.auth.current_account(ref['account'], connection=conn)
        else:
            base = self.auth.native_authorization
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.execute('SELECT * FROM native_v2_credentials WHERE access_hash=%s', (ref['accessHash'],)).fetchone()
                if not row:
                    fail(403, 'SOURCE_UNAVAILABLE')
                certificate = base._certificate(cursor, ref['certificate'])
                grant = base._grant(cursor, ref['grant'], certificate)
                base._live(grant, connection=conn)
                _scope_check(grant)
                if (grant['state'] != 'TOKEN_ISSUED' or grant['account_id'] != ref['account'] or grant['device_id'] != ref['device']
                        or row['grant_id'] != ref['grant'] or certificate['active_grant_id'] != ref['grant']
                        or row['certificate_sha256'] != ref['certificate'] or row['generation'] != certificate['current_generation']
                        or row['credential_epoch'] != grant['credential_epoch'] or grant['credential_epoch'] != ref['epoch']
                        or row['slot_revision'] != certificate['slot_revision'] or certificate['slot_revision'] != ref['slot']
                        or row['access_expires_at'] <= base.now()):
                    fail(403, 'SOURCE_UNAVAILABLE')
                functional = self.auth.functional_access.snapshot(cursor, grant)
            if functional['revision'] != ref['functional']:
                fail(403, 'SOURCE_UNAVAILABLE')
        context, stamp = self._context(conn, clip.trip, ref['account'])
        if stamp != ref['stamp'] or context['roomId'] != clip.room or self._suspended(conn, clip.room, ref['account']):
            fail(403, 'SOURCE_UNAVAILABLE')
        if ref['kind'] == 'native':
            principal = dict(id=ref['account'], grantId=ref['grant'], deviceId=ref['device'])
            self._native_direction(conn, principal, functional, context, transmit=True)

    def _visible(self, conn, clip, actor, context, reference):
        if clip.room != context['roomId'] or clip.speaker == actor['id'] or clip.audience.get(actor['id']) != reference['stamp']:
            return False
        row = conn.execute('SELECT protected FROM team_voice_filters WHERE room_id=%s AND account_id=%s AND speaker_id=%s',
                           (clip.room, actor['id'], clip.speaker)).fetchone()
        if row and self.voice.rooms.restore('voice-filter:' + actor['id'], clip.room + ':' + clip.speaker, row[0])['muted']:
            return False
        try:
            self._source_current(conn, clip)
        except (HTTPException, FunctionalError, NativeAuthorizationError) as error:
            status = getattr(error, 'status_code', getattr(error, 'status', 503))
            if status in (401, 403, 404, 409, 410):
                return False
            raise
        return True

    def upload(self, trip, request, value):
        try:
            encoded = value['pcmBase64']
            if type(encoded) is not str or len(encoded) > 640000 or not ID.fullmatch(value['clientMessageId']):
                fail(400, 'INVALID_MESSAGE')
            pcm = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError, KeyError, binascii.Error):
            fail(400, 'INVALID_MESSAGE')
        if not 640 <= len(pcm) <= MAX_PCM or len(pcm) % 640:
            fail(400, 'INVALID_MESSAGE')
        with psycopg.connect(self.auth.dsn) as conn:
            actor, context, reference = self._actor(request, conn, trip, transmit=True)
            self.auth.rate('voice-clip-upload:' + actor['id'], limit=60)
            audience = {}
            for account, member in context['members'].items():
                if member['state'] == 'accepted':
                    _, voice = self.auth.trip_service.voice_membership(conn, trip, context['roomId'], account)
                    if voice['participating']:
                        audience[account] = (voice['memberJoinedAt'], voice['revision'])
            return self.memory.publish(trip, context['roomId'], reference, audience, value['clientMessageId'], pcm).metadata()

    def feed(self, trip, request, cursor):
        with psycopg.connect(self.auth.dsn) as conn:
            actor, context, reference = self._actor(request, conn, trip)
            latest, clips = self.memory.feed(trip, cursor)
            return dict(cursor=latest, clips=[clip.metadata() for clip in clips
                if self._visible(conn, clip, actor, context, reference)])

    def download(self, trip, identifier, request):
        with psycopg.connect(self.auth.dsn) as conn:
            actor, context, reference = self._actor(request, conn, trip)
            clip = self.memory.get(identifier)
            if clip.trip != trip or not self._visible(conn, clip, actor, context, reference):
                fail(404, 'UNAVAILABLE')
            self.memory.delivered(clip, actor['id'], reference['stamp'])
            return dict(clip.metadata(), pcmBase64=base64.b64encode(clip.pcm).decode('ascii'))

    def report_receipt(self, conn, room, identifier, account):
        try:
            clip = self.memory.get(identifier)
        except HTTPException:
            return None
        if clip.room != room or account not in clip.delivered:
            return None
        _, voice = self.auth.trip_service.voice_membership(conn, clip.trip, room, account)
        if clip.delivered[account] != (voice['memberJoinedAt'], voice['revision']):
            return None
        return dict(leaseId=clip.id, speakerId=clip.speaker, sequence=clip.sequence,
                    deliveredTo=set(clip.delivered), endedAt=clip.created)

    def router(self):
        routes = APIRouter()
        if not self.auth.enabled:
            return routes

        def validate_query(request, *, feed=False):
            values = list(request.query_params.multi_items())
            if values and (not feed or len(values) != 1 or values[0][0] != 'cursor' or not CURSOR.fullmatch(values[0][1])):
                fail(400, 'INVALID_CURSOR')
            return values[0][1] if values else None

        @routes.get('/v1/iphone/trips/{trip}/voice-clips', include_in_schema=False)
        @routes.get('/v1/social/trips/{trip}/voice-clips')
        def listing(trip: str, request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            return self.feed(trip, request, validate_query(request, feed=True))

        @routes.post('/v1/iphone/trips/{trip}/voice-clips', include_in_schema=False)
        @routes.post('/v1/social/trips/{trip}/voice-clips')
        async def upload(trip: str, request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            validate_query(request)
            raw = await body(request, 'application/json', maximum_bytes=MAX_BODY)
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            try:
                value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if type(value) is not dict:
                    raise ValueError()
                if is_native_principal(getattr(request.state, 'device_identity', None)):
                    value, revision = functional_body(value)
                    request.state.functional_revision = revision
                if set(value) != {'clientMessageId', 'pcmBase64'}:
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError, RecursionError):
                fail(400, 'INVALID_MESSAGE')
            return await run_in_threadpool(self.upload, trip, request, value)

        @routes.get('/v1/iphone/trips/{trip}/voice-clips/{identifier}', include_in_schema=False)
        @routes.get('/v1/social/trips/{trip}/voice-clips/{identifier}')
        def download(trip: str, identifier: str, request: Request, response: Response):
            response.headers['Cache-Control'] = 'private, no-store'
            validate_query(request)
            if not ID.fullmatch(identifier):
                fail(404, 'UNAVAILABLE')
            return self.download(trip, identifier, request)

        return routes
