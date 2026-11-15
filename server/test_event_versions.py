import json
import socket
import unittest
from unittest.mock import patch

import psycopg
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

import test_team_auth as fixture
from team_event_versions import CHAT_PROTOCOL, PROTOCOL, trip_changed


class EventVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.h = fixture.TeamTests()
        self.h.setUp()
        self.session = self.h.login()
        status, _, value = self.h.call('/v1/social/trips', dict(title='Synthetic trip', description='', memberIds=[]),
            'POST', session=self.session)
        self.assertEqual(status, 201, value)
        self.trip = value['id']

    def socket(self, protocols=(PROTOCOL,), path='/v1/events'):
        raw = socket.create_connection(('127.0.0.1', self.h.port), timeout=5)
        return connect('ws://web.wegoh.invalid' + path, sock=raw, origin=fixture.WEB,
            additional_headers={'Cookie': self.session['cookie'], 'Cf-Access-Jwt-Assertion': self.h.assertion()},
            subprotocols=protocols, open_timeout=3, close_timeout=1)

    def test_location_signal_and_music_versions_do_not_invalidate_other_sections(self):
        prefix = 'trip.' + self.trip + '.'
        with self.socket() as ws:
            self.assertEqual(ws.subprotocol, 'wegoh.events.v1')
            first = json.loads(ws.recv(timeout=2))
            self.assertIn(prefix + 'location', first['versions'])
            status, _, result = self.h.call('/v1/social/trips/' + self.trip + '/location-sharing',
                dict(locationConsent=True), 'PATCH', session=self.session)
            self.assertEqual(status, 200, result)
            location = json.loads(ws.recv(timeout=3))
            self.assertEqual(set(location['versions']), {prefix + 'location'})
            for section in ('signals', 'music', 'route'):
                with psycopg.connect(self.h.dsn) as conn:
                    trip_changed(conn, self.trip, (section,))
                event = json.loads(ws.recv(timeout=3))
                self.assertEqual(set(event['versions']), {prefix + section})
            latest = {**first['versions'], **location['versions']}
        with self.socket() as ws:
            resumed = json.loads(ws.recv(timeout=2))
            self.assertEqual(latest['devices'], resumed['versions']['devices'])
            self.assertEqual(latest['courses'], resumed['versions']['courses'])
            self.assertEqual(latest[prefix + 'location'], resumed['versions'][prefix + 'location'])

    def test_partial_route_does_not_read_workspace_music_or_full_trip(self):
        service = self.h.module.TEAM_AUTH.trip_service
        with patch.object(service, 'detail', side_effect=AssertionError('Full trip read')):
            status, _, result = self.h.call('/v1/social/trips/' + self.trip + '?section=route', session=self.session)
        self.assertEqual(status, 200, result)
        self.assertEqual(set(result), {'id', 'revision', 'cars', 'courses'})

    def test_trip_chat_emits_a_version_without_message_content(self):
        key = 'trip.' + self.trip + '.chat'
        with self.socket() as previous:
            self.assertNotIn(key, json.loads(previous.recv(timeout=2))['versions'])
        with self.socket(protocols=(CHAT_PROTOCOL,)) as ws:
            self.assertEqual(ws.subprotocol, CHAT_PROTOCOL)
            first = json.loads(ws.recv(timeout=2))
            self.assertIn(key, first['versions'])
            text = '가족 여행 메시지'
            status, _, value = self.h.call('/v1/social/trips/' + self.trip + '/chat',
                dict(id='a' * 32, text=text), 'POST', session=self.session)
            self.assertEqual(status, 201, value)
            frame = ws.recv(timeout=3)
            self.assertNotIn(text, frame)
            self.assertEqual(set(json.loads(frame)['versions']), {key})

    def test_native_location_section_with_other_cars_matches_consent_without_full_detail(self):
        bob = self.h.login('bob')
        _, _, credential = self.h.pair(self.session)
        fingerprint = self.h._native_fingerprint
        _, _, peer_credential = self.h.pair(bob, 'bob')
        for session, device, who in ((self.session, credential, 'alice'), (bob, peer_credential, 'bob')):
            self.assertEqual(self.h.call('/v1/devices/' + device['deviceId'] + '/vehicle-profile',
                dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT', session=session, who=who)[0], 200)
        path = '/v1/social/trips/' + self.trip
        _, _, link = self.h.call(path + '/link', {}, 'POST', session=self.session)
        self.assertEqual(self.h.call('/v1/social/trip-links/join', dict(token=link['token'], locationConsent=False),
            'POST', session=bob, who='bob')[0], 200)
        cars = []
        for session, who in ((self.session, 'alice'), (bob, 'bob')):
            status, _, car = self.h.call(path + '/cars', dict(name='Synthetic car', seats=4), 'POST', session=session, who=who)
            self.assertEqual(status, 201, car)
            cars.append(car['id'])
        revision = self.h.call(path, session=self.session)[2]['revision']
        self.assertEqual(self.h.call(path + '/start', dict(revision=revision), 'POST', session=self.session)[0], 200)
        service = self.h.module.TEAM_AUTH.trip_service
        for sharing, label in ((False, '위치 공유 꺼짐'), (True, '최근 공유 위치 없음')):
            self.assertEqual(self.h.call(path + '/location-sharing', dict(locationConsent=sharing), 'PATCH', session=bob, who='bob')[0], 200)
            with patch.object(service, 'detail', side_effect=AssertionError('Full trip read')):
                status, _, value = self.h.native('/v1/native/trips/' + self.trip + '?section=location',
                    token=credential['accessToken'], certificate=fingerprint)
            self.assertEqual(status, 200, value)
            self.assertEqual(set(value), {'id', 'revision', 'locationConsent', 'display'})
            self.assertEqual(value['display']['companions'], [dict(carId=cars[1], label=label)])
        status, _, route = self.h.native('/v1/native/trips/' + self.trip + '?section=route',
            token=credential['accessToken'], certificate=fingerprint)
        self.assertEqual(status, 200, route)
        self.assertTrue(all('driverId' not in car and 'passengers' not in car for car in route['cars']))

    def test_native_business_changes_do_not_change_authority_and_partial_reads_keep_the_same_boundary(self):
        _, _, credential = self.h.pair(self.session)
        path = '/v1/devices/' + credential['deviceId'] + '/functional-permissions'
        _, _, settings = self.h.call(path, session=self.session)
        body = {key: value for key, value in settings.items() if key not in ('deviceId', 'expiresAt')}
        body['approvedPurposes'] = self.h.web_purposes(settings, ['rooms:read'])
        self.assertEqual(self.h.call(path, body, 'PUT', session=self.session)[0], 200)
        raw = socket.create_connection(('127.0.0.1', self.h.port), timeout=5)
        headers = {'Authorization': 'Bearer ' + credential['accessToken'],
            'cf-cert-sha256': self.h._native_fingerprint, 'cf-cert-presented': 'true',
            'cf-cert-verified': 'true', 'cf-cert-revoked': 'false'}
        with connect('ws://api.wegoh.invalid/v1/events', sock=raw, origin=None, subprotocols=[PROTOCOL],
                additional_headers=headers, open_timeout=3, close_timeout=1) as ws:
            initial = json.loads(ws.recv(timeout=3))
            key = 'trip.' + self.trip + '.location'
            self.assertIn(key, initial['versions'])
            self.assertNotIn('trip.' + self.trip + '.chat', initial['versions'])
            with psycopg.connect(self.h.dsn) as conn:
                trip_changed(conn, self.trip, ('location',))
            event = json.loads(ws.recv(timeout=3))
            self.assertEqual(set(event['versions']), {key})
            service = self.h.module.TEAM_AUTH.trip_service
            with patch.object(service, 'detail', side_effect=AssertionError('Full trip read')):
                status, _, route = self.h.native('/v1/native/trips/' + self.trip + '?section=route',
                    token=credential['accessToken'], certificate=self.h._native_fingerprint)
            self.assertEqual(status, 200, route)
            for query in ('section=music', 'section=route&section=route', 'token=private'):
                self.assertGreaterEqual(self.h.native('/v1/native/trips/' + self.trip + '?' + query,
                    token=credential['accessToken'], certificate=self.h._native_fingerprint)[0], 400)
        raw = socket.create_connection(('127.0.0.1', self.h.port), timeout=5)
        with self.assertRaises(InvalidStatus) as denied:
            connect('ws://api.wegoh.invalid/v1/events', sock=raw, origin=None, subprotocols=[CHAT_PROTOCOL],
                additional_headers=headers, open_timeout=3, close_timeout=1)
        self.assertEqual(denied.exception.response.status_code, 403)
        for route in ('/v1/social/trips/', '/v1/native/trips/'):
            for method, payload in (('GET', None), ('POST', dict(id='f' * 32, text='Private chat'))):
                with self.subTest(route=route, method=method):
                    status, _, _ = self.h.native(route + self.trip + '/chat', payload, method,
                        token=credential['accessToken'], certificate=self.h._native_fingerprint)
                    self.assertIn(status, (403, 404))

    def test_private_trip_is_absent_and_revocation_still_closes_the_socket(self):
        bob = self.h.login('bob')
        _, _, other = self.h.call('/v1/social/trips', dict(title='Bob private', description='', memberIds=[]),
            'POST', who='bob', session=bob)
        with self.socket() as ws:
            first = json.loads(ws.recv(timeout=2))
            self.assertFalse(any(other['id'] in key for key in first['versions']))
            self.h.call('/v1/auth/session', method='DELETE', session=self.session)
            with self.assertRaises(ConnectionClosed) as closed:
                ws.recv(timeout=3)
            self.assertEqual(closed.exception.rcvd.code, 4003)

    def test_native_revocation_and_normal_rotation_have_distinct_close_codes(self):
        _, _, credential = self.h.pair(self.session)
        def opened():
            raw = socket.create_connection(('127.0.0.1', self.h.port), timeout=5)
            return connect('ws://api.wegoh.invalid/v1/events', sock=raw, origin=None, subprotocols=[PROTOCOL],
                additional_headers={'Authorization': 'Bearer ' + credential['accessToken'],
                    'cf-cert-sha256': self.h._native_fingerprint, 'cf-cert-presented': 'true',
                    'cf-cert-verified': 'true', 'cf-cert-revoked': 'false'}, open_timeout=3, close_timeout=1)
        with patch.object(self.h.module.TEAM_AUTH, 'native_socket_seconds', .1):
            with opened() as ws:
                self.assertEqual(json.loads(ws.recv(timeout=3))['type'], 'snapshot')
                with self.assertRaises(ConnectionClosed) as closed:
                    ws.recv(timeout=3)
                self.assertEqual(closed.exception.rcvd.code, 1008)
        with opened() as ws:
            self.assertEqual(json.loads(ws.recv(timeout=3))['type'], 'snapshot')
            self.assertEqual(self.h.call('/v1/devices/' + credential['deviceId'], method='DELETE', session=self.session)[0], 200)
            with self.assertRaises(ConnectionClosed) as closed:
                ws.recv(timeout=3)
            self.assertEqual(closed.exception.rcvd.code, 4003)

    def test_no_offer_keeps_legacy_frames_and_other_offers_are_denied(self):
        with self.socket(None) as ws:
            self.assertIsNone(ws.subprotocol)
            self.assertEqual(set(json.loads(ws.recv(timeout=2))), {'type', 'epoch', 'seq', 'resources'})
        for protocols, path in ((('wegoh.events.v2',), '/v1/events'),
                                ((PROTOCOL, 'wegoh.events.v2'), '/v1/events'),
                                (('Bearer.secret',), '/v1/events'),
                                ((PROTOCOL,), '/v1/events?token=secret')):
            with self.subTest(protocols=protocols, path=path):
                with self.assertRaises(InvalidStatus) as denied:
                    self.socket(protocols, path)
                self.assertEqual(denied.exception.response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
