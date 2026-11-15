from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import psycopg

from native_functional_policy import WIRE
from private_records import VisitCipher
from team_trip_driving_versus import TeamTripDrivingVersus, average
from test_trip_driving_scores import score
from test_trip_route_segments import TripRouteSegmentsTests


class DrivingVersusContractTests(unittest.TestCase):
    def test_unavailable_reasons_preserve_redaction_and_do_not_invent_measurements(self):
        reports = {car: {'coast': dict(score=score, measurable=True)}
            for car, score in (('first', 90), ('second', 85))}
        value = dict(cars={'first': dict(driverId='one', name='1호차'), 'second': dict(driverId='two', name='2호차')},
            courses=[dict(packId='coast', version=1)], reports=reports, withdrawn=[], finalCarIds=['first', 'second'],
            result=TeamTripDrivingVersus.result('final', winners=['first']))
        context = dict(members={driver: dict(state='accepted') for driver in ('one', 'two')})
        for hidden, sharing, proof, missing, expected in (
                (False, True, True, False, None),
                (True, True, True, False, 'course-unavailable'),
                (False, False, True, False, 'vehicle-connection-required'),
                (False, True, False, False, 'report-device-changed'),
                (True, False, False, False, 'vehicle-authority-unavailable'),
                (False, True, True, True, 'final-reports-pending')):
            with self.subTest(hidden=hidden, sharing=sharing, proof=proof, missing=missing):
                trips = SimpleNamespace(auth=None, cars=lambda *args: {'first': dict(driverId='one'), 'second': dict(driverId='two')},
                    riders=lambda *args: {}, person=lambda *args: True,
                    courses=lambda *args: [] if hidden else [dict(packId='coast', version=1)])
                current = dict(value, reports={} if missing else reports,
                    result=None if missing else value['result'])
                service = TeamTripDrivingVersus(trips)
                with patch('team_trip_driving_versus.resolve_trip_context', return_value=context), \
                        patch('team_trip_driving_versus.blocked', return_value=False), \
                        patch.object(service, 'refresh', return_value=current), \
                        patch.object(service, 'sharing_current', return_value=sharing), \
                        patch.object(service, 'proof_current', return_value=proof):
                    result = service.view(None, 'trip', 'one')
                self.assertEqual(result['reason'], expected)
                if expected in ('course-unavailable', 'vehicle-connection-required', 'report-device-changed', 'vehicle-authority-unavailable'):
                    self.assertEqual((result['state'], result['winnerCarIds'], result['tied']), ('unavailable', [], False))
                    self.assertTrue(all(car['averageScore'] is None for car in result['cars']))
                    self.assertTrue(all(course['score'] is None for car in result['cars'] for course in car['courses']))
                    self.assertNotIn('driverId', json.dumps(result))
                    self.assertNotIn('grantId', json.dumps(result))
                elif missing:
                    self.assertEqual(result['state'], 'pending')
                    self.assertTrue(all(car['measuredCourseCount'] == 0 for car in result['cars']))
                else:
                    self.assertEqual((result['state'], result['winnerCarIds']), ('final', ['first']))

    def test_average_compares_exact_fractions_and_never_fills_missing_scores(self):
        self.assertIsNone(average([]))
        self.assertEqual(average([85, 95]), Fraction(90))
        self.assertEqual(average([90]), average([85, 95]))
        self.assertNotEqual(average([95, 90, 90]), average([90, 90, 90]))

    def test_frozen_v3_registry_is_distinct_from_current_v5_and_v2_unchanged(self):
        old = next(item for item in WIRE['previousDisclosures'] if item['version'] == 3)
        raw = dict(version=3, purposes=old['purposeRegistry'])
        actual = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(actual, '74e93e6fb3b374e627b572fe0a49de390fd276074a004f00a9ffac470964fe92')
        self.assertEqual(actual, old['sha256'])
        before = next(row for row in old['purposeRegistry'] if row['id'] == 'driving-score:report')
        current = next(row for row in WIRE['purposeRegistry'] if row['id'] == 'driving-score:report')
        self.assertIn('같은 차', before['purpose'])
        self.assertIn('참가 차', current['purpose'])
        self.assertEqual(WIRE['disclosureVersion'], 5)
        legacy = next(item for item in WIRE['previousDisclosures'] if item['version'] == 2)
        self.assertEqual(legacy['sha256'], 'ec92f07e28aa015408006bd5430f9d9b440870238fabc9393c176c263d4e6657')
        self.assertEqual(len(legacy['purposeIds']), 19)


