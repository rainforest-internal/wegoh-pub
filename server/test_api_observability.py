"""Access, error and WebSocket records: ids, trace continuation, privacy and tail sampling."""
import asyncio
import json
import logging
import unittest

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
import psycopg
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from api_observability import (ACCESS_PREFIX, CLIENT_EVENT_PREFIX, ERROR_PREFIX, HostSurfaces, Pseudonyms,
                               decode_journal_event, install, log_record, note_identity, record_boundary_errors)
from api_tracing import TailSampler, TraceBudget, Tracing

SECRET = 'synthetic-observability-secret-' + 'x' * 16
NATIVE_HOST = 'api.wegoh.invalid'
PRIVATE_ID = 'f' * 32
PRIVATE_ACCOUNT = 'team-' + 'e' * 40


def scope(path, *, method='GET', host=NATIVE_HOST, headers=(), kind='http', query=b''):
    return {'type': kind, 'method': method, 'path': path, 'raw_path': path.encode(), 'query_string': query,
            'headers': [(b'host', host.encode()), *[(key.lower().encode(), value.encode()) for key, value in headers]],
            'client': ('192.0.2.23', 50000), 'server': (host, 443), 'scheme': 'https' if kind == 'http' else 'wss',
            'http_version': '1.1', 'root_path': '', 'asgi': {'version': '3.0'}}


async def call(app, request, body=b'', *, disconnect_first=False, client_close=None, timeout=5):
    sent = []
    if request['type'] == 'http':
        inbox = [{'type': 'http.disconnect'}] if disconnect_first else [
            {'type': 'http.request', 'body': body, 'more_body': False}]
    else:
        inbox = [{'type': 'websocket.connect'}]
        if client_close is not None:
            inbox.append({'type': 'websocket.disconnect', 'code': client_close})

    async def receive():
        if inbox:
            return inbox.pop(0)
        await asyncio.sleep(timeout)
        return {'type': 'http.disconnect'} if request['type'] == 'http' else {'type': 'websocket.disconnect', 'code': 1006}

    async def send(message):
        sent.append(message)

    try:
        await asyncio.wait_for(app(request, receive, send), timeout)
    except Exception as error:
        sent.append({'type': 'raised', 'error': type(error).__name__})
    return sent


def lines(logs, prefix):
    rows = []
    for record in logs.records:
        message = record.getMessage()
        if message.startswith(prefix):
            decoded = decode_journal_event('INFO:     ' + message)
            assert decoded is not None, message
            rows.append(decoded[1])
    return rows


def headers_of(sent):
    start = next(message for message in sent if message['type'] in ('http.response.start', 'websocket.accept'))
    return {name.decode(): value.decode() for name, value in start.get('headers', ())}


def build_app():
    app = FastAPI()

    @app.get('/v1/native/trips/{trip_id}')
    def trip(trip_id: str):
        note_identity(PRIVATE_ACCOUNT, PRIVATE_ID)
        if trip_id == 'boom':
            raise RuntimeError('private failure text ' + PRIVATE_ID)
        if trip_id == 'db':
            raise psycopg.OperationalError('password=private-db-secret')
        if trip_id == 'wrapped':
            try:
                raise OSError('private storage path')
            except OSError:
                raise HTTPException(503, 'TRIP_STORAGE_UNAVAILABLE')
        raise HTTPException(404, 'TRIP_NOT_FOUND')

    @app.get('/v1/native/stream')
    def stream():
        return StreamingResponse(iter([b'a', b'b']), media_type='text/plain')

    @app.post('/v1/native/echo')
    async def echo():
        return {'ok': True}

    @app.exception_handler(psycopg.Error)
    async def database_error(request, error):
        return JSONResponse({'detail': 'DATABASE_UNAVAILABLE'}, status_code=503)

    @app.websocket('/v1/events')
    async def events(websocket: WebSocket):
        if websocket.headers.get('x-reject'):
            await websocket.close(1008)
            return
        await websocket.accept()
        message = await websocket.receive()
        if message['type'] != 'websocket.disconnect':
            await websocket.close(1000)

    return app


class AccessLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider(shutdown_on_exit=False)
        self.addCleanup(self.provider.shutdown)
        self.provider.add_span_processor(TailSampler(SimpleSpanProcessor(self.exporter)))
        self.tracing = Tracing(self.provider.get_tracer('test'), 0.0)
        self.app = build_app()
        self.served = install(self.app, application='api', secret=SECRET,
                              surfaces=HostSurfaces(native=(NATIVE_HOST,), iphone=('iphone.wegoh.invalid',),
                                                    web=('web.wegoh.invalid',)),
                              tracing=self.tracing)

    async def request(self, *args, **kwargs):
        with self.assertLogs('uvicorn.error', 'INFO') as logs:
            sent = await call(self.served, *args, **kwargs)
        return sent, logs

    async def test_request_id_and_traceparent_round_trip_without_caller_sampling(self):
        traceparent = '00-' + 'a' * 32 + '-' + 'b' * 16 + '-01'
        sent, logs = await self.request(scope('/v1/native/trips/' + PRIVATE_ID, headers=(
            ('X-Request-Id', 'client-request-0001'), ('traceparent', traceparent),
            ('X-WegoH-Client', 'android/1.4.2'))))
        access, = lines(logs, ACCESS_PREFIX)
        self.assertEqual(access['req_id'], 'client-request-0001')
        self.assertEqual(access['trace_id'], 'a' * 32)
        self.assertEqual(access['route'], '/v1/native/trips/{trip_id}')
        self.assertEqual((access['status'], access['error_class'], access['error_code']), (404, 'not_found', 'TRIP_NOT_FOUND'))
        self.assertEqual((access['surface'], access['client_platform'], access['client_version']), ('native', 'android', '1.4.2'))
        self.assertIs(access['trace_kept'], False)
        self.assertEqual(headers_of(sent)['x-request-id'], 'client-request-0001')
        self.assertEqual(headers_of(sent)['traceresponse'], f'00-{"a" * 32}-{access["span_id"]}-00')
        # A caller's sampled flag never forces export: a 404 at ratio 0 is dropped.
        self.assertEqual(self.exporter.get_finished_spans(), ())

        for unsafe in ('short', 'x' * 65, 'bad id with spaces', '../../etc'):
            sent, logs = await self.request(scope('/v1/native/stream', headers=(('X-Request-Id', unsafe),
                                                                                ('traceparent', '00-' + '0' * 32 + '-' + 'b' * 16 + '-01'))))
            access, = lines(logs, ACCESS_PREFIX)
            self.assertRegex(access['req_id'], r'^[0-9a-f]{32}$')
            self.assertNotEqual(access['trace_id'], '0' * 32)
            self.assertEqual(headers_of(sent)['x-request-id'], access['req_id'])

    async def test_records_hold_no_identifiers_query_tokens_or_messages(self):
        sent, logs = await self.request(scope('/v1/native/trips/boom', query=b'lat=37.5&token=private-query', headers=(
            ('Authorization', 'Bearer private-bearer'), ('Cookie', 'session=private-cookie'))))
        self.assertEqual(sent[0]['status'], 500)
        access, = lines(logs, ACCESS_PREFIX)
        error, = lines(logs, ERROR_PREFIX)
        self.assertEqual(access['acct_h'], Pseudonyms(SECRET)('account', PRIVATE_ACCOUNT))
        self.assertEqual(access['device_h'], Pseudonyms(SECRET)('device', PRIVATE_ID))
        self.assertNotEqual(access['acct_h'], Pseudonyms('another-secret-' + 'y' * 32)('account', PRIVATE_ACCOUNT))
        spans = self.exporter.get_finished_spans()
        stored = '\n'.join(record.getMessage() for record in logs.records) + ''.join(span.to_json() for span in spans)
        for private in (PRIVATE_ID, PRIVATE_ACCOUNT, 'private-query', 'private-bearer', 'private-cookie',
                        'private failure text', '192.0.2.23', '37.5'):
            self.assertNotIn(private, stored)
        self.assertEqual(error['exc_type'], 'RuntimeError')
        self.assertTrue(error['location'].startswith('test_api_observability.py:'))
        self.assertEqual(error['function'], 'trip')
        self.assertEqual((error['req_id'], error['trace_id'], error['route'], error['status'], error['handled']),
                         (access['req_id'], access['trace_id'], '/v1/native/trips/{trip_id}', 500, False))

    async def test_handled_and_wrapped_server_errors_are_logged_and_kept(self):
        _, logs = await self.request(scope('/v1/native/trips/db'))
        access, = lines(logs, ACCESS_PREFIX)
        error, = lines(logs, ERROR_PREFIX)
        self.assertEqual((access['status'], access['error_code'], access['trace_kept']), (503, 'DATABASE_UNAVAILABLE', True))
        self.assertEqual((error['exc_type'], error['handled'], error['status']), ('OperationalError', True, 503))
        self.assertNotIn('private-db-secret', json.dumps(error))

        _, logs = await self.request(scope('/v1/native/trips/wrapped'))
        error, = lines(logs, ERROR_PREFIX)
        self.assertEqual((error['exc_type'], error['cause_type'], error['status']), ('HTTPException', 'OSError', 503))
        root = [span for span in self.exporter.get_finished_spans() if span.attributes.get('http.route')]
        self.assertEqual([span.attributes['wegoh.trace.reason'] for span in root], ['error', 'error'])
        self.assertEqual(root[-1].attributes['wegoh.error_code'], 'TRIP_STORAGE_UNAVAILABLE')

    async def test_boundary_failure_before_routing_is_recorded(self):
        class Boundary:
            def check(self):
                raise psycopg.OperationalError('private dsn')
        boundary = Boundary()
        record_boundary_errors(boundary, 'check')

        @self.app.middleware('http')
        async def guard(request, call_next):
            try:
                boundary.check()
            except psycopg.Error:
                return JSONResponse({'detail': 'Team authentication unavailable'}, status_code=503)
            return await call_next(request)

        _, logs = await self.request(scope('/v1/native/echo', method='POST'))
        access, = lines(logs, ACCESS_PREFIX)
        error, = lines(logs, ERROR_PREFIX)
        self.assertEqual((access['route'], access['status'], access['error_class']), ('/v1/native/echo', 503, 'server'))
        self.assertNotIn('error_code', access)
        self.assertEqual((error['exc_type'], error['handled'], error['function']), ('OperationalError', True, 'check'))

    async def test_streaming_unmatched_and_client_closed(self):
        _, logs = await self.request(scope('/v1/native/stream'))
        access, = lines(logs, ACCESS_PREFIX)
        self.assertEqual((access['route'], access['status']), ('/v1/native/stream', 200))
        self.assertNotIn('error_class', access)
        _, logs = await self.request(scope('/v1/unknown/' + PRIVATE_ID))
        access, = lines(logs, ACCESS_PREFIX)
        self.assertEqual((access['route'], access['status']), ('unmatched', 404))
        _, logs = await self.request(scope('/v1/native/echo', method='PUT'))
        self.assertEqual(lines(logs, ACCESS_PREFIX)[0]['route'], '/v1/native/echo')

        async def slow(scope_, receive, send):
            # The client left before any response; the app stops without answering.
            self.assertEqual((await receive())['type'], 'http.disconnect')
        served = install(FastAPI(), application='api', secret=SECRET, surfaces=HostSurfaces(), serve=slow)
        with self.assertLogs('uvicorn.error', 'INFO') as logs:
            await call(served, scope('/v1/anything'), disconnect_first=True)
        access, = lines(logs, ACCESS_PREFIX)
        self.assertEqual((access['status'], access['error_class'], access['surface']), (499, 'client_closed', 'web'))

    async def test_websocket_accept_close_and_reject(self):
        sent, logs = await self.request(scope('/v1/events', kind='websocket'), client_close=1001)
        accept, close = lines(logs, ACCESS_PREFIX)
        self.assertEqual([message['type'] for message in sent], ['websocket.accept'])
        self.assertIn('x-request-id', headers_of(sent))
        self.assertEqual((accept['ws_event'], accept['method'], accept['route'], accept['status']), ('accept', 'WS', '/v1/events', 101))
        self.assertEqual((close['ws_event'], close['ws_close_code'], close['req_id']), ('close', 1001, accept['req_id']))
        self.assertIn('ws_dur_ms', close)
        self.assertNotIn('error_class', close)

        sent, logs = await self.request(scope('/v1/events', kind='websocket', headers=(('X-Reject', '1'),)))
        reject, = lines(logs, ACCESS_PREFIX)
        self.assertEqual((reject['ws_event'], reject['status'], reject['ws_close_code'], reject['error_class']),
                         ('reject', 403, 1008, 'forbidden'))
        sessions = [span for span in self.exporter.get_finished_spans() if span.name == 'WS /v1/events']
        self.assertEqual(len(sessions), 2)

    async def test_internal_loopback_and_journal_decoding(self):
        _, logs = await self.request(scope('/v1/native/stream', host='127.0.0.1:18082'))
        access, = lines(logs, ACCESS_PREFIX)
        self.assertEqual(access['surface'], 'internal')
        row = log_record('wegoh_access_v1', access, 'wegoh-live-api')
        self.assertEqual((row['@timestamp'], row['event.name'], row['service.name']), (access['ts'], 'wegoh.access', 'wegoh-live-api'))
        self.assertIsNone(log_record('wegoh_access_v1', access, 'other-service'))
        for broken in ('wegoh_access_v1 {}', 'wegoh_access_v1 ' + json.dumps(dict(access, route='/v1/x?' + PRIVATE_ID)),
                       'wegoh_access_v1 ' + json.dumps(dict(access, extra='private')),
                       'wegoh_error_v1 ' + json.dumps({'ts': access['ts'], 'exc_type': 'X', 'handled': True, 'message': 'p'}),
                       CLIENT_EVENT_PREFIX + '{"ts": 1}'):
            self.assertIsNone(decode_journal_event(broken))


