import json
import unittest
from unittest.mock import patch

import client_reports
from client_reports import (MAX_JOURNAL_BYTES, MAX_LINES, PER_GRANT, ReportLimit, WINDOW_SECONDS, analysis_record,
                            decode_journal_message, journal_payload, mask, report_body)
from native_functional_policy import FunctionalError
from test_climate_commands import ClimateHttpTests


def body(**changes):
    value = dict(reportVersion=1, screen='trip.detail', reason='invalid_field',
                 requestTemplate='GET /v1/native/trips/{id}', appVersion='0.4.0', appBuild=4,
                 lines=['trip.detail.read: queued',
                        'trip.detail: load failed reason=invalid_field trip=1a2b3c4d kind=invalid_response field=routePlan'])
    value.update(changes)
    return json.dumps(value).encode()


class ClientReportContractTests(unittest.TestCase):
    def test_masks_identifiers_tokens_places_and_text(self):
        line = ('climate.receiver: inbox requested account_ref=0123456789ab deviceId=' + 'd' * 32 +
                ' at 37.56651,127.12345 title="Jeju trip" 제주 여행 https://example.test/x?q=1 '
                'Bearer abc.def eyJhbGciOiJIUzI1NiJ9abc1234567 a@b.co 0f8fad5b-d9cb-469f-a165-70867728950e')
        masked = mask(line)
        for secret in ('0123456789ab', 'd' * 32, '37.56651', '127.12345', 'Jeju', '제주', 'example.test',
                       'abc.def', 'eyJhbGci', 'a@b.co', '0f8fad5b'):
            self.assertNotIn(secret, masked)
        kept = 'trip.detail: load failed reason=invalid_field trip=1a2b3c4d status=0 field=routePlan'
        self.assertEqual(mask(kept), kept)

    def test_closed_bounded_body(self):
        report = report_body(body())
        self.assertEqual(report['screen'], 'trip.detail')
        self.assertEqual(report_body(body(requestTemplate=None))['requestTemplate'], None)
        self.assertEqual(report_body(body(lines=['token=abc']))['lines'], ['token={masked}'])
        for change in ({'reportVersion': 2}, {'reportVersion': True}, {'screen': 'Trip'}, {'reason': ''},
                       {'requestTemplate': 'GET https://x'}, {'appVersion': '0.4 beta'}, {'appBuild': 0},
                       {'appBuild': True}, {'lines': 'x'}, {'lines': [1]}, {'lines': ['x' * 241]},
                       {'lines': ['x'] * (MAX_LINES + 1)}, {'deviceId': 'd' * 32}):
            with self.subTest(change=change), self.assertRaises(FunctionalError):
                report_body(body(**change))
        with self.assertRaises(FunctionalError):
            report_body(b'{"reportVersion":1,"reportVersion":1}')
        with self.assertRaises(FunctionalError) as caught:
            report_body(b' ' * 8193)
        self.assertEqual(caught.exception.status, 413)

    def test_journal_line_round_trips_and_stays_under_collector_limit(self):
        report = report_body(body(lines=['x' * 100] * MAX_LINES))
        message = journal_payload(report, 'a' * 16)
        self.assertTrue(message.startswith('wegoh_client_report_v1 '))
        record = decode_journal_message('INFO:     ' + message)
        self.assertEqual(record['report_id'], 'a' * 16)
        self.assertFalse(record['truncated'])
        wide = dict(report, lines=['"\\' * 50] * MAX_LINES)
        record = decode_journal_message(journal_payload(wide, 'b' * 16))
        self.assertTrue(record['truncated'])
        self.assertLess(len(record['lines']), MAX_LINES)
        self.assertLessEqual(client_reports._journal_size(journal_payload(wide, 'b' * 16)), MAX_JOURNAL_BYTES)
        entry = analysis_record(dict(record, **{'@timestamp': '2026-11-15T00:00:00.000000Z'}), '2026-11-15T00:00:00.000000Z')
        self.assertEqual(entry['event.name'], 'wegoh.client.report')
        self.assertEqual(entry['wegoh.client.line_count'], len(record['lines']))
        # Unmasked or unknown journal lines are never forwarded.
        raw = json.loads(message[len('wegoh_client_report_v1 '):])
        self.assertIsNone(decode_journal_message('wegoh_client_report_v1 ' + json.dumps(dict(raw, lines=['token=abc']))))
        self.assertIsNone(decode_journal_message('wegoh_client_report_v1 ' + json.dumps(dict(raw, deviceId='d' * 32))))
        self.assertIsNone(decode_journal_message('wegoh_api_quality_v1 {}'))

    def test_rate_limit_per_grant_and_window(self):
        limit = ReportLimit()
        for _ in range(PER_GRANT):
            self.assertIsNone(limit.admit('a', 1000))
        self.assertGreater(limit.admit('a', 1000), 0)
        self.assertIsNone(limit.admit('b', 1000))
        self.assertIsNone(limit.admit('a', 1000 + WINDOW_SECONDS))
        with patch.object(client_reports, 'TOTAL', 2):
            limit = ReportLimit()
            self.assertIsNone(limit.admit('a', 0)); self.assertIsNone(limit.admit('b', 0))
            self.assertIsNotNone(limit.admit('c', 0))


class ClientReportHttpTests(ClimateHttpTests):
    def setUp(self):
        super().setUp()
        self.limit = patch.object(client_reports, 'LIMIT', ReportLimit())
        self.limit.start()

    def tearDown(self):
        self.limit.stop()
        super().tearDown()

    def report(self, raw=None, client=None):
        data = json.loads(raw or body())
        kwargs = {} if client is None else dict(client=client)
        return self.tls.native(client_reports.PATH, data, 'POST', token=self.token['accessToken'], **kwargs)

    def test_vehicle_report_is_logged_once_without_identifiers(self):
        self.prepare(False)
        with self.assertLogs('uvicorn.error.wegoh_client_report', 'INFO') as logs:
            code, value = self.report(body(lines=['native.social: ended client=trip reason=expired', 'deviceId=' + self.did]))
        self.assertEqual(code, 200, value)
        self.assertEqual(set(value), {'status', 'reportId'})
        self.assertEqual(len(logs.output), 1)
        written = logs.output[0]
        self.assertIn(value['reportId'], written)
        for identifier in (self.did, self.token['grantId'], self.a['user']['id']):
            self.assertNotIn(identifier, written)
        record = decode_journal_message(written.split(':', 2)[2])
        self.assertEqual(record['lines'][-1], 'deviceId={masked}')

    def test_rejects_browser_other_certificate_and_too_many_reports(self):
        self.prepare(False)
        self.assertNotEqual(self.web(client_reports.PATH, json.loads(body()), 'POST', session=self.a)[0], 200)
        self.assertEqual(self.report(client='b')[0], 403)
        self.assertEqual(self.report(body(screen='Bad'))[0], 400)
        for _ in range(PER_GRANT):
            self.assertEqual(self.report()[0], 200)
        code, value = self.report()
        self.assertEqual(code, 429, value)
        self.assertEqual(value['error'], 'CLIENT_REPORT_RATE_LIMITED')


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(loader.loadTestsFromNames([name], kind) for kind in
        (ClientReportContractTests, ClientReportHttpTests) for name in vars(kind) if name.startswith('test_'))
