import copy
import unittest
from unittest.mock import patch

import psycopg

import test_iphone_trips as fixture
from team_trip_hand_raise import HandRaiseCandidates
from test_trip_hand_raise import FakeKakao


class IPhoneTripFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.IPhoneTripTests.setUpClass.__func__(cls)

    def setUp(self):
        self.h = fixture.IPhoneTripTests()
        self.h.setUp()
        self.addCleanup(self.h.phone.doCleanups)
        h = self.h
        h.befriend(h.bob)
        h.befriend(h.eve)
        self.trip = h.create()
        h.join(self.trip, h.bob)
        h.join(self.trip, h.eve)
        self.vehicle = h.vehicle()
        self.certificate = h.phone.api._native_fingerprint
        self.car = h.checked(h.call('/' + self.trip + '/cars',
            dict(name='실제 HTTP 경로의 차', seats=2), 'POST'), 201)['id']
        h.checked(h.call('/' + self.trip + '/cars/' + self.car + '/ride', {}, 'PUT', session=h.bob))
        self.packs = []
        self.add_course()

    def add_course(self):
        h = self.h
        pack = h.phone.api.pack()
        pack['stops'] = [dict(pack['stops'][0], id='join', name='합류 장소'),
            dict(pack['stops'][0], id='last', name='마지막 공유 장소', latitude=37.51)]
        h.checked(h.phone.iphone('/v1/iphone/courses', dict(pack=pack, rightsConfirmed=True),
            'POST', token=h.alice['accessToken']), 201)
        h.checked(h.call('/' + self.trip + '/courses', dict(packId=pack['id']), 'POST'), 201)
        self.packs.append(pack)
        return pack

    def start(self):
        h = self.h
        revision = h.detail(self.trip)['revision']
        started = h.checked(h.call('/' + self.trip + '/start',
            dict(revision=revision, routeContractVersion=2), 'POST'))
        self.assertEqual(started['state'], 'active')
        self.assertGreater(started['revision'], revision)
        return started

    def current_car(self, *, session=None, car=None):
        return next(value for value in self.h.detail(self.trip, session=session)['cars']
            if value['id'] == (car or self.car))

    def arrive(self, *, vehicle=None, certificate=None, car=None, session=None, body=None):
        h = self.h
        vehicle = vehicle or self.vehicle
        certificate = certificate or self.certificate
        current = self.current_car(session=session, car=car)
        route = current['routePlan']
        self.assertIsNotNone(route)
        self.assertIsNotNone(route['next'])
        permissions = h.checked(h.phone.api.native('/v1/device/functional-permissions',
            token=vehicle['accessToken'], certificate=certificate))
        data = dict(routeRevision=current['routeRevision'], progressRevision=route['progressRevision'],
            item=copy.deepcopy(route['next']), functionalRevision=permissions['revision'])
        if body:
            data.update(body)
        return h.phone.api.native('/v1/native/trips/' + self.trip + '/cars/' + (car or self.car) + '/route-arrivals',
            data, 'POST', vehicle['accessToken'], certificate=certificate)

    def denied_signals(self, session, reason):
        h = self.h
        requests = [('/signals', dict(kind='rest')),
            ('/signals/candidates', dict(kind='rest', location=dict(lat=37.5, lng=127, heading=0)))]
        with patch.object(h.phone.api.module.TEAM_AUTH.hand_raise_service, 'admit',
                side_effect=AssertionError('Denied phase must not reach the map provider')):
            for suffix, data in requests:
                with self.subTest(account=session['user']['displayName'], suffix=suffix, reason=reason):
                    result = h.call('/' + self.trip + suffix, data, 'POST', session=session)
                    self.assertEqual((result[0], result[2]), (409, dict(detail=reason)))

    def test_iphone_host_starts_v2_and_reads_native_arrivals_without_location(self):
        h = self.h
        revision = h.detail(self.trip)['revision']
        self.assertEqual(h.call('/' + self.trip + '/start',
            dict(revision=revision, routeContractVersion=2), 'POST', session=h.bob)[0], 403)
        self.assertEqual(h.detail(self.trip)['state'], 'planned')
        started = self.start()
        initial = self.current_car()['routePlan']
        self.assertEqual(initial['contractVersion'], 2)
        self.assertEqual(initial['phase'], 'pickup')
        self.assertEqual(initial['next'], dict(type='course', courseId=self.packs[0]['id'], ref='join'))
        with psycopg.connect(h.phone.api.dsn) as conn:
            self.assertIsNone(conn.execute('SELECT ended_at FROM team_trips WHERE trip_id=%s', (self.trip,)).fetchone()[0])
        reply = h.checked(self.arrive())
        self.assertEqual(reply['routePlan']['phase'], 'shared')
        shown = self.current_car(session=h.bob)['routePlan']
        self.assertEqual(shown['next']['ref'], 'last')
        self.assertEqual(shown['progressRevision'], initial['progressRevision'] + 1)
        self.assertEqual(shown['joinBarrier'], dict(arrivedCarIds=[self.car], totalCarCount=1, released=True))
        h.checked(self.arrive())
        completed = h.detail(self.trip)
        self.assertEqual(completed['state'], 'completed')
        with psycopg.connect(h.phone.api.dsn) as conn:
            self.assertIsNotNone(conn.execute('SELECT ended_at FROM team_trips WHERE trip_id=%s', (self.trip,)).fetchone()[0])
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results WHERE trip_id=%s',
                (self.trip,)).fetchone()[0], 1)
        self.assertEqual(self.current_car()['routePlan']['phase'], 'done')
        retry = h.checked(h.call('/' + self.trip + '/start',
            dict(revision=started['revision'], routeContractVersion=2), 'POST'), 409)
        self.assertEqual(retry['detail'], 'TRIP_STATE_CONFLICT')

    def raise_and_cancel(self, session):
        h = self.h
        created = h.checked(h.call('/' + self.trip + '/signals', dict(kind='rest'), 'POST', session=session), 201)
        signals = h.checked(h.call('/' + self.trip + '/signals', session=session))['signals']
        # Requests cancelled in earlier phases stay in the trip's signal list.
        self.assertIn(created['id'], [value['id'] for value in signals])
        h.checked(h.call('/' + self.trip + '/signals/' + created['id'] + '/finish',
            dict(result='cancelled'), 'POST', session=session))

    def test_assigned_rider_raises_hands_in_every_route_phase_until_completed(self):
        h = self.h
        drop = h.checked(h.call('/' + self.trip + '/cars/' + self.car + '/places',
            dict(kind='drop', name='하차 장소', lat=37.52, lng=127), 'POST'), 201)['id']
        self.start()
        self.assertEqual(self.current_car(session=h.bob)['routePlan']['phase'], 'pickup')
        self.raise_and_cancel(h.bob)
        self.denied_signals(h.eve, 'TRIP_SIGNAL_CAR_REQUIRED')
        h.checked(self.arrive())
        self.assertEqual(self.current_car(session=h.bob)['routePlan']['phase'], 'shared')
        self.raise_and_cancel(h.bob)
        self.denied_signals(h.eve, 'TRIP_SIGNAL_CAR_REQUIRED')
        h.checked(self.arrive())
        next_car = self.current_car(session=h.bob)
        self.assertEqual(next_car['routePlan']['phase'], 'drop')
        self.assertEqual(next_car['routePlan']['next'], dict(type='drop', ref=drop))
        self.raise_and_cancel(h.bob)
        self.denied_signals(h.eve, 'TRIP_SIGNAL_CAR_REQUIRED')
        h.checked(self.arrive())
        self.assertEqual(h.detail(self.trip)['state'], 'completed')
        self.denied_signals(h.bob, 'TRIP_STATE_CONFLICT')
        self.denied_signals(h.eve, 'TRIP_STATE_CONFLICT')

    def test_waiting_rider_queries_candidates_before_every_car_joins(self):
        h = self.h
        h.checked(h.call('/' + self.trip + '/ride', {}, 'DELETE', session=h.bob))
        h.checked(h.call('/' + self.trip + '/cars/' + self.car + '/ride', {}, 'PUT', session=h.eve))
        web = h.phone.api.login('bob')
        _, _, second_vehicle = h.phone.api.pair(web, who='bob')
        h.checked(h.phone.iphone('/v1/iphone/vehicles/' + second_vehicle['deviceId'] + '/profile',
            dict(plateNumber='234나5678', name='', expectedRevision=0), 'PUT', token=h.bob['accessToken']))
        h.checked(h.call('/' + self.trip + '/cars', dict(name='함께 합류할 차', seats=2),
            'POST', session=h.bob), 201)
        self.start()
        h.checked(self.arrive())
        self.assertEqual(self.current_car(session=h.eve)['routePlan']['phase'], 'waiting')
        fake = FakeKakao()
        with patch.object(h.phone.api.module.TEAM_AUTH, 'hand_raise_service', HandRaiseCandidates(fake.provider())):
            response = h.call('/' + self.trip + '/signals/candidates',
                dict(kind='rest', location=dict(lat=37.5, lng=127, heading=0)), 'POST', session=h.eve)
        h.checked(response)
        self.assertIn('candidates', response[2])

    def test_iphone_finish_is_owner_only_and_revision_checked(self):
        h = self.h
        self.start()
        before = h.detail(self.trip)
        base = '/' + self.trip + '/finish'
        self.assertEqual(h.call(base, dict(revision=before['revision']), 'POST', session=h.bob)[0], 403)
        stale = h.call(base, dict(revision=before['revision'] - 1), 'POST')
        self.assertEqual((stale[0], stale[2]), (409, dict(detail='TRIP_STATE_CONFLICT')))
        self.assertEqual(h.detail(self.trip)['state'], 'active')
        result = h.checked(h.call(base, dict(revision=before['revision']), 'POST'))
        self.assertEqual(result['state'], 'completed')
        self.assertIsNotNone(result['endedAt'])
        self.assertEqual(h.checked(h.call(base, dict(revision=before['revision']), 'POST')), result)
        with psycopg.connect(h.phone.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results WHERE trip_id=%s',
                (self.trip,)).fetchone()[0], 1)

    def test_iphone_shared_course_order_is_owner_only_even_with_edit_permission(self):
        h = self.h
        second = self.add_course()
        web = h.phone.api.login()
        h.checked(h.phone.api.call('/v1/social/trips/' + self.trip + '/members/' + h.b + '/permissions',
            dict(invite=False, edit=True), 'PUT', session=web))
        self.assertTrue(h.detail(self.trip, session=h.bob)['myPermissions']['edit'])
        before = h.detail(self.trip)
        path = '/' + self.trip + '/courses/priority'
        order = [second['id'], self.packs[0]['id']]
        data = dict(packIds=order, revision=before['revision'])
        self.assertEqual(h.call(path, data, 'PUT', session=h.bob)[0], 403)
        self.assertEqual(h.detail(self.trip)['courses'], before['courses'])
        changed = h.checked(h.call(path, data, 'PUT'))
        self.assertGreater(changed['revision'], before['revision'])
        self.assertEqual([value['packId'] for value in h.detail(self.trip, session=h.bob)['courses']], order)
        self.assertEqual(h.call(path, dict(packIds=list(reversed(order)), revision=before['revision']), 'PUT')[0], 409)


if __name__ == '__main__':
    unittest.main()
