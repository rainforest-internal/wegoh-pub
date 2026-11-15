import copy
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import threading
import unittest

import psycopg

from team_rooms import TeamRooms
from test_trip_merge_api import PLACE, TripApiFixture


class TripRouteSegmentsTests(TripApiFixture):
    def checked(self, response, status=200):
        self.assertEqual(response[0], status, response[2])
        return response[2]

    def course(self, name='공유 코스', version=1, identifier=None, actor=None):
        pack = self.h.pack()
        if identifier is not None:
            pack['id'] = identifier
        pack.update(title=name, author='사용자A', version=version)
        first = dict(pack['stops'][0], id='join', name='합류 장소')
        last = dict(first, id='last', name='공유 코스 마지막 장소', latitude=37.51)
        pack['stops'] = [first, last]
        author = actor or self.a
        self.checked(self.h.publish(pack, author, author['user']['displayName']), 201)
        self.checked(self.h.approve(pack, self.a))
        return pack

    def prepared(self, *, pickups=0, drops=True, courses=1):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        self.h.join(trip, self.a, self.e)
        for actor in (self.a, self.b, self.e):
            self.sharing(trip, actor)
        cars, devices, actors, certificates = {}, {}, {}, {}
        for index, actor in enumerate((self.a, self.b), 1):
            device = self.h.vehicle(actor)
            certificates[device['deviceId']] = self.h._native_fingerprint
            car = self.checked(self.api(trip, '/cars', actor,
                dict(name=str(index) + '호차', seats=2), 'POST'), 201)['id']
            cars[index] = car
            devices[car] = device
            actors[car] = actor
        self.checked(self.api(trip, '/cars/' + cars[1] + '/ride', self.e, {}, 'PUT'))
        packs = [self.course('공유 코스 ' + str(index + 1)) for index in range(courses)]
        for pack in packs:
            self.checked(self.h.attach(trip, pack, self.a), 201)
        picked, dropped = {}, {}
        for car in cars.values():
            actor = actors[car]
            picked[car] = [self.place(trip, car, actor, 'pickup', index) for index in range(pickups if car == cars[1] else 0)]
            dropped[car] = [self.place(trip, car, actor, 'drop', 0)] if drops else []
        return dict(trip=trip, cars=cars, devices=devices, actors=actors,
            packs=packs, pickups=picked, drops=dropped, certificates=certificates)

    def place(self, trip, car, actor, kind, index):
        return self.checked(self.api(trip, '/cars/' + car + '/places', actor,
            dict(kind=kind, name=kind + ' 장소 ' + str(index + 1), lat=37.4 + index / 100, lng=127), 'POST'), 201)['id']

    def detail(self, setup, actor=None):
        return self.checked(self.api(setup['trip'], '', actor or self.a))

    def car(self, setup, car):
        return next(value for value in self.detail(setup, setup['actors'][car])['cars'] if value['id'] == car)

    def plan(self, setup, car):
        result = self.car(setup, car).get('routePlan')
        self.assertIsNotNone(result)
        return result

    def start(self, setup, version=2):
        body = dict(revision=self.detail(setup)['revision'])
        if version is not None:
            body['routeContractVersion'] = version
        return self.checked(self.api(setup['trip'], '/start', self.a, body, 'POST'))

    def body(self, setup, car):
        shown = self.car(setup, car)
        plan = shown['routePlan']
        self.assertIsNotNone(plan['next'])
        data = dict(routeRevision=shown['routeRevision'], progressRevision=plan['progressRevision'], item=copy.deepcopy(plan['next']))
        if car in setup.get('explicitJoinCars', ()) and data['item'] == self.join_item(setup, car):
            data['singleJoinCompletion'] = 'explicit-v1'
        return data

    def arrival(self, setup, car, body=None, actor=None):
        return self.api(setup['trip'], '/cars/' + car + '/route-arrivals', actor or setup['actors'][car],
            body if body is not None else self.body(setup, car), 'POST')

    def join_item(self, setup, car):
        join = self.plan(setup, car)['joinPoint']
        return dict(type='course', courseId=join['courseId'], ref=join['ref'])

    def before_join(self, setup, car):
        join = self.join_item(setup, car)
        for _ in range(51):
            if self.plan(setup, car)['next'] == join:
                return
            self.checked(self.arrival(setup, car))
        self.fail('Pickup route never reached the join point')

    def reach(self, setup, car, phase):
        for _ in range(51):
            if self.plan(setup, car)['phase'] == phase:
                return
            self.assertNotEqual(self.plan(setup, car)['phase'], 'waiting')
            self.checked(self.arrival(setup, car))
        self.fail('Route never reached ' + phase)

    def release(self, setup):
        for car in setup['cars'].values():
            self.before_join(setup, car)
        for car in setup['cars'].values():
            self.checked(self.arrival(setup, car))
        for car in setup['cars'].values():
            self.assertTrue(self.plan(setup, car)['joinBarrier']['released'])

    def database_race(self, setup, entries):
        from team_trip_route_segments import TeamTripRouteSegments
        service = TeamTripRouteSegments(self.h.module.TEAM_TRIPS)
        ready = threading.Barrier(len(entries))

        def report(entry):
            car, body = entry
            with psycopg.connect(self.dsn) as conn:
                ready.wait(timeout=5)
                TeamRooms.graph_lock(conn)
                return service.arrive(conn, setup['trip'], car, setup['actors'][car]['user']['id'], body)

        with ThreadPoolExecutor(max_workers=len(entries)) as pool:
            return list(pool.map(report, entries))

    def native_revision(self, setup, car, purposes):
        device, actor = setup['devices'][car], setup['actors'][car]
        path = '/v1/devices/' + device['deviceId'] + '/functional-permissions'
        old = self.checked(self.h.call(path, session=actor, who=actor['user']['displayName']))
        data = {key: value for key, value in old.items() if key not in ('deviceId', 'expiresAt')}
        data['approvedPurposes'] = self.h.web_purposes(old, purposes)
        return self.checked(self.h.call(path, data, 'PUT', session=actor, who=actor['user']['displayName']))['revision']

    def single_join(self, *, drops=True, courses=1, optin=True):
        setup = self.prepared(drops=drops, courses=courses)
        pack = copy.deepcopy(setup['packs'][0])
        pack['version'] += 1
        pack['stops'] = pack['stops'][:1]
        self.checked(self.h.publish(pack, self.a, self.a['user']['displayName']), 201)
        self.checked(self.h.approve(pack, self.a))
        setup['packs'][0] = pack
        setup['explicitJoinCars'] = set(setup['cars'].values()) if optin else set()
        return setup

    def completion(self, setup, car, data=None, actor=None):
        return self.api(setup['trip'], '/cars/' + car + '/courses/' + setup['packs'][0]['id'] + '/complete',
            actor or setup['actors'][car], data if data is not None else {}, 'POST')

    def completion_body(self, setup, car):
        current = self.car(setup, car)
        return dict(routeRevision=current['routeRevision'], progressRevision=current['routePlan']['progressRevision'])

    def test_single_join_starts_shared_until_explicit_driver_completion_and_retries_are_idempotent(self):
        setup = self.single_join(drops=False)
        self.start(setup)
        first, second = setup['cars'].values()
        first_join, second_join = self.body(setup, first), self.body(setup, second)
        self.checked(self.arrival(setup, first, first_join))
        self.assertEqual(self.plan(setup, first)['phase'], 'waiting')
        self.assertEqual(self.completion(setup, first)[0], 409)
        self.checked(self.arrival(setup, second, second_join))
        for car in (first, second):
            self.assertEqual(self.plan(setup, car)['phase'], 'shared')
            self.assertEqual(self.detail(setup)['courses'][0]['completedCarIds'], [])
        self.assertEqual(self.detail(setup)['state'], 'active')
        before = self.completion_body(setup, first)
        self.assertEqual(self.checked(self.arrival(setup, first, first_join))['status'], 'unchanged')
        old_shape = {key: value for key, value in first_join.items() if key != 'singleJoinCompletion'}
        self.assertEqual(self.checked(self.arrival(setup, first, old_shape))['status'], 'unchanged')
        self.assertEqual(self.completion_body(setup, first), before)
        self.assertEqual(self.completion(setup, first)[0], 409)
        self.assertEqual(self.completion(setup, first, before, self.e)[0], 403)
        self.assertEqual(self.completion(setup, first, dict(before, progressRevision=before['progressRevision'] - 1))[0], 409)
        for invalid in ({'routeRevision': before['routeRevision']}, {'progressRevision': before['progressRevision']},
                        dict(before, routeRevision=True), dict(before, progressRevision=-1), dict(before, progressRevision=2147483648)):
            self.assertEqual(self.completion(setup, first, invalid)[0], 400)
        signal = self.checked(self.api(setup['trip'], '/signals', self.a, dict(kind='rest', destination=PLACE), 'POST'), 201)['id']
        self.checked(self.vote(setup['trip'], signal, self.b))
        with_detour = self.completion_body(setup, first)
        self.assertEqual(self.plan(setup, first)['next']['type'], 'signal')
        self.assertEqual(self.completion(setup, first, before)[0], 409)
        self.assertEqual(self.completion(setup, first, with_detour)[0], 409)
        self.checked(self.arrival(setup, first))
        fresh = self.completion_body(setup, first)
        self.assertEqual(self.checked(self.completion(setup, first, fresh))['status'], 'completed')
        self.assertEqual(self.plan(setup, first)['phase'], 'done')
        self.assertEqual(self.checked(self.completion(setup, first, fresh))['status'], 'completed')
        self.assertEqual(self.detail(setup)['state'], 'active')
        self.checked(self.arrival(setup, second))
        second_complete = self.completion_body(setup, second)
        self.checked(self.completion(setup, second, second_complete))
        self.assertEqual(self.detail(setup)['state'], 'completed')
        self.checked(self.completion(setup, second, second_complete))
        self.assertEqual(self.checked(self.arrival(setup, second, second_join))['status'], 'unchanged')

    def test_single_join_explicit_completion_with_drop_is_cas_safe_under_duplicate_requests(self):
        setup = self.single_join()
        self.start(setup)
        self.release(setup)
        first, second = setup['cars'].values()
        before = self.completion_body(setup, first)
        ready = threading.Barrier(2)
        def send(_):
            ready.wait(timeout=5)
            return self.completion(setup, first, before)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(send, range(2)))
        self.assertEqual([reply[0] for reply in replies], [200, 200], replies)
        self.assertEqual(self.plan(setup, first)['phase'], 'drop')
        self.assertEqual(self.plan(setup, first)['progressRevision'], before['progressRevision'] + 1)
        self.checked(self.completion(setup, second, self.completion_body(setup, second)))
        for car in (first, second):
            self.assertEqual(self.plan(setup, car)['phase'], 'drop')
            self.checked(self.arrival(setup, car))
        self.assertEqual(self.detail(setup)['state'], 'completed')
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_car_course_completions WHERE trip_id=%s',
                (setup['trip'],)).fetchone()[0], 2)

    def test_legacy_completed_single_join_plan_is_not_reopened_and_accepts_old_completion_shape(self):
        setup = self.single_join(drops=False)
        self.start(setup)
        from team_trip_route_segments import TeamTripRouteSegments
        service = TeamTripRouteSegments(self.h.module.TEAM_TRIPS)
        with psycopg.connect(self.dsn) as conn:
            value = service.load(conn, setup['trip'])
            value['released'] = True
            for state in value['cars'].values():
                state['joined'] = True
                state['completed'] = copy.deepcopy(state['items'])
                state['revision'] = 1
            service.save(conn, setup['trip'], value)
            service.advance(conn, setup['trip'], value)
        self.assertEqual(self.detail(setup)['state'], 'completed')
        for car in setup['cars'].values():
            self.assertEqual(self.plan(setup, car)['phase'], 'done')
            self.checked(self.completion(setup, car))
            self.assertEqual(self.plan(setup, car)['phase'], 'done')

    def test_single_join_completion_advances_to_the_next_shared_course(self):
        setup = self.single_join(courses=2)
        self.start(setup)
        self.release(setup)
        first = setup['cars'][1]
        before = self.completion_body(setup, first)
        self.checked(self.completion(setup, first, before))
        after = self.plan(setup, first)
        self.assertEqual(after['phase'], 'shared')
        self.assertEqual(after['next']['courseId'], setup['packs'][1]['id'])
        self.checked(self.completion(setup, first, before))
        self.assertEqual(self.plan(setup, first), after)

    def test_single_join_optin_is_optional_strict_and_cannot_upgrade_a_legacy_join(self):
        setup = self.single_join(optin=False)
        self.start(setup)
        first, second = setup['cars'].values()
        first_join = self.body(setup, first)
        for invalid in (True, False, 1, None, 'explicit-v2', {}):
            self.assertEqual(self.arrival(setup, first, dict(first_join, singleJoinCompletion=invalid))[0], 400)
            self.assertEqual(self.plan(setup, first)['phase'], 'pickup')
        self.checked(self.arrival(setup, first, first_join))
        self.assertEqual(self.plan(setup, first)['phase'], 'waiting')
        self.assertEqual(self.checked(self.arrival(setup, first, dict(first_join, singleJoinCompletion='explicit-v1')))['status'], 'unchanged')
        self.checked(self.arrival(setup, second))
        for car in (first, second):
            self.assertEqual(self.plan(setup, car)['phase'], 'drop')
        self.assertEqual(self.checked(self.arrival(setup, first, dict(first_join, singleJoinCompletion='explicit-v1')))['status'], 'unchanged')
        self.assertEqual(self.plan(setup, first)['phase'], 'drop')

    def test_mixed_single_join_keeps_legacy_completion_and_existing_group_signal_safety(self):
        setup = self.single_join()
        first, second = setup['cars'].values()
        setup['explicitJoinCars'] = {first}
        self.start(setup)
        self.release(setup)
        self.assertEqual(self.plan(setup, first)['phase'], 'shared')
        self.assertEqual(self.plan(setup, second)['phase'], 'drop')
        self.checked(self.api(setup['trip'], '/signals', self.a, dict(kind='rest', destination=PLACE), 'POST'), 201)
        self.checked(self.completion(setup, first, self.completion_body(setup, first)))
        self.assertEqual(self.plan(setup, first)['phase'], 'drop')

    def test_v2_normalizes_three_segments_and_preserves_local_pickup_order(self):
        setup = self.prepared(pickups=2)
        car = setup['cars'][1]
        shared = [dict(type='course', courseId=pack['id'], ref=stop['id']) for pack in setup['packs'] for stop in pack['stops']]
        pickups = [dict(type='pickup', ref=identifier) for identifier in reversed(setup['pickups'][car])]
        drop = dict(type='drop', ref=setup['drops'][car][0])
        mixed = [drop, shared[0], pickups[0], shared[1], pickups[1]]
        self.checked(self.api(setup['trip'], '/cars/' + car + '/route-order', self.a, dict(items=mixed), 'PUT'))
        self.start(setup)
        plan = self.plan(setup, car)
        self.assertEqual(plan['contractVersion'], 2)
        self.assertEqual(plan['phase'], 'pickup')
        self.assertEqual([segment['segment'] for segment in plan['segments']], ['pickup', 'shared', 'drop'])
        self.assertEqual([segment['items'] for segment in plan['segments']], [pickups, shared, [drop]])
        self.assertEqual(plan['next'], pickups[0])
        self.assertIsNone(plan['joinEtaSeconds'])
        self.assertFalse(plan['joinBarrier']['released'])
        self.assertEqual(plan['joinBarrier']['totalCarCount'], 2)
        self.assertEqual(self.car(setup, car)['routeNext'], pickups[0])

    def guide(self, setup, car, next_item, revision=None):
        shown = self.car(setup, car)
        return self.api(setup['trip'], '/cars/' + car + '/route-progress', setup['actors'][car],
            dict(next=next_item, routeRevision=shown['routeRevision'] if revision is None else revision), 'PUT')

    def test_driver_guidance_is_shared_without_confirming_arrivals(self):
        setup = self.prepared(pickups=2)
        self.start(setup)
        car, other = setup['cars'][1], setup['cars'][2]
        plan = self.plan(setup, car)
        pickups, shared, _ = (segment['items'] for segment in plan['segments'])
        self.assertEqual(self.car(setup, car)['routeNext'], pickups[0])
        self.assertEqual(self.checked(self.guide(setup, car, shared[-1])), dict(status='updated'))
        self.assertEqual(self.plan(setup, car), plan)
        rider = next(value for value in self.detail(setup, self.e)['cars'] if value['id'] == car)
        self.assertEqual(rider['routeNext'], shared[-1])
        self.assertEqual(rider['routePlan']['next'], pickups[0])
        self.assertNotIn('routeNext', next(value for value in self.detail(setup, self.b)['cars'] if value['id'] == car))
        refused = self.guide(setup, car, None)
        self.assertEqual((refused[0], refused[2]), (409, dict(detail='TRIP_ROUTE_PROGRESS_CHANGED')))
        self.assertEqual(self.guide(setup, car, shared[0], revision=self.car(setup, car)['routeRevision'] + 1)[0], 409)
        self.assertEqual(self.api(setup['trip'], '/cars/' + car + '/route-progress', self.e,
            dict(next=shared[0], routeRevision=self.car(setup, car)['routeRevision']), 'PUT')[0], 403)
        self.checked(self.arrival(setup, car))
        self.assertEqual(self.car(setup, car)['routeNext'], shared[-1])
        self.assertEqual(self.plan(setup, car)['next'], pickups[1])
        refused = self.guide(setup, car, pickups[0])
        self.assertEqual((refused[0], refused[2]), (409, dict(detail='TRIP_ROUTE_PROGRESS_CHANGED')))
        self.checked(self.guide(setup, car, pickups[1]))
        self.checked(self.arrival(setup, car))
        self.assertEqual(self.car(setup, car)['routeNext'], shared[0])
        self.checked(self.guide(setup, other, self.plan(setup, other)['segments'][1]['items'][-1]))
        self.checked(self.arrival(setup, car))
        self.checked(self.arrival(setup, other))
        self.assertTrue(self.plan(setup, car)['joinBarrier']['released'])
        self.assertEqual(self.car(setup, other)['routeNext'], shared[-1])
        self.assertEqual(self.plan(setup, other)['next'], shared[-1])

    def test_agreed_signal_joins_before_next_arrival_when_guidance_runs_ahead(self):
        setup = self.prepared(pickups=1)
        self.start(setup)
        car = setup['cars'][1]
        pickups, shared, drops = (segment['items'] for segment in self.plan(setup, car)['segments'])
        self.checked(self.guide(setup, car, drops[0]))
        signal = self.checked(self.api(setup['trip'], '/signals', self.a, dict(kind='rest', destination=PLACE), 'POST'), 201)['id']
        self.checked(self.vote(setup['trip'], signal, self.b))
        added = dict(type='signal', ref=signal)
        plan = self.plan(setup, car)
        self.assertEqual(plan['next'], added)
        self.assertEqual(plan['segments'][0]['items'], [added] + pickups)
        shown = self.car(setup, car)
        self.assertEqual(shown['routeNext'], added)
        self.assertEqual(shown['routeOrder'][:2], [added, pickups[0]])

    def test_start_version_and_post_publication_restriction_fail_without_mutation(self):
        setup = self.prepared()
        before = self.detail(setup)
        for version in (True, False, 1, 3, '2', None, 2.0):
            response = self.api(setup['trip'], '/start', self.a,
                dict(revision=before['revision'], routeContractVersion=version), 'POST')
            self.assertEqual(response[0], 400, response[2])
            self.assertEqual(self.detail(setup)['state'], 'planned')
            self.assertEqual(self.detail(setup)['revision'], before['revision'])
        pack = setup['packs'][0]
        with psycopg.connect(self.dsn) as conn:
            from test_course_moderation_fixture import restrict_course
            for (checksum,) in conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=%s', (pack['id'],)).fetchall():
                restrict_course(conn, checksum, state='quarantined')
        refused = self.api(setup['trip'], '/start', self.a,
            dict(revision=before['revision'], routeContractVersion=2), 'POST')
        self.assertEqual(refused[0], 409, refused[2])
        self.assertEqual(self.detail(setup)['state'], 'planned')
        self.checked(self.h.approve(pack, self.a))
        self.start(setup)

    def test_explicit_v2_route_order_rejects_cross_segment_moves_and_keeps_local_order(self):
        setup = self.prepared(pickups=2, courses=2)
        car = setup['cars'][1]
        path = '/cars/' + car + '/route-order'
        shared = [dict(type='course', courseId=pack['id'], ref=stop['id'])
            for pack in setup['packs'] for stop in pack['stops']]
        pickups = [dict(type='pickup', ref=identifier) for identifier in setup['pickups'][car]]
        drop = dict(type='drop', ref=setup['drops'][car][0])
        before = self.car(setup, car)
        self.assertEqual(before['routeRevision'], 0)
        invalid = [
            pickups + list(reversed(shared)) + [drop],
            pickups[:1] + shared + pickups[1:] + [drop],
            [drop] + pickups + shared,
            pickups + shared[:1] + [drop] + shared[1:],
            pickups + [dict(shared[0], dropRef=drop['ref'])] + shared[1:],
        ]
        for items in invalid:
            response = self.api(setup['trip'], path, self.a,
                dict(routeContractVersion=2, routeRevision=0, items=items), 'PUT')
            self.assertEqual((response[0], response[2]), (400, dict(detail='TRIP_ROUTE_SEGMENT_ORDER_INVALID')))
            current = self.car(setup, car)
            self.assertEqual((current['routeRevision'], current['routeOrder']),
                (before['routeRevision'], before['routeOrder']))
        local = list(reversed(pickups))
        valid = local + shared + [drop]
        self.checked(self.api(setup['trip'], path, self.a,
            dict(routeContractVersion=2, routeRevision=0, items=valid), 'PUT'))
        self.assertEqual(self.car(setup, car)['routeOrder'], valid)
        self.start(setup)
        route = self.plan(setup, car)
        self.assertEqual([part['items'] for part in route['segments']], [local, shared, [drop]])
        self.assertEqual(route['next'], local[0])

    def test_active_v2_locks_new_cars_and_empty_roster_does_not_auto_finish(self):
        setup = self.prepared()
        self.h.vehicle(self.e)
        self.start(setup)
        refused = self.api(setup['trip'], '/cars', self.e, dict(name='늦게 추가한 차', seats=2), 'POST')
        self.assertEqual((refused[0], refused[2]), (409, dict(detail='TRIP_ROUTE_ROSTER_LOCKED')))
        current = self.detail(setup, self.e)
        self.assertEqual(len(current['cars']), 2)
        self.assertTrue(next(car for car in current['cars'] if car['id'] == setup['cars'][1])['iRide'])
        for car in setup['cars'].values():
            self.checked(self.api(setup['trip'], '/cars/' + car, setup['actors'][car], method='DELETE'))
        empty = self.detail(setup)
        self.assertEqual(empty['cars'], [])
        self.assertEqual(empty['state'], 'active')
        with psycopg.connect(self.dsn) as conn:
            self.assertIsNone(conn.execute('SELECT ended_at FROM team_trips WHERE trip_id=%s',
                (setup['trip'],)).fetchone()[0])
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results WHERE trip_id=%s',
                (setup['trip'],)).fetchone()[0], 0)

    def test_driver_expected_next_cas_and_duplicate_http_arrivals(self):
        setup = self.prepared(pickups=2)
        self.start(setup)
        car = setup['cars'][1]
        initial = self.body(setup, car)
        self.assertEqual(self.arrival(setup, car, initial, self.e)[0], 403)
        self.assertEqual(self.arrival(setup, setup['cars'][2], self.body(setup, setup['cars'][2]), self.a)[0], 403)
        for bad in (dict(initial, routeRevision=True), dict(initial, progressRevision=2147483648), dict(initial, extra=True)):
            self.assertEqual(self.arrival(setup, car, bad)[0], 400)
        ready = threading.Barrier(2)

        def send(_):
            ready.wait(timeout=5)
            return self.arrival(setup, car, initial)

        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(send, range(2)))
        self.assertEqual([response[0] for response in replies], [200, 200], replies)
        self.assertEqual({response[2]['status'] for response in replies}, {'updated', 'unchanged'})
        self.assertEqual(self.plan(setup, car)['progressRevision'], initial['progressRevision'] + 1)
        stale = dict(self.body(setup, car), progressRevision=initial['progressRevision'])
        self.assertEqual(self.arrival(setup, car, stale)[2], dict(detail='TRIP_ROUTE_PROGRESS_CHANGED'))

    def test_two_database_connections_release_join_barrier_once(self):
        setup = self.prepared()
        self.start(setup)
        entries = [(car, self.body(setup, car)) for car in setup['cars'].values()]
        self.assertTrue(all(body['item'] == self.join_item(setup, car) for car, body in entries))
        results = self.database_race(setup, entries)
        self.assertEqual([result['status'] for result in results], ['updated', 'updated'])
        expected = set(setup['cars'].values())
        for car in expected:
            plan = self.plan(setup, car)
            self.assertEqual(plan['phase'], 'shared')
            self.assertEqual(set(plan['joinBarrier']['arrivedCarIds']), expected)
            self.assertTrue(plan['joinBarrier']['released'])
            self.assertEqual(plan['next']['ref'], 'last')

    def test_waiting_and_drop_allow_signals_and_keep_pending_requests(self):
        from team_trip_route_segments import TeamTripRouteSegments
        setup = self.prepared()
        self.start(setup)
        first, second = setup['cars'].values()
        self.checked(self.arrival(setup, first))
        self.assertEqual(self.plan(setup, first)['phase'], 'waiting')
        with psycopg.connect(self.dsn) as conn:
            TeamTripRouteSegments(self.h.module.TEAM_TRIPS).check_shared(conn, setup['trip'], self.a['user']['id'])
        self.checked(self.arrival(setup, second))
        signal = self.checked(self.api(setup['trip'], '/signals', self.a, dict(kind='rest', destination=PLACE), 'POST'), 201)['id']
        self.reach(setup, first, 'drop')
        with psycopg.connect(self.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_trip_signal_contexts WHERE trip_id=%s AND signal_id=%s', (setup['trip'], signal)).fetchone()[0]
            saved = self.h.module.TEAM_AUTH.trip_signal_contexts.restore(setup['trip'], signal, raw)
            self.assertEqual(saved['resolution'], 'pending')
            for actor in (self.a, self.b):
                TeamTripRouteSegments(self.h.module.TEAM_TRIPS).check_shared(conn, setup['trip'], actor['user']['id'])

    def test_frozen_course_version_and_order_survive_new_publication_and_result(self):
        setup = self.prepared(courses=2)
        self.start(setup)
        before = self.detail(setup)
        frozen = [(pack['packId'], pack['version']) for pack in before['courses']]
        self.course('새 승인 버전', version=2, identifier=setup['packs'][0]['id'])
        self.assertEqual([(pack['packId'], pack['version']) for pack in self.detail(setup)['courses']], frozen)
        third = self.course('새 공유 코스')
        self.assertEqual(self.h.attach(setup['trip'], third, self.a)[0], 409)
        self.assertEqual(self.h.detach(setup['trip'], setup['packs'][0], self.a)[0], 409)
        priority = dict(packIds=[pack['id'] for pack in reversed(setup['packs'])], revision=before['revision'])
        self.assertEqual(self.api(setup['trip'], '/courses/priority', self.a, priority, 'PUT')[0], 409)
        self.release(setup)
        for car in setup['cars'].values():
            self.reach(setup, car, 'drop')
        for car in setup['cars'].values():
            self.checked(self.arrival(setup, car))
        self.assertEqual(self.detail(setup)['state'], 'completed')
        archive = self.checked(self.api(setup['trip'], '/results', self.a))
        self.assertEqual([(pack['id'], pack['version']) for pack in archive['summary']['courses']], frozen)

    def test_two_database_drop_arrivals_close_once_and_revoke_pending_remote(self):
        setup = self.prepared()
        self.h.befriend(self.a, self.e, 'eve')
        first = setup['cars'][1]
        self.checked(self.api(setup['trip'], '/cars/' + first + '/remote-policy', self.a,
            dict(enabled=True, actions=['hvac.temperature'], deviceId=setup['devices'][first]['deviceId']), 'PUT'))
        self.start(setup)
        self.release(setup)
        for car in setup['cars'].values():
            self.reach(setup, car, 'drop')
        remote = self.checked(self.api(setup['trip'], '/vehicle-remotes', self.e))['remotes'][0]
        command = dict(eventId='segmented-close-command-001', grantRevision=remote['grantRevision'],
            capabilityId='hvac.temperature', capabilityRevision=1, arguments=dict(seat='ROW_1_RIGHT', value=22))
        queued = self.checked(self.api(setup['trip'], '/vehicle-remotes/' + remote['deviceId'] + '/commands', self.e, command, 'POST'), 201)
        entries = [(car, self.body(setup, car)) for car in setup['cars'].values()]
        self.assertEqual([result['status'] for result in self.database_race(setup, entries)], ['updated', 'updated'])
        closed = self.detail(setup)
        self.assertEqual(closed['state'], 'completed')
        for car, body in entries:
            retry = self.checked(self.arrival(setup, car, body))
            self.assertEqual(retry['status'], 'unchanged')
            self.assertEqual(retry['routePlan']['phase'], 'done')
        self.assertEqual(self.detail(setup)['revision'], closed['revision'])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results WHERE trip_id=%s', (setup['trip'],)).fetchone()[0], 1)
            self.assertEqual(self.h.module.TEAM_DEVICE_COMMANDS.load_request(conn, queued['id'])['stage'], 'cancelled')
        self.assertEqual(self.api(setup['trip'], '/vehicle-remotes', self.e)[0], 409)

    def test_empty_pickup_and_drop_skip_without_unmeasured_eta(self):
        setup = self.prepared(drops=False)
        self.start(setup)
        for car in setup['cars'].values():
            plan = self.plan(setup, car)
            self.assertEqual(plan['segments'][0]['items'], [])
            self.assertEqual(plan['segments'][2]['items'], [])
            self.assertEqual(plan['next'], self.join_item(setup, car))
            self.assertIsNone(plan['joinEtaSeconds'])
        self.release(setup)
        for car in setup['cars'].values():
            self.checked(self.arrival(setup, car))
        self.assertEqual(self.detail(setup)['state'], 'completed')

    def test_removed_waiting_car_releases_remaining_roster(self):
        setup = self.prepared()
        self.start(setup)
        first, second = setup['cars'].values()
        self.checked(self.arrival(setup, first))
        self.checked(self.api(setup['trip'], '/cars/' + second, self.b, {}, 'DELETE'))
        plan = self.plan(setup, first)
        self.assertEqual(plan['phase'], 'shared')
        self.assertEqual(plan['joinBarrier'], dict(arrivedCarIds=[first], totalCarCount=1, released=True))
        self.reach(setup, first, 'drop')
        self.checked(self.arrival(setup, first))
        self.assertEqual(self.detail(setup)['state'], 'completed')

    def test_driver_member_leave_reconciles_context_before_remaining_done_auto_closes(self):
        setup = self.prepared(drops=False)
        self.start(setup)
        self.release(setup)
        owner_car, leaving_car = setup['cars'].values()
        self.checked(self.arrival(setup, owner_car))
        self.assertEqual(self.plan(setup, owner_car)['phase'], 'done')
        self.assertEqual(self.detail(setup)['state'], 'active')
        removed = self.api(setup['trip'], '/members/' + self.b['user']['id'], self.b, method='DELETE')
        self.checked(removed)
        detail = self.detail(setup)
        self.assertEqual(detail['state'], 'completed')
        self.assertEqual([car['id'] for car in detail['cars']], [owner_car])
        self.assertNotIn(self.b['user']['id'], [member['id'] for member in detail['members']])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results WHERE trip_id=%s', (setup['trip'],)).fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_cars WHERE trip_id=%s AND car_id=%s',
                (setup['trip'], leaving_car)).fetchone()[0], 0)

    def test_departing_course_author_preserves_frozen_link_scores_and_remaining_completion(self):
        setup = self.prepared()
        old = setup['packs'][0]
        self.checked(self.api(setup['trip'], '/courses/' + old['id'], self.a, method='DELETE'))
        pack = self.course('떠나는 일행의 공유 코스', actor=self.b)
        self.checked(self.h.attach(setup['trip'], pack, self.b), 201)
        setup['packs'] = [pack]
        self.start(setup)
        self.release(setup)
        car = setup['cars'][1]
        current = self.native_revision(setup, car, ['rooms:read', 'rooms:interact', 'driving-score:report'])
        from test_trip_driving_scores import score
        path = '/v1/native/trips/' + setup['trip'] + '/cars/' + car + '/courses/' + pack['id'] + '/driving-score'
        device = setup['devices'][car]
        self.checked(self.h.native(path, dict(drivingScore=score(), functionalRevision=current), 'PUT',
            device['accessToken'], certificate=setup['certificates'][device['deviceId']]))
        with psycopg.connect(self.dsn) as conn:
            before = conn.execute('SELECT protected FROM team_trip_car_driving_scores WHERE trip_id=%s AND car_id=%s',
                (setup['trip'], car)).fetchone()[0]
        self.checked(self.api(setup['trip'], '/members/' + self.b['user']['id'], self.b, method='DELETE'))
        shown = self.detail(setup)
        self.assertEqual([course['packId'] for course in shown['courses']], [pack['id']])
        self.assertEqual(shown['courses'][0]['drivingScores'], [dict(carId=car, **score())])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT added_by FROM team_trip_courses WHERE trip_id=%s AND pack_id=%s',
                (setup['trip'], pack['id'])).fetchone()[0], self.b['user']['id'])
            self.assertEqual(conn.execute('SELECT protected FROM team_trip_car_driving_scores WHERE trip_id=%s AND car_id=%s',
                (setup['trip'], car)).fetchone()[0], before)
        self.checked(self.arrival(setup, car))
        self.assertEqual(self.plan(setup, car)['phase'], 'drop')
        self.checked(self.arrival(setup, car))
        self.assertEqual(self.detail(setup)['state'], 'completed')

    def test_public_route_status_keeps_other_car_points_private_and_hides_blocked_cars(self):
        setup = self.prepared(pickups=1)
        self.start(setup)
        first, second = setup['cars'].values()
        rider = {value['id']: value for value in self.detail(setup, self.e)['cars']}
        self.assertIsNotNone(rider[first]['routePlan'])
        self.assertIsNone(rider[second]['routePlan'])
        other_driver = {value['id']: value for value in self.detail(setup, self.b)['cars']}
        self.assertIsNone(other_driver[first]['routePlan'])
        self.assertIsNotNone(other_driver[second]['routePlan'])
        self.checked(self.arrival(setup, first))
        self.checked(self.arrival(setup, first))
        owner = {value['id']: value for value in self.detail(setup)['cars']}
        self.assertEqual(owner[first]['routeStatus'], dict(phase='waiting', joinEtaSeconds=None, progress=None))
        self.assertEqual(owner[second]['routeStatus'], dict(phase='pickup', joinEtaSeconds=None, progress=None))
        self.assertIsNotNone(owner[first]['routePlan'])
        self.assertIsNone(owner[second]['routePlan'])
        self.assertEqual(owner[second]['places'], [])
        self.assertIsNone(owner[second]['routeOrder'])
        self.assertNotIn('routeNext', owner[second])
        self.assertNotIn('routeRevision', owner[second])
        self.checked(self.api(setup['trip'], '/ride', self.e, method='DELETE'))
        former = {value['id']: value for value in self.detail(setup, self.e)['cars']}
        self.assertTrue(all(value['routePlan'] is None for value in former.values()))
        self.assertTrue(all(value['places'] == [] for value in former.values()))
        self.checked(self.h.social('/blocks', self.e, dict(targetId=self.b['user']['id']), 'POST'), 201)
        shown = self.detail(setup, self.e)['cars']
        self.assertEqual([value['id'] for value in shown], [first])

    def share_fix(self, setup, actor, lat, lng=127.0):
        from datetime import datetime, timezone
        share = self.checked(self.api(setup['trip'], '/location-sharing', actor, dict(locationConsent=True), 'PATCH'))['locationShareId']
        self.checked(self.api(setup['trip'], '/locations/me', actor, dict(shareId=share, latitude=lat, longitude=lng,
            accuracyMeters=5, capturedAt=datetime.now(timezone.utc).isoformat()), 'POST'))

    def test_live_progress_follows_shared_locations_between_places_and_keeps_private_places_hidden(self):
        setup = self.prepared(pickups=1)
        self.start(setup)
        first, second = setup['cars'].values()
        self.assertIsNone(self.plan(setup, first)['progress'])
        self.assertIsNone(self.car(setup, first)['routeStatus']['progress'])
        # The rider's phone stands halfway between the pickup (37.4) and the join point (37.5).
        self.share_fix(setup, self.e, 37.45)
        plan = self.plan(setup, first)
        self.assertEqual(plan['next']['type'], 'pickup')
        self.assertIsNone(plan['progress']['legFraction'])
        self.assertAlmostEqual(plan['progress']['remainingMeters'], 5560, delta=10)
        other = {value['id']: value for value in self.detail(setup, self.b)['cars']}
        self.assertIsNone(other[first]['routePlan'])
        self.assertEqual(other[first]['routeStatus']['progress'], dict(target=self.join_item(setup, first),
            remainingMeters=5600, legFraction=None))
        self.assertIsNone(other[second]['routeStatus']['progress'])
        self.checked(self.arrival(setup, first))
        plan = self.plan(setup, first)
        self.assertEqual(plan['next'], self.join_item(setup, first))
        self.assertEqual(plan['progress']['legFraction'], 0.5)
        self.assertAlmostEqual(plan['progress']['remainingMeters'], 5560, delta=10)
        rider = next(value for value in self.detail(setup, self.e)['cars'] if value['id'] == first)
        self.assertEqual(rider['routePlan']['progress'], plan['progress'])
        self.release(setup)
        self.share_fix(setup, self.e, 37.505)
        plan = self.plan(setup, first)
        self.assertEqual(plan['phase'], 'shared')
        self.assertEqual(plan['progress']['legFraction'], 0.5)
        self.assertAlmostEqual(plan['progress']['remainingMeters'], 556, delta=5)
        status = next(value for value in self.detail(setup, self.b)['cars'] if value['id'] == first)['routeStatus']
        self.assertEqual(status['progress'], dict(target=plan['next'], remainingMeters=600, legFraction=0.5))
        self.checked(self.api(setup['trip'], '/location-sharing', self.e, dict(locationConsent=False), 'PATCH'))
        self.assertIsNone(self.plan(setup, first)['progress'])
        self.assertIsNone(next(value for value in self.detail(setup, self.b)['cars'] if value['id'] == first)['routeStatus']['progress'])

    def test_native_arrival_keeps_functional_cas_and_driver_boundary(self):
        setup = self.prepared()
        self.start(setup)
        car = setup['cars'][1]
        path = '/v1/native/trips/' + setup['trip'] + '/cars/' + car + '/route-arrivals'
        current = self.native_revision(setup, car, ['rooms:read', 'rooms:interact'])
        body = dict(self.body(setup, car), functionalRevision=current)
        token = setup['devices'][car]['accessToken']
        certificate = setup['certificates'][setup['devices'][car]['deviceId']]
        self.assertEqual(self.h.native(path, dict(body, functionalRevision=current + 1), 'POST', token, certificate=certificate)[0], 409)
        other = setup['cars'][2]
        other_revision = self.native_revision(setup, other, ['rooms:read', 'rooms:interact'])
        other_certificate = setup['certificates'][setup['devices'][other]['deviceId']]
        self.assertEqual(self.h.native(path, dict(body, functionalRevision=other_revision), 'POST', setup['devices'][other]['accessToken'], certificate=other_certificate)[0], 403)
        self.assertEqual(self.h.native(path, body, 'POST', token, certificate='f' * 64)[0], 403)
        self.checked(self.h.native(path, body, 'POST', token, certificate=certificate))

    def test_native_route_presentation_preserves_legacy_keys_and_negotiates_v2(self):
        setup = self.prepared()
        self.start(setup)
        car = setup['cars'][1]
        self.native_revision(setup, car, ['rooms:read'])
        token = setup['devices'][car]['accessToken']
        path = '/v1/native/trips/' + setup['trip'] + '?section=route'

        def read(values):
            connection = http.client.HTTPConnection('127.0.0.1', self.h.port, timeout=5)
            connection.putrequest('GET', path, skip_host=True)
            for name, value in [('Host', 'api.wegoh.invalid'), ('Authorization', 'Bearer ' + token),
                    ('cf-cert-sha256', setup['certificates'][setup['devices'][car]['deviceId']]),
                    ('cf-cert-presented', 'true'), ('cf-cert-verified', 'true'), ('cf-cert-revoked', 'false')]:
                connection.putheader(name, value)
            for value in values:
                connection.putheader('X-WegoH-Trip-Route-Contract', value)
            connection.endheaders()
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), json.loads(response.read())
            connection.close()
            return result

        legacy = self.checked(read([]))
        self.assertEqual(set(legacy), {'id', 'revision', 'cars', 'courses'})
        for value in legacy['cars']:
            keys = {'id', 'isMine', 'iRide', 'places', 'routeOrder'}
            self.assertEqual(set(value), keys | ({'routeRevision', 'routeNext'} if value['isMine'] or value['iRide'] else set()))
        modern = self.checked(read(['2']))
        self.assertEqual(modern['routeContractVersion'], 2)
        self.assertEqual(set(modern), set(legacy) | {'routeContractVersion'})
        self.assertEqual(len({value['ordinal']for value in modern['cars']}),len(modern['cars']))
        for old, new in zip(legacy['cars'], modern['cars']):
            self.assertIs(type(new['ordinal']),int);self.assertGreater(new['ordinal'],0)
            self.assertEqual({key: value for key, value in new.items() if key not in ('routePlan', 'routeStatus','ordinal')}, old)
            self.assertEqual(new['routeStatus'], dict(phase='pickup', joinEtaSeconds=None, progress=None))
            if not old['isMine']:
                self.assertIsNone(new['routePlan'])
                self.assertEqual(new['places'], [])
                self.assertIsNone(new['routeOrder'])
        self.assertEqual(next(value for value in modern['cars'] if value['id'] == car)['routePlan']['contractVersion'], 2)
        for values in (['1'], ['02'], ['2, 2'], ['2', '2'], ['2', '1']):
            result = read(values)
            self.assertEqual((result[0], result[2]), (400, dict(detail='TRIP_ROUTE_PRESENTATION_INVALID')))

    def test_v1_omission_retains_legacy_progress_and_active_course_add(self):
        setup = self.prepared(pickups=1)
        self.start(setup, version=None)
        car = setup['cars'][1]
        shown = self.car(setup, car)
        self.assertIsNone(shown.get('routePlan'))
        pack = setup['packs'][0]
        next_item = dict(type='course', courseId=pack['id'], ref=pack['stops'][-1]['id'])
        self.checked(self.api(setup['trip'], '/cars/' + car + '/route-progress', self.a,
            dict(next=next_item, routeRevision=shown['routeRevision']), 'PUT'))
        self.assertEqual(self.car(setup, car)['routeNext'], next_item)
        extra = self.course('기존 여행에 더한 코스')
        self.checked(self.h.attach(setup['trip'], extra, self.a), 201)


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(TripRouteSegmentsTests)
