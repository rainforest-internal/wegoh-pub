"""Demo-only shared playback control for vehicles in one trip.

The server keeps one process-local session per trip and only distributes control
state: who is ready, the shared start time on the server clock, and whether the
session ended. It never stores, relays or streams audio. Every vehicle plays the
same bundled team-owned WAV locally after checking the track hash.
"""
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response

from native_access import native_resource
from native_functional_identity import business_json, transaction_actor
from team_rooms import TeamRooms
from team_trip_context import resolve_trip_context

ID = re.compile(r'[a-f0-9]{32}')
SHA256 = re.compile(r'[a-f0-9]{64}')
TRACK = dict(id='wegoh-demo-01', version=1,
             sha256='0c0c4853ce351cc91852d39423f55cd0ef19bedbfc52f914c74c0e0a947d6ccf', durationMs=48000)
START_DELAY_MS = 4000
# Vehicles confirm every 1.5 s, but their reads queue behind other native calls (waits of 3.4 s were
# measured), and they stop locally after 6 s without a confirmation. Expire only after that.
PRESENCE_TIMEOUT_MS = 8000
ENDED_RETENTION_MS = 60000
MINIMUM_DEVICES = 2
ENDED_REASONS = ('host-ended', 'track-finished', 'everyone-left', 'trip-closed')
TRIPS_ENVIRONMENT = 'WEGOH_LISTEN_TOGETHER_TRIPS'


def fail(status, code):
    raise HTTPException(status, 'LISTEN_TOGETHER_' + code)


def allowed_trips(environ=None):
    """Exact allow-list of demo trips. Any malformed entry disables the feature."""
    raw = (os.environ if environ is None else environ).get(TRIPS_ENVIRONMENT, '')
    values = [value.strip() for value in raw.split(',') if value.strip()]
    if any(not ID.fullmatch(value) for value in values):
        return frozenset()
    return frozenset(values)


def now_ms():
    return time.time_ns() // 1000000


@dataclass
class Device:
    device: str
    grant: str
    seen: int


@dataclass
class Session:
    id: str
    state: str
    revision: int
    devices: dict = field(default_factory=dict)
    start_at: int = None
    ended_reason: str = None
    ended_at: int = None


class ListenTogetherSessions:
    """One canonical session per trip. Callers pass the current accepted members."""

    def __init__(self, clock=now_ms):
        self.clock = clock
        self.lock = threading.Lock()
        self.items = {}

    @staticmethod
    def _mine(session, account, device, grant):
        entry = session.devices.get(account)
        return entry is not None and entry.device == device and entry.grant == grant

    def _end(self, session, reason, now):
        session.state, session.ended_reason, session.ended_at = 'ended', reason, now
        session.devices.clear()
        session.revision += 1

    def _settle(self, trip, members, now):
        """Drop departed members and silent devices, finish the track, expire old results."""
        session = self.items.get(trip)
        if session is None:
            return None, False
        changed = False
        if session.state != 'ended':
            for account in [key for key, entry in session.devices.items()
                            if key not in members or now - entry.seen > PRESENCE_TIMEOUT_MS]:
                del session.devices[account]
                changed = True
            if changed:
                session.revision += 1
        if session.state == 'playing' and now >= session.start_at + TRACK['durationMs']:
            self._end(session, 'track-finished', now)
            changed = True
        elif session.state == 'playing' and not session.devices:
            self._end(session, 'everyone-left', now)
            changed = True
        elif session.state == 'preparing' and not session.devices:
            del self.items[trip]
            return None, True
        if session.state == 'ended' and now - session.ended_at > ENDED_RETENTION_MS:
            del self.items[trip]
            return None, changed
        return session, changed

    def _view(self, trip, session, account, device, grant, host, available, now):
        value = None
        if session is not None:
            value = dict(id=session.id, revision=session.revision, state=session.state,
                         deviceCount=len(session.devices), joined=self._mine(session, account, device, grant),
                         startAtMs=session.start_at, endedReason=session.ended_reason)
        return dict(tripId=trip, available=available, serverTimeMs=now, host=host,
                    minimumDevices=MINIMUM_DEVICES, track=dict(TRACK), session=value)

    def read(self, trip, account, device, grant, host, members, available=True):
        with self.lock:
            now = self.clock()
            session, changed = self._settle(trip, members, now)
            if session is not None and self._mine(session, account, device, grant):
                session.devices[account].seen = now
            return self._view(trip, session, account, device, grant, host, available, now), changed

    def join(self, trip, account, device, grant, host, members, session_id, track_sha256, joined):
        with self.lock:
            now = self.clock()
            session, changed = self._settle(trip, members, now)
            if session is not None and session.state == 'ended':
                session = None
            if session_id is not None and (session is None or session.id != session_id):
                fail(409, 'SESSION_CHANGED')
            if joined:
                if track_sha256 != TRACK['sha256']:
                    fail(409, 'TRACK_MISMATCH')
                if session is None:
                    session = Session(id=secrets.token_hex(16), state='preparing', revision=0)
                    self.items[trip] = session
                if not self._mine(session, account, device, grant):
                    session.devices[account] = Device(device, grant, now)
                    session.revision += 1
                    changed = True
                session.devices[account].seen = now
            elif session is not None and account in session.devices:
                del session.devices[account]
                session.revision += 1
                changed = True
                session, _ = self._settle(trip, members, now)
            return self._view(trip, session, account, device, grant, host, True, now), changed

    def start(self, trip, account, device, grant, host, members, session_id, revision):
        if not host:
            fail(403, 'HOST_REQUIRED')
        with self.lock:
            now = self.clock()
            session, changed = self._settle(trip, members, now)
            if session is None or session.id != session_id:
                fail(409, 'SESSION_CHANGED')
            if session.state == 'ended':
                fail(409, 'SESSION_ENDED')
            if session.state == 'preparing':
                if session.revision != revision:
                    fail(409, 'SESSION_CHANGED')
                if not self._mine(session, account, device, grant):
                    fail(409, 'HOST_NOT_READY')
                if len(session.devices) < MINIMUM_DEVICES:
                    fail(409, 'NOT_ENOUGH_DEVICES')
                session.state, session.start_at = 'playing', now + START_DELAY_MS
                session.revision += 1
                changed = True
            return self._view(trip, session, account, device, grant, host, True, now), changed

    def end(self, trip, account, device, grant, host, members, session_id):
        if not host:
            fail(403, 'HOST_REQUIRED')
        with self.lock:
            now = self.clock()
            session, changed = self._settle(trip, members, now)
            if session is None or session.id != session_id:
                fail(409, 'SESSION_CHANGED')
            if session.state != 'ended':
                self._end(session, 'host-ended', now)
                changed = True
            return self._view(trip, session, account, device, grant, host, True, now), changed

    def withdraw(self, trip, account=None):
        """Membership, room or trip withdrawal removes participation immediately."""
        with self.lock:
            session = self.items.get(trip)
            if session is None or session.state == 'ended':
                return False
            now = self.clock()
            if account is None:
                self._end(session, 'trip-closed', now)
                return True
            if session.devices.pop(account, None) is None:
                return False
            session.revision += 1
            self._settle(trip, set(session.devices), now)
            return True


