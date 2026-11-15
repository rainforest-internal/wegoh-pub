"""Client failure reports: strict template-only validation, limits, logs and span events."""
import json
import unittest

from fastapi import FastAPI, HTTPException
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from api_observability import ACCESS_PREFIX, CLIENT_EVENT_PREFIX, HostSurfaces, Pseudonyms, install
from api_tracing import TailSampler, Tracing
from client_diagnostics import IPHONE_PATH, MAX_EVENTS, NATIVE_PATH, create_router, parse_events
from native_access_policy import required_scope
from test_api_observability import NATIVE_HOST, SECRET, call, lines, scope

ACCOUNT = 'team-' + 'a' * 40
DEVICE = 'd' * 32
TEMPLATES = {('GET', '/v1/native/trips/{id}'), ('GET', '/v1/native/trips'), ('WS', '/v1/events')}
GOOD = {'kind': 'invalid_response', 'method': 'GET', 'route': '/v1/native/trips/{id}', 'requestId': 'req-00000001',
        'traceId': 'c' * 32, 'status': 200, 'decodePath': 'routePlan.stops[2].arrival', 'decodeRule': 'missing',
        'elapsedMs': 320}


def body(*events):
    return json.dumps({'events': list(events)}).encode()


class ParseTests(unittest.TestCase):
    def test_accepts_templates_and_rules_only(self):
        (row,), skipped = parse_events(body(GOOD), TEMPLATES)
        self.assertEqual(skipped, 0)
        self.assertEqual(row, dict(kind='invalid_response', target_method='GET', target_route='/v1/native/trips/{id}',
                                   ref_req_id='req-00000001', ref_trace_id='c' * 32, http_status=200,
                                   decode_path='routePlan.stops[2].arrival', decode_rule='missing', elapsed_ms=320))
        (row,), _ = parse_events(body(dict(GOOD, decodePath='versions.' + 'e' * 32 + '.revision')), TEMPLATES)
        self.assertEqual(row['decode_path'], 'versions.*.revision')
        (row,), _ = parse_events(body({'kind': 'timeout', 'method': 'WS', 'route': '/v1/events'}), TEMPLATES)
        self.assertEqual(row['kind'], 'timeout')

    def test_skips_only_unmounted_routes_and_keeps_the_rest(self):
        unmounted = (dict(GOOD, route='/v1/native/trips/' + 'f' * 32), dict(GOOD, route='/v1/native/unknown'),
                     dict(GOOD, method='POST'))
        rows, skipped = parse_events(body(GOOD, *unmounted), TEMPLATES)
        self.assertEqual((len(rows), skipped), (1, 3))
        self.assertEqual(rows[0]['target_route'], '/v1/native/trips/{id}')
        self.assertEqual(parse_events(body(*unmounted), TEMPLATES), ([], 3))

    def test_decode_path_hides_every_server_identifier_format(self):
        # Formats the server issues: uuid4, token_hex(16/8/6), team-/trip-waypoint- hex, token_urlsafe(32).
        for segment in ('3f2b8c1e-9a4d-4c7b-8e2f-1a2b3c4d5e6f', '3F2B8C1E-9A4D-4C7B-8E2F-1A2B3C4D5E6F',
                        'e' * 32, 'c' * 16, '0a1b2c3d4e5f', 'team-' + 'a' * 40, 'trip-waypoint-' + 'b' * 32,
                        'kq3J-x9_ZbT2vNw8YpL4mRc7sUe1oHa6dGf5iKj0lMn', 'Q' * 43, '1731628800123'):
            for path in (f'members.{segment}.name', f'members[{segment}]', f'$.{segment}'):
                with self.subTest(path=path):
                    (row,), _ = parse_events(body(dict(GOOD, decodePath=path)), TEMPLATES)
                    self.assertNotIn(segment, row['decode_path'])
                    self.assertIn('*', row['decode_path'])
        for path in ('routePlan.stops[2].arrival', 'estimatedArrivalSeconds', 'members[0].display_name',
                     '$.data.items[12].startedAt', 'deadline'):
            with self.subTest(path=path):
                (row,), _ = parse_events(body(dict(GOOD, decodePath=path)), TEMPLATES)
                self.assertEqual(row['decode_path'], path)

    def test_rejects_values_ids_unknown_fields_and_oversized_batches(self):
        for event in (
            dict(GOOD, route=['/v1/native/trips/{id}']),
            dict(GOOD, method='HEAD'),
            dict(GOOD, kind='crash'),
            dict(GOOD, value='private payload'),
            dict(GOOD, decodePath='title="private"'),
            dict(GOOD, decodeRule='private'),
            dict(GOOD, requestId='short'),
            dict(GOOD, traceId='0' * 32),
            dict(GOOD, status=99),
            dict(GOOD, elapsedMs=-1),
            {key: value for key, value in GOOD.items() if key != 'decodeRule'},
        ):
            with self.subTest(event=event), self.assertRaises(HTTPException) as raised:
                parse_events(body(event), TEMPLATES)
            self.assertEqual(raised.exception.detail, 'INVALID_DIAGNOSTIC')
        for raw in (b'not json', b'[]', b'{"events":[]}', body(*[GOOD] * (MAX_EVENTS + 1)),
                    json.dumps({'events': [GOOD], 'device': DEVICE}).encode()):
            with self.subTest(raw=raw[:30]), self.assertRaises(HTTPException):
                parse_events(raw, TEMPLATES)


