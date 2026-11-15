import json
import unittest

import psycopg
from team_rooms import CONSENTS
import test_team_trips as trip_fixture

PLACE = dict(name='공유한 쉼터', latitude=37.5, longitude=127.0)


class TripApiFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = trip_fixture.TripTests
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)

    def setUp(self):
        self.h = self.fixture(methodName='test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.a, self.b, self.e = self.h.sessions()
        self.dsn = self.h.dsn

    def api(self, trip, suffix, session, data=None, method='GET', **kwargs):
        return self.h.trip('/' + trip + suffix, data, method, session=session, **kwargs)

    def workspace(self, trip, session):
        response = self.api(trip, '/workspace', session)
        self.assertEqual(response[0], 200, response[2])
        return response[2]

    def sharing(self, trip, session, **changes):
        choices = {key: key in ('status', 'location') for key in CONSENTS}
        choices.update(changes)
        response = self.api(trip, '/sharing', session, dict(consents=choices), 'PATCH')
        self.assertEqual(response[0], 200, response[2])
        return response[2]

    def transition(self, trip, action, session=None, **extra):
        session = session or self.a
        revision = self.workspace(trip, session)['revision']
        response = self.api(trip, '/' + action, session, dict(revision=revision, **extra), 'POST')
        self.assertEqual(response[0], 200, response[2])
        return response[2]

    def role(self, trip, owner, target, role):
        response = self.api(trip, '/members/' + target['user']['id'] + '/role', owner,
            dict(role=role, revision=self.workspace(trip, owner)['revision']), 'PUT')
        self.assertEqual(response[0], 200, response[2])

    def active(self, *members):
        trip = self.h.new_trip(self.a)
        for member in members:
            self.h.join(trip, self.a, member)
        for member in (self.a, *members):
            self.sharing(trip, member)
        self.transition(trip, 'start')
        return trip

    def signal(self, trip, author=None):
        response = self.api(trip, '/signals', author or self.a, dict(kind='rest', destination=PLACE), 'POST')
        self.assertEqual(response[0], 201, response[2])
        return response[2]['id']

    def vote(self, trip, signal, session, choice='agree'):
        return self.api(trip, '/signals/' + signal + '/vote', session, dict(choice=choice), 'POST')

    def signals(self, trip, session=None):
        response = self.api(trip, '/signals', session or self.a)
        self.assertEqual(response[0], 200, response[2])
        return response[2]['signals']


class TripMergeApiTests(TripApiFixture):
    def signal(self, trip, author=None):
        service = self.h.module.TEAM_AUTH.trip_signal_contexts
        with psycopg.connect(self.dsn) as conn:
            result = service.create(conn, trip, (author or self.a)['user']['id'], 'rest', PLACE, preparation=True)
            raw = conn.execute('SELECT protected FROM team_trip_signal_contexts WHERE trip_id=%s AND signal_id=%s',
                (trip, result['id'])).fetchone()[0]
            saved = service.restore(trip, result['id'], raw)
            saved.update(handRaise=True, resolution='pending')
            service.save(conn, trip, result['id'], saved)
        return result['id']

    def active(self, *members):
        trip = super().active(*members)
        provisioned = getattr(self, '_active_vehicle_accounts', set())
        for member in (self.a, *members):
            if member['user']['id'] not in provisioned:
                self.h.vehicle(member)
                provisioned.add(member['user']['id'])
            self.h.new_car(trip, member)
        self._active_vehicle_accounts = provisioned
        return trip

    def test_workspace_membership_privacy_and_web_mutation_boundaries(self):
        self.h.befriend(self.a, self.b)
        trip = self.h.new_trip(self.a, members=(self.b,))
        self.assertEqual(self.api(trip, '/workspace', self.b)[0], 404)
        self.assertEqual(self.api(trip, '/workspace', self.e)[0], 404)
        response = self.api(trip, '/workspace', self.a)
        self.assertEqual(response[1]['cache-control'], 'private, no-store')
        value = response[2]
        self.assertEqual(set(value), {'tripId', 'revision', 'state', 'startedAt', 'endedAt', 'title', 'description',
            'myPermissions', 'members', 'cars', 'roles', 'mySharing', 'features'})
        self.assertEqual([member['id'] for member in value['members']], [self.a['user']['id']])
        self.assertEqual(value['mySharing'], {key: key == 'voice' for key in CONSENTS})
        self.assertFalse(value['features']['signals']['available'])
        for field in ('roomId', 'expiresAt', 'code', 'latitude', 'longitude', 'musicSelection', 'deviceId'):
            self.assertNotIn('"' + field + '"', json.dumps(value))
        self.assertEqual(self.h.respond(trip, self.b)[0], 200)
        revision = self.workspace(trip, self.a)['revision']
        self.assertEqual(self.api(trip, '/start', self.b, dict(revision=revision), 'POST')[0], 403)
        self.assertEqual(self.api(trip, '/start', self.a, dict(revision=revision), 'POST', csrf=False)[0], 403)
        self.assertEqual(self.api(trip, '/start', self.a, dict(revision=revision, roomId='0' * 32), 'POST')[0], 400)
        self.assertEqual(self.api(trip, '/start', self.a, method='POST', raw=b'{"revision":1,"revision":1}')[0], 400)
        self.assertEqual(self.api(trip, '/start', self.a, method='POST', raw=b'x' * 4097)[0], 413)
        started = self.transition(trip, 'start')
        self.assertEqual(self.api(trip, '/start', self.a, dict(revision=revision), 'POST')[2], started)
        self.assertEqual(self.api(trip, '/finish', self.a, dict(revision=revision), 'POST')[0], 409)
        self.transition(trip, 'finish')
        self.assertEqual(self.api(trip, '/signals', self.a, dict(kind='rest'), 'POST')[0], 409)
        self.assertEqual(self.sharing(trip, self.a, status=False, location=False)['consents']['status'], False)

    def test_other_trip_signal_ids_and_strict_signal_inputs(self):
        first = self.active(self.b)
        with trip_fixture.concurrent_active_trips():
            second = self.active(self.b)
        signal = self.signal(first)
        self.assertEqual(self.vote(first, signal, self.b, None)[0], 400)
        self.assertEqual(self.vote(second, signal, self.b)[0], 404)
        self.assertEqual(self.api(second, '/signals/' + signal + '/vote', self.b, method='DELETE')[0], 404)
        self.assertEqual(self.api(first, '/signals', self.a, dict(kind=[], destination=PLACE), 'POST')[0], 400)
        for bad in (dict(PLACE, latitude=True), dict(PLACE, longitude=181), dict(PLACE, hidden='x')):
            self.assertEqual(self.api(first, '/signals', self.a, dict(kind='rest', destination=bad), 'POST')[0], 400)
        self.sharing(first, self.a, location=False)
        self.assertEqual(self.api(first, '/signals', self.a, dict(kind='rest', destination=PLACE), 'POST')[0], 201)

    def test_member_reduction_does_not_turn_old_votes_into_agreement(self):
        trip = self.active(self.b, self.e)
        signal = self.signal(trip)
        self.assertEqual(self.vote(trip, signal, self.b)[0], 200)
        self.assertTrue(self.signals(trip)[0]['agreed'])
        self.assertEqual(self.api(trip, '/members/' + self.e['user']['id'], self.e, method='DELETE')[0], 200)
        old = self.signals(trip)[0]
        self.assertEqual(old['contextState'], 'reconfirm')
        self.assertEqual(old['votes'], dict(agree=0, **{'pass': 0}))
        self.assertFalse(old['agreed'])
        self.assertEqual(self.vote(trip, signal, self.b)[0], 409)
        current = self.signal(trip)
        self.assertEqual(self.vote(trip, current, self.b)[0], 200)
        self.assertTrue(self.signals(trip)[0]['agreed'])
        self.assertEqual(self.vote(trip, current, self.a, 'pass')[0], 409)
        self.assertTrue(self.signals(trip)[0]['agreed'])

    def test_rejoin_never_restores_old_signals_or_votes(self):
        trip = self.active(self.b)
        own = self.signal(trip, self.b)
        self.assertEqual(self.api(trip, '/signals/' + own + '/finish', self.b,
                                 dict(result='cancelled'), 'POST')[0], 200)
        other = self.signal(trip)
        self.assertEqual(self.vote(trip, other, self.b)[0], 200)
        self.assertEqual(self.api(trip, '/members/' + self.b['user']['id'], self.b, method='DELETE')[0], 200)
        self.h.join(trip, self.a, self.b)
        self.sharing(trip, self.b)
        values = self.signals(trip)
        self.assertNotIn(own, [value['id'] for value in values])
        old = next(value for value in values if value['id'] == other)
        self.assertFalse(old['agreed'])
        self.assertEqual(old['votes']['agree'], 0)
        self.assertEqual(self.vote(trip, other, self.b)[0], 409)
        fresh = self.signal(trip, self.b)
        self.assertIn(fresh, [value['id'] for value in self.signals(trip)])

    def test_consent_off_on_and_role_change_require_new_context(self):
        trip = self.active(self.b)
        signal = self.signal(trip)
        self.vote(trip, signal, self.b)
        self.role(trip, self.a, self.b, 'food')
        self.assertEqual(self.signals(trip)[0]['contextState'], 'reconfirm')
        self.sharing(trip, self.a, location=False)
        self.assertEqual(self.signals(trip, self.b), [])
        self.sharing(trip, self.a)
        self.assertEqual(self.signals(trip, self.b), [])
        self.assertEqual(self.vote(trip, signal, self.b)[0], 404)

    def test_block_filters_viewer_members_signals_votes_and_invalidates_agreement(self):
        trip = self.active(self.b, self.e)
        signal = self.signal(trip, self.b)
        self.vote(trip, signal, self.a)
        self.assertEqual(self.vote(trip, signal, self.e)[0], 409)
        self.assertTrue(self.signals(trip)[0]['agreed'])
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.e['user']['id']), 'POST')[0], 201)
        self.assertNotIn(self.e['user']['id'], [item['id'] for item in self.workspace(trip, self.b)['members']])
        self.assertNotIn(self.b['user']['id'], [item['accountId'] for item in self.workspace(trip, self.e)['roles']])
        self.assertEqual(self.signals(trip, self.e), [])
        self.assertFalse(self.signals(trip)[0]['agreed'])
        self.assertEqual(self.vote(trip, signal, self.e)[0], 404)

    def test_signal_pagination_and_legacy_signals_fail_closed(self):
        trip = self.active(self.b)
        identifiers = set()
        for _ in range(3):
            signal = self.signal(trip)
            identifiers.add(signal)
            self.assertEqual(self.api(trip, '/signals/' + signal + '/finish', self.a,
                                     dict(result='cancelled'), 'POST')[0], 200)
        first = self.api(trip, '/signals?limit=2', self.a)[2]
        second = self.api(trip, '/signals?limit=2&cursor=' + first['nextCursor'], self.a)[2]
        self.assertEqual({item['id'] for item in first['signals'] + second['signals']}, identifiers)
        self.assertIsNone(second['nextCursor'])
        self.assertEqual(self.api(trip, '/signals?limit=101', self.a)[0], 400)
        self.assertEqual(self.api(trip, '/signals?limit=1&limit=2', self.a)[0], 400)
        self.assertEqual(self.api(trip, '/signals?cursor=-1', self.a)[0], 400)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('DELETE FROM team_trip_signal_contexts WHERE trip_id=%s', (trip,))
        self.assertEqual(self.signals(trip), [])
        self.assertEqual(self.vote(trip, next(iter(identifiers)), self.b)[0], 404)

    def test_native_workspace_omits_settings_for_unapproved_purposes(self):
        from team_trip_routes import TeamTripRoutes
        trip = self.active(self.b)
        routes = TeamTripRoutes(self.h.module.TEAM_AUTH)
        with psycopg.connect(self.dsn) as conn:
            value = routes.workspace(conn, trip, self.a['user']['id'], native=True, purposes=frozenset({'rooms:read'}))
        self.assertEqual(set(value['mySharing']), {'status', 'location'})
        self.assertEqual(value['features']['reports'], dict(available=True, consentRequired=False))
        for feature in ('music', 'voice', 'missions', 'drivingData', 'results'):
            self.assertEqual(value['features'][feature], dict(available=False, consentRequired=True))

    def test_trip_state_and_context_are_encrypted(self):
        trip = self.active(self.b)
        signal = self.signal(trip)
        self.vote(trip, signal, self.b)
        service = self.h.module.TEAM_AUTH.trip_signal_contexts
        with psycopg.connect(self.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_trip_signal_contexts WHERE trip_id=%s AND signal_id=%s', (trip, signal)).fetchone()[0]
            value = service.restore(trip, signal, raw)
        self.assertNotIn(self.b['user']['id'].encode(), bytes(raw))
        self.assertIn(self.b['user']['id'], value['roster'])
        self.assertEqual(value['votes'][self.b['user']['id']]['revision'], value['tripRevision'])
        self.assertEqual(value['votes'][self.b['user']['id']]['joinedAt'], value['roster'][self.b['user']['id']]['joinedAt'])
