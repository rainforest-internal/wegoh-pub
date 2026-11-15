import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException

from native_functional_policy import WIRE
from team_trip_listen_together import (ENDED_RETENTION_MS, PRESENCE_TIMEOUT_MS, START_DELAY_MS, TRACK,
                                       ListenTogetherSessions, TripListenTogether, allowed_trips)

ROOT = Path(__file__).resolve().parents[1]
TRIP = 'a' * 32
HOST, GUEST, THIRD, OUTSIDER = 'team-' + '1' * 40, 'team-' + '2' * 40, 'team-' + '3' * 40, 'team-' + '4' * 40
MEMBERS = {HOST, GUEST, THIRD}
DEVICES = {HOST: ('d' * 32, 'e' * 32), GUEST: ('f' * 32, 'b' * 32), THIRD: ('c' * 32, '9' * 32)}
SHA = TRACK['sha256']


class Clock:
    def __init__(self):
        self.value = 1_000_000

    def __call__(self):
        return self.value


class ListenTogetherSessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.sessions = ListenTogetherSessions(self.clock)

    def who(self, account, members=MEMBERS):
        device, grant = DEVICES.get(account, ('8' * 32, '7' * 32))
        return (TRIP, account, device, grant, account == HOST, members)

    def join(self, account, joined=True, session=None, sha=SHA):
        return self.sessions.join(*self.who(account), session, sha, joined)[0]

    def read(self, account, members=MEMBERS):
        return self.sessions.read(*self.who(account, members))[0]

    def expect(self, status, code, call, *args, **kwargs):
        with self.assertRaises(HTTPException) as error:
            call(*args, **kwargs)
        self.assertEqual((error.exception.status_code, error.exception.detail), (status, 'LISTEN_TOGETHER_' + code))

    def start(self, account=HOST, session=None, revision=None):
        current = self.read(HOST)['session']
        return self.sessions.start(*self.who(account), session or current['id'],
                                   revision if revision is not None else current['revision'])[0]

    def test_ready_devices_start_once_at_shared_future_time(self):
        self.assertIsNone(self.read(HOST)['session'])
        first = self.join(GUEST)['session']
        self.assertEqual((first['state'], first['deviceCount'], first['joined']), ('preparing', 1, True))
        self.expect(409, 'HOST_NOT_READY', self.start)
        self.join(HOST, session=first['id'])
        self.assertEqual(self.read(THIRD)['session']['deviceCount'], 2)
        self.assertFalse(self.read(THIRD)['session']['joined'])
        self.expect(403, 'HOST_REQUIRED', self.start, GUEST)
        before = self.read(HOST)['session']
        started = self.start()
        session = started['session']
        self.assertEqual(session['state'], 'playing')
        self.assertEqual(session['startAtMs'], self.clock.value + START_DELAY_MS)
        self.assertEqual(started['serverTimeMs'], self.clock.value)
        # Duplicate tap or a retry after an unknown response reuses the same session.
        again = self.sessions.start(*self.who(HOST), before['id'], before['revision'])[0]['session']
        self.assertEqual((again['id'], again['startAtMs'], again['revision']), (session['id'], session['startAtMs'], session['revision']))

    def test_start_requires_two_ready_devices_and_current_revision(self):
        session = self.join(HOST)['session']
        self.expect(409, 'NOT_ENOUGH_DEVICES', self.start)
        self.join(GUEST)
        self.expect(409, 'SESSION_CHANGED', self.start, revision=session['revision'])
        self.expect(409, 'SESSION_CHANGED', self.start, session='0' * 32)
        self.assertEqual(self.start()['session']['state'], 'playing')

    def test_track_hash_must_match_before_joining(self):
        self.expect(409, 'TRACK_MISMATCH', self.join, GUEST, sha='0' * 64)
        self.assertIsNone(self.read(GUEST)['session'])

    def test_late_join_leave_and_end_are_distinguished(self):
        self.join(HOST);self.join(GUEST);self.start()
        self.clock.value += START_DELAY_MS
        self.read(HOST);self.read(GUEST)
        self.clock.value += 3000
        late = self.join(THIRD)['session']
        self.assertEqual((late['state'], late['deviceCount'], late['joined']), ('playing', 3, True))
        left = self.join(GUEST, joined=False)['session']
        self.assertEqual((left['state'], left['deviceCount'], left['joined']), ('playing', 2, False))
        self.expect(403, 'HOST_REQUIRED', self.sessions.end, *self.who(THIRD), late['id'])
        ended = self.sessions.end(*self.who(HOST), late['id'])[0]['session']
        self.assertEqual((ended['state'], ended['endedReason'], ended['deviceCount']), ('ended', 'host-ended', 0))
        self.assertEqual(self.read(THIRD)['session']['endedReason'], 'host-ended')
        # An ended session never restarts; joining again creates a new preparing session.
        fresh = self.join(GUEST)['session']
        self.assertNotEqual(fresh['id'], late['id'])
        self.assertEqual(fresh['state'], 'preparing')

    def test_track_end_and_everyone_leaving_finish_the_session(self):
        self.join(HOST);self.join(GUEST)
        session = self.start()['session']
        self.clock.value = session['startAtMs'] + TRACK['durationMs']
        self.assertEqual(self.read(HOST)['session']['endedReason'], 'track-finished')
        self.clock.value += ENDED_RETENTION_MS + 1
        self.assertIsNone(self.read(HOST)['session'])
        self.join(HOST);self.join(GUEST);self.start()
        self.join(HOST, joined=False)
        self.assertEqual(self.join(GUEST, joined=False)['session']['endedReason'], 'everyone-left')

    def test_silent_or_departed_devices_lose_participation_without_rejoining(self):
        self.join(HOST);self.join(GUEST);self.join(THIRD)
        self.start()
        self.clock.value += PRESENCE_TIMEOUT_MS - 1
        self.read(HOST);self.read(GUEST)
        self.clock.value += 2
        view = self.read(HOST)['session']
        self.assertEqual(view['deviceCount'], 2)
        # Reconnecting alone does not restore playback; THIRD must explicitly join again.
        self.assertFalse(self.read(THIRD)['session']['joined'])
        view = self.read(HOST, members={HOST, THIRD})['session']
        self.assertEqual(view['deviceCount'], 1)
        self.assertFalse(self.read(GUEST, members={HOST, THIRD})['session']['joined'])

    def test_other_device_of_same_account_is_not_the_joined_device(self):
        self.join(GUEST)
        moved = self.sessions.read(TRIP, GUEST, '6' * 32, 'b' * 32, False, MEMBERS)[0]['session']
        self.assertFalse(moved['joined'])
        regranted = self.sessions.read(TRIP, GUEST, 'f' * 32, '5' * 32, False, MEMBERS)[0]['session']
        self.assertFalse(regranted['joined'])

    def test_stale_session_identifier_never_changes_new_session(self):
        old = self.join(GUEST)['session']
        self.join(GUEST, joined=False)
        self.expect(409, 'SESSION_CHANGED', self.join, GUEST, session=old['id'])
        fresh = self.join(HOST)['session']
        self.expect(409, 'SESSION_CHANGED', self.join, GUEST, joined=False, session=old['id'])
        self.expect(409, 'SESSION_CHANGED', self.sessions.end, *self.who(HOST), old['id'])
        self.assertEqual(self.read(HOST)['session']['id'], fresh['id'])

    def test_withdrawal_removes_member_or_closes_trip_session(self):
        self.join(HOST);self.join(GUEST);self.join(THIRD);self.start()
        self.assertTrue(self.sessions.withdraw(TRIP, GUEST))
        self.assertFalse(self.read(GUEST)['session']['joined'])
        self.assertFalse(self.sessions.withdraw(TRIP, OUTSIDER))
        self.assertTrue(self.sessions.withdraw(TRIP))
        self.assertEqual(self.read(HOST)['session']['endedReason'], 'trip-closed')


