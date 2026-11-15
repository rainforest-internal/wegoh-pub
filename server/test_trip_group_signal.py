from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch

import psycopg
from fastapi import HTTPException
from team_trip_plan import TeamTripPlan
from team_trip_signal_contexts import GROUP_FIELDS
from test_trip_merge_api import PLACE, TripApiFixture


class TripGroupSignalTests(TripApiFixture):
    def groups(self, *drivers):
        trip = self.active(self.b, self.e)
        cars = {}
        for session in drivers:
            self.h.vehicle(session)
            cars[session['user']['id']] = self.h.new_car(trip, session)
        return trip, cars

    def send(self, trip, session, destination=PLACE):
        return self.api(trip, '/signals', session, dict(kind='rest', destination=destination), 'POST')

    def test_all_groups_answer_before_rejection_finishes(self):
        trip, cars = self.groups(self.a, self.b, self.e)
        created = self.send(trip, self.a)
        self.assertEqual(created[0], 201, created[2])
        signal = created[2]['id']
        view = self.signals(trip, self.b)[0]
        self.assertEqual(view['decisionRule'], 'other-car-groups-v1')
        self.assertEqual(view['requesterCarId'], cars[self.a['user']['id']].rsplit('/', 1)[1])
        self.assertEqual(view['groupVotes'], dict(agree=0, **{'pass': 0}, total=2))
        self.assertTrue(view['canRespond'])
        self.assertEqual(self.vote(trip, signal, self.b, 'pass')[0], 200)
        view = self.signals(trip, self.e)[0]
        self.assertTrue(view['inProgress'])
        self.assertEqual(view['resolution'], 'pending')
        self.assertEqual(view['groupVotes'], dict(agree=0, **{'pass': 1}, total=2))
        refused = next(row for row in view['groupResponses'] if row['choice'] == 'pass')
        self.assertEqual(refused['carId'], cars[self.b['user']['id']].rsplit('/', 1)[1])
        self.assertTrue(refused['carName'])
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True) as apply:
            self.assertEqual(self.vote(trip, signal, self.e)[0], 200)
            apply.assert_not_called()
        view = self.signals(trip)[0]
        self.assertEqual(view['resolution'], 'passed')
        self.assertFalse(view['inProgress'])

    def test_requester_group_is_implicit_and_another_passenger_can_answer(self):
        trip, cars = self.groups(self.a, self.b)
        self.assertEqual(self.h.ride(cars[self.b['user']['id']], self.e)[0], 200)
        created = self.send(trip, self.a)
        self.assertEqual(created[0], 201, created[2])
        signal = created[2]['id']
        self.assertFalse(self.signals(trip, self.a)[0]['canRespond'])
        self.assertIsNone(self.signals(trip, self.a)[0]['myGroupChoice'])
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True) as apply:
            self.assertEqual(self.vote(trip, signal, self.e)[0], 200)
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(set(apply.call_args.args[-1]), {value.rsplit('/', 1)[1] for value in cars.values()})
        view = self.signals(trip, self.b)[0]
        self.assertEqual(view['resolution'], 'agreed')
        self.assertEqual(view['myGroupChoice'], 'agree')
        self.assertFalse(view['canRespond'])
        self.assertEqual(view['groupVotes'], dict(agree=1, **{'pass': 0}, total=1))
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True) as apply:
            self.assertEqual(self.vote(trip, signal, self.e)[0], 200)
            apply.assert_not_called()
        repeated = self.vote(trip, signal, self.b)
        self.assertEqual(repeated[0], 200, repeated[2])
        self.assertTrue(repeated[2]['already'])
        self.assertEqual(repeated[2]['responderAccountId'], self.e['user']['id'])
        self.assertEqual(self.api(trip, '/signals/' + signal + '/vote', self.e, method='DELETE')[0], 409)

    def test_push_request_group_and_reaction_are_rechecked_at_delivery(self):
        from iphone_push_events import push_event_visible

        trip, cars = self.groups(self.a, self.b)
        owner, driver, passenger = (session['user']['id'] for session in (self.a, self.b, self.e))
        self.assertEqual(self.h.ride(cars[driver], self.e)[0], 200)
        auth = self.h.module.TEAM_AUTH
        with patch('team_trip_signal_contexts.enqueue_push') as enqueue:
            first = self.send(trip, self.a)
            self.assertEqual(first[0], 201, first[2])
            signal = first[2]['id']
            self.assertEqual(self.send(trip, self.a)[2]['id'], signal)
            self.assertEqual(enqueue.call_count, 1)
            self.assertEqual(set(enqueue.call_args.kwargs['recipients']), {driver, passenger})
            self.assertEqual(enqueue.call_args.kwargs['kind'], 'hand_raise')
            self.assertEqual(enqueue.call_args.kwargs['resource_id'], signal)
            self.assertEqual(enqueue.call_args.kwargs['trip_id'], trip)

            def visible(kind, actor, recipient):
                with psycopg.connect(self.dsn) as conn:
                    return push_event_visible(conn, dict(kind=kind, actor_id=actor, recipient_id=recipient,
                        resource_id=signal, trip_id=trip), auth, None)

            self.assertTrue(visible('hand_raise', owner, driver))
            self.assertTrue(visible('hand_raise', owner, passenger))
            self.assertFalse(visible('hand_raise', owner, owner))
            with patch.object(TeamTripPlan, 'apply_agreed_signal', side_effect=HTTPException(409, 'TRIP_ROUTE_RECONFIRM_REQUIRED')):
                self.assertEqual(self.vote(trip, signal, self.e)[0], 409)
            self.assertEqual(enqueue.call_count, 1)
            self.assertTrue(visible('hand_raise', owner, passenger))
            self.assertEqual(self.vote(trip, signal, self.e)[0], 200)
            self.assertEqual(self.vote(trip, signal, self.b)[2]['already'], True)
            self.assertEqual(enqueue.call_count, 2)
            self.assertEqual(enqueue.call_args.kwargs, dict(kind='hand_raise_reaction', actor=passenger,
                recipients=[owner], resource_id=signal, trip_id=trip))
            self.assertFalse(visible('hand_raise', owner, driver))
            self.assertTrue(visible('hand_raise_reaction', passenger, owner))
            self.assertFalse(visible('hand_raise_reaction', driver, owner))
            self.assertFalse(visible('hand_raise_reaction', passenger, driver))
            self.assertEqual(self.h.social('/blocks', self.a, dict(targetId=passenger), 'POST')[0], 201)
            self.assertFalse(visible('hand_raise_reaction', passenger, owner))

    def test_same_group_concurrent_responses_have_one_winner(self):
        trip, cars = self.groups(self.a, self.b)
        self.assertEqual(self.h.ride(cars[self.b['user']['id']], self.e)[0], 200)
        signal = self.send(trip, self.a)[2]['id']
        ready = threading.Barrier(2)
        def respond(value):
            session, choice = value
            ready.wait(timeout=5)
            return self.vote(trip, signal, session, choice)
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(respond, ((self.b, 'agree'), (self.e, 'pass'))))
        self.assertEqual([row[0] for row in results], [200, 200], results)
        self.assertEqual(sum(row[2].get('already', False) for row in results), 1)
        self.assertEqual(results[0][2]['choice'], results[1][2]['choice'])
        view = self.signals(trip, self.b)[0]
        self.assertEqual(sum(view['groupVotes'][key] for key in ('agree', 'pass')), 1)
        self.assertEqual(len(view['groupResponses']), 1)
        self.assertFalse(view['canRespond'])

    def test_no_continuous_location_consent_is_required_for_a_new_place(self):
        trip, _ = self.groups(self.a, self.b)
        flags = {key: False for key in ('status', 'location', 'visits', 'music', 'voice', 'control')}
        for session in (self.a, self.b):
            self.assertEqual(self.api(trip, '/sharing', session, dict(consents=flags), 'PATCH')[0], 200)
        result = self.send(trip, self.a)
        self.assertEqual(result[0], 201, result[2])
        signal = result[2]['id']
        self.assertEqual(self.signals(trip, self.b)[0]['destination'], PLACE)
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True):
            self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
        self.assertEqual(self.signals(trip, self.b)[0]['resolution'], 'agreed')

    def test_default_sharing_choices_allow_native_group_response(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        devices = {}
        for session in (self.a, self.b):
            devices[session['user']['id']] = self.h.vehicle(session)
            self.h.new_car(trip, session)
        self.transition(trip, 'start')
        workspace = self.workspace(trip, self.b)
        self.assertFalse(workspace['mySharing']['status'])
        self.assertFalse(workspace['mySharing']['location'])
        self.assertFalse(workspace['features']['signals']['consentRequired'])
        credential = devices[self.b['user']['id']]
        certificate = self.h._native_fingerprint
        permissions = self.h.native('/v1/device/functional-permissions', token=credential['accessToken'],
                                     certificate=certificate)
        self.assertEqual(permissions[0], 200, permissions[2])
        signal = self.send(trip, self.a)[2]['id']
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True):
            result = self.h.native('/v1/social/trips/' + trip + '/signals/' + signal + '/vote',
                dict(choice='agree', functionalRevision=permissions[2]['revision']), 'POST',
                token=credential['accessToken'], certificate=certificate)
        self.assertEqual(result[0], 200, result[2])
        self.assertEqual(self.signals(trip, self.b)[0]['resolution'], 'agreed')

    def test_unassigned_place_is_refused_but_unplaced_request_can_finish(self):
        trip, _ = self.groups(self.a, self.b)
        result = self.send(trip, self.e)
        self.assertEqual(result[0], 409, result[2])
        self.assertEqual(result[2]['detail'], 'TRIP_SIGNAL_CAR_REQUIRED')
        result = self.send(trip, self.e, None)
        self.assertEqual(result[0], 201, result[2])
        view = self.signals(trip, self.e)[0]
        self.assertNotIn('decisionRule', view)
        self.assertEqual(self.api(trip, '/signals/' + result[2]['id'] + '/finish', self.e,
                                 dict(result='completed'), 'POST')[0], 200)

    def test_only_group_applies_immediately_once(self):
        trip, _ = self.groups(self.a)
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True) as apply:
            result = self.send(trip, self.a)
            self.assertEqual(result[0], 201, result[2])
            self.assertEqual(apply.call_count, 1)
        view = self.signals(trip)[0]
        self.assertEqual(view['resolution'], 'agreed')
        self.assertEqual(view['groupVotes'], dict(agree=0, **{'pass': 0}, total=0))
        self.assertFalse(view['inProgress'])

    def test_failed_route_application_rolls_back_the_final_group_response(self):
        trip, _ = self.groups(self.a, self.b)
        signal = self.send(trip, self.a)[2]['id']
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True,
                          side_effect=HTTPException(409, 'TRIP_ROUTE_RECONFIRM_REQUIRED')):
            result = self.vote(trip, signal, self.b)
            self.assertEqual(result[0], 409, result[2])
        view = self.signals(trip, self.b)[0]
        self.assertEqual(view['resolution'], 'pending')
        self.assertTrue(view['canRespond'])
        self.assertIsNone(view['myGroupChoice'])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_votes WHERE signal_id=%s',
                                          (signal,)).fetchone()[0], 0)
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True) as apply:
            self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
            self.assertEqual(apply.call_count, 1)

    def test_legacy_consent_withdrawal_does_not_reexpose_old_locations(self):
        trip, _ = self.groups(self.a, self.b)
        signal = self.send(trip, self.a)[2]['id']
        service = self.h.module.TEAM_AUTH.trip_signal_contexts
        with psycopg.connect(self.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_trip_signal_contexts WHERE signal_id=%s', (signal,)).fetchone()[0]
            saved = service.restore(trip, signal, raw)
            for key in GROUP_FIELDS:
                saved.pop(key)
            saved.pop('directAction', None)
            service.save(conn, trip, signal, saved)
        self.sharing(trip, self.a, status=False, location=False)
        self.assertEqual(self.signals(trip, self.b), [])
        fresh = self.send(trip, self.a)
        self.assertEqual(fresh[0], 201, fresh[2])
        self.assertEqual([item['id'] for item in self.signals(trip, self.b)], [fresh[2]['id']])

    def test_terminal_group_history_survives_sharing_changes(self):
        trip, _ = self.groups(self.a, self.b, self.e)
        signal = self.send(trip, self.a)[2]['id']
        self.assertEqual(self.vote(trip, signal, self.b, 'pass')[0], 200)
        self.assertEqual(self.vote(trip, signal, self.e)[0], 200)
        before = self.signals(trip, self.b)[0]
        self.sharing(trip, self.a, status=False, location=False)
        after = self.signals(trip, self.b)[0]
        self.assertEqual(after['resolution'], 'passed')
        self.assertEqual(after['contextState'], 'valid')
        self.assertEqual(after['groupResponses'], before['groupResponses'])
        self.assertEqual(after['groupVotes'], before['groupVotes'])
        self.assertEqual(after['myGroupChoice'], 'pass')
        self.assertFalse(after['inProgress'])

    def test_agreed_group_history_remains_agreed_but_author_leave_hides_it(self):
        trip, _ = self.groups(self.a, self.b)
        signal = self.send(trip, self.b)[2]['id']
        with patch.object(TeamTripPlan, 'apply_agreed_signal', create=True):
            self.assertEqual(self.vote(trip, signal, self.a)[0], 200)
        self.sharing(trip, self.a, status=False, location=False)
        view = self.signals(trip, self.a)[0]
        self.assertEqual(view['resolution'], 'agreed')
        self.assertTrue(view['agreed'])
        self.assertEqual(self.api(trip, '/members/' + self.b['user']['id'], self.b, method='DELETE')[0], 200)
        self.assertEqual(self.signals(trip, self.a), [])

    def test_unreachable_required_group_is_refused_without_excluding_it(self):
        trip, _ = self.groups(self.a, self.b, self.e)
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.e['user']['id']), 'POST')[0], 201)
        result = self.send(trip, self.b)
        self.assertEqual(result[0], 409, result[2])
        self.assertEqual(result[2]['detail'], 'TRIP_SIGNAL_GROUP_UNREACHABLE')
        self.assertEqual(self.signals(trip), [])

    def test_default_sharing_choices_allow_an_unplaced_direct_action(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        self.transition(trip, 'start')
        result = self.send(trip, self.b, None)
        self.assertEqual(result[0], 201, result[2])
        signal = result[2]['id']
        self.assertNotIn('decisionRule', self.signals(trip, self.a)[0])
        self.assertEqual(self.api(trip, '/signals/' + signal + '/finish', self.b,
                                 dict(result='completed'), 'POST')[0], 200)

    def test_final_group_agreement_persists_each_car_route_once(self):
        trip, cars = self.groups(self.a, self.b)
        signal = self.send(trip, self.a)[2]['id']
        revision = self.workspace(trip, self.a)['revision']
        self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
        self.assertEqual(self.workspace(trip, self.a)['revision'], revision)
        with psycopg.connect(self.dsn) as conn:
            before = conn.execute('SELECT car_id,route_order,protected FROM team_trip_cars '
                                  'WHERE trip_id=%s ORDER BY car_id', (trip,)).fetchall()
        for session in (self.a, self.b):
            detail = self.api(trip, '', session)[2]
            car = next(value for value in detail['cars'] if value['driverId'] == session['user']['id'])
            self.assertEqual(car['routeOrder'], [dict(type='signal', ref=signal)])
            self.assertEqual(next(value for value in car['places'] if value['kind'] == 'signal')['name'], PLACE['name'])
        self.assertEqual(self.signals(trip)[0]['resolution'], 'agreed')
        self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT car_id,route_order,protected FROM team_trip_cars '
                             'WHERE trip_id=%s ORDER BY car_id', (trip,)).fetchall(), before)
