from concurrent.futures import ThreadPoolExecutor
import secrets
import threading

import psycopg

from test_team_trips import concurrent_active_trips
from test_trip_merge_api import PLACE, TripApiFixture


class TripSingleSignalTests(TripApiFixture):
    def active(self, *members):
        trip = super().active(*members)
        self.vehicle_credentials=getattr(self,'vehicle_credentials',{})
        for member in (self.a, *members):
            if member['user']['id'] not in self.vehicle_credentials:
                device=self.h.vehicle(member)
                self.vehicle_credentials[member['user']['id']]=(device,self.h._native_fingerprint)
            self.h.new_car(trip, member)
        return trip

    def send(self, trip, session, kind='rest', destination=PLACE):
        return self.api(trip, '/signals', session, dict(kind=kind, destination=destination), 'POST')

    def legacy_send(self, trip, session, kind='rest'):
        service = self.h.module.TEAM_AUTH.trip_signal_contexts
        with psycopg.connect(self.dsn) as conn:
            result = service.create(conn, trip, session['user']['id'], kind, PLACE, preparation=True)
            raw = conn.execute('SELECT protected FROM team_trip_signal_contexts WHERE trip_id=%s AND signal_id=%s',
                (trip, result['id'])).fetchone()[0]
            saved = service.restore(trip, result['id'], raw)
            saved.update(handRaise=True, resolution='pending')
            service.save(conn, trip, result['id'], saved)
        return result

    def stored(self, trip):
        with psycopg.connect(self.dsn) as conn:
            return conn.execute('SELECT s.signal_id,s.protected,c.protected,c.revision '
                'FROM team_room_signals s JOIN team_trip_signal_contexts c USING(signal_id) '
                'WHERE c.trip_id=%s ORDER BY s.signal_id', (trip,)).fetchall()

    def active_with_drivers(self, *drivers):
        trip = TripApiFixture.active(self, self.b, self.e)
        cars = {}
        for driver in drivers:
            self.h.vehicle(driver)
            cars[driver['user']['id']] = self.h.new_car(trip, driver)
        return trip, cars

    def test_concurrent_members_create_exactly_one_request(self):
        trip = self.active(self.b)
        ready = threading.Barrier(2)

        def send(session):
            ready.wait(timeout=5)
            return self.send(trip, session)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, (self.a, self.b)))
        self.assertEqual(sorted(result[0] for result in results), [201, 409], results)
        refused = next(result for result in results if result[0] == 409)
        self.assertEqual(refused[2], dict(detail='TRIP_SIGNAL_IN_PROGRESS'))
        winner = next(result for result in results if result[0] == 201)
        self.assertEqual([row[0] for row in self.stored(trip)], [winner[2]['id']])
        listing = self.api(trip, '/signals', self.a)[2]
        self.assertTrue(listing['hasActiveSignal'])
        self.assertEqual(sum(item['inProgress'] for item in listing['signals']), 1)

    def test_retry_preserves_request_and_other_trip_is_independent(self):
        trip = self.active(self.b)
        status, _, first = self.send(trip, self.a)
        self.assertEqual(status, 201, first)
        stored = self.stored(trip)
        retry = self.send(trip, self.a)
        self.assertEqual(retry[0], 201, retry[2])
        self.assertEqual(retry[2], first)
        for member, kind in ((self.a, 'hungry'), (self.b, 'rest')):
            with self.subTest(member=member['user']['id'], kind=kind):
                result = self.send(trip, member, kind)
                self.assertEqual(result[0], 409, result[2])
                self.assertEqual(result[2], dict(detail='TRIP_SIGNAL_IN_PROGRESS'))
        self.assertEqual(self.stored(trip), stored)
        with concurrent_active_trips():
            other = self.active(self.b)
        result = self.send(other, self.b, 'hungry')
        self.assertEqual(result[0], 201, result[2])
        self.assertNotEqual(result[2]['id'], first['id'])
        self.assertEqual(self.stored(trip), stored)

    def test_browser_and_native_requests_share_the_same_trip_slot(self):
        trip = self.active(self.b)
        credential,certificate = self.vehicle_credentials[self.b['user']['id']]
        permissions = self.h.native('/v1/device/functional-permissions', token=credential['accessToken'],
                                    certificate=certificate)
        self.assertEqual(permissions[0], 200, permissions[2])
        ready = threading.Barrier(2)

        def browser():
            ready.wait(timeout=5)
            return self.send(trip, self.a)

        def native():
            ready.wait(timeout=5)
            return self.h.native('/v1/social/trips/' + trip + '/signals',
                dict(kind='hungry', destination=PLACE, functionalRevision=permissions[2]['revision']),
                'POST', token=credential['accessToken'], certificate=certificate)

        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(browser), pool.submit(native)]
            results = [request.result() for request in requests]
        self.assertEqual(sorted(result[0] for result in results), [201, 409], results)
        self.assertEqual(len(self.stored(trip)), 1)
        refused = next(result for result in results if result[0] == 409)
        self.assertEqual(refused[2], dict(detail='TRIP_SIGNAL_IN_PROGRESS'))

    def test_legacy_overlapping_requests_are_retained_and_block_new_requests(self):
        trip = self.active(self.b)
        signal = self.legacy_send(trip, self.a)['id']
        service = self.h.module.TEAM_AUTH.trip_signal_contexts
        duplicate = secrets.token_hex(16)
        with psycopg.connect(self.dsn) as conn:
            room, sender, raw, protected = conn.execute('SELECT s.room_id,s.account_id,s.protected,c.protected '
                'FROM team_room_signals s JOIN team_trip_signal_contexts c USING(signal_id) '
                'WHERE c.trip_id=%s AND s.signal_id=%s', (trip, signal)).fetchone()
            value = service.rooms.restore('signal:' + sender, signal, raw)
            value['kind'] = 'hungry'
            context = service.restore(trip, signal, protected)
            conn.execute('INSERT INTO team_room_signals(signal_id,room_id,account_id,protected) VALUES(%s,%s,%s,%s)',
                (duplicate, room, sender, service.rooms.protect('signal:' + sender, duplicate, value)))
            conn.execute('INSERT INTO team_trip_signal_contexts(signal_id,trip_id,protected) VALUES(%s,%s,%s)',
                (duplicate, trip, service.protect(trip, duplicate, context)))
        stored = self.stored(trip)
        listing = self.signals(trip)
        self.assertEqual({item['id'] for item in listing}, {signal, duplicate})
        self.assertEqual(sum(item['inProgress'] for item in listing), 1)
        result = self.send(trip, self.b, 'smoking')
        self.assertEqual(result[0], 409, result[2])
        self.assertEqual(result[2], dict(detail='TRIP_SIGNAL_IN_PROGRESS'))
        self.assertEqual(self.stored(trip), stored)

    def test_legacy_room_signal_route_cannot_bypass_the_trip_slot(self):
        trip = self.active(self.b)
        self.signal(trip)
        stored = self.stored(trip)
        with psycopg.connect(self.dsn) as conn:
            room = conn.execute('SELECT room_id FROM team_rooms WHERE trip_id=%s', (trip,)).fetchone()[0]
        result = self.h.social('/rooms/' + room + '/signals', self.b, dict(kind='hungry'), 'POST')
        self.assertEqual(result[0], 409, result[2])
        self.assertEqual(result[2], dict(detail='TRIP_CLIENT_UPDATE_REQUIRED'))
        self.assertEqual(self.stored(trip), stored)

    def test_arrival_signal_does_not_replace_an_in_progress_hand_raise(self):
        trip = self.active(self.b)
        first = self.send(trip, self.a)
        self.assertEqual(first[0], 201, first[2])
        arrival = self.send(trip, self.b, 'arrived', destination=None)
        self.assertEqual(arrival[0], 201, arrival[2])
        listing = self.api(trip, '/signals', self.a)[2]
        self.assertTrue(listing['hasActiveSignal'])
        self.assertEqual([item['id'] for item in listing['signals'] if item['inProgress']], [first[2]['id']])
        result = self.send(trip, self.b, 'hungry')
        self.assertEqual(result[0], 409, result[2])

    def test_author_finish_releases_slot_without_finishing_a_new_request(self):
        trip = self.active(self.b)
        first = self.send(trip, self.a, destination=None)
        self.assertEqual(first[0], 201, first[2])
        path = '/signals/' + first[2]['id'] + '/finish'
        denied = self.api(trip, path, self.b, dict(result='completed'), 'POST')
        self.assertEqual(denied[0], 403, denied[2])
        result = self.api(trip, path, self.a, dict(result='completed'), 'POST')
        self.assertEqual(result[0], 200, result[2])
        self.assertFalse(self.api(trip, '/signals', self.a)[2]['hasActiveSignal'])
        second = self.send(trip, self.b, 'hungry', destination=None)
        self.assertEqual(second[0], 201, second[2])
        stored = self.stored(trip)
        retry = self.api(trip, path, self.a, dict(result='completed'), 'POST')
        self.assertEqual(retry[0], 200, retry[2])
        self.assertEqual(self.stored(trip), stored)
        refused = self.send(trip, self.a, 'smoking', destination=None)
        self.assertEqual(refused[0], 409, refused[2])
        result = self.api(trip, '/signals/' + second[2]['id'] + '/finish', self.b,
                          dict(result='cancelled'), 'POST')
        self.assertEqual(result[0], 200, result[2])
        self.assertEqual(self.send(trip, self.a, 'smoking', destination=None)[0], 201)

    def test_legacy_passenger_request_needs_both_of_two_drivers_to_agree(self):
        trip, cars = self.active_with_drivers(self.a, self.b)
        self.assertEqual(self.h.ride(cars[self.a['user']['id']], self.e)[0], 200)
        signal = self.legacy_send(trip, self.e)['id']
        self.assertEqual(self.signals(trip)[0]['driverVotes'], dict(agree=0, **{'pass': 0}, total=2))
        denied = self.vote(trip, signal, self.e)
        self.assertEqual(denied[0], 403, denied[2])
        self.assertEqual(self.vote(trip, signal, self.a)[0], 200)
        listing = self.api(trip, '/signals', self.e)[2]
        self.assertTrue(listing['hasActiveSignal'])
        self.assertEqual(listing['signals'][0]['driverVotes'], dict(agree=1, **{'pass': 0}, total=2))
        self.assertEqual(listing['signals'][0]['resolution'], 'pending')
        self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
        listing = self.api(trip, '/signals', self.e)[2]
        self.assertFalse(listing['hasActiveSignal'])
        self.assertEqual(listing['signals'][0]['resolution'], 'agreed')
        self.assertEqual(listing['signals'][0]['driverVotes'], dict(agree=2, **{'pass': 0}, total=2))
        self.assertEqual(self.api(trip, '/signals/' + signal + '/vote', self.a, method='DELETE')[0], 409)
        self.assertEqual(self.send(trip, self.e, 'hungry')[0], 201)

    def test_legacy_requesting_driver_counts_once_and_majority_can_finish_before_unanimity(self):
        trip, _ = self.active_with_drivers(self.a, self.b, self.e)
        signal = self.legacy_send(trip, self.a)['id']
        self.assertEqual(self.signals(trip)[0]['driverVotes'], dict(agree=1, **{'pass': 0}, total=3))
        self.assertEqual(self.vote(trip, signal, self.a)[0], 200)
        self.assertEqual(self.signals(trip)[0]['driverVotes'], dict(agree=1, **{'pass': 0}, total=3))
        self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
        listing = self.api(trip, '/signals', self.a)[2]
        self.assertFalse(listing['hasActiveSignal'])
        self.assertEqual(listing['signals'][0]['resolution'], 'agreed')
        self.assertEqual(listing['signals'][0]['driverVotes'], dict(agree=2, **{'pass': 0}, total=3))
        without_vote = next(item for item in self.signals(trip, self.e) if item['id'] == signal)
        self.assertIsNone(without_vote['myVote'])
        self.assertEqual(self.vote(trip, signal, self.e)[0], 409)
        self.assertEqual(self.send(trip, self.e, 'hungry')[0], 201)

    def test_legacy_two_driver_pass_majority_finishes_and_releases_trip_slot(self):
        trip, _ = self.active_with_drivers(self.a, self.b)
        signal = self.legacy_send(trip, self.e)['id']
        self.assertEqual(self.vote(trip, signal, self.a, 'pass')[0], 200)
        listing = self.api(trip, '/signals', self.e)[2]
        self.assertTrue(listing['hasActiveSignal'])
        self.assertEqual(listing['signals'][0]['driverVotes'], dict(agree=0, **{'pass': 1}, total=2))
        self.assertEqual(self.vote(trip, signal, self.b, 'pass')[0], 200)
        listing = self.api(trip, '/signals', self.e)[2]
        self.assertFalse(listing['hasActiveSignal'])
        self.assertEqual(listing['signals'][0]['resolution'], 'passed')
        self.assertEqual(listing['signals'][0]['driverVotes'], dict(agree=0, **{'pass': 2}, total=2))
        self.assertEqual(self.api(trip, '/signals/' + signal + '/vote', self.a, method='DELETE')[0], 409)
        self.assertEqual(self.send(trip, self.a, 'hungry')[0], 201)

    def test_native_requester_can_finish_without_a_destination(self):
        trip = self.active(self.b)
        credential,certificate = self.vehicle_credentials[self.b['user']['id']]
        permissions = self.h.native('/v1/device/functional-permissions', token=credential['accessToken'],
                                    certificate=certificate)
        self.assertEqual(permissions[0], 200, permissions[2])
        revision = permissions[2]['revision']
        result = self.h.native('/v1/social/trips/' + trip + '/signals',
            dict(kind='rest', functionalRevision=revision), 'POST',
            token=credential['accessToken'], certificate=certificate)
        self.assertEqual(result[0], 201, result[2])
        signal = result[2]['id']
        result = self.h.native('/v1/social/trips/' + trip + '/signals/' + signal + '/finish',
            dict(result='completed', functionalRevision=revision), 'POST',
            token=credential['accessToken'], certificate=certificate)
        self.assertEqual(result[0], 200, result[2])
        self.assertEqual(result[2]['status'], 'completed')
        self.assertFalse(self.api(trip, '/signals', self.a)[2]['hasActiveSignal'])
        self.assertEqual(self.send(trip, self.a, 'hungry')[0], 201)

    def test_passenger_status_does_not_prevent_drivers_from_agreeing(self):
        trip, _ = self.active_with_drivers(self.a, self.b)
        self.sharing(trip, self.e, status=False)
        created = self.send(trip, self.a)
        self.assertEqual(created[0], 201, created[2])
        signal = created[2]['id']
        self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
        result = self.signals(trip)[0]
        self.assertEqual(result['resolution'], 'agreed')
        self.assertTrue(result['agreed'])
        self.assertFalse(result['inProgress'])
        self.transition(trip, 'finish')
        with psycopg.connect(self.dsn) as conn:
            archived = self.h.module.TEAM_AUTH.trip_places_service.result_reader(conn, trip, self.a['user']['id'])
        self.assertIn(signal, [item['id'] for item in archived['places']])

    def test_legacy_blocked_driver_votes_and_hidden_request_are_not_exposed(self):
        trip, _ = self.active_with_drivers(self.a, self.b, self.e)
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.e['user']['id']), 'POST')[0], 201)
        signal = self.legacy_send(trip, self.a)['id']
        self.assertEqual(self.vote(trip, signal, self.e)[0], 200)
        visible = self.signals(trip, self.b)[0]
        self.assertEqual(visible['driverVotes'], dict(agree=1, **{'pass': 0}, total=2))
        self.assertEqual(visible['votes'], dict(agree=0, **{'pass': 0}))
        self.assertEqual(visible['resolution'], 'agreed')
        self.assertEqual(self.signals(trip, self.a)[0]['driverVotes'], dict(agree=2, **{'pass': 0}, total=3))
        hidden = self.legacy_send(trip, self.e, 'hungry')
        listing = self.api(trip, '/signals', self.b)[2]
        self.assertTrue(listing['hasActiveSignal'])
        self.assertNotIn(hidden['id'], [item['id'] for item in listing['signals']])
        conflict = self.send(trip, self.b, 'restroom')
        self.assertEqual(conflict[0], 409, conflict[2])
        self.assertEqual(conflict[2], dict(detail='TRIP_SIGNAL_IN_PROGRESS'))
