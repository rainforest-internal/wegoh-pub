"""Phone management adapters and durable car identities on isolated HTTP/DB."""
from datetime import datetime, timezone
import unittest

import psycopg
from test_iphone_trips import IPhoneTripTests


class IPhoneTripManagementTests(IPhoneTripTests):
    def second_vehicle(self):
        web = self.phone.api.login('bob')
        _, _, credential = self.phone.api.pair(web, who='bob')
        self.checked(self.phone.iphone('/v1/iphone/vehicles/' + credential['deviceId'] + '/profile',
            dict(plateNumber='234나5678', name='', expectedRevision=0), 'PUT', token=self.bob['accessToken']))
        return web, credential

    def test_edit_remove_leave_cancel_delete_keep_owner_and_scope_checks(self):
        self.befriend(self.bob)
        self.befriend(self.eve)
        trip = self.create()
        self.join(trip, self.bob)
        self.join(trip, self.eve)
        path = '/' + trip
        data = dict(title='고친 여행', description='새 소개', startDate=None, endDate=None)
        self.assertEqual(self.call(path, data, 'PATCH', session=self.bob)[0], 403)
        self.assertEqual(self.checked(self.call(path, data, 'PATCH')), dict(status='updated'))
        self.assertEqual(self.detail(trip)['title'], '고친 여행')
        self.assertEqual(self.call(path + '/members/' + self.e, {}, 'DELETE', session=self.bob)[0], 403)
        self.checked(self.call(path + '/members/' + self.e, {}, 'DELETE'))
        self.checked(self.call(path + '/members/' + self.b, {}, 'DELETE', session=self.bob))
        self.assertEqual(self.call(path, session=self.bob)[0], 404)
        self.assertEqual(self.call(path, {}, 'DELETE')[0], 409)
        detail = self.detail(trip)
        self.assertEqual(self.call(path + '/cancel', dict(revision=detail['revision'] - 1), 'POST')[0], 409)
        cancelled = self.checked(self.call(path + '/cancel', dict(revision=detail['revision']), 'POST'))
        self.assertEqual(cancelled['state'], 'cancelled')
        self.checked(self.call(path, {}, 'DELETE'))
        self.assertNotIn(trip, [row['id'] for row in self.checked(self.call())['trips']])

    def test_car_ordinal_survives_deletion_and_is_never_reused(self):
        self.befriend(self.bob)
        trip = self.create()
        self.join(trip, self.bob)
        self.vehicle()
        self.second_vehicle()
        base = '/' + trip + '/cars'
        first = self.checked(self.call(base, dict(name='처음 차', seats=2), 'POST'), 201)['id']
        second = self.checked(self.call(base, dict(name='다음 차', seats=2), 'POST', session=self.bob), 201)['id']
        self.assertEqual({c['id']: c['ordinal'] for c in self.detail(trip)['cars']}, {first: 1, second: 2})
        self.assertEqual(self.call(base + '/' + first, dict(name='무단 수정', seats=2), 'PATCH', session=self.bob)[0], 403)
        self.checked(self.call(base + '/' + first, dict(name='고친 차', seats=1), 'PATCH'))
        self.checked(self.call(base + '/' + first, {}, 'DELETE'))
        self.assertEqual([(c['id'], c['ordinal']) for c in self.detail(trip)['cars']], [(second, 2)])
        third = self.checked(self.call(base, dict(name='새 차', seats=2), 'POST'), 201)['id']
        self.assertEqual({c['id']: c['ordinal'] for c in self.detail(trip)['cars']}, {second: 2, third: 3})
        self.assertEqual(self.detail(trip, session=self.bob)['cars'][0]['ordinal'], 2)

    def test_ride_invite_response_and_course_removal_use_current_membership(self):
        self.befriend(self.bob)
        trip = self.create()
        self.join(trip, self.bob)
        self.vehicle()
        car = self.checked(self.call('/' + trip + '/cars', dict(name='함께 탈 차', seats=2), 'POST'), 201)['id']
        web = self.phone.api.login()
        invite = self.checked(self.phone.api.call('/v1/social/trips/' + trip + '/cars/' + car + '/ride-invites',
            dict(accountId=self.b), 'POST', session=web), 201)['id']
        path = '/' + trip + '/cars/' + car + '/ride-invites/' + invite + '/respond'
        self.assertEqual(self.call(path, dict(accept=True), 'POST')[0], 404)
        self.assertEqual(self.checked(self.call(path, dict(accept=True), 'POST', session=self.bob)), dict(status='accepted'))
        self.assertTrue(self.detail(trip, session=self.bob)['cars'][0]['iRide'])
        pack = self.phone.api.pack()
        self.checked(self.phone.api.publish(pack, web), 201)
        self.checked(self.call('/' + trip + '/courses', dict(packId=pack['id']), 'POST'), 201)
        self.assertEqual(self.call('/' + trip + '/courses/' + pack['id'], {}, 'DELETE', session=self.bob)[0], 403)
        self.checked(self.call('/' + trip + '/courses/' + pack['id'], {}, 'DELETE'))
        self.assertEqual(self.detail(trip)['courses'], [])

    def test_locations_return_only_current_shared_fresh_fixes(self):
        self.befriend(self.bob)
        trip = self.create()
        self.join(trip, self.bob)
        base = '/' + trip
        self.assertEqual(self.call(base + '/locations')[0], 409)
        self.checked(self.call(base + '/start', dict(revision=self.detail(trip)['revision']), 'POST'))
        self.assertEqual(self.checked(self.call(base + '/locations'))['locations'], [])
        sharing = self.checked(self.call(base + '/location-sharing', dict(locationConsent=True), 'PATCH', session=self.bob))
        web = self.phone.api.login('bob')
        fix = dict(shareId=sharing['locationShareId'], capturedAt=datetime.now(timezone.utc).isoformat(),
            latitude=37.5, longitude=127.0, accuracyMeters=12)
        self.checked(self.phone.api.call('/v1/social/trips/' + trip + '/locations/me', fix, 'POST', session=web, who='bob'))
        data = self.checked(self.call(base + '/locations'))
        self.assertEqual(len(data['locations']), 1)
        self.assertEqual((data['locations'][0]['accountId'], data['locations'][0]['source']), (self.b, 'phone'))
        self.assertIsNone(data['shareId'])
        self.checked(self.call(base + '/location-sharing', dict(locationConsent=False), 'PATCH', session=self.bob))
        self.assertEqual(self.checked(self.call(base + '/locations'))['locations'], [])
        self.assertEqual(self.call(base + '/locations', session=self.eve)[0], 404)
        self.assertEqual(self.call(base + '/locations?unknown=1')[0], 400)

    def test_phone_response_source_is_server_assigned_and_first_response_is_final(self):
        self.befriend(self.bob)
        trip = self.create()
        self.join(trip, self.bob)
        self.vehicle()
        web, _ = self.second_vehicle()
        for session, name in ((self.alice, '첫 차'), (self.bob, '둘째 차')):
            self.checked(self.call('/' + trip + '/cars', dict(name=name, seats=2), 'POST', session=session), 201)
        self.checked(self.call('/' + trip + '/start', dict(revision=self.detail(trip)['revision']), 'POST'))
        signal = self.checked(self.call('/' + trip + '/signals', dict(kind='cafe', destination=dict(
            name='실제 선택 장소', latitude=37.5, longitude=127.0)), 'POST'), 201)['id']
        path = '/' + trip + '/signals/' + signal + '/vote'
        self.assertEqual(self.call(path, dict(choice='agree', source='native'), 'POST', session=self.bob)[0], 400)
        self.checked(self.call(path, dict(choice='agree'), 'POST', session=self.bob))
        self.checked(self.phone.api.call('/v1/social/trips' + path, dict(choice='pass'), 'POST', session=web, who='bob'))
        group = self.checked(self.call('/' + trip + '/signals'))['signals'][0]['groupResponses'][0]
        self.assertEqual((group['responseSource'], group['choice']), ('iphone', 'agree'))
        with psycopg.connect(self.phone.api.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_trip_signal_contexts WHERE signal_id=%s', (signal,)).fetchone()[0]
            self.assertNotIn(b'iphone', bytes(raw))

    def test_added_mutations_recheck_phone_scope(self):
        trip = self.create()
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s WHERE account_id=%s', (['trips:read'], self.a))
        for path, body, method in (
            ('/' + trip, dict(title='금지', description=''), 'PATCH'),
            ('/' + trip + '/cancel', dict(revision=self.detail(trip)['revision']), 'POST'),
            ('/' + trip + '/members/' + self.b, {}, 'DELETE'),
            ('/' + trip + '/cars/' + 'a' * 32, dict(name='금지', seats=2), 'PATCH'),
            ('/' + trip + '/cars/' + 'a' * 32, {}, 'DELETE'),
            ('/' + trip + '/courses/example', {}, 'DELETE')):
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(path, body, method)[0], 403)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(IPhoneTripManagementTests(name) for name in IPhoneTripManagementTests.__dict__ if name.startswith('test_'))
