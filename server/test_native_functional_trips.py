"""차량 여행의 허용 경로·기능 권한·멤버 경계와 웹 응답 유지."""
import json
import socket
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import psycopg
from websockets.sync.client import connect
from native_functional_policy import PURPOSES, WIRE, FunctionalError, authorize, is_functional_route
from team_trips import TeamTrips
from private_records import VisitCipher
from api_doc_trip_plan import NATIVE as PLAN_NATIVE
import test_native_functional_business as business_fixture


ALLOWED = {
    ('GET', '/v1/social/trips/{trip}/voice-clips'): ['rooms:read'],
    ('POST', '/v1/social/trips/{trip}/voice-clips'): ['rooms:read', 'rooms:interact'],
    ('GET', '/v1/social/trips/{trip}/voice-clips/{identifier}'): ['rooms:read'],
    ('GET', '/v1/social/trips/{room}/voice/filters'): ['rooms:read'],
    ('GET', '/v1/social/trips'): ['rooms:read'],
    ('GET', '/v1/social/trips/{id}'): ['rooms:read'],
    ('POST', '/v1/social/trips/{id}/respond'): ['rooms:read', 'rooms:interact'],
    ('GET', '/v1/social/trips/{id}/workspace'): ['rooms:read'],
    ('GET', '/v1/social/trips/{id}/signals'): ['rooms:read'],
    ('POST', '/v1/social/trips/{id}/signals'): ['rooms:read', 'rooms:interact'],
    ('POST', '/v1/social/trips/{id}/signals/{signal}/vote'): ['rooms:read', 'rooms:interact'],
    ('POST', '/v1/social/trips/{id}/signals/{signal}/finish'): ['rooms:read', 'rooms:interact'],
    ('DELETE', '/v1/social/trips/{id}/signals/{signal}/vote'): ['rooms:read', 'rooms:interact'],
    ('GET', '/v1/social/trips/{id}/places'): ['rooms:read'],
    ('GET', '/v1/social/trips/{trip}/music/saved-playlists'): ['rooms:read'],
    ('POST', '/v1/social/trips/{trip}/music/saved-playlists'): ['rooms:read', 'rooms:interact'],
    ('PATCH', '/v1/social/trips/{trip}/music/saved-playlists/{item}/position'): ['rooms:read', 'rooms:interact'],
    ('PUT', '/v1/social/trips/{trip}/music/now-playing'): ['rooms:read', 'rooms:interact'],
}


class NativeTripPolicyTests(unittest.TestCase):
    def test_route_progress_requires_both_existing_purposes_and_exact_native_route(self):
        path = '/v1/native/trips/' + 'a' * 32 + '/cars/' + 'b' * 32 + '/route-progress'
        purposes = frozenset(('rooms:read', 'rooms:interact'))
        self.assertTrue(authorize('PUT', path, purposes))
        for missing in purposes:
            with self.subTest(missing=missing), self.assertRaises(FunctionalError) as error:
                authorize('PUT', path, purposes - {missing})
            self.assertEqual((error.exception.status, error.exception.code), (403, 'FUNCTIONAL_PURPOSE_REQUIRED'))
        for method in ('GET', 'POST', 'PATCH', 'DELETE'):
            self.assertFalse(is_functional_route(method, path))
        for invalid in (path + '/extra', path.replace('b' * 32, 'b' * 31), path.replace('/native/', '/social/')):
            self.assertFalse(is_functional_route('PUT', invalid))

    def test_exact_trip_routes_and_existing_purposes(self):
        routes = [row for row in WIRE['nativeRoutes'] if row['path'].startswith('/v1/social/trip')]
        self.assertEqual({(row['method'], row['path']): row['all'] for row in routes}, ALLOWED)
        self.assertEqual(len(routes), len(ALLOWED))
        self.assertTrue(all(row['any'] == [] for row in routes))
        for (method, template), purposes in ALLOWED.items():
            path = template.format(id='a' * 32, trip='a' * 32, signal='b' * 32, identifier='c'*32, room='d'*32, item='e'*32)
            self.assertTrue(authorize(method, path, frozenset(purposes)))
            for missing in purposes:
                with self.subTest(path=path, missing=missing), self.assertRaises(FunctionalError) as error:
                    authorize(method, path, frozenset(purposes) - {missing})
                self.assertEqual((error.exception.status, error.exception.code), (403, 'FUNCTIONAL_PURPOSE_REQUIRED'))
        for suffix in ('a' * 31, 'A' * 32, 'a' * 33, 'a' * 32 + '/link', 'a' * 32 + '/respond/extra'):
            for method in ('GET', 'POST'):
                self.assertFalse(is_functional_route(method, '/v1/social/trips/' + suffix))


class NativeTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        business_fixture.FunctionalBusinessTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        business_fixture.FunctionalBusinessTests.tearDownClass()

    def setUp(self):
        self.factory = business_fixture.FunctionalBusinessTests()
        self.factory.setUp()
        self.h = self.factory.h
        self.owner, self.guest = self.h.login(), self.h.login('bob')
        self.browser(self.owner, '/v1/social/friends/requests', dict(targetId=self.guest['user']['id']), 'POST', 201)
        self.browser(self.guest, '/v1/social/friends/requests/' + self.owner['user']['id'] + '/respond', dict(accept=True), 'POST')
        self.trip = self.browser(self.owner, '/v1/social/trips',
            dict(title='함께 여행', description='여행 설명', memberIds=[self.guest['user']['id']]), 'POST', 201)['id']
        self.path = '/v1/social/trips/' + self.trip
        self.device = self.factory.connect(self.guest, 'bob')

    def browser(self, session, path, body=None, method='GET', expected=200):
        result = self.h.call(path, body, method, session=session, who=session['user']['displayName'])
        self.assertEqual(result[0], expected, result[2])
        return result[2]

    def approve(self, purposes):
        return self.factory.approve(self.guest, self.device, purposes, 'bob')

    def native(self, path, body=None, method='GET', expected=200, device=None):
        result = self.factory.native(device or self.device, path, body, method)
        self.assertEqual(result[0], expected, result[2])
        if expected == 200:
            self.assertEqual(result[1]['cache-control'], 'private, no-store')
        return result[2]

    @contextmanager
    def events(self, device=None):
        device = device or self.device
        raw = socket.create_connection(('127.0.0.1', self.h.port), timeout=5)
        with connect('ws://api.wegoh.invalid/v1/events', sock=raw, origin=None,
                open_timeout=3, close_timeout=1, additional_headers={
                    'Authorization': 'Bearer ' + device['accessToken'],
                    'cf-cert-sha256': self.factory.certificates[device['grantId']],
                    'cf-cert-presented': 'true', 'cf-cert-verified': 'true', 'cf-cert-revoked': 'false'}) as channel:
            first = json.loads(channel.recv(timeout=3))
            self.assertEqual(first['type'], 'snapshot')
            self.assertEqual(first['resources'], ['courses', 'devices', 'playlists'])
            self.assertEqual(first['seq'], 0)
            yield channel, first['epoch']

    def invalidated(self, channel, epoch, seq):
        self.assertEqual(json.loads(channel.recv(timeout=4)),
            dict(type='invalidate', epoch=epoch, seq=seq, resources=['devices']))

    def quiet(self, channel):
        with self.assertRaises(TimeoutError):
            channel.recv(timeout=1.5)

    def change_revision(self, *, trip=False):
        owner = self.guest['user']['id']
        with psycopg.connect(self.h.dsn) as conn:
            row = conn.execute('SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource=%s',
                ('trip-account:' + owner if trip else owner, 'rooms' if trip else 'friends')).fetchone()
        return row[0] if row else 0

    def test_rooms_read_events_cover_invitation_member_car_and_ride_changes(self):
        self.approve(['rooms:read'])
        driver = self.factory.connect(self.owner)
        self.browser(self.owner, '/v1/devices/' + driver['deviceId'] + '/vehicle-profile',
            dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT')
        with self.events() as (channel, epoch):
            other = self.browser(self.owner, '/v1/social/trips',
                dict(title='새 초대', description='', memberIds=[self.guest['user']['id']]), 'POST', 201)['id']
            self.invalidated(channel, epoch, 1)
            self.assertIn(other, [row['tripId'] for row in self.native('/v1/social/trips')['invitations']])
            self.browser(self.guest, self.path + '/respond', dict(accept=True), 'POST')
            self.invalidated(channel, epoch, 2)
            car = self.browser(self.owner, self.path + '/cars', dict(name='함께 타는 차', seats=2), 'POST', 201)['id']
            self.invalidated(channel, epoch, 3)
            self.assertEqual(self.native(self.path)['cars'][0]['id'], car)
            self.browser(self.guest, self.path + '/cars/' + car + '/ride', {}, 'PUT')
            self.invalidated(channel, epoch, 4)
            self.assertTrue(self.native(self.path)['cars'][0]['iRide'])
            self.browser(self.owner, self.path + '/cars/' + car, dict(name='큰 차', seats=3), 'PATCH')
            self.invalidated(channel, epoch, 5)
            self.assertEqual(self.native(self.path)['cars'][0]['seats'], 3)
            self.browser(self.guest, self.path + '/ride', {}, 'DELETE')
            self.invalidated(channel, epoch, 6)
            self.assertFalse(self.native(self.path)['cars'][0]['iRide'])
            self.browser(self.owner, self.path + '/members/' + self.guest['user']['id'], {}, 'DELETE')
            self.invalidated(channel, epoch, 7)
            self.native(self.path, expected=404)

    def test_trip_events_follow_account_membership_with_personal_controls_off(self):
        for purposes in ([], ['rooms:interact']):
            with self.subTest(purposes=purposes):
                self.approve(purposes)
                before = self.change_revision(trip=True)
                with self.events() as (channel, epoch):
                    self.browser(self.owner, self.path, dict(title='여행 수정', description='새 설명'), 'PATCH')
                    self.assertGreater(self.change_revision(trip=True), before)
                    self.invalidated(channel, epoch, 1)
        self.approve(['rooms:read'])
        outsider = self.h.login('eve')
        unrelated = self.factory.connect(outsider, 'eve')
        self.factory.approve(outsider, unrelated, ['rooms:read'], 'eve')
        with self.events() as (channel, epoch), self.events(unrelated) as (other, _):
            self.browser(self.owner, self.path, dict(title='내 여행 변경', description=''), 'PATCH')
            self.invalidated(channel, epoch, 1)
            self.quiet(other)
            self.browser(self.owner, self.path, {}, 'DELETE', expected=409)
            self.quiet(channel)
            self.quiet(other)
            with psycopg.connect(self.h.dsn) as conn:
                revision = conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s', (self.trip,)).fetchone()[0]
                self.h.module.TEAM_TRIPS.transition(conn, self.trip, self.owner['user']['id'], 'cancel', revision)
            self.invalidated(channel, epoch, 2)
            self.quiet(other)
            self.browser(self.owner, self.path, {}, 'DELETE')
            self.invalidated(channel, epoch, 3)
            self.quiet(other)
            self.assertEqual(self.native('/v1/social/trips'), dict(trips=[], invitations=[]))

    def test_friend_changes_update_account_events_without_touching_trip_revision(self):
        self.approve(['rooms:read'])
        self.browser(self.guest, self.path + '/respond', dict(accept=True), 'POST')
        outsider = self.h.login('eve')
        owner_id, guest_id = self.owner['user']['id'], self.guest['user']['id']
        before = self.change_revision(trip=True)
        with psycopg.connect(self.h.dsn) as conn:
            trip_revision = conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s', (self.trip,)).fetchone()[0]
        with self.events() as (channel, epoch):
            actions = (
                (self.guest, '/v1/social/friends/requests', dict(targetId=outsider['user']['id']), 'POST', 201),
                (self.guest, '/v1/social/friends/' + owner_id, None, 'DELETE', 200),
                (self.guest, '/v1/social/friends/requests', dict(targetId=owner_id), 'POST', 201),
                (self.owner, '/v1/social/friends/requests/' + guest_id + '/respond', dict(accept=True), 'POST', 200),
            )
            for seq, (session, path, body, method, status) in enumerate(actions, 1):
                with self.subTest(method=method, path=path):
                    friend_before = self.change_revision()
                    self.browser(session, path, body, method, status)
                    self.assertGreater(self.change_revision(), friend_before)
                    self.assertEqual(self.change_revision(trip=True), before)
                    with psycopg.connect(self.h.dsn) as conn:
                        self.assertEqual(conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s', (self.trip,)).fetchone()[0], trip_revision)
                    self.invalidated(channel, epoch, seq)
            self.browser(self.owner, self.path, dict(title='여행 자체 변경', description=''), 'PATCH')
            self.invalidated(channel, epoch, len(actions) + 1)

    def test_trip_events_continue_after_optional_permissions_are_withdrawn(self):
        self.approve(['room-music:read'])
        with self.events() as (channel, epoch):
            self.approve([])
            self.invalidated(channel, epoch, 1)
            self.browser(self.owner, self.path, dict(title='철회 뒤 변경', description=''), 'PATCH')
            self.invalidated(channel, epoch, 2)
            self.assertEqual(self.native('/v1/social/trips'), self.browser(self.guest, '/v1/social/trips'))

    def test_member_block_updates_shared_account_events_with_per_viewer_visibility(self):
        self.approve(['rooms:read'])
        self.browser(self.guest, self.path + '/respond', dict(accept=True), 'POST')
        outsider = self.h.login('eve')
        link = self.browser(self.owner, self.path + '/link', {}, 'POST', 201)
        self.browser(outsider, '/v1/social/trip-links/join', dict(token=link['token']), 'POST')
        owner_device = self.factory.connect(self.owner)
        self.factory.approve(self.owner, owner_device, ['rooms:read'])
        with self.events() as (channel, epoch), self.events(owner_device) as (owner_channel, owner_epoch):
            self.browser(self.guest, '/v1/social/blocks', dict(targetId=outsider['user']['id']), 'POST', 201)
            self.invalidated(channel, epoch, 1)
            self.invalidated(owner_channel, owner_epoch, 1)
            self.assertNotIn(outsider['user']['id'], [member['id'] for member in self.native(self.path)['members']])
            self.assertIn(outsider['user']['id'], [member['id'] for member in self.native(self.path, device=owner_device)['members']])

    def test_reads_match_browser_and_show_link_metadata_only_for_owner_and_inviter(self):
        self.approve(['rooms:read'])
        self.assertEqual(self.native('/v1/social/trips'), self.browser(self.guest, '/v1/social/trips'))
        self.native(self.path, expected=404)
        self.browser(self.guest, self.path + '/respond', dict(accept=True), 'POST')
        self.browser(self.owner, self.path + '/members/' + self.guest['user']['id'] + '/permissions',
            dict(invite=True, edit=True), 'PUT')
        link = self.browser(self.owner, self.path + '/link', {}, 'POST', 201)
        owner_device = self.factory.connect(self.owner)
        self.factory.approve(self.owner, owner_device, ['rooms:read'])
        for session, device in ((self.owner, owner_device), (self.guest, self.device)):
            with self.subTest(account=session['user']['id']):
                web = self.browser(session, self.path)
                self.assertTrue(web['link']['active'])
                vehicle = self.native(self.path, device=device)
                self.assertEqual(vehicle, web)
                native = self.native('/v1/native/trips/' + self.trip, device=device)
                display = native.pop('display')
                self.assertEqual(native, web)
                self.assertEqual(set(display), {'serverNow', 'validUntil', 'endedAt', 'timeline', 'visitCount', 'metrics', 'music', 'companions'})
                lifetime = (datetime.fromisoformat(display['validUntil']) - datetime.fromisoformat(display['serverNow'])).total_seconds()
                self.assertGreaterEqual(lifetime, 0)
                self.assertLessEqual(lifetime, 10)
                self.assertEqual(display['timeline'], [])
                self.assertEqual(display['companions'], [])
                for field in ('endedAt', 'visitCount', 'metrics', 'music'):
                    self.assertIsNone(display[field])
                self.assertNotIn(link['token'], json.dumps(native))
                self.assertEqual(set(vehicle['link']), {'active', 'expiresAt'})
                self.assertNotIn(link['token'], json.dumps(vehicle))
                self.assertNotIn('token', json.dumps(vehicle))
                self.assertEqual(self.native('/v1/social/trips', device=device), self.browser(session, '/v1/social/trips'))

        self.browser(self.owner, self.path + '/members/' + self.guest['user']['id'] + '/permissions',
            dict(invite=False, edit=True), 'PUT')
        for path in (self.path, '/v1/native/trips/' + self.trip):
            self.assertIsNone(self.native(path)['link'])
        with psycopg.connect(self.h.dsn) as conn:
            conn.execute("UPDATE team_trip_links SET expires_at=clock_timestamp()-interval '1 second' WHERE trip_id=%s", (self.trip,))
        self.assertEqual(self.native('/v1/native/trips/' + self.trip, device=owner_device)['link'],
            dict(active=False, expiresAt=None))

    def test_accept_and_decline_only_my_pending_invitation(self):
        revision = self.approve(['rooms:read', 'rooms:interact'])
        self.assertEqual(self.native(self.path + '/respond', dict(accept=True, functionalRevision=revision), 'POST'),
            dict(status='accepted'))
        self.assertEqual(self.native('/v1/social/trips')['invitations'], [])
        self.native(self.path)
        self.assertFalse(self.native(self.path + '/workspace')['mySharing']['location'])
        self.native(self.path + '/respond', dict(accept=False, functionalRevision=revision), 'POST', 404)
        other = self.browser(self.owner, '/v1/social/trips',
            dict(title='다음 여행', description='', memberIds=[self.guest['user']['id']]), 'POST', 201)['id']
        self.assertEqual(self.native('/v1/social/trips/' + other + '/respond',
            dict(accept=False, functionalRevision=revision), 'POST'), dict(status='declined'))
        self.native('/v1/social/trips/' + other, expected=404)
        self.assertEqual(self.native('/v1/social/trips')['invitations'], [])
        self.assertNotIn(self.guest['user']['id'], [member['id'] for member in self.browser(self.owner, '/v1/social/trips/' + other)['members']])

    def test_native_join_location_choice_is_optional_and_retry_cannot_restore_withdrawn_sharing(self):
        revision = self.approve(['rooms:read', 'rooms:interact'])
        respond = self.path + '/respond'
        update = '/v1/native/trips/' + self.trip + '/location-sharing'
        workspace = self.path + '/workspace'
        consent = dict(locationConsent=True, functionalRevision=revision)
        self.native(update, consent, 'PATCH', 404)
        for invalid in (None, 1, 'true'):
            with self.subTest(invalid=invalid):
                self.native(respond, dict(accept=True, locationConsent=invalid, functionalRevision=revision), 'POST', 400)
        self.assertEqual([item['tripId'] for item in self.native('/v1/social/trips')['invitations']], [self.trip])

        self.native(respond, dict(accept=True, **consent), 'POST')
        self.assertTrue(self.native(workspace)['mySharing']['location'])
        receipt = self.native(update)['locationShareId']
        self.assertRegex(receipt, r'^[0-9a-f]{32}$')
        self.assertFalse(self.native(update, dict(locationConsent=False, functionalRevision=revision), 'PATCH')['locationConsent'])
        self.native(respond, dict(accept=True, **consent), 'POST')
        self.assertFalse(self.native(workspace)['mySharing']['location'])
        self.assertIsNone(self.native(update)['locationShareId'])
        resumed = self.native(update, consent, 'PATCH')
        self.assertTrue(resumed['locationConsent'])
        self.assertNotEqual(resumed['locationShareId'], receipt)

    def test_joined_trips_and_invitation_response_need_only_current_vehicle_account(self):
        self.native('/v1/device/functional-permissions')
        grant = self.device['grantId']
        legacy = dict(approvedPurposes=[], functionalDisclosureVersion=WIRE['disclosureVersion'],
                      functionalDisclosureSha256=WIRE['disclosureSha256'])
        with psycopg.connect(self.h.dsn) as conn:
            revision = conn.execute('UPDATE native_functional_authorizations SET protected=%s,revision=revision+1 '
                'WHERE grant_id=%s RETURNING revision', (VisitCipher().protect('native-functional', grant, legacy), grant)).fetchone()[0]
        self.assertEqual([item['tripId'] for item in self.native('/v1/social/trips')['invitations']], [self.trip])
        self.native(self.path, expected=404)
        self.native(self.path + '/respond', dict(accept=True, functionalRevision=revision), 'POST')
        self.assertEqual(self.native(self.path), self.browser(self.guest, self.path))


    def test_other_trip_routes_are_denied_with_all_purposes_and_iphone_routes_are_hidden(self):
        revision = self.approve(sorted(PURPOSES))
        routes = TeamTrips(self.h.module.TEAM_AUTH).router().routes
        denied = set()
        for route in routes:
            for method in route.methods:
                if (method, route.path) in ALLOWED or (method.lower(), route.path) in PLAN_NATIVE:
                    continue
                path = route.path
                for name in route.param_convertors:
                    path = path.replace('{' + name + '}', self.guest['user']['id'] if name == 'accountId' else self.trip)
                with self.subTest(method=method, path=route.path):
                    self.native(path, dict(functionalRevision=revision), method,
                        404 if path.startswith('/v1/iphone/') else 403)
                denied.add((method, route.path))
        self.assertTrue({('POST', '/v1/social/trips'), ('POST', '/v1/social/trip-links/join'),
                         ('DELETE', '/v1/social/trips/{id}')} <= denied)

        self.assertEqual(self.browser(self.owner, self.path)['title'], '함께 여행')

    def test_respond_requires_current_revision_and_closed_body(self):
        revision = self.approve(['rooms:read', 'rooms:interact'])
        path = self.path + '/respond'
        for body in (dict(accept=True), dict(accept=True, functionalRevision=True),
                dict(accept=True, functionalRevision=0), dict(accept=True, functionalRevision=revision, extra=True),
                dict(accept=1, functionalRevision=revision)):
            with self.subTest(body=body):
                self.native(path, body, 'POST', 400)
        for raw in (b'{"accept":true,"accept":false,"functionalRevision":1}', b'x' * 4097):
            result = self.h.call(path, method='POST', who=None, host='api.wegoh.invalid', origin=None,
                bearer=self.device['accessToken'], certificate=self.factory.certificates[self.device['grantId']], raw=raw)
            self.assertEqual(result[0], 413 if len(raw) > 4096 else 400, result[2])
        newer = self.approve(['room-music:read'])
        self.assertGreater(newer, revision)
        self.assertEqual(self.native(path, dict(accept=True, functionalRevision=revision), 'POST', 409),
            dict(detail='FUNCTIONAL_REVISION_CHANGED'))
        self.assertEqual(len(self.browser(self.guest, '/v1/social/trips')['invitations']), 1)
        self.native(path, dict(accept=True, functionalRevision=newer), 'POST')

    def test_membership_blocks_and_certificate_remain_required(self):
        revision = self.approve(['rooms:read', 'rooms:interact'])
        outsider = self.h.login('eve')
        other_device = self.factory.connect(outsider, 'eve')
        other_revision = self.factory.approve(outsider, other_device, ['rooms:read', 'rooms:interact'], 'eve')
        self.native(self.path, expected=404, device=other_device)
        self.native(self.path + '/respond', dict(accept=True, functionalRevision=other_revision), 'POST', 404, device=other_device)
        wrong = self.factory.native(self.device, '/v1/social/trips', certificate=self.factory.certificates[other_device['grantId']])
        self.assertEqual(wrong[0], 401, wrong[2])
        self.browser(self.owner, '/v1/social/blocks', dict(targetId=self.guest['user']['id']), 'POST', 201)
        self.assertEqual(self.native('/v1/social/trips'), dict(trips=[], invitations=[]))
        self.native(self.path, expected=404)
        self.native(self.path + '/respond', dict(accept=True, functionalRevision=revision), 'POST', 404)

    def test_disconnected_vehicle_cannot_finish_inflight_trip_response(self):
        from team_trips import request_actor
        revision = self.approve([])

        def disconnect(auth, request, *, mutate=False):
            identity = request_actor(auth, request, mutate=mutate)
            self.assertTrue(auth.native_authorization.revoke_owned_device(identity['id'], identity['deviceId']))
            return identity

        with patch('team_trips.request_actor', side_effect=disconnect) as actor:
            self.native(self.path + '/respond', dict(accept=True, functionalRevision=revision), 'POST', 401)
        actor.assert_called_once()
        self.native('/v1/social/trips', expected=401)
        self.native(self.path + '/respond', dict(accept=True, functionalRevision=revision), 'POST', 401)
        self.assertEqual(len(self.browser(self.guest, '/v1/social/trips')['invitations']), 1)


if __name__ == '__main__':
    unittest.main()