class TripListenTogether:
    def __init__(self, music, *, sessions=None, environ=None):
        self.music = music
        self.auth = music.auth
        self.sessions = sessions or ListenTogetherSessions()
        self.environ = environ

    def withdraw_trip_context(self, conn, trip, room, account=None):
        if self.sessions.withdraw(trip, account):
            self.music.rooms.notify(conn, room, sections=('music',))

    def _context(self, request, conn, trip, *, mutate=False):
        if not native_resource(request):
            fail(404, 'UNAVAILABLE')
        TeamRooms.graph_lock(conn)
        actor = transaction_actor(self.auth, request, conn, mutate=mutate)
        context = resolve_trip_context(self.auth, conn, trip, actor['id'])
        members = {account for account, member in context['members'].items() if member['state'] == 'accepted'}
        if actor['id'] not in members:
            fail(403, 'MEMBERSHIP_REQUIRED')
        return actor, context, members

    def _call(self, request, trip, operation, *, mutate=False, **values):
        with psycopg.connect(self.auth.dsn) as conn:
            actor, context, members = self._context(request, conn, trip, mutate=mutate)
            available = trip in allowed_trips(self.environ)
            identity = (trip, actor['id'], actor['deviceId'], actor['grantId'], actor['id'] == context['ownerId'], members)
            if operation == 'read':
                result, changed = self.sessions.read(*identity, available=available)
                if not available:
                    result['session'] = None
            elif not available:
                fail(403, 'NOT_ENABLED')
            else:
                result, changed = getattr(self.sessions, operation)(*identity, **values)
            if changed:
                self.music.rooms.notify(conn, context['roomId'], sections=('music',))
            return result

    def router(self):
        routes = APIRouter()
        base = '/v1/native/trips/{trip}/listen-together'

        async def payload(request, fields):
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 1024:
                    fail(413, 'REQUEST_TOO_LARGE')
            value = business_json(request, raw, maximum=1024)
            if set(value) != set(fields):
                fail(400, 'INVALID_REQUEST')
            return value

        def session_id(value, *, optional=False):
            if (value is None and optional) or (type(value) is str and ID.fullmatch(value)):
                return value
            fail(400, 'INVALID_REQUEST')

        def guard(request, response):
            response.headers['Cache-Control'] = 'private, no-store'
            if request.query_params:
                fail(400, 'INVALID_REQUEST')

        @routes.get(base)
        def read(trip: str, request: Request, response: Response):
            guard(request, response)
            return self._call(request, trip, 'read')

        @routes.put(base + '/participation')
        async def participation(trip: str, request: Request, response: Response):
            guard(request, response)
            data = await payload(request, ('sessionId', 'trackSha256', 'joined'))
            if type(data['joined']) is not bool or type(data['trackSha256']) is not str or not SHA256.fullmatch(data['trackSha256']):
                fail(400, 'INVALID_REQUEST')
            return self._call(request, trip, 'join', mutate=True, session_id=session_id(data['sessionId'], optional=True),
                              track_sha256=data['trackSha256'], joined=data['joined'])

        @routes.post(base + '/start')
        async def start(trip: str, request: Request, response: Response):
            guard(request, response)
            data = await payload(request, ('sessionId', 'revision'))
            if type(data['revision']) is not int or not 1 <= data['revision'] <= 2147483647:
                fail(400, 'INVALID_REQUEST')
            return self._call(request, trip, 'start', mutate=True, session_id=session_id(data['sessionId']),
                              revision=data['revision'])

        @routes.post(base + '/end')
        async def end(trip: str, request: Request, response: Response):
            guard(request, response)
            data = await payload(request, ('sessionId',))
            return self._call(request, trip, 'end', mutate=True, session_id=session_id(data['sessionId']))

        return routes