class ListenTogetherBoundaryTests(unittest.TestCase):
    def test_allow_list_is_exact_and_fails_closed(self):
        self.assertEqual(allowed_trips({}), frozenset())
        self.assertEqual(allowed_trips({'WEGOH_LISTEN_TOGETHER_TRIPS': 'a' * 32 + ', ' + 'b' * 32}), {'a' * 32, 'b' * 32})
        self.assertEqual(allowed_trips({'WEGOH_LISTEN_TOGETHER_TRIPS': 'a' * 32 + ',*'}), frozenset())

    def test_bundled_demo_track_matches_server_catalog(self):
        data = (ROOT / 'android/app/src/debug/assets/listen-together/wegoh-demo-01.wav').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), TRACK['sha256'])
        rate = int.from_bytes(data[24:28], 'little')
        self.assertEqual((len(data) - 44) * 1000 // (rate * 2), TRACK['durationMs'])

    def test_native_routes_are_exact_trip_purposes(self):
        base = '/v1/native/trips/{trip}/listen-together'
        rules = {(row['method'], row['path']): (row['all'], row['any']) for row in WIRE['nativeRoutes'] if row['path'].startswith(base)}
        self.assertEqual(rules, {
            ('GET', base): (['rooms:read'], []),
            ('PUT', base + '/participation'): (['rooms:read', 'rooms:interact'], []),
            ('POST', base + '/start'): (['rooms:read', 'rooms:interact'], []),
            ('POST', base + '/end'): (['rooms:read', 'rooms:interact'], []),
        })
        routes = {(method, route.path) for route in TripListenTogether(MagicMock()).router().routes for method in route.methods}
        self.assertEqual(routes, set(rules))

    def test_browser_and_phone_calls_are_rejected_before_database_access(self):
        service = TripListenTogether(MagicMock())
        request = MagicMock()
        request.state = object()
        with self.assertRaises(HTTPException) as error:
            service._context(request, MagicMock(), 'a' * 32)
        self.assertEqual(error.exception.status_code, 404)

    def test_withdraw_hook_notifies_only_when_state_changed(self):
        music = MagicMock()
        service = TripListenTogether(music)
        service.withdraw_trip_context(None, 'a' * 32, 'b' * 32, HOST)
        music.rooms.notify.assert_not_called()
        service.sessions.join('a' * 32, HOST, 'd' * 32, 'e' * 32, True, {HOST}, None, SHA, True)
        service.withdraw_trip_context(None, 'a' * 32, 'b' * 32, HOST)
        music.rooms.notify.assert_called_once_with(None, 'b' * 32, sections=('music',))


if __name__ == '__main__':
    unittest.main()