class FakeAuth:
    def __init__(self, limit=2):
        self.limit, self.hits = limit, {}

    def rate(self, key, *, limit):
        self.hits[key] = self.hits.get(key, 0) + 1
        if self.hits[key] > self.limit:
            raise HTTPException(429, 'Request limit exceeded', headers={'Retry-After': '60'})

    def iphone(self, request, scope_):
        if request.headers.get('authorization') != 'Bearer synthetic-iphone':
            raise HTTPException(401, 'IPHONE_SESSION_REQUIRED')
        return {'id': ACCOUNT}


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        self.addCleanup(provider.shutdown)
        provider.add_span_processor(TailSampler(SimpleSpanProcessor(self.exporter)))
        app = FastAPI()
        self.auth = FakeAuth()

        @app.middleware('http')
        async def native_boundary(request, call_next):
            # Stands in for TeamAuth.boundary minting the mTLS device principal.
            if request.headers.get('x-synthetic-device'):
                request.state.device_identity = {'id': ACCOUNT, 'deviceId': DEVICE}
            return await call_next(request)

        @app.get('/v1/native/trips/{id}')
        def trip(id: str):
            return {}

        app.include_router(create_router(self.auth, app))
        self.served = install(app, application='api', secret=SECRET, tracing=Tracing(provider.get_tracer('t'), 0.0),
                              surfaces=HostSurfaces(native=(NATIVE_HOST,), iphone=('iphone.wegoh.invalid',)))

    async def post(self, path, payload, *, headers=(('x-synthetic-device', '1'),), host=NATIVE_HOST):
        request = scope(path, method='POST', host=host, headers=(('content-type', 'application/json'), *headers))
        with self.assertLogs('uvicorn.error', 'INFO') as logs:
            sent = await call(self.served, request, payload)
        return sent[0]['status'], logs

    async def test_native_report_writes_event_line_and_forced_span_event(self):
        status, logs = await self.post(NATIVE_PATH, body(GOOD))
        self.assertEqual(status, 202)
        event, = lines(logs, CLIENT_EVENT_PREFIX)
        access, = lines(logs, ACCESS_PREFIX)
        self.assertEqual((event['surface'], event['kind'], event['target_route'], event['decode_rule'], event['ref_req_id']),
                         ('native', 'invalid_response', '/v1/native/trips/{id}', 'missing', 'req-00000001'))
        self.assertEqual((event['req_id'], event['trace_id']), (access['req_id'], access['trace_id']))
        self.assertEqual((access['acct_h'], access['device_h'], access['trace_kept']),
                         (Pseudonyms(SECRET)('account', ACCOUNT), Pseudonyms(SECRET)('device', DEVICE), True))
        root, = self.exporter.get_finished_spans()
        self.assertEqual(root.attributes['wegoh.trace.reason'], 'forced')
        span_event, = root.events
        self.assertEqual(span_event.name, 'wegoh.client_event')
        self.assertEqual(span_event.attributes['wegoh.client_event.decode_path'], 'routePlan.stops[2].arrival')
        stored = '\n'.join(record.getMessage() for record in logs.records) + root.to_json()
        self.assertNotIn(ACCOUNT, stored)
        self.assertNotIn(DEVICE, stored)

    async def test_authentication_size_and_rate_limits(self):
        status, logs = await self.post(NATIVE_PATH, body(GOOD), headers=())
        self.assertEqual(status, 404)
        self.assertEqual(lines(logs, CLIENT_EVENT_PREFIX), [])
        status, _ = await self.post(IPHONE_PATH, body(GOOD), headers=(), host='iphone.wegoh.invalid')
        self.assertEqual(status, 401)
        status, logs = await self.post(IPHONE_PATH, body(GOOD), host='iphone.wegoh.invalid',
                                       headers=(('authorization', 'Bearer synthetic-iphone'),))
        self.assertEqual(status, 202)
        self.assertEqual(lines(logs, CLIENT_EVENT_PREFIX)[0]['surface'], 'iphone')
        status, _ = await self.post(NATIVE_PATH, b'{"events":[' + b' ' * 9000 + b']}')
        self.assertEqual(status, 413)
        status, _ = await self.post(NATIVE_PATH, body(GOOD))
        self.assertEqual(status, 202)
        status, logs = await self.post(NATIVE_PATH, body(GOOD))
        self.assertEqual(status, 429)
        self.assertEqual(lines(logs, ACCESS_PREFIX)[0]['error_code'], 'RATE_LIMITED')
        self.assertEqual(lines(logs, CLIENT_EVENT_PREFIX), [])
        status, logs = await self.post(NATIVE_PATH, body(dict(GOOD, kind='crash')))
        self.assertEqual(status, 400)

    async def test_unmounted_route_is_skipped_counted_and_never_logged(self):
        status, logs = await self.post(NATIVE_PATH, body(GOOD, dict(GOOD, route='/v1/native/trips/' + DEVICE)))
        self.assertEqual(status, 202)
        event, = lines(logs, CLIENT_EVENT_PREFIX)
        self.assertEqual(event['target_route'], '/v1/native/trips/{id}')
        skipped, = [record.getMessage() for record in logs.records if 'skipped unmounted=' in record.getMessage()]
        self.assertIn('skipped unmounted=1 accepted=1', skipped)
        self.assertNotIn(DEVICE, '\n'.join(record.getMessage() for record in logs.records))

    def test_native_policy_allows_the_report_with_the_mandatory_scope(self):
        self.assertEqual(required_scope('POST', NATIVE_PATH), 'device:self:manage')


if __name__ == '__main__':
    unittest.main()
