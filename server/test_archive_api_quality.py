"""Closed-day API archives retain only validated observations and never overwrite."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from api_quality_metrics import summarize
from archive_api_quality import ArchiveError, EPOCH, UNIT, _journal, archive_day, export


DAY = date(2026, 11, 14)
MESSAGE = 'INFO:     wegoh_api_quality_v1 {"route":"iphone.session","method":"GET","status":401,"ttfb_ms":17}'
START = datetime(2026, 11, 13, 15, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 11, 14, 15, 0, 0, tzinfo=timezone.utc)


def entry(when, message=MESSAGE, unit=UNIT):
    elapsed = when - EPOCH
    timestamp = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
    return json.dumps({'_SYSTEMD_UNIT': unit, 'MESSAGE': message, '__REALTIME_TIMESTAMP': str(timestamp),
                       '__CURSOR': 'internal-journal-cursor', '_HOSTNAME': 'internal-host'})


class ArchiveDayTests(unittest.TestCase):
    def test_previous_and_explicit_dates_use_seoul_calendar(self):
        self.assertEqual(archive_day('previous', END), DAY)
        self.assertEqual(archive_day('2026-11-14', END), DAY)
        with self.assertRaisesRegex(ArchiveError, 'completed'):
            archive_day('2026-11-15', END)
        with self.assertRaisesRegex(ArchiveError, 'completed'):
            archive_day('2026-11-14', END.replace(hour=14))
        for invalid in ('20261114', '2026-02-30', '../path', '0001-01-01'):
            with self.subTest(invalid=invalid), self.assertRaises(ArchiveError):
                archive_day(invalid, END)


@unittest.skipUnless(os.name == 'posix', 'Ubuntu archive permission and fsync contract')
class ArchiveOutputTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.target = self.directory / 'api-quality-2026-11-14.jsonl'

    def test_filters_source_window_and_private_fields_then_reports_plain_jsonl(self):
        @contextmanager
        def source(start, end):
            self.assertEqual((start, end), (START, END))
            yield [
                entry(START.replace(hour=14)),
                entry(START),
                entry(START, MESSAGE, 'other.service'),
                entry(START, 'Unstructured private diagnostics'),
                entry(START, MESSAGE.replace('iphone.session', 'private-synthetic-id')),
                entry(START, MESSAGE[:-1] + ',"address":"private-synthetic-address"}'),
                entry(START, list(MESSAGE.encode())),
                entry(END),
                'invalid JSON',
                entry(END.replace(second=0, microsecond=7, hour=14)),
            ]

        result = export(DAY, self.directory, source)
        self.assertEqual(result, dict(status='archived', date='2026-11-14', records=2, file=self.target.name))
        lines = self.target.read_text().splitlines()
        self.assertEqual([json.loads(line) for line in lines], [
            {'schema_version': 2, '@timestamp': timestamp, 'service.name': 'wegoh-live-api',
             'event.name': 'wegoh.api.response_headers', 'wegoh.api.route_template': '/v1/iphone/session',
             'http.request.method': 'GET', 'http.response.status_code': 401,
             'wegoh.api.route_id': 'iphone.session', 'wegoh.api.time_to_headers_ms': 17}
            for timestamp in ('2026-11-13T15:00:00.000000Z', '2026-11-14T14:00:00.000007Z')])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(summarize(lines), summarize([MESSAGE, MESSAGE]))
        self.assertEqual(list(self.directory.iterdir()), [self.target])

        def must_not_reopen_journal(start, end):
            self.fail('retry reread journal')
        self.assertEqual(export(DAY, self.directory, must_not_reopen_journal)['status'], 'already_present')
        self.assertEqual(self.target.read_text().splitlines(), lines)

    def test_no_observations_and_journal_error_leave_no_file(self):
        @contextmanager
        def empty(start, end):
            yield []
        self.assertEqual(export(DAY, self.directory, empty),
                         dict(status='no_observations', date='2026-11-14', records=0))
        self.assertEqual(list(self.directory.iterdir()), [])

        @contextmanager
        def broken(start, end):
            yield [entry(START)]
            raise ArchiveError('Synthetic journal failure.')
        with self.assertRaisesRegex(ArchiveError, 'Synthetic journal failure'):
            export(DAY, self.directory, broken)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_refuses_directory_accessible_to_other_users_and_existing_symlink(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(ArchiveError, 'mode 0700'):
            export(DAY, self.directory)
        self.directory.chmod(0o700)
        original = self.directory / 'original'
        original.write_text('must be preserved')
        self.target.symlink_to(original)
        with self.assertRaisesRegex(ArchiveError, 'protected regular file'):
            export(DAY, self.directory)
        self.assertEqual(original.read_text(), 'must be preserved')

    def test_concurrent_publication_keeps_first_file(self):
        @contextmanager
        def racing_source(start, end):
            @contextmanager
            def first_to_publish(start, end):
                yield [entry(START)]
            self.assertEqual(export(DAY, self.directory, first_to_publish)['status'], 'archived')
            yield [entry(START.replace(hour=16))]

        self.assertEqual(export(DAY, self.directory, racing_source)['status'], 'already_present')
        self.assertEqual(json.loads(self.target.read_text())['@timestamp'], '2026-11-13T15:00:00.000000Z')
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_nonzero_exit_and_warning_fail_closed(self):
        popen = subprocess.Popen
        for code, warning in [(2, ''), (0, 'private diagnostics')]:
            with self.subTest(code=code, warning=bool(warning)):
                def run_test_child(command, **kwargs):
                    self.assertIn('--since=2026-11-13 15:00:00 UTC', command)
                    self.assertIn('--until=2026-11-14 15:00:00 UTC', command)
                    self.assertIn('_SYSTEMD_UNIT=' + UNIT, command)
                    return popen(['/bin/sh', '-c', 'printf %s "$1" >&2; exit "$2"', '--',
                                  warning, str(code)], **kwargs)
                with patch('archive_api_quality.subprocess.Popen', side_effect=run_test_child):
                    with self.assertRaisesRegex(ArchiveError, '^Journal read failed or reported warnings'):
                        with _journal(START, END) as lines:
                            self.assertEqual(list(lines), [])
