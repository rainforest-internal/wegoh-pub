import unittest

import psycopg

import test_friend_vehicle_controls as fixture
from native_functional_policy import WIRE
from private_records import VisitCipher


PATH = '/v1/device/command-receiver'
RECEIVE = 'device-commands:receive'


class CommandReceiverTests(fixture.FriendRemoteTests):
    def receiver(self, data=None):
        return self.tls.native(PATH, data, 'GET' if data is None else 'PUT', token=self.token['accessToken'])

    def read_receiver(self):
        status, state = self.receiver()
        self.assertEqual(status, 200, state)
        self.assertEqual(set(state), {'deviceId', 'grantId', 'revision', 'enabled'})
        self.assertEqual((state['deviceId'], state['grantId']), (self.did, self.token['grantId']))
        return state

    def toggle(self, state, enabled):
        status, result = self.receiver(dict(grantId=state['grantId'], revision=state['revision'], enabled=enabled))
        self.assertEqual(status, 200, result)
        self.assertIs(result['enabled'], enabled)
        return result

    def test_pause_resume_preserves_approval_and_never_delivers_previous_commands(self):
        self.setup_remote()
        self.allow([dict(id='hvac.temperature', revision=1)])
        self.start_trip()
        self.enable()
        status, _, delivered = self.send('receiver-delivered-001')
        self.assertEqual(status, 201, delivered)
        status, claim = self.claim(delivered['id'])
        self.assertEqual(status, 200, claim)
        status, _, queued = self.send('receiver-queued-0001', arguments=dict(seat='ROW_2_LEFT', value=20))
        self.assertEqual(status, 201, queued)

        before = self.read_receiver()
        self.assertTrue(before['enabled'])
        paused = self.toggle(before, False)
        self.assertGreater(paused['revision'], before['revision'])
        self.assertEqual(self.toggle(paused, False), paused)
        stale = dict(grantId=self.token['grantId'], revision=before['revision'], enabled=True)
        self.assertEqual(self.receiver(stale)[0], 409)
        self.assertEqual(self.web(self.trip_remotes, who='bob', session=self.b)[2]['remotes'], [])
        self.assertIn(self.send('receiver-blocked-0001')[0], (403, 404, 409))

        self.toggle(paused, True)
        self.assertTrue(self.web(self.d, session=self.a)[2]['consent'])
        remotes = self.web(self.trip_remotes, who='bob', session=self.b)[2]['remotes']
        self.assertEqual([(r['deviceId'], r['grantRevision']) for r in remotes], [(self.did, self.grant_revision)])
        self.functional_revision = self.native('/v1/device/functional-permissions')[1]['revision']
        self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'], [])
        self.assertIn(self.claim(queued['id'])[0], (403, 404, 409, 410))
        self.assertIn(self.ack(delivered['id'], claim['leaseId'], 'received')[0], (403, 404, 409, 410))
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(self.service.load_request(conn, queued['id'])['stage'], 'cancelled')
            self.assertEqual(self.service.load_request(conn, delivered['id'])['stage'], 'unknown')
        status, _, fresh = self.send('receiver-resumed-001')
        self.assertEqual(status, 201, fresh)
        self.assertEqual(self.claim(fresh['id'])[0], 200)

    def test_native_binding_prevents_browser_or_other_car_from_changing_this_receiver(self):
        self.setup_remote()
        before = self.read_receiver()
        switch_off = dict(grantId=before['grantId'], revision=before['revision'], enabled=False)
        for other in (self.factory.connect(self.e, 'eve'),):
            with self.subTest(device=other['deviceId']):
                self.assertEqual(self.factory.native(other, PATH, switch_off, 'PUT')[0], 409)
                status, _, state = self.factory.native(other, PATH)
                self.assertEqual(status, 200, state)
                self.assertEqual((state['deviceId'], state['enabled']), (other['deviceId'], True))
                own_switch = dict(grantId=state['grantId'], revision=state['revision'], enabled=False)
                self.assertEqual(self.factory.native(other, PATH, own_switch, 'PUT')[0], 200)
        self.assertIn(self.tls.native(PATH, switch_off, 'PUT', token=self.token['accessToken'], client='b')[0], (401, 403))
        self.assertIn(self.web(PATH, switch_off, 'PUT', session=self.a)[0], (401, 403, 404))

        access = '/v1/devices/' + self.did + '/functional-permissions'
        status, _, settings = self.web(access, session=self.a)
        self.assertEqual(status, 200, settings)
        body = {key: value for key, value in settings.items() if key not in ('deviceId', 'expiresAt')}
        body['approvedPurposes'] = [item for item in settings['approvedPurposes'] if item != RECEIVE]
        self.assertEqual(self.web(access, body, 'PUT', session=self.a)[0], 403)
        self.assertEqual(self.web(access + '/' + RECEIVE, method='DELETE', session=self.a)[0], 403)
        self.assertEqual(self.read_receiver(), before)
        paused = self.toggle(before, False)
        body['approvedPurposes'] = sorted(set(body['approvedPurposes']) | {'history:write'})
        self.assertEqual(self.web(access, body, 'PUT', session=self.a)[0], 200)
        self.assertEqual(self.read_receiver(), paused)
        self.assertEqual(self.receiver(switch_off)[0], 409)

    def test_legacy_off_stays_off_until_car_enables_it_and_does_not_restore_revoked_grants(self):
        self.setup_remote()
        self.start_trip()
        self.enable()
        legacy_purposes = ['rooms:read']
        old = WIRE['previousDisclosures'][0]
        payload = dict(approvedPurposes=legacy_purposes, functionalDisclosureVersion=old['version'],
                       functionalDisclosureSha256=old['sha256'])
        protected = VisitCipher().protect('native-functional', self.token['grantId'], payload)
        with psycopg.connect(self.dsn) as conn:
            self.service.revoke_device(conn, self.did, self.a['user']['id'])
            conn.execute('UPDATE native_functional_authorizations SET revision=revision+1, protected=%s WHERE grant_id=%s',
                         (protected, self.token['grantId']))
        off = self.read_receiver()
        self.assertFalse(off['enabled'])
        self.assertEqual(off, self.read_receiver())
        effective = set(self.native('/v1/device/functional-permissions')[1]['approvedPurposes'])
        self.assertNotIn(RECEIVE, effective)
        with psycopg.connect(self.dsn) as conn:
            raw = conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s',
                               (self.token['grantId'],)).fetchone()[0]
            self.assertEqual(bytes(raw), bytes(protected))
        self.toggle(off, True)
        self.assertEqual(set(self.native('/v1/device/functional-permissions')[1]['approvedPurposes']), effective | {RECEIVE})
        self.assertEqual(self.web(self.trip_remotes, who='bob', session=self.b)[2]['remotes'], [])
        self.assertIn(self.send('receiver-revoked-0001')[0], (403, 404, 409))


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(CommandReceiverTests(test) for test in vars(CommandReceiverTests) if test.startswith('test_'))
