"""Scoped phone trip adapters over HTTP with disposable PostgreSQL accounts."""
from concurrent.futures import ThreadPoolExecutor
import threading
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import psycopg
import test_iphone_session as fixture


class IPhoneTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(fixture.IphoneSessionTests.doClassCleanups)
        fixture.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.phone = fixture.IphoneSessionTests()
        self.phone.setUp()
        self.alice = self.phone.login()
        self.bob = self.phone.login(who='bob')
        self.eve = self.phone.login(who='eve')
        self.a, self.b, self.e = [value['user']['id'] for value in (self.alice, self.bob, self.eve)]

    def call(self, suffix='', data=None, method='GET', *, session=None, **kwargs):
        return self.phone.iphone('/v1/iphone/trips' + suffix, data, method,
                                 token=(session or self.alice)['accessToken'], **kwargs)

    def checked(self, response, status=200):
        self.assertEqual(response[0], status, response[2])
        return response[2]

    def befriend(self, target):
        self.checked(self.phone.iphone('/v1/iphone/friends/requests', dict(targetId=target['user']['id']),
            'POST', token=self.alice['accessToken']), 201)
        self.checked(self.phone.iphone('/v1/iphone/friends/requests/' + self.a + '/respond', dict(accept=True),
            'POST', token=target['accessToken']))

    def create(self, members=()):
        return self.checked(self.call(data=dict(title='여행 준비', description='함께 출발',
            memberIds=[member['user']['id'] for member in members], startDate='2026-11-13', endDate=None),
            method='POST'), 201)['id']

    def detail(self, trip, **kwargs):
        return self.checked(self.call('/' + trip, **kwargs))

    def join(self, trip, member):
        self.checked(self.call('/' + trip + '/members', dict(accountId=member['user']['id']), 'POST'), 201)
        self.checked(self.call('/' + trip + '/respond', dict(accept=True), 'POST', session=member))

    def vehicle(self):
        web = self.phone.api.login()
        _, _, credential = self.phone.api.pair(web)
        self.checked(self.phone.iphone('/v1/iphone/vehicles/' + credential['deviceId'] + '/profile',
            dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT', token=self.alice['accessToken']))
        return credential

    def test_create_invite_respond_members_and_same_web_trip(self):
        self.checked(self.call())
        self.assertEqual(self.call()[2], dict(trips=[], invitations=[]))
        self.befriend(self.bob)
        trip = self.create((self.bob,))
        listing = self.checked(self.call())
        self.assertEqual(listing['trips'][0]['id'], trip)
        self.assertEqual(listing['trips'][0]['startDate'], '2026-11-13')
        self.assertEqual(listing['trips'][0]['memberCount'], 1)
        invitations = self.checked(self.call(session=self.bob))['invitations']
        self.assertEqual(invitations, [dict(tripId=trip, title='여행 준비', ownerName='alice')])
        self.assertEqual(self.call('/' + trip, session=self.bob)[0], 404)
        self.checked(self.call('/' + trip + '/respond', dict(accept=True, locationConsent=False), 'POST', session=self.bob))
        detail = self.detail(trip)
        self.assertEqual({member['id'] for member in detail['members']}, {self.a, self.b})
        self.assertEqual({member['id'] for member in detail['unassigned']}, {self.a, self.b})
        self.assertTrue(detail['myPermissions']['invite'])
        self.assertFalse(detail['locationConsent'])
        self.assertEqual(self.phone.header(self.call('/' + trip)[1], 'cache-control'), 'private, no-store')
        web = self.phone.api.login()
        web_detail = self.checked(self.phone.api.call('/v1/social/trips/' + trip, session=web))
        self.assertEqual(web_detail, detail)
        with psycopg.connect(self.phone.api.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()[0]
            self.assertNotIn('함께 출발'.encode(), bytes(raw))
        self.assertEqual(self.call('/' + trip + '/members', dict(accountId=self.e), 'POST', session=self.bob)[0], 403)
        self.assertEqual(self.call('/' + trip, session=self.eve)[0], 404)

    def test_cancelled_pending_invitation_rejects_stale_accept_and_disappears_from_list(self):
        self.befriend(self.bob)
        trip = self.create((self.bob,))
        pending = self.checked(self.call(session=self.bob))['invitations']
        self.assertEqual([row['tripId'] for row in pending], [trip])
        revision = self.detail(trip)['revision']
        cancelled = self.checked(self.call('/' + trip + '/cancel', dict(revision=revision), 'POST'))
        self.assertEqual(cancelled['state'], 'cancelled')
        response = self.call('/' + trip + '/respond', dict(accept=True, locationConsent=False),
                             'POST', session=self.bob)
        self.assertEqual((response[0], response[2]), (409, dict(detail='TRIP_STATE_CONFLICT')))
        self.assertEqual(self.checked(self.call(session=self.bob))['invitations'], [])

    def test_maximum_unicode_trip_payload_and_nineteen_invitees_fit_domain_limit(self):
        original_members = self.phone.api.members_rows
        names = [f'guest{index:02d}' for index in range(17)]
        self.phone.api.write_members(original_members + [dict(email=name + '@example.invalid', name=name,
            role='viewer') for name in names])
        self.addCleanup(self.phone.api.write_members, original_members)
        friends = [self.bob, self.eve] + [self.phone.login(who=name) for name in names]
        for friend in friends:
            self.befriend(friend)
        payload = dict(title='여' * 40, description='🚗' * 300,
                       memberIds=[friend['user']['id'] for friend in friends])
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.assertGreater(len(raw), 2048)
        self.assertLess(len(raw), 4096)
        trip = self.checked(self.call(method='POST', raw=raw), 201)['id']
        detail = self.detail(trip)
        self.assertEqual(detail['title'], payload['title'])
        self.assertEqual(detail['description'], payload['description'])
        self.assertEqual(len(detail['members']), 20)
        self.checked(self.call(method='POST', raw=raw + b' ' * (4096 - len(raw))), 201)
        self.assertEqual(self.call(method='POST', raw=raw + b' ' * (4097 - len(raw)))[0], 413)
        self.assertEqual(len(self.checked(self.call())['trips']), 2)
        self.assertEqual(self.phone.iphone(fixture.LOGIN + '/requests', method='POST', raw=b'x' * 2049)[0], 413)

    def test_invite_candidates_respect_rights_and_blocks_and_decline(self):
        self.befriend(self.bob)
        self.befriend(self.eve)
        trip = self.create()
        candidates = self.checked(self.call('/' + trip + '/friends'))['friends']
        self.assertEqual({p['id'] for p in candidates}, {self.b, self.e})
        self.assertTrue(all(p['tripState'] == 'none' for p in candidates))
        self.checked(self.call('/' + trip + '/members', dict(accountId=self.b), 'POST'), 201)
        self.checked(self.call('/' + trip + '/respond', dict(accept=False), 'POST', session=self.bob))
        self.assertEqual(self.checked(self.call(session=self.bob)), dict(trips=[], invitations=[]))
        self.join(trip, self.bob)
        self.assertEqual(self.call('/' + trip + '/friends', session=self.bob)[0], 403)
        self.checked(self.phone.iphone('/v1/iphone/blocks', dict(targetId=self.e), 'POST', token=self.alice['accessToken']), 201)
        self.assertEqual([p['id'] for p in self.checked(self.call('/' + trip + '/friends'))['friends']], [self.b])
        self.assertEqual(self.call('/' + trip + '/members', dict(accountId=self.e), 'POST')[0], 404)

    def test_vehicle_group_capacity_driver_limit_and_ride_leave(self):
        self.befriend(self.bob)
        self.befriend(self.eve)
        trip = self.create()
        self.join(trip, self.bob)
        self.join(trip, self.eve)
        path = '/' + trip
        self.assertEqual(self.call(path + '/cars', dict(name='우리 차', seats=1), 'POST')[0], 409)
        self.vehicle()
        car = self.checked(self.call(path + '/cars', dict(name='우리 차', seats=1), 'POST'), 201)['id']
        self.assertEqual(self.call(path + '/cars', dict(name='두 번째 차', seats=1), 'POST')[0], 409)
        ride = path + '/cars/' + car + '/ride'
        self.assertEqual(self.call(ride, {}, 'PUT')[0], 409)
        self.checked(self.call(ride, {}, 'PUT', session=self.bob))
        self.assertEqual(self.call(ride, {}, 'PUT', session=self.eve)[0], 409)
        detail = self.detail(trip)
        self.assertEqual(detail['cars'][0]['seats'], 1)
        self.assertEqual(detail['cars'][0]['driverName'], 'alice')
        self.assertEqual([p['id'] for p in detail['cars'][0]['passengers']], [self.b])
        self.checked(self.call(path + '/ride', {}, 'DELETE', session=self.bob))
        self.checked(self.call(ride, {}, 'PUT', session=self.eve))
        self.assertTrue(self.detail(trip, session=self.eve)['cars'][0]['iRide'])
        for body in (dict(name='잘못된 차', seats=0), dict(name='잘못된 차', seats=True),
                     dict(name='잘못된 차', seats=9), dict(name='우리 차', seats=1, deviceId='a' * 32)):
            self.assertEqual(self.call(path + '/cars', body, 'POST')[0], 400)

    def test_location_courses_start_and_revision_and_owner_checks(self):
        self.befriend(self.bob)
        trip = self.create()
        self.join(trip, self.bob)
        path = '/' + trip
        self.assertFalse(self.checked(self.call(path + '/location-sharing'))['locationConsent'])
        self.assertTrue(self.checked(self.call(path + '/location-sharing', dict(locationConsent=True), 'PATCH'))['locationConsent'])
        self.assertFalse(self.checked(self.call(path + '/location-sharing', dict(locationConsent=False), 'PATCH'))['locationConsent'])
        pack = self.phone.api.pack()
        web = self.phone.api.login()
        self.checked(self.phone.api.publish(pack, web), 201)
        self.checked(self.call(path + '/courses', dict(packId=pack['id']), 'POST'), 201)
        self.assertEqual(self.detail(trip)['courses'][0]['packId'], pack['id'])
        revision = self.detail(trip)['revision']
        self.assertEqual(self.call(path + '/start', dict(revision=revision), 'POST', session=self.bob)[0], 403)
        self.assertEqual(self.call(path + '/start', dict(revision=revision - 1), 'POST')[0], 409)
        self.checked(self.call(path + '/start', dict(revision=revision), 'POST'))
        self.assertEqual(self.detail(trip)['state'], 'active')

    def test_scope_host_query_cookie_origin_and_strict_body_boundaries(self):
        trip = self.create()
        path = '/' + trip
        web = self.phone.api.login()
        self.assertEqual(self.phone.api.call('/v1/iphone/trips', session=web, bearer=self.alice['accessToken'])[0], 404)
        self.assertEqual(self.phone.api.native('/v1/iphone/trips', token=self.alice['accessToken'])[0], 404)
        self.assertEqual(self.phone.api.call('/v1/iphone/trips', who=None, host=fixture.IPHONE,
            bearer=self.alice['accessToken'], origin='https://other.invalid')[0], 400)
        self.assertEqual(self.phone.iphone('/v1/iphone/trips',
            token=self.alice['accessToken'], session=web)[0], 400)
        for suffix in ('?owner=' + self.e, path + '?section=route', path + '/friends?limit=1'):
            self.assertEqual(self.call(suffix)[0], 400)
        self.assertEqual(self.call(path + '/cars', raw=b'{"name":"car","seats":1,"seats":2}', method='POST')[0], 400)
        self.assertEqual(self.call(path + '/cars', raw=b'x' * 4097, method='POST')[0], 413)
        for scopes in (['account:read'], ['trips:read']):
            with psycopg.connect(self.phone.api.dsn) as conn:
                conn.execute('UPDATE iphone_sessions SET scopes=%s WHERE account_id=%s', (scopes, self.a))
            self.assertEqual(self.call()[0], 200 if 'trips:read' in scopes else 403)
            self.assertEqual(self.call(data=dict(title='거절', description='', memberIds=[]), method='POST')[0], 403)
            self.assertEqual(self.call(path + '/start', dict(revision=1), 'POST')[0], 403)

    def test_revoked_session_between_actor_and_transaction_never_writes(self):
        trip = self.create()
        service = self.phone.api.module.TEAM_AUTH.iphone_sessions
        original = service.authenticate
        def revoked(request, scope, **options):
            if options.get('lock'):
                with psycopg.connect(self.phone.api.dsn) as conn:
                    conn.execute('UPDATE iphone_sessions SET revoked_at=0 WHERE account_id=%s', (self.a,))
            return original(request, scope, **options)
        revision = self.detail(trip)['revision']
        for suffix, data, method in (
                ('', dict(title='없어야 함', description='', memberIds=[]), 'POST'),
                ('/' + trip + '/location-sharing', dict(locationConsent=True), 'PATCH'),
                ('/' + trip + '/start', dict(revision=revision), 'POST')):
            self.alice = self.phone.login()
            with patch.object(service, 'authenticate', side_effect=revoked):
                self.assertEqual(self.call(suffix, data, method)[0], 401)
        self.alice = self.phone.login()
        self.assertEqual(len(self.checked(self.call())['trips']), 1)
        self.assertFalse(self.detail(trip)['locationConsent'])
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET revoked_at=0 WHERE account_id=%s', (self.a,))
        self.assertEqual(self.call()[0], 401)
        self.assertEqual(self.call('/' + trip)[0], 401)

    def test_pickup_drop_places_keep_membership_visibility_and_encrypted_storage(self):
        self.befriend(self.bob)
        self.befriend(self.eve)
        trip = self.create()
        self.join(trip, self.bob)
        self.join(trip, self.eve)
        self.vehicle()
        car = self.checked(self.call('/' + trip + '/cars', dict(name='우리 차', seats=2), 'POST'), 201)['id']
        base = '/' + trip + '/cars/' + car
        self.checked(self.call(base + '/ride', {}, 'PUT', session=self.bob))
        pickup = dict(kind='pickup', name='검색해 선택한 픽업', lat=37.5, lng=127.0)
        place = self.checked(self.call(base + '/places', pickup, 'POST', session=self.bob), 201)['id']
        full = self.checked(self.call(base + '/places', session=self.bob))['places']
        self.assertEqual(full[0]['id'], place)
        self.assertEqual(full[0]['addedBy'], self.b)
        self.assertEqual({key: full[0][key] for key in pickup}, pickup)
        self.assertEqual(self.checked(self.call(base + '/places', session=self.eve))['places'],
                         [dict(name=pickup['name'], selectedBy=0)])
        self.assertEqual(self.call(base + '/places', pickup, 'POST', session=self.eve)[0], 403)
        self.assertEqual(self.call(base + '/places/' + place, {}, 'DELETE', session=self.eve)[0], 403)
        with psycopg.connect(self.phone.api.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_trip_car_places WHERE trip_id=%s AND place_id=%s',
                               (trip, place)).fetchone()[0]
            self.assertNotIn(pickup['name'].encode(), bytes(raw))
        self.checked(self.call(base + '/places/' + place, {}, 'DELETE'))
        drop = dict(kind='drop', name='검색해 선택한 드랍', lat=37.6, lng=127.1)
        place = self.checked(self.call(base + '/places', drop, 'POST', session=self.bob), 201)['id']
        self.checked(self.call(base + '/places/' + place, {}, 'DELETE', session=self.bob))
        self.assertEqual(self.checked(self.call(base + '/places'))['places'], [])

    def test_place_scope_foreign_trip_and_coordinate_validation(self):
        trip = self.create()
        self.vehicle()
        car = self.checked(self.call('/' + trip + '/cars', dict(name='우리 차', seats=2), 'POST'), 201)['id']
        base = '/' + trip + '/cars/' + car + '/places'
        value = dict(kind='pickup', name='검색 위치', lat=37.5, lng=127.0)
        for invalid in (dict(value, kind='other'), dict(value, lat=True), dict(value, lat=91),
                        dict(value, lng=-181), dict(value, lat=10**400), dict(value, owner=self.a)):
            self.assertEqual(self.call(base, invalid, 'POST')[0], 400)
        self.assertEqual(self.call(base, session=self.eve)[0], 404)
        other = self.create()
        self.assertEqual(self.call('/' + other + '/cars/' + car + '/places')[0], 404)
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s WHERE account_id=%s', (['trips:read'], self.a))
        self.assertEqual(self.call(base)[0], 200)
        self.assertEqual(self.call(base, value, 'POST')[0], 403)
        self.assertEqual(self.call(base + '/' + 'a' * 32, {}, 'DELETE')[0], 403)

    def test_legacy_v1_v2_v3_approvals_and_existing_sessions_keep_disclosed_scopes(self):
        from iphone_sessions import CONSENT_VERSIONS
        for version in ('v1', 'v2', 'v3'):
            with self.subTest(version=version):
                request, verifier, state = self.phone.start()
                secret = self.phone.api.module.TEAM_AUTH.secret
                message = f"wegoh-iphone-login-{version}:{request['requestId']}:{self.a}".encode('ascii')
                fields = dict(request_id=request['requestId'], csrf=hmac.new(secret, message, hashlib.sha256).hexdigest())
                status, headers, _ = self.phone.submit(fields, 'approve')
                self.assertEqual(status, 303)
                callback = parse_qs(urlsplit(self.phone.header(headers, 'location')).query, strict_parsing=True)
                self.assertEqual(callback['state'], [state])
                legacy = self.checked(self.phone.exchange(request, verifier, callback['code'][0]))
                self.assertEqual(tuple(legacy['scopes']), CONSENT_VERSIONS[version][1])
                self.assertEqual(self.call(session=legacy)[0], 403)
                restored = self.checked(self.phone.iphone('/v1/iphone/session', token=legacy['accessToken']))
                self.assertEqual(restored['scopes'], legacy['scopes'])
        self.assertTrue({'trips:read', 'trips:manage'} <= set(self.phone.login()['scopes']))

    def test_role_alias_keeps_owner_revision_and_scope_checks(self):
        self.befriend(self.bob)
        trip = self.create((self.bob,))
        self.checked(self.call('/' + trip + '/respond', dict(accept=True), 'POST', session=self.bob))
        initial = self.detail(trip)
        self.assertTrue(all(member['role'] == 'member' for member in initial['members']))
        path = '/' + trip + '/members/' + self.b + '/role'
        body = dict(role='food', revision=initial['revision'])
        self.assertEqual(self.call(path, body, 'PUT', session=self.bob)[0], 403)
        changed = self.checked(self.call(path, body, 'PUT'))
        detail = self.detail(trip)
        self.assertEqual(next(m['role'] for m in detail['members'] if m['id'] == self.b), 'food')
        self.assertGreater(changed['revision'], initial['revision'])
        self.assertEqual(self.call(path, body, 'PUT')[0], 409)
        self.assertEqual(detail['myPermissions'], initial['myPermissions'])
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s WHERE account_id=%s', (['trips:read'], self.a))
        self.assertEqual(self.call(path, dict(role='rest', revision=detail['revision']), 'PUT')[0], 403)

    def test_phone_and_native_same_car_race_records_one_response_and_inserts_one_stop(self):
        self.befriend(self.bob)
        self.befriend(self.eve)
        trip = self.create()
        self.join(trip, self.bob)
        self.join(trip, self.eve)
        self.vehicle()
        first = self.checked(self.call('/' + trip + '/cars', dict(name='사용자A의 차', seats=2), 'POST'), 201)['id']
        web = self.phone.api.login('bob')
        _, _, credential = self.phone.api.pair(web, who='bob')
        self.checked(self.phone.iphone('/v1/iphone/vehicles/' + credential['deviceId'] + '/profile',
            dict(plateNumber='234나5678', name='', expectedRevision=0), 'PUT', token=self.bob['accessToken']))
        second = self.checked(self.call('/' + trip + '/cars', dict(name='사용자B의 차', seats=2), 'POST', session=self.bob), 201)['id']
        self.checked(self.call('/' + trip + '/cars/' + second + '/ride', {}, 'PUT', session=self.eve))
        self.checked(self.call('/' + trip + '/start', dict(revision=self.detail(trip)['revision']), 'POST'))
        destination = dict(name='서산휴게소', latitude=36.7, longitude=126.6)
        created = self.checked(self.call('/' + trip + '/signals', dict(kind='cafe', destination=destination), 'POST'), 201)
        path = '/' + trip + '/signals/' + created['id'] + '/vote'
        permissions = self.checked(self.phone.api.native('/v1/device/functional-permissions', token=credential['accessToken']))
        ready = threading.Barrier(2)
        def vote(phone):
            ready.wait(timeout=5)
            if phone:
                return self.call(path, dict(choice='agree'), 'POST', session=self.eve)
            return self.phone.api.native('/v1/social/trips' + path,
                dict(choice='agree', functionalRevision=permissions['revision']), 'POST', token=credential['accessToken'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(vote, (True, False)))
        self.assertEqual([row[0] for row in results], [200, 200], results)
        self.assertEqual(sum(row[2].get('already', False) for row in results), 1)
        signals = self.checked(self.call('/' + trip + '/signals'))['signals']
        group = signals[0]['groupResponses'][0]
        self.assertIn(group['responderAccountId'], (self.b, self.e))
        self.assertEqual(group['choice'], 'agree')
        self.assertEqual(signals[0]['groupVotes'], dict(agree=1, **{'pass':0}, total=1))
        with psycopg.connect(self.phone.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_votes WHERE signal_id=%s', (created['id'],)).fetchone()[0], 1)
        for car in self.detail(trip)['cars']:
            self.assertEqual(car['routeOrder'], [dict(type='signal', ref=created['id'])])
        self.checked(self.call('/' + trip + '/ride', {}, 'DELETE', session=self.eve))
        self.assertNotEqual(self.call(path, dict(choice='agree'), 'POST', session=self.eve)[0], 200)

    def test_candidate_alias_checks_maps_scope_and_facilities_before_provider(self):
        trip = self.create()
        self.checked(self.call('/' + trip + '/start', dict(revision=self.detail(trip)['revision']), 'POST'))
        body = dict(kind='fuel', location=dict(lat=36.7, lng=126.6, heading=180), requiredFacilities=['toilet','gasStation'])
        path = '/' + trip + '/signals/candidates'
        for required in (['unknown'], ['toilet','toilet'], None):
            self.assertEqual(self.call(path, dict(body, requiredFacilities=required), 'POST')[0], 400)
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s WHERE account_id=%s', (['trips:read'], self.a))
        self.assertEqual(self.call(path, body, 'POST')[0], 403)
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s WHERE account_id=%s', (['trips:read','maps:read'], self.a))
        from team_trip_hand_raise import HandRaiseCandidates
        from test_trip_hand_raise import FakeKakao
        with patch.object(self.phone.api.module.TEAM_AUTH, 'hand_raise_service', HandRaiseCandidates(FakeKakao().provider())):
            self.assertEqual(self.call(path, body, 'POST')[0], 200)
