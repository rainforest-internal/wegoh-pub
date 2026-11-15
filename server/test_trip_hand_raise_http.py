"""Hand-raise candidate HTTP authority on an isolated PostgreSQL fixture with fake Kakao transports."""
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import psycopg
import test_native_functional_trips as fixture
from team_trip_hand_raise import HandRaiseCandidates
from test_trip_hand_raise import DESTINATION, FakeKakao, LEAD, REQUESTER

CONSENTS = {key: key in ('status', 'location') for key in ('status', 'location', 'visits', 'music', 'voice', 'control')}


class TripHandRaiseHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.NativeTripTests.setUpClass()
        cls.addClassCleanup(fixture.NativeTripTests.tearDownClass)

    def setUp(self):
        self.n = fixture.NativeTripTests()
        self.n.setUp()
        self.addCleanup(self.n.doCleanups)
        n = self.n
        n.browser(n.guest, n.path + '/respond', dict(accept=True), 'POST')
        self.fake = FakeKakao()
        auth = n.h.module.TEAM_AUTH
        patcher = patch.object(auth, 'hand_raise_service', HandRaiseCandidates(self.fake.provider()))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.web = n.path + '/signals/candidates'
        self.native_path = '/v1/native/trips/' + n.trip + '/signals/candidates'
        self.body = dict(kind='restroom', location=dict(lat=REQUESTER[0], lng=REQUESTER[1], heading=205),
            destination=DESTINATION)

    def call(self, session, path, body=None, method='GET', **kwargs):
        return self.n.h.call(path, body, method, session=session, who=session['user']['displayName'], **kwargs)

    def share(self, session):
        self.n.browser(session, self.n.path + '/location-sharing', dict(locationConsent=True), 'PATCH')
        self.n.browser(session, self.n.path + '/sharing', dict(consents=CONSENTS), 'PATCH')

    def start(self):
        revision = self.n.browser(self.n.owner, self.n.path + '/workspace')['revision']
        self.n.browser(self.n.owner, self.n.path + '/start', dict(revision=revision), 'POST')

    def counts(self):
        with psycopg.connect(self.n.h.dsn) as conn:
            return {table: conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in
                ('team_room_signals', 'team_trip_signal_contexts', 'team_vehicle_latest_reports', 'team_vehicle_report_receipts')}

    def owner_car_report(self):
        n = self.n
        owner_device = n.factory.connect(n.owner)
        n.browser(n.owner, '/v1/devices/' + owner_device['deviceId'] + '/vehicle-profile',
            dict(plateNumber='12가3456', name='', expectedRevision=0), 'PUT')
        n.browser(n.owner, n.path + '/cars', dict(name='방장 차', seats=2), 'POST', 201)
        revision = n.factory.approve(n.owner, owner_device, ['vehicle-location:report'])
        domain = n.browser(n.owner, '/v1/devices/' + owner_device['deviceId'] + '/trips/' + n.trip + '/vehicle-domain')
        reporting = domain['tripReporting']
        reporting = n.browser(n.owner, n.path + '/device-reporting', dict(deviceId=owner_device['deviceId'],
            revision=reporting['revision'], joinedAt=reporting['joinedAt'], devicePermissionRevision=revision,
            shareLocation=True, shareVisits=False, receiveLocation=False, receiveVisits=False, expiresInHours=1), 'PUT')['tripReporting']
        report = dict(eventId=secrets.token_hex(16), devicePermissionRevision=revision, reportingRevision=reporting['revision'],
            capturedAt=datetime.now(timezone.utc).isoformat(), latitude=LEAD[0], longitude=LEAD[1], accuracyMeters=5.0,
            functionalRevision=revision)
        result = n.factory.native(owner_device, '/v1/native/trips/' + n.trip + '/reports/location', report, 'POST')
        self.assertEqual(result[0], 200, result[2])
        return owner_device

    def receive_on_web(self, session):
        current = self.n.browser(session, self.n.path + '/report-receiving')
        self.n.browser(session, self.n.path + '/report-receiving', dict(revision=current['revision'],
            joinedAt=current['joinedAt'], receiveLocation=True, receiveVisits=False, expiresInHours=1), 'PUT')

    def owner_car(self, value):
        return next(car for car in value['cars'] if car['carId'] != value['cars'][0]['carId'])

    def test_current_trip_location_reaches_other_cars_without_receiver_or_friendship(self):
        n = self.n
        n.browser(n.guest, '/v1/devices/' + n.device['deviceId'] + '/vehicle-profile',
            dict(plateNumber='34나5678', name='', expectedRevision=0), 'PUT')
        guest_car = n.browser(n.guest, n.path + '/cars', dict(name='손든 차', seats=2), 'POST', 201)['id']
        self.share(n.owner)
        self.share(n.guest)
        self.assertEqual(self.call(n.guest, self.web, self.body, 'POST')[2], dict(detail='TRIP_STATE_CONFLICT'))
        self.start()
        self.owner_car_report()
        before = self.counts()
        self.assertEqual(self.call(n.guest, '/v1/social/friends/' + n.owner['user']['id'], method='DELETE')[0], 200)
        status, headers, value = self.call(n.guest, self.web, self.body, 'POST')
        self.assertEqual(status, 200, value)
        self.assertEqual(headers['cache-control'], 'private, no-store')
        self.assertEqual(value['cars'][0], dict(carId=guest_car, state='same_road', alongMeters=0))
        self.assertEqual((value['basis'], value['partial']), ('route', False))
        self.assertEqual(value['candidates'][0]['name'], '화성휴게소(목포방향)')
        self.assertEqual(self.fake.calls[0], ('directions', 'angle=205', None))
        owner = self.owner_car(value)
        self.assertEqual(owner['state'], 'same_road')
        self.assertTrue(2500 < owner['alongMeters'] < 3500)
        self.assertEqual(self.counts(), before)
        revision = n.approve(['rooms:read'])
        native = n.native(self.native_path, dict(self.body, functionalRevision=revision), 'POST')
        self.assertEqual(self.owner_car(native), owner)
        self.assertEqual(native['candidates'][0]['name'], '화성휴게소(목포방향)')
        n.native(self.native_path, dict(self.body, functionalRevision=revision + 1), 'POST', expected=409)
        n.native(self.native_path, self.body, 'POST', expected=400)
        self.assertIn(n.factory.native(n.device, self.web, dict(self.body, functionalRevision=revision), 'POST')[0], (403, 404))
        native_reports = n.native('/v1/native/trips/' + n.trip + '/device-reports')['reports']
        self.assertEqual([r['accountId'] for r in native_reports], [n.owner['user']['id']])
        self.assertIsNone(native_reports[0]['visit'])
        self.assertEqual(self.counts()['team_room_signals'], before['team_room_signals'])

    def test_link_participant_sees_live_location_only_during_membership(self):
        n = self.n
        path = n.path + '/device-reports'
        link = n.browser(n.owner, n.path + '/link', {}, 'POST', 201)['token']
        eve = n.h.login('eve')
        self.share(n.owner)
        self.start()
        self.owner_car_report()
        n.browser(eve, path, expected=404)
        join = dict(token=link, locationConsent=False)
        n.browser(eve, '/v1/social/trip-links/join', join, 'POST')
        reports = n.browser(eve, path)['reports']
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['accountId'], n.owner['user']['id'])
        self.assertEqual(reports[0]['location']['latitude'], LEAD[0])
        self.assertIsNone(reports[0]['visit'])
        n.browser(eve, n.path + '/members/' + eve['user']['id'], {}, 'DELETE')
        n.browser(eve, path, expected=404)
        other = n.browser(eve, '/v1/social/trips',
            dict(title='다른 여행', description='', memberIds=[]), 'POST', 201)['id']
        other_path = '/v1/social/trips/' + other
        revision = n.browser(eve, other_path + '/workspace')['revision']
        n.browser(eve, other_path + '/start', dict(revision=revision), 'POST')
        self.assertEqual(n.browser(eve, other_path + '/device-reports')['reports'], [])
        n.browser(eve, '/v1/social/trip-links/join', join, 'POST', 409)
        revision = n.browser(eve, other_path + '/workspace')['revision']
        n.browser(eve, other_path + '/finish', dict(revision=revision), 'POST')
        n.browser(eve, '/v1/social/trip-links/join', join, 'POST')
        self.assertEqual(n.browser(eve, path)['reports'][0]['accountId'], n.owner['user']['id'])
        n.browser(eve, '/v1/social/blocks', dict(targetId=n.owner['user']['id']), 'POST', 201)
        n.browser(eve, path, expected=404)
        revision = n.browser(n.owner, n.path + '/workspace')['revision']
        n.browser(n.owner, n.path + '/finish', dict(revision=revision), 'POST')
        n.browser(n.guest, path, expected=409)

    def test_withdrawn_report_makes_the_car_unknown(self):
        n = self.n
        self.share(n.owner)
        self.share(n.guest)
        self.start()
        self.owner_car_report()
        self.receive_on_web(n.guest)
        self.assertEqual(self.owner_car(self.call(n.guest, self.web, self.body, 'POST')[2])['state'], 'same_road')
        n.browser(n.owner, n.path + '/device-reporting', method='DELETE')
        value = self.call(n.guest, self.web, self.body, 'POST')[2]
        self.assertEqual(self.owner_car(value), dict(carId=value['cars'][1]['carId'], state='unknown', alongMeters=None))

    def test_membership_consent_csrf_and_input_boundaries(self):
        n = self.n
        self.share(n.owner)
        self.share(n.guest)
        self.start()
        eve = n.h.login('eve')
        self.assertEqual(self.call(eve, self.web, self.body, 'POST')[0], 404)
        self.assertEqual(self.call(n.guest, self.web, self.body, 'POST', csrf=False)[0], 403)
        for body, detail in ((dict(self.body, kind='arrived'), 'Invalid hand-raise kind'),
                (dict(self.body, location=dict(lat=37.2, lng=200)), 'Invalid location'),
                (dict(kind='rest', location=dict(lat=37.2, lng=126.9)), 'Choose a destination or heading'),
                (dict(self.body, extra=True), 'Invalid trip fields')):
            with self.subTest(detail=detail):
                self.assertEqual(self.call(n.guest, self.web, body, 'POST')[2], dict(detail=detail))
        heading = self.call(n.guest, self.web, dict(self.body, destination=None), 'POST')[2]
        self.assertEqual(heading['basis'], 'heading')
        self.assertEqual(heading['cars'], [dict(carId=None, state='same_road', alongMeters=0)])
        n.browser(n.guest, n.path + '/location-sharing', dict(locationConsent=False), 'PATCH')
        self.assertEqual(self.call(n.guest, self.web, self.body, 'POST')[0], 200)
        n.browser(n.guest, n.path + '/sharing',
            dict(consents={key: False for key in CONSENTS}), 'PATCH')
        self.assertEqual(self.call(n.guest, self.web, self.body, 'POST')[0], 200)
        with patch.object(n.h.module.TEAM_AUTH, 'hand_raise_service', HandRaiseCandidates(None)):
            self.share(n.guest)
            self.assertEqual(self.call(n.guest, self.web, self.body, 'POST')[2], dict(detail='CANDIDATES_UNAVAILABLE'))

    def test_hungry_signal_is_a_stop_kind(self):
        n = self.n
        self.share(n.owner)
        self.share(n.guest)
        self.start()
        self.owner_car_report()
        n.browser(n.guest, '/v1/devices/' + n.device['deviceId'] + '/vehicle-profile',
            dict(plateNumber='34나5678', name='', expectedRevision=0), 'PUT')
        n.browser(n.guest, n.path + '/cars', dict(name='참여 차', seats=2), 'POST', 201)
        place = dict(name='화성휴게소', latitude=37.1436, longitude=126.879)
        result = self.call(n.guest, n.path + '/signals', dict(kind='hungry', destination=place), 'POST')
        self.assertEqual(result[0], 201, result[2])
        signal = result[2]['id']
        self.assertEqual(self.call(n.owner, n.path + '/signals/' + signal + '/vote', dict(choice='agree'), 'POST')[0], 200)
        listed = self.call(n.guest, n.path + '/signals')[2]['signals']
        self.assertEqual((listed[0]['kind'], listed[0]['agreed']), ('hungry', True))

    def test_passenger_candidate_and_native_approval_add_one_waypoint_per_car(self):
        n = self.n
        passenger = n.h.login('eve')
        token = n.browser(n.owner, n.path + '/link', {}, 'POST', 201)['token']
        n.browser(passenger, '/v1/social/trip-links/join', dict(token=token, locationConsent=False), 'POST')
        n.browser(n.guest, '/v1/devices/' + n.device['deviceId'] + '/vehicle-profile',
            dict(plateNumber='34나5678', name='', expectedRevision=0), 'PUT')
        passenger_car = n.browser(n.guest, n.path + '/cars', dict(name='동승자 차', seats=2), 'POST', 201)['id']
        n.browser(passenger, n.path + '/cars/' + passenger_car + '/ride', {}, 'PUT')
        self.share(n.owner)
        self.start()
        owner_device = self.owner_car_report()

        candidates = n.browser(passenger, self.web, self.body, 'POST')
        self.assertEqual(candidates['basis'], 'route')
        candidate = candidates['candidates'][0]
        self.assertEqual((candidate['name'], candidate['verdict']), ('화성휴게소(목포방향)', 'ahead'))
        destination = dict(name=candidate['name'], latitude=candidate['lat'], longitude=candidate['lng'])
        revision = n.factory.approve(n.owner, owner_device, ['rooms:read', 'rooms:interact', 'vehicle-location:report'])
        detail = '/v1/native/trips/' + n.trip
        before = {car['id']: car for car in n.native(detail, device=owner_device)['cars']}
        self.assertEqual(len(before), 2)
        signals = n.path + '/signals'
        signal = n.browser(passenger, signals, dict(kind='restroom', destination=destination), 'POST', 201)['id']
        shown = n.native(signals, device=owner_device)['signals'][0]
        self.assertEqual((shown['id'], shown['kind'], shown['destination']), (signal, 'restroom', destination))
        self.assertEqual(shown['requesterCarId'], passenger_car)
        self.assertTrue(shown['canRespond'])
        self.assertFalse(n.browser(passenger, signals)['signals'][0]['canRespond'])

        vote = signals + '/' + signal + '/vote'
        denied = self.call(n.guest, vote, dict(choice='agree'), 'POST')
        self.assertEqual((denied[0], denied[2]), (403, dict(detail='TRIP_SIGNAL_OTHER_GROUP_REQUIRED')))
        self.assertEqual({car['id']: car for car in n.native(detail, device=owner_device)['cars']}, before)
        agreement = dict(choice='agree', functionalRevision=revision)
        n.native(vote, agreement, 'POST', device=owner_device)
        after = n.native(detail, device=owner_device)['cars']
        n.native(vote, agreement, 'POST', device=owner_device)
        self.assertEqual(n.native(detail, device=owner_device)['cars'], after)
        waypoint = dict(type='signal', ref=signal)
        for car in after:
            self.assertEqual(car['routeRevision'], before[car['id']]['routeRevision'] + 1)
            self.assertEqual(car['routeOrder'].count(waypoint), 1)
            self.assertEqual(car['routeNext'], waypoint)
            self.assertIn(dict(id=signal, kind='signal', name=candidate['name'], lat=candidate['lat'],
                lng=candidate['lng']), car['places'])
        mobile_cars = n.browser(passenger, n.path)['cars']
        mobile_route = next(car for car in mobile_cars if car['id'] == passenger_car)
        self.assertEqual(mobile_route['routeNext'], waypoint)
        resolved = n.browser(passenger, signals)['signals'][0]
        self.assertEqual((resolved['id'], resolved['resolution'], resolved['agreed']), (signal, 'agreed', True))


if __name__ == '__main__':
    unittest.main()
