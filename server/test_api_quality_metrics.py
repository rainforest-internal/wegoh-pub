"""API quality observations must be useful without exposing request data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from api_quality_metrics import ApiQualityMetrics, analysis_record, decode_journal_message, summarize


IPHONE_HOST = b'iphone.example.invalid'
WEB_HOST = b'web.example.invalid'
MARKER = 'wegoh_api_quality_v1 '


def scope(path='/v1/iphone/session', method='GET', host=IPHONE_HOST):
    return {
        'type': 'http', 'method': method, 'path': path, 'query_string': b'search=private-query',
        'headers': [(b'host', host), (b'authorization', b'Bearer private-credential'),
                    (b'cookie', b'private-cookie'), (b'user-agent', b'private-agent')],
        'client': ('192.0.2.23', 2555),
    }


class ApiQualityMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, request, status=200):
        response = [
            {'type': 'http.response.start', 'status': status, 'headers': [(b'cache-control', b'private, no-store')]},
            {'type': 'http.response.body', 'body': b'private-response'},
        ]
        actual = []

        async def receive():
            return {'type': 'http.request', 'body': b'private-request', 'more_body': False}

        async def send(message):
            actual.append(message)

        async def app(incoming, incoming_receive, outgoing):
            self.assertIs(incoming, request)
            self.assertIs(incoming_receive, receive)
            for message in response:
                await outgoing(message)

        middleware = ApiQualityMetrics(app, iphone_host=IPHONE_HOST.decode(), web_host=WEB_HOST.decode())
        await middleware(request, receive, send)
        self.assertEqual(actual, response)

    async def test_logs_one_canonical_observation_without_request_or_response_data(self):
        with patch('api_quality_metrics.monotonic_ns', side_effect=[0, 17_001_000]), \
                self.assertLogs('uvicorn.error.wegoh_api_quality', 'INFO') as logs:
            await self.call(scope('/v1/iphone/courses/public/private-course/versions/7/cover', host=IPHONE_HOST+b':443'))
        self.assertEqual(len(logs.records), 1)
        text = logs.records[0].getMessage()
        self.assertTrue(text.startswith(MARKER))
        self.assertEqual(json.loads(text.removeprefix(MARKER)), dict(
            route='iphone.public_course_cover', method='GET', status=200, ttfb_ms=18))
        self.assertNotIn('private', text)
        self.assertNotIn('192.0.2.23', text)

    async def test_only_known_method_host_and_path_are_observed(self):
        with self.assertNoLogs('uvicorn.error.wegoh_api_quality', 'INFO'):
            await self.call(scope(host=WEB_HOST), 404)
            await self.call(scope('/v1/iphone/session', method='DELETE'), 204)
            await self.call(scope('/v1/iphone/unspecified'), 404)
            await self.call(scope('/v1/routes/preview', 'POST'), 404)
            duplicate = scope()
            duplicate['headers'].append((b'host', WEB_HOST))
            await self.call(duplicate, 400)
        with self.assertLogs('uvicorn.error.wegoh_api_quality', 'INFO') as logs:
            await self.call(scope('/v1/routes/preview', 'POST', WEB_HOST), 401)
            await self.call(scope('/v1/iphone/routes/preview', 'POST'), 503)
        self.assertEqual([json.loads(record.getMessage().removeprefix(MARKER))['route']
                          for record in logs.records], ['web.route_preview', 'iphone.route_preview'])

    async def test_demo_flows_are_measured_within_the_scrape_sample_limit(self):
        import api_quality_metrics

        trip, signal, device = 'a' * 32, 'b' * 32, 'c' * 32
        with self.assertLogs('uvicorn.error.wegoh_api_quality', 'INFO') as logs:
            await self.call(scope(f'/v1/iphone/trips/{trip}/start', 'POST'))
            await self.call(scope(f'/v1/iphone/trips/{trip}/signals', 'POST'), 201)
            await self.call(scope(f'/v1/iphone/trips/{trip}/signals/{signal}/vote', 'POST'))
            await self.call(scope(f'/v1/iphone/trips/{trip}/vehicle-remotes/{device}/commands', 'POST'), 201)
        routes = [json.loads(record.getMessage().removeprefix(MARKER))['route'] for record in logs.records]
        self.assertEqual(routes, ['iphone.trip_start', 'iphone.hand_raise', 'iphone.hand_raise_reply',
                                  'iphone.vehicle_remote_command'])
        self.assertTrue(all(api_quality_metrics.is_metric_route(route) for route in routes))
        self.assertFalse(api_quality_metrics.is_metric_route('iphone.public_course_cover'))
        # Counter, 22 buckets, +Inf, count and sum for each of four status classes.
        self.assertLessEqual(len(api_quality_metrics._METRIC_ROUTE_IDS) * 4 * 26, 2048 - 64)


class ApiQualityReportTests(unittest.TestCase):
    def test_correlation_fields_must_be_a_valid_pair(self):
        observation = dict(route='iphone.session', method='GET', status=401, ttfb_ms=17)
        trace = dict(trace_id='1' * 32, span_id='2' * 16)
        timestamp = '2026-11-13T15:00:00.000000Z'
        traced = observation | trace
        self.assertEqual(decode_journal_message(MARKER + json.dumps(traced)), traced)
        record = analysis_record(traced, timestamp)
        self.assertEqual({key: record[key] for key in trace}, trace)
        self.assertEqual(summarize([json.dumps(record)]), summarize([MARKER + json.dumps(observation)]))
        for invalid in ({'trace_id': '1' * 32}, trace | {'trace_id': '0' * 32}, trace | {'span_id': 'A' * 16}):
            self.assertIsNone(decode_journal_message(MARKER + json.dumps(observation | invalid)))

    def test_analysis_record_uses_verified_route_template_and_journal_observation_time(self):
        observation = dict(route='iphone.public_course_cover', method='GET', status=200, ttfb_ms=17)
        observed_at = '2026-11-13T15:00:00.000000Z'
        record = analysis_record(observation, observed_at)
        self.assertEqual(record, {
            'schema_version': 2, '@timestamp': observed_at, 'service.name': 'wegoh-live-api',
            'event.name': 'wegoh.api.response_headers',
            'wegoh.api.route_template': '/v1/iphone/courses/public/{pack_id}/versions/{version}/cover',
            'http.request.method': 'GET', 'http.response.status_code': 200,
            'wegoh.api.route_id': 'iphone.public_course_cover', 'wegoh.api.time_to_headers_ms': 17,
        })
        self.assertIsNone(analysis_record(dict(observation, path='/private'), observed_at))
        self.assertIsNone(analysis_record(observation, '2026-02-30T15:00:00.000000Z'))

    def test_report_accepts_both_archive_versions_and_rejects_extra_or_mismatched_fields(self):
        observation = dict(route='iphone.session', method='GET', status=401, ttfb_ms=17)
        observed_at = '2026-11-13T15:00:00.000000Z'
        record_v1 = {'schema_version': 1, '@timestamp': observed_at, **observation}
        record_v2 = analysis_record(observation, observed_at)
        invalid = [
            {'wegoh.api.route_template': '/v1/iphone/trips/private'},
            {'http.request.method': 'POST'},
            {'http.response.status_code': True},
            {'event.name': 'private'},
            {'service.name': 'private'},
            {'schema_version': True},
            {'event_id': 'archive records do not store collector keys'},
            {'wegoh.api.time_to_headers_ms': -1},
        ]
        archive_lines = [json.dumps(record) for record in (record_v1, record_v2)]
        archive_lines += [json.dumps(record_v2 | override) for override in invalid]
        report = summarize(archive_lines)
        self.assertEqual(report, summarize([MARKER + json.dumps(observation)] * 2))

    def test_counts_and_success_latency_do_not_conflate_rejections_or_server_failures(self):
        def entry(status, ms, route='iphone.session'):
            return 'INFO:     ' + MARKER + json.dumps(dict(route=route, method='GET', status=status, ttfb_ms=ms)) + '\n'

        report = summarize([entry(200, 8), entry(200, 47), entry(401, 3), entry(403, 4),
                            entry(429, 5), entry(503, 2000), entry(502, 90000)])
        self.assertEqual(report['status'], 'observed')
        row = report['routes']['iphone.session']
        self.assertEqual(row['responses'], 7)
        self.assertEqual(row['status_classes'], {'2xx': 2, '3xx': 0, '4xx': 3, '5xx': 2})
        self.assertEqual((row['unauthorized_401'], row['forbidden_403'], row['rate_limited_429']), (1, 1, 1))
        self.assertEqual(row['server_error_rate'], 2 / 7)
        self.assertEqual(row['all_response_ttfb'], dict(
            samples=7, over_max_bucket=1, p50_upper_bound_ms=10, p95_upper_bound_ms=None))
        self.assertEqual(row['successful_response_ttfb'], dict(
            samples=2, over_max_bucket=0, p50_upper_bound_ms=10, p95_upper_bound_ms=50))

    def test_empty_input_and_unknown_or_invalid_fields(self):
        report = summarize([
            'ordinary log with secret token',
            'ERROR: ' + MARKER + '{"route":"iphone.session","method":"GET","status":200,"ttfb_ms":5}',
            MARKER + '{"route":"private-identifier","method":"GET","status":200,"ttfb_ms":5}',
            MARKER + '{"route":"private-identifier","method":null,"status":200,"ttfb_ms":5}',
            MARKER + '{"route":"iphone.session","method":"GET","status":200,"ttfb_ms":5,"name":"private"}',
            MARKER + '{"route":"iphone.session","method":"GET","status":700,"ttfb_ms":5}',
            MARKER + '{"route":"iphone.session","method":"GET","status":200,"ttfb_ms":-1}',
        ])
        self.assertEqual(report, dict(version=1, status='no_observations', max_histogram_bucket_ms=60000, routes={}))


class ApiQualityEntrypointTests(unittest.TestCase):
    def test_real_live_entrypoint_and_uvicorn_format_preserve_session_response(self):
        # Isolate environment and imported app globals from the other HTTP fixtures.
        with tempfile.TemporaryDirectory() as directory:
            credentials = Path(directory)
            key = credentials / 'visit.key'
            members = credentials / 'members.json'
            key.write_bytes(b'x' * 32)
            members.write_text('[{"email":"synthetic@example.invalid","name":"Synthetic","role":"viewer"}]')
            key.chmod(0o600)
            members.chmod(0o600)
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith('WEGOH_') and key != 'CREDENTIALS_DIRECTORY'}
            environment.update(
                CREDENTIALS_DIRECTORY=str(credentials), WEGOH_API_KEY='x' * 32,
                WEGOH_AUTH_MODE='cloudflare', WEGOH_PUBLIC_ORIGIN='https://web.example.invalid',
                WEGOH_IPHONE_API_ORIGIN='https://iphone.example.invalid',
                WEGOH_ACCESS_ISSUER='https://synthetic.cloudflareaccess.com', WEGOH_ACCESS_AUD='x' * 16,
            )
            live = subprocess.run([sys.executable, '-B', '-c', UVICORN_PROBE],
                                  cwd=Path(__file__).resolve().parent, env=environment,
                                  text=True, capture_output=True, timeout=20)
            self.assertEqual(live.returncode, 0, live.stderr)
            self.assertIn('401 private, no-store {"detail":"IPHONE_SESSION_REQUIRED"}', live.stdout)
            report = summarize(live.stderr.splitlines())
            self.assertEqual(report['routes']['iphone.session']['unauthorized_401'], 1)
            # The deployed entrypoint also writes one access line with the route template and code.
            from api_observability import decode_journal_event
            access = [decoded[1] for line in live.stderr.splitlines()
                      if (decoded := decode_journal_event(line)) and decoded[0] == 'wegoh_access_v1']
            self.assertEqual([(row['surface'], row['route'], row['status'], row['error_code']) for row in access],
                             [('iphone', '/v1/iphone/session', 401, 'IPHONE_SESSION_REQUIRED')])

            del environment['CREDENTIALS_DIRECTORY']
            environment['WEGOH_TEAM_MEMBERS_FILE'] = str(members)
            subprocess.run([sys.executable, '-B', '-c', 'import api_application, app; assert api_application.app is app.app'],
                           cwd=Path(__file__).resolve().parent, env=environment,
                           text=True, capture_output=True, check=True, timeout=20)


UVICORN_PROBE = '''
import asyncio
import http.client
import socket
import uvicorn
from fastapi.openapi.utils import _get_api_route_for_openapi
from fastapi.routing import iter_route_contexts
from api_quality_metrics import _ROUTE_TEMPLATES
from api_application import TEAM_AUTH, app
from app import app as fastapi_app

# Vehicle owner routes are feature-gated in the API application.
routes = fastapi_app.routes + TEAM_AUTH.native_authorization.browser_router().routes
registered = {(method, route.path) for context in iter_route_contexts(routes)
              if (route := _get_api_route_for_openapi(context)) is not None
              for method in route.methods}
assert set(_ROUTE_TEMPLATES.values()) <= registered, set(_ROUTE_TEMPLATES.values()) - registered

def request(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        connection.request("GET", "/v1/iphone/session", headers={"Host": "iphone.example.invalid"})
        result = connection.getresponse()
        print(result.status, result.getheader("Cache-Control"), result.read().decode())
    finally:
        connection.close()

async def probe(listener):
    server = uvicorn.Server(uvicorn.Config(app, proxy_headers=False, access_log=False, log_level="info"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(.01)
        await asyncio.to_thread(request, listener.getsockname()[1])
    finally:
        server.should_exit = True
        await serving

with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    asyncio.run(probe(listener))
'''
