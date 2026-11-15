import unittest
import psycopg
from native_functional_policy import WIRE
from private_records import VisitCipher

from test_trip_route_segments import TripRouteSegmentsTests
from test_trip_driving_scores import score
from test_trip_merge_api import PLACE


class TripTotalScoreTests(TripRouteSegmentsTests):
    def prepare_total(self):
        setup = self.prepared(pickups=1)
        setup['versions'] = {car: self.native_revision(setup, car, ['rooms:read', 'rooms:interact', 'driving-score:report']) for car in setup['cars'].values()}
        self.start(setup)
        return setup

    def total(self, setup, car, value=None):
        device = setup['devices'][car]
        suffix = '/cars/' + car + '/driving-score' if value is not None else '/driving-score'
        body = dict(drivingScore=value, functionalRevision=setup['versions'][car]) if value is not None else None
        return self.h.native('/v1/native/trips/' + setup['trip'] + suffix, body, 'PUT' if body else 'GET', device['accessToken'], certificate=setup['certificates'][device['deviceId']])

    def test_total_spans_pickup_shared_drop_and_final_is_not_a_course_average(self):
        setup = self.prepare_total()
        first, second = setup['cars'].values()
        self.checked(self.total(setup, first, score(1, 0)))
        self.assertEqual(next(car for car in self.checked(self.total(setup, first))['cars'] if car['carId'] == first)['totalScore'], 95)
        other = self.checked(self.total(setup, second))
        self.assertEqual(next(row for row in other['cars'] if row['carId'] == first)['totalScore'], 95)
        self.assertEqual(other['state'], 'pending')
        self.assertEqual(self.total(setup, first, score(1, 0, final=True))[0], 409)
        self.release(setup)
        self.checked(self.total(setup, first, score(1, 1)))
        for car in (first, second):
            self.reach(setup, car, 'drop')
        self.checked(self.total(setup, first, score(2, 1)))
        self.assertEqual(self.checked(self.total(setup, first))['state'], 'pending')
        self.reach(setup, first, 'done')
        self.checked(self.total(setup, first, score(2, 1, final=True)))
        self.reach(setup, second, 'done')
        self.checked(self.total(setup, second, score(0, 1, final=True)))
        result = self.checked(self.total(setup, first))
        self.assertEqual((result['scope'], result['state'], result['winnerCarIds']), ('trip', 'final', [second]))
        self.assertEqual({car['carId']: car['totalScore'] for car in result['cars']}, {first: 85, second: 95})
        self.assertTrue(all(car['averageScore'] is None and car['courses'] == [] for car in result['cars']))
        self.assertEqual(self.checked(self.total(setup, first, score(2, 1, final=True)))['status'], 'unchanged')
        self.assertEqual(self.total(setup, first, score(3, 1, final=True))[0], 409)

    def test_total_rejects_counter_reset_but_does_not_require_score_consent(self):
        setup = self.prepare_total(); car = setup['cars'][1]
        self.checked(self.total(setup, car, score(2, 0)))
        self.assertEqual(self.total(setup, car, score(1, 0))[0], 409)
        self.assertEqual(self.total(setup, car, dict(score(2, 0), score=99))[0], 400)
        setup['versions'][car] = self.native_revision(setup, car, ['rooms:read', 'rooms:interact'])
        self.checked(self.total(setup, car, score(2, 1)))
        result = self.checked(self.total(setup, car))
        row = next(row for row in result['cars'] if row['carId'] == car)
        self.assertEqual(row['totalScore'], 85)
        self.assertEqual((row['state'], result['winnerCarIds']), ('ready', []))

    def test_old_v4_approval_does_not_block_trip_total(self):
        setup = self.prepare_total(); car = setup['cars'][1]
        device = setup['devices'][car]
        old = next(row for row in WIRE['previousDisclosures'] if row['version'] == 4)
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s', (device['grantId'],)).fetchone()
            value = VisitCipher().restore('native-functional', device['grantId'], row[0])
            value.update(functionalDisclosureVersion=4, functionalDisclosureSha256=old['sha256'])
            conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s', (VisitCipher().protect('native-functional', device['grantId'], value), device['grantId']))
        self.checked(self.total(setup, car, score()))
        result = self.checked(self.total(setup, car))
        self.assertEqual(next(row for row in result['cars'] if row['carId'] == car)['totalScore'], 90)
        with psycopg.connect(self.dsn) as conn:
            from team_trip_driving_versus import TeamTripDrivingVersus
            saved = TeamTripDrivingVersus(self.h.module.TEAM_TRIPS).load(conn, setup['trip'])['tripReports'][car]
            self.assertEqual(saved['functionalDisclosureVersion'], 4)
            self.assertEqual(saved['functionalDisclosureSha256'], old['sha256'])

    def test_legacy_report_survives_unrelated_permission_changes_and_final_retry(self):
        setup = self.prepare_total(); first, second = setup['cars'].values()
        self.release(setup)
        self.reach(setup, first, 'done')
        final = score(final=True)
        self.checked(self.total(setup, first, final))
        with psycopg.connect(self.dsn) as conn:
            from team_trip_driving_versus import TeamTripDrivingVersus
            store = TeamTripDrivingVersus(self.h.module.TEAM_TRIPS)
            data = store.load(conn, setup['trip'])
            data['tripReports'][first].update(functionalRevision=setup['versions'][first],
                functionalDisclosureVersion=5, functionalDisclosureSha256=WIRE['disclosureSha256'])
            store.save(conn, setup['trip'], data)
        setup['versions'][first] = self.native_revision(setup, first, ['rooms:read', 'rooms:interact'])
        self.assertEqual(self.checked(self.total(setup, first, final))['status'], 'unchanged')
        result = self.checked(self.total(setup, second))
        self.assertEqual(next(row for row in result['cars'] if row['carId'] == first)['totalScore'], 90)

    def test_current_device_binding_is_required_even_without_score_consent(self):
        setup = self.prepare_total(); first, second = setup['cars'].values()
        self.checked(self.total(setup, first, score()))
        with psycopg.connect(self.dsn) as conn:
            from team_trip_driving_versus import TeamTripDrivingVersus
            store = TeamTripDrivingVersus(self.h.module.TEAM_TRIPS)
            data = store.load(conn, setup['trip'])
            data['tripReports'][first]['deviceId'] = 'f' * 32
            store.save(conn, setup['trip'], data)
        result = self.checked(self.total(setup, second))
        self.assertEqual(result['reason'], 'report-device-changed')
        self.assertIsNone(next(row for row in result['cars'] if row['carId'] == first)['totalScore'])
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE native_v2_grants SET expires_at=0 WHERE grant_id=%s", (setup['devices'][first]['grantId'],))
        result = self.checked(self.total(setup, second))
        self.assertEqual(result['reason'], 'vehicle-connection-required')
        self.assertEqual(self.total(setup, first, score())[0], 410)

    def test_other_car_driver_cannot_upload_scores(self):
        setup = self.prepare_total(); first, second = setup['cars'].values()
        device = setup['devices'][first]
        response = self.h.native('/v1/native/trips/' + setup['trip'] + '/cars/' + second + '/driving-score',
            dict(drivingScore=score(), functionalRevision=setup['versions'][first]), 'PUT',
            device['accessToken'], certificate=setup['certificates'][device['deviceId']])
        self.assertIn(response[0], (403, 404))
        self.assertEqual(self.checked(self.total(setup, first))['state'], 'pending')

    def check_signal_phase(self, phase):
        setup = self.prepare_total(); first, second = setup['cars'].values()
        if phase == 'waiting':
            self.before_join(setup, first); self.checked(self.arrival(setup, first))
        elif phase == 'drop':
            self.release(setup); self.reach(setup, first, 'drop')
        self.assertEqual(self.plan(setup, first)['phase'], phase)
        self.checked(self.api(setup['trip'], '/signals', self.a, dict(kind='rest', destination=PLACE), 'POST'), 201)

    def test_pickup_signal(self):
        self.check_signal_phase('pickup')

    def test_waiting_signal(self):
        self.check_signal_phase('waiting')

    def test_drop_signal(self):
        self.check_signal_phase('drop')


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(TripTotalScoreTests(name) for name in TripTotalScoreTests.__dict__ if name.startswith('test_'))
