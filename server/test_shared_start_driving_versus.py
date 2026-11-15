import unittest

from test_trip_driving_scores import score
from test_trip_driving_versus import DrivingVersusTests


class SharedStartDrivingVersusTests(DrivingVersusTests):
    def test_explicit_single_join_keeps_reporting_window_and_freezes_real_reports(self):
        setup = self.single_join(drops=False)
        first, second = setup['cars'].values()
        for car in (first, second):
            self.approve_score(setup, car)
        self.start(setup)
        pack = setup['packs'][0]['id']
        partial = score(1, 1)
        suffix = '/cars/' + first + '/courses/' + pack
        self.assertEqual(self.native(setup, first, suffix + '/driving-score', dict(drivingScore=partial), 'PUT')[0], 409)
        self.checked(self.arrival(setup, first))
        self.assertEqual(self.plan(setup, first)['phase'], 'waiting')
        self.assertEqual(self.native(setup, first, suffix + '/driving-score', dict(drivingScore=partial), 'PUT')[0], 409)
        self.checked(self.arrival(setup, second))
        for car, value in ((first, partial), (second, score(2, 1))):
            self.assertEqual(self.plan(setup, car)['phase'], 'shared')
            path = '/cars/' + car + '/courses/' + pack + '/driving-score'
            self.checked(self.native(setup, car, path, dict(drivingScore=value), 'PUT'))
        self.assertEqual(self.detail(setup)['courses'][0]['completedCarIds'], [])
        for car, final in ((first, score(1, 1, final=True)), (second, score(2, 1, final=True))):
            path = '/cars/' + car + '/courses/' + pack + '/complete'
            body = dict(self.completion_body(setup, car), drivingScore=final)
            self.checked(self.native(setup, car, path, body, 'POST'))
            self.checked(self.native(setup, car, path, body, 'POST'))
        self.assertEqual(self.detail(setup)['state'], 'completed')
        result = self.duel(setup)
        self.assertEqual((result['state'], result['winnerCarIds']), ('final', [first]))
        self.assertEqual({car['carId']: car['averageScore'] for car in result['cars']}, {first: 90, second: 85})


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(SharedStartDrivingVersusTests(name)
        for name in SharedStartDrivingVersusTests.__dict__ if name.startswith('test_'))
