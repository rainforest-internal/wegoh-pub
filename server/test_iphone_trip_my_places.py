from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

import psycopg
from fastapi import HTTPException

import test_iphone_trips as fixture
from team_trip_my_places import my_place_fields


def selection(revision=1, pickup=None, drop=None, *, same=False):
    return dict(revision=revision, pickup=pickup, drop=drop, dropAtPickup=same)


def searched(name='내 탑승 장소', lat=37.5, lng=127.0):
    return dict(name=name, lat=lat, lng=lng)


class MyPlaceFieldsTests(unittest.TestCase):
    def test_closed_choice_and_strict_scalar_validation(self):
        self.assertEqual(my_place_fields(selection(pickup=searched(), same=True)),
                         selection(pickup=searched(), same=True))
        invalid = [None, {}, dict(selection(), accountId='a' * 32), selection(True), selection(0),
            selection(2147483648), dict(selection(), dropAtPickup=1), selection(same=True),
            selection(pickup=searched(), drop=searched(), same=True), selection(pickup=[]),
            selection(pickup=dict(placeId='invalid')), selection(pickup=dict(placeId='a' * 32, name='extra')),
            selection(pickup=searched(lat=True)), selection(pickup=searched(lat=float('inf'))),
            selection(drop=searched(lng=-181)), selection(pickup=searched(name='x' * 41))]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(HTTPException) as error:
                my_place_fields(value)
            self.assertEqual(error.exception.status_code, 400)


class IPhoneMyPlacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.IPhoneTripTests.setUpClass.__func__(cls)

    def setUp(self):
        self.h = fixture.IPhoneTripTests()
        self.h.setUp()
        self.addCleanup(self.h.phone.doCleanups)
        h = self.h
        h.befriend(h.bob)
        self.trip = h.create()
        h.join(self.trip, h.bob)
        h.vehicle()
        self.car = h.checked(h.call('/' + self.trip + '/cars', dict(name='우리 차', seats=2), 'POST'), 201)['id']
        self.base = '/' + self.trip + '/cars/' + self.car
        h.checked(h.call(self.base + '/ride', {}, 'PUT', session=h.bob))

    def revision(self):
        return self.h.detail(self.trip)['revision']

    def save(self, body, *, session=None, status=200):
        result = self.h.call(self.base + '/my-places', body, 'PUT', session=session or self.h.bob)
        return self.h.checked(result, status)

    def database(self):
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            places = conn.execute('SELECT place_id,kind,added_by,protected FROM team_trip_car_places '
                'WHERE trip_id=%s AND car_id=%s ORDER BY place_id', (self.trip, self.car)).fetchall()
            selections = conn.execute('SELECT account_id,kind,place_id FROM team_trip_car_place_selections '
                'WHERE trip_id=%s AND car_id=%s ORDER BY account_id,kind', (self.trip, self.car)).fetchall()
            events = dict(conn.execute('SELECT account_id,revision FROM team_resource_versions '
                "WHERE account_id=ANY(%s) AND resource='rooms'", (
                ['event-trip:' + self.trip + ':' + section for section in ('route', 'detail')],)))
        return places, selections, events

    def test_new_places_atomic_encrypted_and_same_desired_stale_retry(self):
        revision = self.revision()
        before = self.database()
        body = selection(revision, searched(), searched('내 하차 장소', 37.6, 127.1))
        saved = self.save(body)
        self.assertEqual(set(saved), {'revision', 'routeRevision', 'pickupPlaceId', 'dropPlaceId', 'dropAtPickup', 'status'})
        self.assertEqual(saved['revision'], revision + 1)
        self.assertEqual(saved['routeRevision'], 1)
        self.assertEqual(saved['status'], 'updated')
        self.assertFalse(saved['dropAtPickup'])
        after = self.database()
        self.assertEqual(len(after[0]), 2)
        self.assertEqual({row[:2] for row in after[1]}, {(self.h.b, 'pickup'), (self.h.b, 'drop')})
        for _, _, _, raw in after[0]:
            self.assertNotIn('내 탑승 장소'.encode(), bytes(raw))
            self.assertNotIn('내 하차 장소'.encode(), bytes(raw))
        for key in after[2]:
            self.assertEqual(after[2][key], before[2].get(key, 0) + 1)
        retry = self.save(body)
        self.assertEqual(retry, dict(saved, status='unchanged'))
        self.assertEqual(self.database(), after)
        explicit = selection(1, dict(placeId=saved['pickupPlaceId']), dict(placeId=saved['dropPlaceId']))
        self.assertEqual(self.save(explicit), retry)

    def test_same_pickup_creates_distinct_drop_kind_and_clear_is_atomic(self):
        body = selection(self.revision(), searched(), same=True)
        saved = self.save(body)
        self.assertTrue(saved['dropAtPickup'])
        self.assertNotEqual(saved['pickupPlaceId'], saved['dropPlaceId'])
        places = self.h.checked(self.h.call(self.base + '/places', session=self.h.bob))['places']
        self.assertEqual({p['kind'] for p in places}, {'pickup', 'drop'})
        self.assertTrue(all(p['selectedBy'] == [self.h.b] for p in places))
        self.assertEqual({(p['name'], p['lat'], p['lng']) for p in places}, {('내 탑승 장소', 37.5, 127.0)})
        self.assertEqual(self.save(body)['status'], 'unchanged')
        cleared = self.save(selection(saved['revision']))
        self.assertEqual(cleared['routeRevision'], saved['routeRevision'] + 1)
        self.assertIsNone(cleared['pickupPlaceId'])
        self.assertIsNone(cleared['dropPlaceId'])
        self.assertFalse(cleared['dropAtPickup'])
        self.assertEqual(self.database()[1], [])

    def test_stale_different_desired_and_invalid_choice_never_write(self):
        saved = self.save(selection(self.revision(), searched(), same=True))
        before = self.database()
        self.assertEqual(self.save(selection(saved['revision'] - 1, searched('다른 위치'), same=True), status=409)['detail'],
                         'TRIP_PLACE_SELECTION_CHANGED')
        for body, status in ((selection(saved['revision'], dict(placeId=saved['dropPlaceId'])), 404),
                (selection(saved['revision'], dict(placeId='f' * 32)), 404),
                (dict(selection(saved['revision']), accountId=self.h.a), 400),
                (selection(saved['revision'], searched(), searched(), same=True), 400)):
            self.save(body, status=status)
        self.assertEqual(self.database(), before)

    def test_capacity_failure_leaves_both_new_places_and_selections_untouched(self):
        for index in range(10):
            self.h.checked(self.h.call(self.base + '/places', dict(kind='drop', **searched('기존 하차 ' + str(index))),
                'POST', session=self.h.bob), 201)
        revision = self.revision()
        before = self.database()
        self.save(selection(revision, searched('만들어지면 안 되는 탑승'), searched('용량 초과 하차')), status=409)
        self.assertEqual(self.revision(), revision)
        self.assertEqual(self.database(), before)

    def test_replacing_routed_pickup_bumps_route_revision_once(self):
        from team_trip_plan import TeamTripPlan
        first = self.save(selection(self.revision(), searched(), same=True))
        plan = TeamTripPlan(self.h.phone.api.module.TEAM_AUTH.trip_service)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            plan.save_order(conn, self.trip, self.car, [dict(type='pickup', ref=first['pickupPlaceId']),
                dict(type='drop', ref=first['dropPlaceId'])])
            before = plan.route_state(conn, self.trip, self.car)[1]['routeRevision']
        saved = self.save(selection(first['revision'], searched('새 탑승 장소', 37.7, 127.2),
                                    dict(placeId=first['dropPlaceId'])))
        self.assertEqual(saved['routeRevision'], before + 1)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            self.assertEqual(plan.stored_order(conn, self.trip, self.car),
                [dict(type='pickup', ref=saved['pickupPlaceId']), dict(type='drop', ref=first['dropPlaceId'])])

    def test_role_membership_scope_and_block_guards_precede_idempotence(self):
        empty = selection(self.revision())
        self.save(empty, session=self.h.alice, status=403)
        self.save(empty, session=self.h.eve, status=404)
        self.assertEqual(self.h.call('/' + self.trip + '/cars/' + 'f' * 32 + '/my-places', empty,
            'PUT', session=self.h.bob)[0], 404)
        self.h.befriend(self.h.eve)
        self.h.join(self.trip, self.h.eve)
        self.save(empty, session=self.h.eve, status=403)
        self.h.checked(self.h.call(self.base + '/ride', {}, 'PUT', session=self.h.eve))
        place = self.h.checked(self.h.call(self.base + '/places', dict(kind='pickup', **searched('친구 장소')),
            'POST', session=self.h.eve), 201)['id']
        self.h.checked(self.h.phone.iphone('/v1/iphone/blocks', dict(targetId=self.h.e), 'POST',
            token=self.h.bob['accessToken']), 201)
        self.save(selection(self.revision(), dict(placeId=place)), status=404)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s WHERE account_id=%s', (['trips:read'], self.h.b))
        self.save(selection(1), status=403)

    def test_active_v2_is_locked_but_legacy_active_remains_mutable(self):
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute("UPDATE team_trips SET state='active',started_at=now() WHERE trip_id=%s", (self.trip,))
        saved = self.save(selection(self.revision(), searched(), same=True))
        before = self.database()
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute('INSERT INTO team_trip_route_plans(trip_id,protected) VALUES(%s,%s)', (self.trip, b'locked-plan'))
        self.assertEqual(self.save(selection(saved['revision'], searched(), same=True), status=409)['detail'],
                         'TRIP_ROUTE_PLAN_LOCKED')
        self.assertEqual(self.database(), before)

    def test_concurrent_same_desired_retries_create_one_pair(self):
        body = selection(self.revision(), searched(), same=True)
        ready = threading.Barrier(2)
        def save(_):
            ready.wait(timeout=5)
            return self.h.call(self.base + '/my-places', body, 'PUT', session=self.h.bob)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (1, 2)))
        self.assertEqual([row[0] for row in results], [200, 200], results)
        self.assertEqual({row[2]['status'] for row in results}, {'updated', 'unchanged'})
        self.assertEqual(len({row[2]['pickupPlaceId'] for row in results}), 1)
        self.assertEqual(len({row[2]['dropPlaceId'] for row in results}), 1)
        self.assertEqual(len(self.database()[0]), 2)

    def test_concurrent_different_desired_uses_trip_revision(self):
        revision = self.revision()
        ready = threading.Barrier(2)
        def save(index):
            ready.wait(timeout=5)
            return self.h.call(self.base + '/my-places', selection(revision, searched('탑승 ' + str(index)), same=True),
                'PUT', session=self.h.bob)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, (1, 2)))
        self.assertEqual(sorted(row[0] for row in results), [200, 409], results)
        self.assertEqual(next(row[2]['detail'] for row in results if row[0] == 409), 'TRIP_PLACE_SELECTION_CHANGED')
        self.assertEqual(len(self.database()[0]), 2)


if __name__ == '__main__':
    unittest.main()
