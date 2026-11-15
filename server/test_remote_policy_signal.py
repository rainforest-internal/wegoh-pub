import unittest

from test_trip_group_signal import TripGroupSignalTests


class RemotePolicySignalTests(TripGroupSignalTests):
    def test_policy_toggle_preserves_pending_group_signal_and_trip_revision(self):
        trip, cars = self.groups(self.a, self.b)
        created = self.send(trip, self.a)
        self.assertEqual(created[0], 201, created[2])
        signal = created[2]['id']
        revision = self.workspace(trip, self.a)['revision']
        path = '/cars/' + cars[self.a['user']['id']].rsplit('/', 1)[1] + '/remote-policy'
        for enabled in (True, False):
            value = dict(enabled=enabled, actions=['hvac.temperature'] if enabled else [])
            response = self.api(trip, path, self.a, value, 'PUT')
            self.assertEqual(response[0], 200, response[2])
            self.assertEqual(self.workspace(trip, self.a)['revision'], revision)
            pending = next(row for row in self.signals(trip, self.b) if row['id'] == signal)
            self.assertTrue(pending['inProgress'])
            self.assertEqual(pending['resolution'], 'pending')
            self.assertTrue(pending['canRespond'])


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(RemotePolicySignalTests(name) for name in vars(RemotePolicySignalTests) if name.startswith('test_'))
