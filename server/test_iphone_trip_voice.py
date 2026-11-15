"""Phone sessions and live PCM on the trip relay, with disposable PostgreSQL."""
import json
import os
import socket
import struct
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import psycopg
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
import test_iphone_trips as fixture
from test_iphone_session import IPHONE

class IPhoneTripVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        enabled = patch.dict(os.environ, {'WEGOH_VOICE_ENABLED': '1'})
        enabled.start(); cls.addClassCleanup(enabled.stop)
        fixture.IPhoneTripTests.setUpClass.__func__(cls)
        from voice_authorization import VoiceDatabase
        cls.databases = []
        original = VoiceDatabase.__init__
        def tracked(database, *args, **kwargs):
            original(database, *args, **kwargs)
            cls.databases.append(database)
        tracking = patch.object(VoiceDatabase, '__init__', tracked)
        tracking.start(); cls.addClassCleanup(tracking.stop)

    def setUp(self):
        self.h = fixture.IPhoneTripTests(); self.h.setUp()
        self.addCleanup(self.h.phone.doCleanups)
        self.h.befriend(self.h.bob)
        self.trip = self.h.create(); self.h.join(self.trip, self.h.bob)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute("UPDATE team_trips SET state='active',started_at=now() WHERE trip_id=%s", (self.trip,))
        self.base = '/' + self.trip + '/voice'

    def tearDown(self):
        deadline = time.monotonic() + 4
        while not all(database.closed for database in self.databases) and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(all(database.closed for database in self.databases))

    def ws(self, session=None, *, host=IPHONE, suffix='', extra=None):
        raw = socket.create_connection(('127.0.0.1', self.h.phone.api.port), timeout=3)
        headers = {'Authorization': 'Bearer ' + (session or self.h.alice)['accessToken']}
        headers.update(extra or {})
        try:
            return connect('ws://' + host + '/v1/iphone/trips/' + self.trip + '/voice' + suffix,
                sock=raw, additional_headers=headers, open_timeout=3, close_timeout=1)
        except BaseException:
            raw.close(); raise

    def control(self, ws, kind):
        for _ in range(20):
            value = ws.recv(timeout=3)
            if isinstance(value, str) and json.loads(value)['type'] == kind: return json.loads(value)
        self.fail('Missing ' + kind)

    def call(self, suffix='', data=None, method='GET', **kwargs):
        return self.h.call(self.base + suffix, data, method, **kwargs)

    def test_bidirectional_realtime_pcm_and_busy_floor(self):
        self.phone_exchange()

    def test_half_second_batches_between_phone_sessions(self):
        self.phone_exchange(count=300, batch=25)

    @contextmanager
    def delayed_voice_queries(self):
        from voice_authorization import VoiceDatabase
        transaction = VoiceDatabase.transaction
        execute = psycopg.Connection.execute
        scope = threading.local()

        @contextmanager
        def delayed_transaction(database):
            with transaction(database) as conn:
                scope.voice = True
                try:
                    yield conn
                finally:
                    scope.voice = False

        def delayed_execute(conn, *args, **kwargs):
            if getattr(scope, 'voice', False):
                time.sleep(.001)
            return execute(conn, *args, **kwargs)

        with patch.object(VoiceDatabase, 'transaction', delayed_transaction), \
                patch.object(psycopg.Connection, 'execute', delayed_execute):
            yield

    def test_query_latency_does_not_fill_the_relay_queue(self):
        with self.delayed_voice_queries():
            self.phone_exchange(count=500, batch=25)

    def test_query_latency_between_phone_and_native_vehicle(self):
        with self.delayed_voice_queries():
            self.native_phone_exchange(count=300, batch=25)

    def phone_exchange(self, count=120, batch=1):
        with self.ws() as a, self.ws(self.h.bob) as b:
            self.control(a, 'ready'); self.control(b, 'ready')
            for sender, receiver in ((a, b), (b, a)):
                sender.send(json.dumps({'type': 'floor-request'}))
                self.control(sender, 'floor-granted'); self.control(receiver, 'floor-started')
                receiver.send(json.dumps({'type': 'floor-request'})); self.control(receiver, 'floor-busy')
                started = time.monotonic()
                errors = []
                def send_frames():
                    try:
                        for sequence in range(count):
                            delivery = ((sequence // batch + 1) * batch - 1) * .02 if batch > 1 else sequence * .02
                            time.sleep(max(0, started + delivery - time.monotonic()))
                            sender.send(struct.pack('<I', sequence) + struct.pack('<h', sequence) * 320)
                    except Exception as error: errors.append(error)
                producer = threading.Thread(target=send_frames, daemon=True)
                producer.start()
                try:
                    for sequence in range(count):
                        frame = struct.pack('<I', sequence) + struct.pack('<h', sequence) * 320
                        self.assertEqual(receiver.recv(timeout=3), frame,
                            'sequence=' + str(sequence) + ', elapsed=' + str(time.monotonic()-started))
                finally:
                    producer.join(4)
                self.assertFalse(producer.is_alive()); self.assertEqual(errors, [])
                sender.send(json.dumps({'type': 'floor-release'}))
                self.control(sender, 'floor-ended'); self.control(receiver, 'floor-ended')

    def test_native_vehicle_and_phone_share_the_same_floor_and_pcm(self):
        self.native_phone_exchange()

    def test_half_second_batches_between_phone_and_native_vehicle(self):
        self.native_phone_exchange(count=150, batch=25)

    def native_phone_exchange(self, count=120, batch=1):
        from test_native_functional_business import FunctionalBusinessTests
        factory = FunctionalBusinessTests('test_native_friend_request_respond_scope_withdrawal_and_original_authority')
        factory.h = self.h.phone.api
        factory.certificates = {}
        browser = factory.h.login()
        vehicle = factory.connect(browser)
        factory.approve(browser, vehicle, ['rooms:read', 'rooms:interact', 'room-voice:receive', 'room-voice:transmit'])
        state = self.h.checked(factory.native(vehicle, '/v1/native/trips/' + self.trip + '/voice-permissions'))
        raw = socket.create_connection(('127.0.0.1', self.h.phone.api.port), timeout=3)
        headers = {'Authorization': 'Bearer ' + vehicle['accessToken'],
            'cf-cert-sha256': factory.certificates[vehicle['grantId']],
            'cf-cert-presented': 'true', 'cf-cert-verified': 'true', 'cf-cert-revoked': 'false',
            'X-WegoH-Functional-Revision': str(state['functionalRevision']),
            'X-WegoH-Room-Voice-Revision': str(state['revision'])}
        try:
            native = connect('ws://api.wegoh.invalid/v1/social/trips/' + self.trip + '/voice',
                sock=raw, additional_headers=headers, origin=None, open_timeout=3, close_timeout=1)
        except BaseException:
            raw.close(); raise
        with native, self.ws(self.h.bob) as phone:
            self.control(native, 'ready'); self.control(phone, 'ready')
            for sender, receiver in ((native, phone), (phone, native)):
                sender.send(json.dumps({'type':'floor-request'}))
                self.control(sender, 'floor-granted'); self.control(receiver, 'floor-started')
                started = time.monotonic()
                errors = []
                def send_frames():
                    try:
                        for sequence in range(count):
                            delivery = ((sequence // batch + 1) * batch - 1) * .02 if batch > 1 else sequence * .02
                            time.sleep(max(0, started + delivery - time.monotonic()))
                            sender.send(struct.pack('<I', sequence) + struct.pack('<h', 100 + sequence) * 320)
                    except Exception as error: errors.append(error)
                producer = threading.Thread(target=send_frames, daemon=True)
                producer.start()
                try:
                    for sequence in range(count):
                        pcm = struct.pack('<I', sequence) + struct.pack('<h', 100 + sequence) * 320
                        self.assertEqual(receiver.recv(timeout=3), pcm)
                finally:
                    producer.join(4)
                self.assertFalse(producer.is_alive()); self.assertEqual(errors, [])
                sender.send(json.dumps({'type':'floor-release'}))
                self.control(sender, 'floor-ended'); self.control(receiver, 'floor-ended')

    def test_participation_revision_and_withdrawal_close_live_socket(self):
        path = '/' + self.trip + '/voice-participation'
        current = self.h.checked(self.h.call(path)); self.assertTrue(current['participating'])
        with self.ws() as ws:
            self.control(ws, 'ready')
            off = self.h.checked(self.h.call(path, dict(participating=False, revision=current['revision'], memberJoinedAt=current['memberJoinedAt']), 'PATCH'))
            self.assertFalse(off['participating'])
            with self.assertRaises(ConnectionClosed): ws.recv(timeout=3)
        with self.assertRaises(InvalidStatus): self.ws()
        self.assertEqual(self.h.call(path, dict(participating=True, revision=current['revision'], memberJoinedAt=current['memberJoinedAt']), 'PATCH')[0], 409)

    def test_session_revocation_and_scope_are_revalidated(self):
        with self.ws() as ws:
            self.control(ws, 'ready')
            with psycopg.connect(self.h.phone.api.dsn) as conn:
                conn.execute('UPDATE iphone_sessions SET revoked_at=%s WHERE account_id=%s', (int(time.time()), self.h.a))
            with self.assertRaises(ConnectionClosed): ws.recv(timeout=3)
        with self.assertRaises(InvalidStatus): self.ws()
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read','trips:read'] WHERE account_id=%s", (self.h.b,))
        with self.ws(self.h.bob) as ws:
            self.control(ws, 'ready'); ws.send(json.dumps({'type': 'floor-request'}))
            with self.assertRaises(ConnectionClosed): ws.recv(timeout=3)
        with self.ws(self.h.bob) as ws:
            self.control(ws, 'ready')
            with psycopg.connect(self.h.phone.api.dsn) as conn:
                conn.execute('UPDATE iphone_sessions SET expires_at=%s WHERE account_id=%s', (int(time.time())-1, self.h.b))
            with self.assertRaises(ConnectionClosed): ws.recv(timeout=3)
        with self.assertRaises(InvalidStatus): self.ws(self.h.bob)

    def test_protected_trip_room_and_members_are_validated_on_phone(self):
        records = (
            ('team_trips', 'trip_id=%s', (self.trip,)),
            ('team_trip_members', 'trip_id=%s AND account_id=%s', (self.trip, self.h.a)),
            ('team_rooms', 'trip_id=%s', (self.trip,)),
        )
        for table, predicate, args in records:
            with self.subTest(table=table), psycopg.connect(self.h.phone.api.dsn) as conn:
                previous, = conn.execute(f'SELECT protected FROM {table} WHERE {predicate}', args).fetchone()
                conn.execute(f'UPDATE {table} SET protected=%s WHERE {predicate}', (b'invalid-ciphertext', *args))
                conn.commit()
                try:
                    with self.assertRaises(InvalidStatus):
                        self.ws()
                finally:
                    conn.execute(f'UPDATE {table} SET protected=%s WHERE {predicate}', (previous, *args))

    def test_current_blocked_pair_is_rejected_for_both_phones(self):
        from team_friends import pair_ids, save_pair
        a, b = pair_ids(self.h.a, self.h.b)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            save_pair(conn, a, b, dict(state='none', requestedBy=None, blockedBy=[self.h.a]))
        for session in (self.h.alice, self.h.bob):
            with self.assertRaises(InvalidStatus):
                self.ws(session)

    def test_host_origin_query_nonmember_and_completed_trip_rejected(self):
        for options in ({'session': self.h.eve}, {'suffix': '?token=not-allowed'}, {'extra': {'Origin': 'https://example.invalid'}}, {'extra': {'Cookie': 'bad=1'}}, {'host': 'web.wegoh.invalid'}, {'host': 'native.wegoh.invalid'}):
            with self.subTest(options=list(options)), self.assertRaises(InvalidStatus): self.ws(**options)
        with self.ws() as ws:
            self.control(ws, 'ready')
            with psycopg.connect(self.h.phone.api.dsn) as conn:
                conn.execute("UPDATE team_trips SET state='completed',ended_at=now() WHERE trip_id=%s", (self.trip,))
            with self.assertRaises(ConnectionClosed): ws.recv(timeout=3)

    def test_filters_and_reports_use_current_phone_authority(self):
        self.assertEqual(self.h.checked(self.call('/filters')), {'mutedSpeakerIds': []})
        self.h.checked(self.call('/filters/' + self.h.b, {'muted': True}, 'PUT'))
        self.assertEqual(self.h.checked(self.call('/filters'))['mutedSpeakerIds'], [self.h.b])
        self.h.checked(self.call('/filters/' + self.h.b, {'muted': False}, 'PUT'))
        self.assertEqual(self.call('/reports', {'speakerId': self.h.b, 'leaseId': 'a'*32, 'reason': 'other'}, 'POST')[0], 404)
        with self.ws(self.h.bob) as sender, self.ws() as receiver:
            self.control(sender, 'ready'); self.control(receiver, 'ready')
            sender.send(json.dumps({'type': 'floor-request'})); lease = self.control(sender, 'floor-granted')
            self.control(receiver, 'floor-started'); sender.send(struct.pack('<I', 0) + b'\0'*640)
            self.assertEqual(len(receiver.recv(timeout=3)), 644)
            result = self.h.checked(self.call('/reports', {'speakerId': self.h.b, 'leaseId': lease['leaseId'], 'reason': 'other'}, 'POST'), 202)
            self.assertFalse(result['audioRetained']); self.control(sender, 'floor-ended')
