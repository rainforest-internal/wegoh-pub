import http.client
import json
import unittest
from unittest.mock import patch

import psycopg

from native_functional_policy import FunctionalError, authorize
import test_native_functional_trips as fixture
from test_trip_driving_scores import score


class SegmentedRouteNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.NativeTripTests.setUpClass()
        cls.addClassCleanup(fixture.NativeTripTests.tearDownClass)

    def setUp(self):
        self.h = fixture.NativeTripTests()
        self.h.setUp()
        self.addCleanup(self.h.factory.h.doCleanups)
        h = self.h
        h.browser(h.guest, h.path + '/respond', dict(accept=True), 'POST')
        h.browser(h.guest, '/v1/devices/' + h.device['deviceId'] + '/vehicle-profile',
            dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT')
        self.revision = h.approve(['rooms:read', 'rooms:interact', 'driving-score:report'])
        self.base = '/v1/native/trips/' + h.trip
        self.car = h.native(self.base + '/cars', dict(name='내 차', seats=2, functionalRevision=self.revision), 'POST', 201)['id']
        self.path = self.base + '/cars/' + self.car
        self.pickup = h.native(self.path + '/places', dict(kind='pickup', name='픽업', lat=37.4, lng=127,
            functionalRevision=self.revision), 'POST', 201)['id']
        self.drop = h.native(self.path + '/places', dict(kind='drop', name='드랍', lat=37.6, lng=127,
            functionalRevision=self.revision), 'POST', 201)['id']
        self.pack = h.h.pack()
        self.pack['author'] = '사용자A'
        self.pack['stops'].append(dict(self.pack['stops'][0], id='last', name='도착', latitude=37.55))
        published = h.h.publish(self.pack, h.guest, 'bob')
        self.assertEqual(published[0], 201, published[2])
        h.h.approve(self.pack, h.owner)
        h.browser(h.guest, h.path + '/courses', dict(packId=self.pack['id']), 'POST', 201)

    def start(self, version=2):
        data = dict(revision=self.h.browser(self.h.owner, self.h.path)['revision'])
        if version is not None:
            data['routeContractVersion'] = version
        return self.h.browser(self.h.owner, self.h.path + '/start', data, 'POST')

    def car_detail(self):
        return self.h.native(self.base)['cars'][0]

    def arrive(self, single_join_completion=False):
        car = self.car_detail()
        body = dict(routeRevision=car['routeRevision'], progressRevision=car['routePlan']['progressRevision'],
            item=car['routePlan']['next'], functionalRevision=self.revision)
        if single_join_completion:
            body['singleJoinCompletion'] = 'explicit-v1'
        return self.h.native(self.path + '/route-arrivals', body, 'POST')

    def section(self, versions=()):
        h = self.h
        conn = http.client.HTTPConnection('127.0.0.1', h.h.port, timeout=5)
        conn.putrequest('GET', self.base + '?section=route', skip_host=True)
        headers = {'Host': 'api.wegoh.invalid', 'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + h.device['accessToken'],
            'cf-cert-sha256': h.factory.certificates[h.device['grantId']],
            'cf-cert-presented': 'true', 'cf-cert-verified': 'true', 'cf-cert-revoked': 'false'}
        for key, value in headers.items():
            conn.putheader(key, value)
        for version in versions:
            conn.putheader('X-WegoH-Trip-Route-Contract', version)
        conn.endheaders()
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result

    def test_old_and_negotiated_section_have_distinct_exact_keys(self):
        for started in (False, True):
            if started:
                self.start(None)
            status, old = self.section()
            self.assertEqual(status, 200, old)
            self.assertEqual(set(old), {'id', 'revision', 'cars', 'courses'})
            self.assertTrue(set(old['cars'][0]) <= {'id', 'isMine', 'iRide', 'places', 'routeOrder', 'routeRevision', 'routeNext'})
            status, modern = self.section(('2',))
            self.assertEqual(status, 200, modern)
            self.assertEqual(set(modern), {'id', 'revision', 'cars', 'courses', 'routeContractVersion'})
            self.assertEqual(modern['routeContractVersion'], 1)
            self.assertIsNone(modern['cars'][0]['routePlan'])
        for invalid in (('1',), ('3',), ('02',), ('2', '2')):
            self.assertEqual(self.section(invalid), (400, dict(detail='TRIP_ROUTE_PRESENTATION_INVALID')))

    def test_new_arrival_requires_both_existing_purposes(self):
        purposes = frozenset(('rooms:read', 'rooms:interact'))
        self.assertTrue(authorize('POST', self.path + '/route-arrivals', purposes))
        for purpose in purposes:
            with self.assertRaises(FunctionalError) as error:
                authorize('POST', self.path + '/route-arrivals', purposes - {purpose})
            self.assertEqual(error.exception.code, 'FUNCTIONAL_PURPOSE_REQUIRED')
        self.start()
        car = self.car_detail()
        body = dict(routeRevision=car['routeRevision'], progressRevision=0, item=car['routePlan']['next'], functionalRevision=self.revision)
        self.h.native(self.path + '/route-arrivals', dict(body, functionalRevision=self.revision + 1), 'POST', 409)
        self.h.native(self.path + '/route-arrivals', dict(body, speedKmh=20), 'POST', 400)
        self.h.native(self.path + '/route-arrivals', body, 'POST')
        self.h.native(self.path + '/route-arrivals', body, 'POST')

    def test_shared_score_boundaries_final_after_autocomplete_and_same_car_privacy(self):
        h = self.h
        h.browser(h.owner, h.path + '/cars/' + self.car + '/ride', method='PUT')
        self.start()
        path = self.path + '/courses/' + self.pack['id']
        body = dict(drivingScore=score(), functionalRevision=self.revision)
        h.native(path + '/driving-score', body, 'PUT', 409)
        self.arrive()
        self.arrive()
        self.assertEqual(self.car_detail()['routePlan']['phase'], 'shared')
        h.native(path + '/driving-score', body, 'PUT')
        self.assertEqual(h.browser(h.owner, h.path)['courses'][0]['drivingScores'], [dict(carId=self.car, **score())])
        for extra in ('speedKmh', 'samples', 'timestamps', 'location'):
            h.native(path + '/driving-score', dict(body, drivingScore=dict(score(), **{extra: []})), 'PUT', 400)
        self.arrive()
        self.assertEqual(self.car_detail()['routePlan']['phase'], 'drop')
        h.native(path + '/driving-score', body, 'PUT', 409)
        h.browser(h.owner, h.path + '/ride', method='DELETE')
        self.assertEqual(h.browser(h.owner, h.path)['courses'][0]['drivingScores'], [])
        self.arrive()
        self.assertEqual(h.browser(h.owner, h.path)['state'], 'completed')
        final = dict(drivingScore=score(final=True), functionalRevision=self.revision)
        h.native(path + '/complete', final, 'POST')
        h.native(path + '/complete', final, 'POST')
        h.native(path + '/complete', dict(final, drivingScore=score(2, 1, final=True)), 'POST', 409)
        h.native(path + '/driving-score', body, 'PUT', 409)
        self.assertTrue(h.native(self.base)['courses'][0]['drivingScores'][0]['final'])
        self.assertEqual(h.browser(h.owner, h.path)['courses'][0]['drivingScores'], [])

    def test_candidates_open_in_every_route_phase_and_recheck_after_trip_finish(self):
        self.start()
        h = self.h
        service = h.h.module.TEAM_AUTH.hand_raise_service
        body = dict(kind='rest', location=dict(lat=37.5, lng=127, heading=0), functionalRevision=self.revision)
        phases = []
        with patch.object(service, 'admit', return_value=None):
            for arrivals in (0, 2, 1):
                for _ in range(arrivals):
                    self.arrive()
                phases.append(self.car_detail()['routePlan']['phase'])
                with patch.object(service, 'find', return_value=dict(candidates=[])) as find:
                    self.assertEqual(h.native(self.base + '/signals/candidates', body, 'POST'), dict(candidates=[]))
                    find.assert_called_once()
            self.assertEqual(phases, ['pickup', 'shared', 'drop'])
            def provider(*args, **kwargs):
                self.arrive()
                return dict(candidates=[])
            with patch.object(service, 'find', side_effect=provider) as find:
                error = h.native(self.base + '/signals/candidates', body, 'POST', 409)
                self.assertEqual(error['detail'], 'TRIP_STATE_CONFLICT')
                find.assert_called_once()
        self.assertEqual(h.browser(h.owner, h.path)['state'], 'completed')
        with patch.object(service, 'admit') as admit, patch.object(service, 'find') as find:
            h.native(self.base + '/signals/candidates', body, 'POST', 409)
            admit.assert_not_called()
            find.assert_not_called()

    def test_single_join_stop_waits_for_explicit_complete_without_invented_score_and_accepts_final_null(self):
        h = self.h
        for place in (self.pickup, self.drop):
            h.native(self.path + '/places/' + place, dict(functionalRevision=self.revision), 'DELETE')
        self.pack['version'] = 2
        self.pack['stops'] = self.pack['stops'][:1]
        published = h.h.publish(self.pack, h.guest, 'bob')
        self.assertEqual(published[0], 201, published[2])
        h.h.approve(self.pack, h.owner)
        self.start()
        before = self.car_detail()['routePlan']
        self.assertEqual(before['phase'], 'pickup')
        self.assertEqual(before['segments'][0]['items'], [])
        arrived = self.arrive(single_join_completion=True)['routePlan']
        self.assertTrue(arrived['joinBarrier']['released'])
        self.assertEqual(arrived['phase'], 'shared')
        self.assertEqual(arrived['next'], before['next'])
        detail = h.native(self.base)
        self.assertEqual(detail['state'], 'active')
        self.assertEqual(detail['courses'][0]['drivingScores'], [])
        self.assertEqual(self.arrive()['status'], 'unchanged')
        final = dict(drivingScore=score(0, 0, final=True, measurable=False), functionalRevision=self.revision)
        path = self.path + '/courses/' + self.pack['id'] + '/complete'
        h.native(path, final, 'POST', 409)
        current = self.car_detail()
        complete = dict(final, routeRevision=current['routeRevision'], progressRevision=arrived['progressRevision'])
        for invalid in (dict(final, routeRevision=current['routeRevision']), dict(final, progressRevision=1),
                        dict(complete, routeRevision=True), dict(complete, progressRevision=2147483648),
                        dict(complete, item=before['next'])):
            h.native(path, invalid, 'POST', 400)
        h.native(path, dict(complete, functionalRevision=self.revision + 1), 'POST', 409)
        h.native(path, complete, 'POST')
        self.assertEqual(h.native(self.base)['state'], 'completed')
        self.assertEqual(self.car_detail()['routePlan']['phase'], 'done')
        h.native(path, final, 'POST')
        saved = h.native(self.base)['courses'][0]['drivingScores'][0]
        self.assertIsNone(saved['score'])
        self.assertFalse(saved['measurable'])
        self.assertTrue(saved['final'])

    def test_agreed_signal_detour_retains_current_course_score_and_is_arrived_once(self):
        self.start()
        self.arrive()
        self.arrive()
        body = dict(kind='rest', destination=dict(name='잠깐 쉴 곳', latitude=37.52, longitude=127),
            functionalRevision=self.revision)
        created = self.h.native('/v1/social/trips/' + self.h.trip + '/signals', body, 'POST', 201)
        route = self.car_detail()['routePlan']
        self.assertEqual(route['phase'], 'shared')
        self.assertEqual(route['next'], dict(type='signal', ref=created['id']))
        self.h.native(self.path + '/courses/' + self.pack['id'] + '/driving-score',
            dict(drivingScore=score(), functionalRevision=self.revision), 'PUT')
        arrived = self.arrive()['routePlan']
        self.assertEqual(arrived['phase'], 'shared')
        self.assertEqual(arrived['next']['courseId'], self.pack['id'])

    def test_current_internal_membership_consistency_is_preserved_for_arrival_and_score(self):
        self.start()
        self.arrive()
        self.arrive()
        car = self.car_detail()
        with psycopg.connect(self.h.h.dsn) as conn:
            conn.execute('UPDATE team_room_members SET left_at=clock_timestamp() WHERE account_id=%s '
                'AND room_id=(SELECT room_id FROM team_rooms WHERE trip_id=%s)',
                (self.h.guest['user']['id'], self.h.trip))
        body = dict(routeRevision=car['routeRevision'], progressRevision=car['routePlan']['progressRevision'],
            item=car['routePlan']['next'], functionalRevision=self.revision)
        expected = dict(detail='TRIP_MEMBERSHIP_INCONSISTENT')
        self.assertEqual(self.h.native(self.path + '/route-arrivals', body, 'POST', 409), expected)
        path = self.path + '/courses/' + self.pack['id']
        self.assertEqual(self.h.native(path + '/driving-score',
            dict(drivingScore=score(), functionalRevision=self.revision), 'PUT', 409), expected)
        self.assertEqual(self.h.native(path + '/complete', dict(functionalRevision=self.revision), 'POST', 409), expected)
