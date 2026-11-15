"""Sustained, real-time trip audio over the actual PostgreSQL/TLS relay."""
import http.client
import json
import threading
import time
import unittest

from test_team_voice import VoiceFixture, VoiceTests
from websockets.exceptions import ConnectionClosed


class TripVoiceStreamingTests(VoiceTests):
    def setUp(self):
        VoiceFixture.drain_voice()
        self.api = VoiceFixture(methodName='test_10_capabilities_browser_only_strict_inputs')
        self.api.connection_factory = lambda host, port, timeout: http.client.HTTPSConnection(
            '127.0.0.1', self.value['tlsPort'], timeout=timeout, context=self.ssl)
        self.api.setUp()
        self.a, self.b = self.api.login(), self.api.login('bob')
        status, _, trip = self.api.call('/v1/social/trips',
            dict(title='Synthetic streaming trip', description='', memberIds=[], locationConsent=False),
            'POST', session=self.a)
        self.assertEqual(status, 201, trip)
        self.base = '/v1/social/trips/' + trip['id']
        status, _, link = self.api.call(self.base + '/link', {}, 'POST', session=self.a)
        self.assertEqual(status, 201, link)
        status, _, result = self.api.call('/v1/social/trip-links/join',
            dict(token=link['token'], locationConsent=False), 'POST', session=self.b, who='bob')
        self.assertEqual(status, 200, result)
        status, _, detail = self.api.call(self.base, session=self.a)
        self.assertEqual(status, 200, detail)
        status, _, result = self.api.call(self.base + '/start', dict(revision=detail['revision']),
            'POST', session=self.a)
        self.assertEqual(status, 200, result)

    def stream(self, sender, receiver, count=120, batch=1):
        errors = []
        started = time.monotonic()

        def send():
            try:
                for sequence in range(count):
                    delivery = ((sequence // batch + 1) * batch - 1) * .02 if batch > 1 else sequence * .02
                    delay = started + delivery - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    sender.send(self.frame(sequence))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=send, daemon=True)
        thread.start()
        try:
            for sequence in range(count):
                self.assertEqual(receiver.recv(timeout=2), self.frame(sequence))
        finally:
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_half_second_batches_are_delivered_in_both_directions(self):
        with self.ws(self.a) as first, self.ws(self.b, 'bob') as second:
            self.start(first, second)
            self.stream(first, second, count=300, batch=25)
            first.send(json.dumps(dict(type='floor-release')))
            self.json(first, 'floor-ended')
            self.json(second, 'floor-ended')
            second.send(json.dumps(dict(type='floor-request')))
            self.json(second, 'floor-granted')
            self.json(first, 'floor-started')
            self.stream(second, first, count=300, batch=25)
            second.send(json.dumps(dict(type='floor-release')))
            self.json(second, 'floor-ended')
            self.json(first, 'floor-ended')

    def test_continuous_trip_pcm_at_fifty_frames_per_second(self):
        with self.ws(self.a) as first, self.ws(self.b, 'bob') as second:
            self.start(first, second)
            databases = [peer.socket.state.voice_database for peer in VoiceFixture.voice.peers]
            self.stream(first, second)
            first.send(json.dumps(dict(type='floor-release')))
            self.json(first, 'floor-ended')
            self.json(second, 'floor-ended')
            second.send(json.dumps(dict(type='floor-request')))
            self.json(second, 'floor-granted')
            self.json(first, 'floor-started')
            self.stream(second, first)
            status, _, result = self.api.call(self.base + '/sharing',
                dict(consents=self.choices(False)), 'PATCH', session=self.a)
            self.assertEqual(status, 200, result)
            with self.assertRaises(ConnectionClosed):
                first.recv(timeout=1)
            second.send(json.dumps(dict(type='floor-release')))
            self.json(second, 'floor-ended')
        VoiceFixture.drain_voice()
        self.assertEqual(len(databases), 2)
        self.assertTrue(all(database.closed and database.connection is None for database in databases))

    def test_reused_connection_rolls_back_failed_transaction(self):
        from fastapi import HTTPException
        from voice_authorization import VoiceDatabase

        database = VoiceDatabase(self.api.dsn)
        self.addCleanup(database.close)
        with database.transaction() as conn:
            backend = conn.info.backend_pid
            conn.execute('CREATE TEMP TABLE voice_transaction_probe(value integer)')
        with self.assertRaisesRegex(RuntimeError, 'probe'):
            with database.transaction() as conn:
                conn.execute('INSERT INTO voice_transaction_probe VALUES (1)')
                raise RuntimeError('probe')
        with database.transaction() as conn:
            self.assertEqual(conn.info.backend_pid, backend)
            self.assertEqual(conn.execute('SELECT count(*) FROM voice_transaction_probe').fetchone()[0], 0)
        database.close()
        with self.assertRaises(HTTPException):
            with database.transaction():
                self.fail('A closed voice connection reopened')


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(TripVoiceStreamingTests(name) for name in vars(TripVoiceStreamingTests)
                              if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