class DrivingVersusTests(TripRouteSegmentsTests):
    def setUp(self):
        super().setUp()
        self.versions = {}

    def approved(self, *, courses=1, drops=True, old=False):
        setup = self.prepared(courses=courses, drops=drops)
        for car in setup['cars'].values():
            self.approve_score(setup, car)
            if old:
                device = setup['devices'][car]
                with psycopg.connect(self.dsn) as conn:
                    row = conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s',
                        (device['grantId'],)).fetchone()
                    value = VisitCipher().restore('native-functional', device['grantId'], row[0])
                    original = next(item for item in WIRE['previousDisclosures'] if item['version'] == 3)
                    value.update(functionalDisclosureVersion=3, functionalDisclosureSha256=original['sha256'])
                    conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s',
                        (VisitCipher().protect('native-functional', device['grantId'], value), device['grantId']))
        self.start(setup)
        self.release(setup)
        return setup

    def approve_score(self, setup, car, *, enabled=True):
        purposes = ['rooms:read', 'rooms:interact'] + (['driving-score:report'] if enabled else [])
        self.versions[car] = self.native_revision(setup, car, purposes)

    def native(self, setup, car, suffix, body=None, method='GET'):
        device = setup['devices'][car]
        if body is not None:
            body = dict(body, functionalRevision=self.versions[car])
        return self.h.native('/v1/native/trips/' + setup['trip'] + suffix, body, method, device['accessToken'],
            certificate=setup['certificates'][device['deviceId']])

    def duel(self, setup, car=None):
        return self.checked(self.native(setup, car or setup['cars'][1], '/driving-versus'))

    def final(self, setup, car, pack=None, value=None):
        return self.native(setup, car, '/cars/' + car + '/courses/' + (pack or setup['packs'][0])['id'] + '/complete',
            dict(drivingScore=value or score(final=True)), 'POST')

    def finish_shared(self, setup):
        for car in setup['cars'].values():
            self.reach(setup, car, 'drop' if setup['drops'][car] else 'done')

    def both_final(self, setup, values=(90, 80)):
        for car, value in zip(setup['cars'].values(), values):
            self.checked(self.final(setup, car, value=score((100 - value) // 5, 0, final=True)))

    def approved_three(self):
        setup = self.prepared()
        device = self.h.vehicle(self.e)
        setup['certificates'][device['deviceId']] = self.h._native_fingerprint
        third = self.checked(self.api(setup['trip'], '/cars', self.e,
            dict(name='3호차', seats=2), 'POST'), 201)['id']
        setup['cars'][3] = third
        setup['devices'][third] = device
        setup['actors'][third] = self.e
        setup['pickups'][third] = []
        setup['drops'][third] = [self.place(setup['trip'], third, self.e, 'drop', 0)]
        for car in setup['cars'].values():
            self.approve_score(setup, car)
        self.start(setup)
        self.release(setup)
        return setup

    def test_all_cars_automatically_participate_without_mission_rows_or_fake_scores(self):
        setup = self.approved()
        result = self.duel(setup)
        self.assertEqual((result['kind'], result['automatic'], result['state']), ('safe-driving-versus', True, 'pending'))
        self.assertEqual({item['carId'] for item in result['cars']}, set(setup['cars'].values()))
        self.assertTrue(all(item['participating'] for item in result['cars']))
        self.assertTrue(all(item['averageScore'] is None and item['measuredCourseCount'] == 0 for item in result['cars']))
        self.assertEqual(result['winnerCarIds'], [])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_missions').fetchone()[0], 0)
            saved = TeamTripDrivingVersus(self.h.module.TEAM_TRIPS).load(conn, setup['trip'])
            self.assertEqual(saved['reports'], {})

    def test_previous_v3_approval_does_not_hide_scores_or_require_reapproval(self):
        setup = self.approved(old=True)
        self.finish_shared(setup)
        self.both_final(setup)
        with psycopg.connect(self.dsn) as conn:
            saved = TeamTripDrivingVersus(self.h.module.TEAM_TRIPS).load(conn, setup['trip'])
            for reports in saved['reports'].values():
                for report in reports.values():
                    self.assertEqual(set(report), {'score', 'measurable', 'grantId', 'deviceId'})
        self.assertTrue(all(item['averageScore'] is not None for item in self.duel(setup)['cars']))
        for car in setup['cars'].values():
            before = self.versions[car]
            self.approve_score(setup, car)
            self.assertEqual(self.versions[car], before + 1)
        self.assertTrue(all(item['averageScore'] is not None for item in self.duel(setup)['cars']))
        self.both_final(setup)
        self.assertEqual(self.duel(setup)['state'], 'final')

    def test_auto_closed_trip_waits_for_actual_late_final_and_saves_history_result(self):
        setup = self.approved(drops=False)
        self.finish_shared(setup)
        self.assertEqual(self.detail(setup)['state'], 'completed')
        self.assertEqual(self.duel(setup)['state'], 'pending')
        first, second = setup['cars'].values()
        self.checked(self.final(setup, first))
        self.assertEqual(self.duel(setup)['state'], 'pending')
        self.checked(self.final(setup, second, value=score(4, 0, final=True)))
        result = self.duel(setup)
        self.assertEqual(result['state'], 'final')
        self.assertEqual(result['winnerCarIds'], [first])
        self.assertFalse(result['tied'])
        archived = self.checked(self.api(setup['trip'], '/results', self.a))
        self.assertNotIn('drivingVersus', archived['summary'])
        self.assertEqual(self.duel(setup), result)
        direct = self.detail(setup)['courses'][0]['drivingScores']
        self.assertEqual([item['carId'] for item in direct], [first])

    def test_average_excludes_unmeasurable_courses_and_ties_are_explicit(self):
        setup = self.approved(courses=2)
        self.finish_shared(setup)
        first, second = setup['cars'].values()
        for car, values in ((first, (90, None)), (second, (85, 95))):
            for pack, value in zip(setup['packs'], values):
                self.checked(self.final(setup, car, pack, value=score((100 - value) // 5, 0, final=True)
                    if value is not None else score(0, 0, final=True, measurable=False)))
        result = self.duel(setup)
        self.assertEqual((result['state'], result['tied']), ('final', True))
        self.assertEqual(set(result['winnerCarIds']), {first, second})
        cars = {item['carId']: item for item in result['cars']}
        self.assertEqual((cars[first]['averageScore'], cars[second]['averageScore']), (90, 90))
        self.assertEqual((cars[first]['measuredCourseCount'], cars[second]['measuredCourseCount']), (1, 2))
        self.assertEqual(cars[first]['courses'][1]['state'], 'unavailable')

    def test_no_winner_for_unmeasured_opponent(self):
        setup = self.approved()
        self.finish_shared(setup)
        first, second = setup['cars'].values()
        self.checked(self.final(setup, first))
        self.checked(self.final(setup, second, value=score(0, 0, final=True, measurable=False)))
        result = self.duel(setup)
        self.assertEqual((result['state'], result['reason'], result['winnerCarIds']),
            ('unavailable', 'insufficient-measurements', []))
    def test_withdrawal_does_not_award_accidental_solo_victory(self):
        other = self.approved()
        self.checked(self.api(other['trip'], '/cars/' + other['cars'][2], self.b, method='DELETE'))
        result = self.duel(other)
        self.assertEqual((result['state'], result['reason'], result['winnerCarIds']),
            ('unavailable', 'insufficient-cars', []))

    def test_one_starting_car_participates_without_a_fabricated_winner(self):
        setup = self.prepared()
        second = setup['cars'].pop(2)
        self.checked(self.api(setup['trip'], '/cars/' + second, self.b, method='DELETE'))
        self.approve_score(setup, setup['cars'][1])
        self.start(setup)
        self.release(setup)
        result = self.duel(setup)
        self.assertEqual((result['state'], result['reason'], result['winnerCarIds']),
            ('unavailable', 'insufficient-cars', []))
        self.assertEqual(len(result['cars']), 1)
        self.assertTrue(result['cars'][0]['participating'])

    def test_manual_early_finish_does_not_make_a_comparison_winner(self):
        setup = self.approved()
        self.transition(setup['trip'], 'finish')
        result = self.duel(setup)
        self.assertEqual((result['state'], result['reason'], result['winnerCarIds']),
            ('unavailable', 'shared-incomplete', []))

    def test_score_purpose_and_unrelated_revision_changes_do_not_hide_final_result(self):
        setup = self.approved()
        self.finish_shared(setup)
        self.both_final(setup)
        first, second = setup['cars'].values()
        before = self.duel(setup, second)
        self.approve_score(setup, first, enabled=False)
        self.assertEqual(self.duel(setup, second), before)
        self.approve_score(setup, first)
        self.assertEqual(self.duel(setup, second), before)

    def test_blocking_hides_other_car_contribution_and_all_winner_inferences(self):
        setup = self.approved()
        self.finish_shared(setup)
        self.both_final(setup)
        first, second = setup['cars'].values()
        self.checked(self.h.social('/blocks', self.a, dict(targetId=self.b['user']['id']), 'POST'), 201)
        result = self.duel(setup)
        self.assertEqual([item['carId'] for item in result['cars']], [first])
        self.assertEqual((result['state'], result['winnerCarIds'], result['tied']), ('unavailable', [], False))
        self.assertNotIn(second, json.dumps(result))

    def test_withdrawn_frozen_contribution_hides_winner_without_rewriting_result(self):
        setup = self.approved()
        self.finish_shared(setup)
        self.both_final(setup)
        first, second = setup['cars'].values()
        self.assertEqual(self.duel(setup)['winnerCarIds'], [first])
        self.checked(self.api(setup['trip'], '/cars/' + first, self.a, method='DELETE'))
        hidden = self.duel(setup, second)
        self.assertEqual((hidden['state'], hidden['reason'], hidden['winnerCarIds'], hidden['tied']),
            ('unavailable', 'participant-unavailable', [], False))
        with psycopg.connect(self.dsn) as conn:
            frozen = TeamTripDrivingVersus(self.h.module.TEAM_TRIPS).load(conn, setup['trip'])
            self.assertEqual(frozen['result']['winnerCarIds'], [first])

    def test_pre_final_withdrawal_leaves_two_real_competitors_and_a_valid_result(self):
        setup = self.approved_three()
        third = setup['cars'][3]
        self.checked(self.api(setup['trip'], '/cars/' + third, self.e, method='DELETE'))
        del setup['cars'][3]
        self.finish_shared(setup)
        self.both_final(setup)
        result = self.duel(setup)
        self.assertEqual((result['state'], result['winnerCarIds']), ('final', [setup['cars'][1]]))
        self.assertEqual(next(item for item in result['cars'] if item['carId'] == third)['state'], 'withdrawn')

    def test_pre_final_driver_leave_does_not_hide_unrelated_remaining_competitors(self):
        setup = self.approved_three()
        third = setup['cars'][3]
        self.checked(self.api(setup['trip'], '/members/' + self.e['user']['id'], self.e, method='DELETE'))
        del setup['cars'][3]
        self.finish_shared(setup)
        self.both_final(setup)
        result = self.duel(setup)
        self.assertEqual((result['state'], result['winnerCarIds']), ('final', [setup['cars'][1]]))
        self.assertNotIn(third, json.dumps(result))
        self.assertEqual(self.native(setup, third, '/driving-versus')[0], 404)

    def test_hidden_course_erases_comparison_values_and_winner_inference(self):
        setup = self.approved()
        self.finish_shared(setup)
        self.both_final(setup)
        with psycopg.connect(self.dsn) as conn:
            from test_course_moderation_fixture import restrict_course
            for (checksum,) in conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=%s',
                    (setup['packs'][0]['id'],)).fetchall():
                restrict_course(conn, checksum, state='quarantined')
        result = self.duel(setup)
        self.assertEqual((result['state'], result['winnerCarIds']), ('unavailable', []))
        self.assertTrue(all(item['courses'] == [] and item['averageScore'] is None for item in result['cars']))
        self.assertNotIn(setup['packs'][0]['id'], json.dumps(result))

    def test_concurrent_final_retry_preserves_one_encrypted_final_and_rejects_rewrite(self):
        setup = self.approved()
        self.finish_shared(setup)
        first, second = setup['cars'].values()
        self.checked(self.final(setup, first))
        barrier = threading.Barrier(2)
        def send(_):
            barrier.wait(timeout=5)
            return self.final(setup, second, value=score(4, 0, final=True))
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(send, range(2)))
        self.assertEqual([item[0] for item in replies], [200, 200], replies)
        before = self.duel(setup)
        self.assertEqual(before['state'], 'final')
        self.assertEqual(self.final(setup, second, value=score(0, 0, final=True))[0], 409)
        self.assertEqual(self.duel(setup), before)
        with psycopg.connect(self.dsn) as conn:
            raw = bytes(conn.execute('SELECT protected FROM team_trip_driving_versus WHERE trip_id=%s',
                (setup['trip'],)).fetchone()[0])
            self.assertNotIn(b'grantId', raw)
            self.assertNotIn(b'averageScore', raw)
            value = TeamTripDrivingVersus(self.h.module.TEAM_TRIPS).load(conn, setup['trip'])
            self.assertEqual(len(value['reports'][second]), 1)
            self.assertEqual(value['result']['winnerCarIds'], [first])

    def test_legacy_trip_has_no_backfilled_duel_and_native_fields_remain_closed(self):
        setup = self.prepared()
        car = setup['cars'][1]
        self.approve_score(setup, car)
        self.start(setup, version=None)
        result = self.duel(setup)
        self.assertEqual((result['state'], result['reason']), ('unavailable', 'contract-unavailable'))
        self.assertEqual(result['cars'], [])
        self.assertEqual(self.native(setup, car, '/driving-versus?carId=' + car)[0], 400)


def load_tests(loader, tests, pattern):
    suite = loader.loadTestsFromTestCase(DrivingVersusContractTests)
    suite.addTests(DrivingVersusTests(name) for name in DrivingVersusTests.__dict__ if name.startswith('test_'))
    return suite
