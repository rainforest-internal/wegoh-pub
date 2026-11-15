import json
import socket
import struct
import unittest
from datetime import datetime

import psycopg
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

import test_trip_merge_music_authority as media_fixture


class TripVoiceParticipationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = media_fixture.TripMediaAuthorityIntegrationTests
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.doClassCleanups)

    def setUp(self):
        self.media = self.fixture()
        self.media.setUp()
        self.addCleanup(self.media.doCleanups)
        self.h = self.media.h
        self.path = '/v1/social/trips/' + self.media.trip + '/voice-participation'
        self.native_path = '/v1/native/trips/' + self.media.trip + '/voice-participation'

    def get(self, session=None):
        status, headers, data = self.h.call(self.path, session=session or self.media.b,
                                             who=(session or self.media.b)['user']['displayName'])
        self.assertEqual(status, 200, data)
        self.assertIn('no-store', headers['cache-control'])
        self.assertEqual(set(data), {'tripId', 'participating', 'memberJoinedAt', 'revision'})
        self.assertEqual(data['tripId'], self.media.trip)
        self.assertIsNotNone(datetime.fromisoformat(data['memberJoinedAt']).tzinfo)
        return data

    def native_patch(self, previous, enabled, functional, expected=200):
        body = dict(participating=enabled, revision=previous['revision'], memberJoinedAt=previous['memberJoinedAt'],
                    functionalRevision=functional)
        status, _, data = self.media.factory.native(self.media.c, self.native_path, body, 'PATCH')
        self.assertEqual(status, expected, data)
        return data

    def native_stream(self, state, functional):
        return self.media.stream(self.media.c, dict(state, functionalRevision=functional))

    def browser_stream(self, user):
        raw = socket.create_connection(('127.0.0.1', self.h.port), timeout=3)
        url = 'ws://web.wegoh.invalid/v1/social/trips/' + self.media.trip + '/voice'
        headers = {'Cookie': user['cookie'], 'Cf-Access-Jwt-Assertion': self.h.assertion(user['user']['displayName'])}
        try:
            return connect(url, sock=raw, origin='https://web.wegoh.invalid', additional_headers=headers,
                           open_timeout=3, close_timeout=1)
        except BaseException:
            raw.close()
            raise

    def control(self, stream, kind):
        for _ in range(12):
            packet = stream.recv(timeout=2)
            if isinstance(packet, str) and json.loads(packet)['type'] == kind:
                return json.loads(packet)
        self.fail('Expected ' + kind)

    def patch(self, previous, enabled, expected=200, *, error='TRIP_VOICE_PARTICIPATION_CHANGED', **overrides):
        body = dict(participating=enabled, revision=previous['revision'], memberJoinedAt=previous['memberJoinedAt'])
        status, _, data = self.h.call(self.path, dict(body, **overrides), 'PATCH', session=self.media.b, who='bob')
        self.assertEqual(status, expected, data)
        if expected == 409 and error:
            self.assertEqual(data['detail'], error)
        return data

    def workspace(self):
        path = '/v1/social/trips/' + self.media.trip + '/workspace'
        status, _, work = self.h.call(path, session=self.media.b, who='bob')
        self.assertEqual(status, 200, work)
        return work

    def test_disable_disconnects_this_account_preserves_other_choices_and_rejects_stale_enable(self):
        start = self.get()
        self.assertTrue(start['participating'])
        self.assertEqual(self.patch(start, True), start)
        initial_work = self.workspace()
        initial_sharing = initial_work['mySharing']
        self.assertTrue(initial_sharing['music'])
        functional = self.media.factory.native(self.media.c, '/v1/device/functional-permissions')[2]['revision']
        with self.native_stream(start, functional) as stream:
            self.media.ready(stream)
            off = self.patch(start, False)
            with self.assertRaises(ConnectionClosed):
                while True:
                    stream.recv(timeout=2)
        self.assertFalse(off['participating'])
        self.assertGreater(off['revision'], start['revision'])
        self.assertEqual(self.patch(off, False), off)
        self.patch(start, True, 409)
        self.assertEqual(self.workspace()['mySharing'], dict(initial_sharing, voice=False))
        self.assertEqual(self.workspace()['revision'], initial_work['revision'])
        self.assertTrue(self.get(self.media.a)['participating'])
        with self.assertRaises(InvalidStatus):
            self.native_stream(off, functional)
        on = self.patch(off, True)
        self.assertTrue(on['participating'])
        self.assertEqual(self.get(), on)

    def test_car_and_browser_share_one_setting_and_audio_even_with_old_vehicle_voice_off(self):
        car = self.media.c
        functional = self.media.factory.approve(self.media.b, car, ['rooms:read', 'rooms:interact'], 'bob')
        status, _, current = self.media.factory.native(car, self.native_path)
        self.assertEqual(status, 200, current)
        self.assertEqual(current, self.get())
        legacy_key = (car['grantId'], self.media.room)
        with psycopg.connect(self.h.dsn) as conn:
            conn.execute("INSERT INTO native_room_voice_authorizations "
                         "(grant_id,room_id,device_id,revision,state,member_joined_at,expires_at) "
                         "VALUES(%s,%s,%s,4,'WITHDRAWN',%s,%s)",
                         (*legacy_key, car['deviceId'], current['memberJoinedAt'], car['grantExpiresAt']))

        self.native_patch(current, False, functional+1, 409)
        with self.browser_stream(self.media.b) as same_account:
            self.control(same_account, 'ready')
            off = self.native_patch(current, False, functional)
            with self.assertRaises(ConnectionClosed):
                while True:
                    same_account.recv(timeout=2)
        self.assertEqual(off, self.get())
        with self.assertRaises(InvalidStatus):
            self.native_stream(off, functional)
        active = self.patch(off, True)
        self.native_patch(off, False, functional, 409)
        self.assertEqual(self.media.factory.native(car, self.native_path)[2], active)
        legacy_view = self.media.own(car)
        self.assertEqual(legacy_view['permissions'], dict(receiveVoice=True, transmitVoice=True))
        self.assertEqual((legacy_view['revision'], legacy_view['memberJoinedAt']),
                         (active['revision'], active['memberJoinedAt']))

        with self.native_stream(active, functional) as vehicle, self.browser_stream(self.media.a) as browser:
            self.control(vehicle, 'ready')
            self.control(browser, 'ready')
            for sender, receiver, sample in ((vehicle, browser, 1), (browser, vehicle, 2)):
                sender.send(json.dumps({'type': 'floor-request'}))
                self.control(sender, 'floor-granted')
                self.control(receiver, 'floor-started')
                frame = struct.pack('<I', 0) + struct.pack('<h', sample) * 320
                sender.send(frame)
                self.assertEqual(receiver.recv(timeout=2), frame)
                sender.send(json.dumps({'type': 'floor-release'}))
                self.control(sender, 'floor-ended')
                self.control(receiver, 'floor-ended')
        with psycopg.connect(self.h.dsn) as conn:
            old = conn.execute('SELECT state, revision, protected FROM native_room_voice_authorizations '
                               'WHERE grant_id=%s AND room_id=%s', legacy_key).fetchone()
            self.assertEqual(old, ('WITHDRAWN', 4, None))

    def test_late_request_from_before_leaving_cannot_edit_rejoined_membership(self):
        before = self.get()
        route = '/' + self.media.trip + '/members/' + self.media.b['user']['id']
        removed = self.h.trip(route, method='DELETE', session=self.media.a)
        self.assertEqual(removed[0], 200, removed[2])
        self.assertEqual(self.h.call(self.path, session=self.media.b, who='bob')[0], 404)
        self.h.join(self.media.trip, self.media.a, self.media.b)
        joined = self.get()
        self.assertNotEqual(joined['memberJoinedAt'], before['memberJoinedAt'])
        self.assertGreater(joined['revision'], before['revision'])
        functional = self.media.factory.native(self.media.c, '/v1/device/functional-permissions')[2]['revision']
        with self.assertRaises(InvalidStatus):
            self.native_stream(before, functional)
        self.patch(joined, False, 409, memberJoinedAt=before['memberJoinedAt'])
        self.assertEqual(self.get(), joined)

    def test_legacy_sharing_and_new_route_use_the_same_member_voice_revision(self):
        initial = self.get()
        initial_sharing = self.workspace()['mySharing']
        path = '/v1/social/trips/' + self.media.trip + '/sharing'

        def save_sharing(**changes):
            choices = dict(initial_sharing, **changes)
            result = self.h.call(path, dict(consents=choices), 'PATCH', session=self.media.b, who='bob')
            self.assertEqual(result[0], 200, result[2])

        save_sharing(music=False)
        self.assertEqual(self.get(), initial)
        save_sharing(music=False, voice=False)
        current = self.get()
        self.assertFalse(current['participating'])
        self.assertGreater(current['revision'], initial['revision'])
        self.patch(initial, True, 409)
        self.patch(current, True)
        self.assertEqual(self.workspace()['mySharing'], dict(initial_sharing, music=False, voice=True))

    def test_session_membership_active_trip_and_closed_request_body(self):
        current = self.get()
        body = dict(participating=False, revision=current['revision'], memberJoinedAt=current['memberJoinedAt'])
        self.assertEqual(self.h.call(self.path)[0], 401)
        self.assertEqual(self.h.call(self.path, session=self.media.e, who='eve')[0], 404)
        self.assertEqual(self.h.call(self.path, body, 'PATCH', session=self.media.b, who='bob', csrf=False)[0], 403)
        self.assertIn(self.media.factory.native(self.media.c, self.path)[0], {403, 404})
        self.assertIn(self.media.factory.native(self.media.c, self.path, body, 'PATCH')[0], {403, 404})
        self.assertEqual(self.media.factory.native(self.media.c, self.native_path, body, 'PATCH')[0], 400)
        outsider = self.media.factory.connect(self.media.e, 'eve')
        self.assertEqual(self.media.factory.native(outsider, self.native_path)[0], 404)
        for override in ({'participating': 1}, {'revision': True}, {'otherAccount': self.media.a['user']['id']}):
            with self.subTest(override=override):
                self.patch(current, False, 400, **override)
        planned = self.h.new_trip(self.media.a)
        self.h.join(planned, self.media.a, self.media.b)
        planned_path = '/v1/social/trips/' + planned + '/voice-participation'
        self.assertEqual(self.h.call(planned_path, session=self.media.b, who='bob')[0], 409)
        blocked = self.h.social('/blocks', self.media.a, dict(targetId=self.media.b['user']['id']), 'POST')
        self.assertEqual(blocked[0], 201, blocked[2])
        self.assertEqual(self.h.call(self.path, session=self.media.b, who='bob')[0], 404)
        self.assertEqual(self.h.call(self.path, body, 'PATCH', session=self.media.b, who='bob')[0], 404)
        self.assertTrue(self.get(self.media.a)['participating'])
        self.h.close_trip(self.media.trip, self.media.a, action='finish')
        self.assertEqual(self.h.call(self.path, body, 'PATCH', session=self.media.a)[0], 409)

    def test_blocked_members_cannot_enter_on_web_or_car_and_the_host_can_still_participate(self):
        owner, bob, eve = self.media.a, self.media.b, self.media.e
        self.h.join(self.media.trip, owner, eve)
        before_bob, before_eve = self.get(bob), self.get(eve)
        functional = self.media.factory.native(self.media.c, '/v1/device/functional-permissions')[2]['revision']
        blocked = self.h.social('/blocks', bob, dict(targetId=eve['user']['id']), 'POST')
        self.assertEqual(blocked[0], 201, blocked[2])

        for session, before in ((bob, before_bob), (eve, before_eve)):
            who = session['user']['displayName']
            body = dict(participating=False, revision=before['revision'], memberJoinedAt=before['memberJoinedAt'])
            self.assertEqual(self.h.call(self.path, session=session, who=who)[0], 404)
            self.assertEqual(self.h.call(self.path, body, 'PATCH', session=session, who=who)[0], 404)
            with self.assertRaises(InvalidStatus):
                self.browser_stream(session)
        self.assertEqual(self.media.factory.native(self.media.c, self.native_path)[0], 404)
        self.native_patch(before_bob, False, functional, 404)
        with self.assertRaises(InvalidStatus):
            self.native_stream(before_bob, functional)
        self.assertTrue(self.get(owner)['participating'])
        with self.browser_stream(owner) as host:
            self.control(host, 'ready')
            host.send(json.dumps({'type': 'floor-request'}))
            self.control(host, 'floor-granted')
            host.send(json.dumps({'type': 'floor-release'}))
            self.control(host, 'floor-ended')

    def test_exhausted_revision_allows_stopping_but_never_renews_old_access(self):
        maximum = 2_147_483_647
        account = self.media.b['user']['id']
        counter = 'trip-voice:' + self.media.trip + ':' + account
        with psycopg.connect(self.h.dsn) as conn:
            conn.execute("INSERT INTO team_resource_versions(account_id,resource,revision) VALUES(%s,'rooms',%s) "
                         "ON CONFLICT(account_id,resource) DO UPDATE SET revision=excluded.revision", (counter, maximum-1))
        before = self.get()
        self.assertEqual(before['revision'], maximum)
        functional = self.media.factory.native(self.media.c, '/v1/device/functional-permissions')[2]['revision']
        off = self.native_patch(before, False, functional)
        self.assertFalse(off['participating'])
        self.assertEqual(off['revision'], maximum)
        self.assertEqual(self.patch(off, False), off)
        self.patch(off, True, 409, error='TRIP_VOICE_REVISION_EXHAUSTED')
        choices = dict(self.workspace()['mySharing'], voice=True)
        denied = self.h.trip('/' + self.media.trip + '/sharing', dict(consents=choices), 'PATCH', session=self.media.b)
        self.assertEqual((denied[0], denied[2]['detail']), (409, 'TRIP_VOICE_REVISION_EXHAUSTED'))
        with self.assertRaises(InvalidStatus):
            self.native_stream(before, functional)

        member_path = '/' + self.media.trip + '/members/' + account
        self.assertEqual(self.h.trip(member_path, method='DELETE', session=self.media.a)[0], 200)
        self.h.join(self.media.trip, self.media.a, self.media.b)
        after = self.get()
        self.assertNotEqual(after['memberJoinedAt'], before['memberJoinedAt'])
        self.assertEqual((after['revision'], after['participating']), (maximum, False))
        self.patch(before, True, 409)
        self.patch(after, True, 409, error='TRIP_VOICE_REVISION_EXHAUSTED')
        with self.assertRaises(InvalidStatus):
            self.native_stream(before, functional)
