import unittest
from unittest.mock import patch

import psycopg

from team_trip_context import resolve_trip_context
from team_trip_plan import TeamTripPlan
from test_trip_plan_api import TripPlanTests


class TripSignalRouteTests(TripPlanTests):
    destination = dict(name='함께 정차할 장소', latitude=37.51, longitude=127.01)

    def apply(self, trip, signal, cars):
        with psycopg.connect(self.dsn) as conn:
            context = resolve_trip_context(self.h.module.TEAM_AUTH, conn, trip, self.a['user']['id'])
            TeamTripPlan(self.h.module.TEAM_TRIPS).apply_agreed_signal(conn, context, signal, self.destination, cars)

    def car_detail(self, trip, car, session=None):
        return next(value for value in self.detail(trip, session or self.a)['cars'] if value['id'] == car)

    def new_signal(self, trip, session=None):
        result = self.api(trip, '/signals', session or self.a, dict(kind='rest', destination=self.destination), 'POST')
        self.assertEqual(result[0], 201, result[2])
        return result[2]['id']

    def test_agreed_signal_preserves_custom_order_and_is_inserted_once_before_reported_next(self):
        trip, car, driver, rider = self.setup_car()
        pack = self.h.published_course(driver)
        self.h.approve(pack, driver); self.h.attach(trip, pack, driver)
        pickup = self.place(trip, car, rider)
        order = [dict(type='course', courseId=pack['id'], ref=stop['id']) for stop in reversed(pack['stops'])]
        order.insert(1, dict(type='pickup', ref=pickup))
        path = '/cars/'+car
        self.assertEqual(self.api(trip, path+'/route-order', driver, dict(items=order), 'PUT')[0], 200)
        self.transition(trip, 'start')
        before = self.car_detail(trip, car)
        next_item = order[-1]
        result = self.api(trip, path+'/route-progress', driver,
            dict(next=next_item, routeRevision=before['routeRevision']), 'PUT')
        self.assertEqual(result[0], 200, result[2])
        revision = self.detail(trip, driver)['revision']
        signal = self.new_signal(trip)
        self.apply(trip, signal, [car]); self.apply(trip, signal, [car])
        after = self.car_detail(trip, car)
        added = dict(type='signal', ref=signal)
        self.assertEqual(after['routeOrder'], order[:-1]+[added, next_item])
        self.assertEqual(after['routeNext'], added)
        self.assertEqual(after['routeRevision'], before['routeRevision']+1)
        self.assertEqual(self.detail(trip, driver)['revision'], revision)
        self.assertIn(dict(id=signal, kind='signal', name=self.destination['name'], lat=37.51, lng=127.01), after['places'])
        redacted = self.car_detail(trip, car, self.e)['places'][-1]
        self.assertEqual(redacted, dict(kind='signal', name=self.destination['name'], selectedBy=0))
        self.assertNotIn('routeNext', self.car_detail(trip, car, self.e))
        with psycopg.connect(self.dsn) as conn:
            raw = conn.execute('SELECT protected,route_order FROM team_trip_cars WHERE trip_id=%s AND car_id=%s',
                (trip, car)).fetchone()
            self.assertNotIn(self.destination['name'].encode(), bytes(raw[0]))
            self.assertNotIn(signal.encode(), bytes(raw[1]))

    def test_first_signal_preserves_default_pickup_course_and_drop_order(self):
        trip, car, driver, rider = self.setup_car()
        pack = self.h.published_course(driver)
        self.h.approve(pack, driver); self.h.attach(trip, pack, driver)
        pickup = self.place(trip, car, rider)
        stop = pack['stops'][0]
        drop = self.place(trip, car, rider, 'drop', stop['latitude'], stop['longitude'])
        self.transition(trip, 'start')
        self.assertIsNone(self.car_detail(trip, car)['routeOrder'])
        signal = self.new_signal(trip)
        self.apply(trip, signal, [car])
        expected = [dict(type='signal', ref=signal), dict(type='pickup', ref=pickup)]
        expected.extend(dict(type='course', courseId=pack['id'], ref=entry['id'],
            **({'dropRef': drop} if index == 0 else {})) for index, entry in enumerate(pack['stops']))
        self.assertEqual(self.car_detail(trip, car)['routeOrder'], expected)

    def test_requester_cancellation_keeps_both_cars_existing_routes(self):
        trip, first, driver, rider = self.setup_car()
        self.h.vehicle(self.e)
        second = self.h.new_car(trip, self.e).split('/')[-1]
        cars = ((first, driver), (second, self.e))
        for car, session in cars:
            place = self.place(trip, car, session)
            self.assertEqual(self.api(trip, '/cars/'+car+'/route-order', session,
                dict(items=[dict(type='pickup', ref=place)]), 'PUT')[0], 200)
        self.transition(trip, 'start')
        before = [self.car_detail(trip, car, session) for car, session in cars]
        signal = self.new_signal(trip)
        self.assertEqual(self.api(trip, '/signals/'+signal+'/finish', driver, dict(result='cancelled'), 'POST')[0], 200)
        self.assertEqual(self.signals(trip)[0]['resolution'], 'cancelled')
        self.assertEqual(self.vote(trip, signal, self.e)[0], 409)
        self.assertEqual([self.car_detail(trip, car, session) for car, session in cars], before)

    def test_progress_is_driver_only_versioned_and_car_edits_preserve_accepted_places(self):
        trip, car, driver, rider = self.setup_car()
        pickup = self.place(trip, car, rider)
        path = '/cars/'+car
        body = dict(next=dict(type='pickup', ref=pickup), routeRevision=0)
        self.assertEqual(self.api(trip, path+'/route-progress', driver, body, 'PUT')[0], 409)
        self.transition(trip, 'start')
        self.assertEqual(self.api(trip, path+'/route-progress', rider, body, 'PUT')[0], 403)
        self.assertEqual(self.api(trip, path+'/route-progress', driver,
            dict(body, next=dict(type='pickup', ref='f'*32)), 'PUT')[0], 400)
        self.assertEqual(self.api(trip, path+'/route-progress', driver, dict(body, routeRevision=True), 'PUT')[0], 400)
        self.assertEqual(self.api(trip, path+'/route-progress', driver, dict(body, next=None), 'PUT')[0], 200)
        signal = self.new_signal(trip)
        self.apply(trip, signal, [car])
        current = self.car_detail(trip, car)
        self.assertEqual(current['routeOrder'][-1], dict(type='signal', ref=signal))
        self.assertEqual(self.api(trip, path+'/route-progress', driver, body, 'PUT')[0], 409)
        self.assertEqual(self.api(trip, path, driver, dict(name='바꾼 차 이름', seats=3), 'PATCH')[0], 200)
        edited = self.car_detail(trip, car)
        self.assertEqual(edited['routeNext'], current['routeNext'])
        self.assertEqual(edited['routeRevision'], current['routeRevision'])
        self.assertEqual(edited['places'], current['places'])
        self.assertEqual(self.api(trip, path+'/route-order', driver,
            dict(items=[dict(type='signal', ref='d'*32)], routeRevision=edited['routeRevision']), 'PUT')[0], 400)
        self.assertEqual(self.api(trip, path+'/places', driver,
            dict(kind='signal', name='위조 장소', lat=0, lng=0), 'POST')[0], 400)

    def test_all_car_updates_share_the_callers_transaction(self):
        trip, first, driver, rider = self.setup_car()
        self.h.vehicle(self.e)
        second = self.h.new_car(trip, self.e).split('/')[-1]
        self.transition(trip, 'start')
        signal = self.new_signal(trip)
        plan = TeamTripPlan(self.h.module.TEAM_TRIPS)
        original = plan.save_order
        def fail_second(conn, selected_trip, car, items):
            if car == second:
                raise RuntimeError('Synthetic second-car failure')
            return original(conn, selected_trip, car, items)
        with self.assertRaises(RuntimeError), patch.object(plan, 'save_order', side_effect=fail_second):
            with psycopg.connect(self.dsn) as conn:
                context = resolve_trip_context(self.h.module.TEAM_AUTH, conn, trip, driver['user']['id'])
                plan.apply_agreed_signal(conn, context, signal, self.destination, [first, second])
        for car in (first, second):
            self.assertIsNone(self.car_detail(trip, car)['routeOrder'])
            self.assertEqual(self.car_detail(trip, car)['routeRevision'], 0)

    def test_stale_route_editor_cannot_erase_a_new_agreement_and_current_driver_can_reorder_it(self):
        trip, car, driver, rider = self.setup_car()
        pickup = self.place(trip, car, rider)
        self.transition(trip, 'start')
        path = '/cars/'+car+'/route-order'
        draft = [dict(type='pickup', ref=pickup)]
        before = self.car_detail(trip, car)['routeRevision']
        signal = self.new_signal(trip)
        current = self.car_detail(trip, car)
        for body in (dict(items=draft), dict(items=draft, routeRevision=before)):
            result = self.api(trip, path, driver, body, 'PUT')
            self.assertEqual((result[0], result[2]), (409, dict(detail='Route revision conflict')))
        self.assertEqual(self.car_detail(trip, car)['routeOrder'], current['routeOrder'])
        self.assertEqual(self.api(trip, path, driver, dict(items=draft, routeRevision=current['routeRevision']), 'PUT')[0], 200)
        changed = self.car_detail(trip, car)
        restored = draft+[dict(type='signal', ref=signal)]
        self.assertEqual(self.api(trip, path, driver,
            dict(items=restored, routeRevision=changed['routeRevision']), 'PUT')[0], 200)
        self.assertEqual(self.car_detail(trip, car)['routeOrder'], restored)

    def test_default_order_without_courses_keeps_pickups_before_earlier_added_drops(self):
        trip, car, driver, rider = self.setup_car()
        drop = self.place(trip, car, rider, 'drop')
        pickup = self.place(trip, car, rider, 'pickup')
        self.transition(trip, 'start')
        signal = self.new_signal(trip)
        self.assertEqual(self.car_detail(trip, car)['routeOrder'],
            [dict(type='signal', ref=signal), dict(type='pickup', ref=pickup), dict(type='drop', ref=drop)])

    def test_course_changes_preserve_accepted_signal_and_invalidate_old_progress_versions(self):
        trip, car, driver, rider = self.setup_car()
        first = self.h.published_course(driver)
        self.h.approve(first, driver); self.h.attach(trip, first, driver)
        self.transition(trip, 'start')
        signal = self.new_signal(trip)
        initial = self.car_detail(trip, car)
        second = self.h.published_course(driver)
        self.h.approve(second, driver); self.h.attach(trip, second, driver)
        added = self.car_detail(trip, car)
        self.assertEqual(added['routeNext'], dict(type='signal', ref=signal))
        self.assertIn(dict(type='signal', ref=signal), added['routeOrder'])
        self.assertEqual({item['courseId'] for item in added['routeOrder'] if item['type'] == 'course'}, {first['id'], second['id']})
        self.assertGreater(added['routeRevision'], initial['routeRevision'])
        result = self.api(trip, '/cars/'+car+'/route-progress', driver,
            dict(next=None, routeRevision=initial['routeRevision']), 'PUT')
        self.assertEqual(result[0], 409)
        self.h.detach(trip, first, driver)
        removed = self.car_detail(trip, car)
        self.assertEqual(removed['routeNext'], dict(type='signal', ref=signal))
        self.assertEqual({item['courseId'] for item in removed['routeOrder'] if item['type'] == 'course'}, {second['id']})
        self.assertIn(dict(type='signal', ref=signal), removed['routeOrder'])

    def test_blocked_signal_author_is_hidden_from_place_route_and_next_projection(self):
        trip, car, driver, rider = self.setup_car()
        self.transition(trip, 'start')
        signal = self.new_signal(trip, rider)
        self.assertEqual(self.car_detail(trip, car)['routeNext'], dict(type='signal', ref=signal))
        self.assertEqual(self.h.social('/blocks', driver, dict(targetId=rider['user']['id']), 'POST')[0], 201)
        hidden = self.car_detail(trip, car)
        self.assertNotIn('routeNext', hidden)
        self.assertFalse(any(place.get('id') == signal for place in hidden['places']))
        self.assertFalse(any(item['type'] == 'signal' and item['ref'] == signal for item in hidden['routeOrder']))
        with psycopg.connect(self.dsn) as conn:
            snapshot = TeamTripPlan(self.h.module.TEAM_TRIPS).route_state(conn, trip, car)[1]
            self.assertIn(signal, snapshot['routeSignals'])

    def test_course_changes_preserve_the_drivers_existing_drop_attachment(self):
        trip, car, driver, rider = self.setup_car()
        first, second = self.h.published_course(driver), self.h.published_course(driver)
        for course in (first, second):
            self.h.approve(course, driver); self.h.attach(trip, course, driver)
        stop = second['stops'][0]
        drop = self.place(trip, car, rider, 'drop', stop['latitude'], stop['longitude'])
        order = [dict(type='course', courseId=second['id'], ref=stop['id'], dropRef=drop),
            dict(type='course', courseId=first['id'], ref=first['stops'][0]['id'])]
        self.assertEqual(self.api(trip, '/cars/'+car+'/route-order', driver, dict(items=order), 'PUT')[0], 200)
        self.transition(trip, 'start'); signal = self.new_signal(trip)
        third = self.h.published_course(driver)
        self.h.approve(third, driver); self.h.attach(trip, third, driver)
        items = self.car_detail(trip, car)['routeOrder']
        self.assertEqual(items[:3], [dict(type='signal', ref=signal)]+order)
        self.assertEqual(sum(item.get('dropRef') == drop for item in items), 1)
        self.h.detach(trip, second, driver)
        items = self.car_detail(trip, car)['routeOrder']
        self.assertEqual(sum(item.get('dropRef') == drop or item['type'] == 'drop' and item['ref'] == drop for item in items), 1)
        self.assertEqual(items[0], dict(type='signal', ref=signal))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(TripSignalRouteTests(name) for name in vars(TripSignalRouteTests) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