class TailSamplingTests(unittest.TestCase):
    def test_ratio_errors_slow_and_budget(self):
        clock = [0.0]
        tracing = Tracing(None, 0.25, TraceBudget(per_second=1, burst=2, clock=lambda: clock[0]))
        low, high = 1, (1 << 64) - 1
        self.assertEqual(tracing.keep(low, status=200, error_class=None, dur_ms=5), (True, 'ratio'))
        self.assertEqual(tracing.keep(high, status=200, error_class=None, dur_ms=5), (False, 'ratio'))
        self.assertEqual(tracing.keep(high, status=404, error_class='not_found', dur_ms=5), (False, 'ratio'))
        self.assertEqual(tracing.keep(high, status=401, error_class='auth', dur_ms=5), (True, 'error'))
        self.assertEqual(tracing.keep(high, status=200, error_class=None, dur_ms=1500), (True, 'slow'))
        self.assertEqual(tracing.keep(high, status=403, error_class='forbidden', dur_ms=5), (False, 'budget_exhausted'))
        clock[0] = 1.0
        self.assertEqual(tracing.keep(high, status=401, error_class='auth', dur_ms=5), (True, 'error'))

    def test_auth_flood_cannot_spend_the_server_error_budget(self):
        clock = [0.0]
        tracing = Tracing(None, 0.0, TraceBudget(per_second=1, burst=1, clock=lambda: clock[0]),
                          TraceBudget(per_second=1, burst=2, clock=lambda: clock[0]))
        self.assertEqual(tracing.keep(9, status=401, error_class='auth', dur_ms=5), (True, 'error'))
        for _ in range(50):
            self.assertEqual(tracing.keep(9, status=401, error_class='auth', dur_ms=5), (False, 'budget_exhausted'))
        # A WebSocket or client report that ends in 5xx or an exception is an error, not a forced trace.
        self.assertEqual(tracing.keep(9, status=500, error_class='server', dur_ms=5, forced=True), (True, 'error'))
        self.assertEqual(tracing.keep(9, status=0, error_class='server', dur_ms=5), (True, 'error'))
        self.assertEqual(tracing.keep(9, status=503, error_class='server', dur_ms=5), (False, 'budget_exhausted'))
        self.assertEqual((tracing.budget.exhausted, tracing.error_budget.exhausted), (50, 1))

    def test_requests_sharing_a_caller_trace_id_decide_separately(self):
        from api_tracing import remote_parent

        exporter = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        provider.add_span_processor(TailSampler(SimpleSpanProcessor(exporter)))
        tracer = provider.get_tracer('test')
        parent = remote_parent(0xabc, 0xdef)
        kept_root = tracer.start_span('kept', context=parent)
        dropped_root = tracer.start_span('dropped', context=parent)
        for root, name in ((kept_root, 'kept-child'), (dropped_root, 'dropped-child')):
            with tracer.start_as_current_span(name, context=trace.set_span_in_context(root)):
                pass
        dropped_root.set_attribute('wegoh.trace.kept', False)
        dropped_root.end()
        with tracer.start_as_current_span('late-child', context=trace.set_span_in_context(kept_root)):
            pass
        kept_root.set_attribute('wegoh.trace.kept', True)
        kept_root.end()
        spans = exporter.get_finished_spans()
        self.assertEqual([span.name for span in spans], ['kept-child', 'late-child', 'kept'])
        self.assertEqual({span.context.trace_id for span in spans}, {0xabc})
        provider.shutdown()

    def test_active_long_session_is_not_evicted_by_short_requests(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        sampler = TailSampler(SimpleSpanProcessor(exporter), max_traces=2, max_spans=8)
        provider.add_span_processor(sampler)
        tracer = provider.get_tracer('test')
        session = tracer.start_span('WS /v1/events')
        within = trace.set_span_in_context(session)
        for index in range(6):
            with tracer.start_as_current_span('message', context=within):
                pass
            with tracer.start_as_current_span('short', end_on_exit=False):
                with tracer.start_as_current_span('query'):
                    pass
        session.set_attribute('wegoh.trace.kept', True)
        session.end()
        self.assertEqual([span.name for span in exporter.get_finished_spans()], ['message'] * 6 + ['WS /v1/events'])
        self.assertEqual(sampler.dropped_spans, 5)
        provider.shutdown()

    def test_children_follow_root_decision_and_buffers_are_bounded(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        sampler = TailSampler(SimpleSpanProcessor(exporter), max_traces=2, max_spans=2)
        provider.add_span_processor(sampler)
        tracer = provider.get_tracer('test')
        for kept in (False, True):
            with tracer.start_as_current_span('root', end_on_exit=False) as root:
                for name in ('a', 'b', 'c'):
                    with tracer.start_as_current_span(name):
                        pass
                root.set_attribute('wegoh.trace.kept', kept)
                root.end()
        self.assertEqual([span.name for span in exporter.get_finished_spans()], ['a', 'b', 'root'])
        self.assertEqual(sampler.dropped_spans, 2)
        for index in range(4):
            with tracer.start_as_current_span('orphan-root', end_on_exit=False):
                with tracer.start_as_current_span('child'):
                    pass
        self.assertLessEqual(len(sampler.pending), 2)
        provider.shutdown()


if __name__ == '__main__':
    logging.basicConfig()
    unittest.main()
