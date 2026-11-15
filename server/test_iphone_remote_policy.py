import unittest

from test_iphone_trips import IPhoneTripTests


class IPhoneRemotePolicyTests(IPhoneTripTests):
    def test_policy_create_and_passenger_command_use_iphone_session(self):
        self.befriend(self.bob)
        trip = self.create((self.bob,))
        self.checked(self.call('/' + trip + '/respond', dict(accept=True), 'POST', session=self.bob))
        device = self.vehicle()
        policy = dict(enabled=True, actions=['hvac.temperature'])
        car = self.checked(self.call('/' + trip + '/cars',
            dict(name='사용자A의 차', seats=2, remotePolicy=policy), 'POST'), 201)['id']
        path = '/' + trip + '/cars/' + car + '/remote-policy'
        saved = self.checked(self.call(path))['remotePolicy']
        shown = self.detail(trip)['cars'][0]
        self.assertNotIn('remotePolicyRevision', shown)
        self.assertNotIn('remotePolicyGrantId', shown)
        self.assertEqual(saved, dict(policy, deviceId=device['deviceId']))
        self.assertEqual(self.call(path, policy, 'PUT', session=self.bob)[0], 403)
        self.checked(self.call('/' + trip + '/cars/' + car + '/ride', {}, 'PUT', session=self.bob))
        self.assertEqual(self.call('/' + trip + '/vehicle-remotes', session=self.bob)[0], 409)
        web = self.phone.api.login()
        self.checked(self.phone.api.call('/v1/social/trips/' + trip + '/start', dict(revision=self.detail(trip)['revision']), 'POST', session=web))
        remotes = self.checked(self.call('/' + trip + '/vehicle-remotes', session=self.bob))['remotes']
        self.assertEqual(len(remotes), 1)
        remote = remotes[0]
        self.assertEqual([action['id'] for action in remote['actions']], ['hvac.temperature'])
        body = dict(eventId='iphone-policy-command-0001', grantRevision=remote['grantRevision'],
            capabilityId='hvac.temperature', capabilityRevision=1, arguments=dict(seat='ROW_1_RIGHT', value=22))
        command_path = '/' + trip + '/vehicle-remotes/' + device['deviceId'] + '/commands'
        receipt = self.checked(self.call(command_path, body, 'POST', session=self.bob), 201)
        self.assertEqual(receipt['tripId'], trip)
        self.assertFalse(receipt['physicalExecutionVerified'])
        self.assertEqual(self.checked(self.call(command_path, body, 'POST', session=self.bob), 201)['id'], receipt['id'])
        # iPhone은 이 경로의 403 FUNCTIONAL_PURPOSE_REQUIRED를 차량 '리모컨 받기' 꺼짐으로 안내한다.
        self.phone.api.set_command_receiver(device, False)
        status, _, paused = self.call(command_path, dict(body, eventId='iphone-policy-paused-0001'), 'POST', session=self.bob)
        self.assertEqual((status, paused), (403, dict(detail='FUNCTIONAL_PURPOSE_REQUIRED')))
        self.phone.api.set_command_receiver(device, True)
        self.checked(self.call(command_path, dict(body, eventId='iphone-policy-resumed-0001'), 'POST', session=self.bob), 201)
        self.befriend(self.eve)
        self.join(trip, self.eve)
        self.assertIsNone(self.detail(trip, session=self.eve)['cars'][0]['remotePolicy'])
        self.assertEqual(self.call(path, session=self.eve)[0], 404)
        self.checked(self.call(path, dict(enabled=False, actions=[]), 'PUT'))
        self.assertEqual(self.checked(self.call('/' + trip + '/vehicle-remotes', session=self.bob))['remotes'], [])
        self.assertEqual(self.call(command_path, dict(body, eventId='iphone-policy-disabled-0001'), 'POST', session=self.bob)[0], 403)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(IPhoneRemotePolicyTests(name) for name in vars(IPhoneRemotePolicyTests) if name.startswith('test_'))
