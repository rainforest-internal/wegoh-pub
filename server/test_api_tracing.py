"""Exercise request spans, dependency spans, private data exclusion and failure isolation."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import os
from threading import BoundedSemaphore, Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
import psycopg
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from api_observability import ACCESS_PREFIX, HostSurfaces, install
from api_quality_metrics import ApiQualityMetrics, decode_journal_message
from api_tracing import (TailSampler, Tracing, instrument_http_client, instrument_iphone_dependencies,
                         instrument_psycopg, query_attributes, tracer_from_environment, tracing_from_environment)
from test_api_observability import SECRET, call, lines
from test_api_quality_metrics import IPHONE_HOST, WEB_HOST, scope
from web_provider import bounded_call


class TracingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = TracerProvider(shutdown_on_exit=False)
        self.addCleanup(self.provider.shutdown)
        self.provider.add_span_processor(TailSampler(SimpleSpanProcessor(self.exporter)))

    async def invoke(self, request, dependency, status, *, rate=1.0, provider=None):
        app = FastAPI()

        async def inner(scope_, receive, send):
            await asyncio.to_thread(dependency)
            await send({'type': 'http.response.start', 'status': status, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'private response'})

        tracer = (provider or self.provider).get_tracer('test')
        quality = ApiQualityMetrics(inner, iphone_host=IPHONE_HOST.decode(), web_host=WEB_HOST.decode())
        served = install(app, application='api', secret=SECRET, tracing=Tracing(tracer, rate),
                         surfaces=HostSurfaces(iphone=(IPHONE_HOST.decode(),), web=(WEB_HOST.decode(),)),
                         serve=quality)
        with self.assertLogs('uvicorn.error', 'INFO') as logs:
            sent = await call(served, request)
        self.assertEqual(sent[0]['status'], status)
        return logs

    async def test_internal_dependencies_inherit_server_span_without_caller_data(self):
        private_trip = 'a' * 32
        request = scope('/v1/iphone/trips/' + private_trip + '/music')
        caller_trace = 'b' * 32
        request['headers'] += [(b'traceparent', f'00-{caller_trace}-{"c"*16}-01'.encode()),
                               (b'baggage', b'account=private-account')]

        def authenticate():
            auth.current_account('private-account', connection=None)
            auth.rate('private-bucket', limit=60)
            return {'id': 'private-account', 'handle': 'private-handle'}

        auth = SimpleNamespace(current_account=lambda *args, **kwargs: None, rate=lambda *args, **kwargs: None,
                               iphone_sessions=SimpleNamespace(authenticate=authenticate))
        instrument_iphone_dependencies(auth)
        logs = await self.invoke(request, auth.iphone_sessions.authenticate, 200)

        spans = {span.name: span for span in self.exporter.get_finished_spans()}
        root = spans.pop('GET /{static_file}')
        self.assertEqual(root.kind, SpanKind.SERVER)
        # The caller's trace id is continued; its sampled flag and baggage are not trusted.
        self.assertEqual(root.context.trace_id, int(caller_trace, 16))
        self.assertTrue(root.parent.is_remote)
        self.assertEqual(root.attributes['wegoh.surface'], 'iphone')
        self.assertEqual(root.attributes['wegoh.trace.reason'], 'ratio')
        session = spans['iphone.session.authenticate']
        self.assertEqual(session.parent.span_id, root.context.span_id)
        for child in ('account.read', 'rate_limit.check'):
            self.assertEqual(spans[child].parent.span_id, session.context.span_id)
        quality = decode_journal_message(next(record.getMessage() for record in logs.records
                                              if record.getMessage().startswith('wegoh_api_quality_v1')))
        access, = lines(logs, ACCESS_PREFIX)
        self.assertEqual(quality['trace_id'], caller_trace)
        self.assertEqual((quality['span_id'], access['span_id']), (access['span_id'], format(root.context.span_id, '016x')))
        stored = '\n'.join(record.getMessage() for record in logs.records) + ''.join(
            span.to_json() for span in self.exporter.get_finished_spans())
        for private in (private_trip, 'private-account', 'private-credential', 'private-query',
                        'private-bucket', 'private response', '192.0.2.23', 'private-agent', 'private-cookie'):
            self.assertNotIn(private, stored)

    async def test_route_provider_worker_thread_keeps_parent_and_hides_exception_content(self):
        class ProviderError(ValueError):
            code, status = 'ROUTE_PROVIDER_UNAVAILABLE', 502

        def raise_provider_error(timeout):
            raise ProviderError('private external URL and coordinates')

        def dependency():
            try:
                bounded_call(raise_provider_error, BoundedSemaphore(1), 1, ProviderError, 'ROUTE', name='test-route')
            except ProviderError:
                pass

        await self.invoke(scope('/v1/iphone/routes/preview', 'POST'), dependency, 502, rate=0.0)
        child, root = self.exporter.get_finished_spans()
        self.assertEqual(child.name, 'route.provider.wait')
        self.assertEqual(child.parent.span_id, root.context.span_id)
        self.assertEqual(child.status.status_code, StatusCode.ERROR)
        self.assertEqual(root.status.status_code, StatusCode.ERROR)
        self.assertEqual(root.attributes['wegoh.trace.reason'], 'error')
        self.assertEqual(child.events, ())
        self.assertNotIn('private', child.to_json())

    async def test_unsampled_success_keeps_structured_logs_without_exporting(self):
        logs = await self.invoke(scope(), lambda: None, 200, rate=0.0)
        access, = lines(logs, ACCESS_PREFIX)
        self.assertIs(access['trace_kept'], False)
        self.assertEqual(self.exporter.get_finished_spans(), ())

    async def test_outbound_http_span_names_only_host_class_and_status(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        instrument_http_client()

        def dependency():
            connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=2)
            connection.request('GET', '/v2/local/geo?x=127.1&y=37.5&query=private-place')
            connection.getresponse().read()
            connection.close()

        await self.invoke(scope('/v1/iphone/places/search'), dependency, 503, rate=0.0)
        outbound = next(span for span in self.exporter.get_finished_spans() if span.kind == SpanKind.CLIENT)
        self.assertEqual(outbound.name, 'HTTP GET')
        self.assertEqual(outbound.attributes['server.address'], 'external')
        self.assertEqual(outbound.attributes['http.response.status_code'], 503)
        self.assertNotIn('private-place', outbound.to_json())
        self.assertNotIn('37.5', outbound.to_json())

    async def test_database_query_spans_show_statement_shape_without_values(self):
        dsn = os.environ.get('WEGOH_DATABASE_DSN')
        if not dsn:
            self.skipTest('PostgreSQL fixture unavailable')
        instrument_psycopg()

        def dependency():
            with psycopg.connect(dsn) as conn:
                conn.execute('SELECT %s::text AS secret_value', ('private-parameter',)).fetchone()
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1 FROM pg_catalog.pg_class WHERE relname=%s', ('private-name',))
                try:
                    conn.execute('SELECT * FROM wegoh_missing_table_for_trace')
                except psycopg.errors.UndefinedTable:
                    pass

        await self.invoke(scope(), dependency, 503, rate=0.0)
        spans = self.exporter.get_finished_spans()
        names = [span.name for span in spans]
        self.assertIn('postgresql.connect', names)
        self.assertIn('postgresql SELECT pg_class', names)
        failed = next(span for span in spans if span.name == 'postgresql SELECT wegoh_missing_table_for_trace')
        self.assertEqual((failed.status.status_code, failed.attributes['error.type']), (StatusCode.ERROR, 'UndefinedTable'))
        root = next(span for span in spans if span.kind == SpanKind.SERVER)
        for span in spans:
            if span is not root:
                self.assertEqual(span.context.trace_id, root.context.trace_id)
            self.assertNotIn('private-parameter', span.to_json())
            self.assertNotIn('private-name', span.to_json())
            self.assertNotIn('secret_value', span.to_json())

    def test_query_attributes_are_shape_only(self):
        self.assertEqual(query_attributes('  select a from team_rooms where id=%s'), {
            'db.system.name': 'postgresql', 'db.operation.name': 'SELECT', 'db.collection.name': 'team_rooms',
            'db.query.summary': 'SELECT team_rooms', 'wegoh.db.statement_hash': query_attributes(
                '  select a from team_rooms where id=%s')['wegoh.db.statement_hash']})
        self.assertEqual(query_attributes(b'INSERT INTO team_rate_limits(scope_hash) VALUES(%s)')['db.query.summary'],
                         'INSERT team_rate_limits')
        self.assertEqual(query_attributes(object())['db.operation.name'], 'COMPOSED')
        self.assertEqual(query_attributes("SELECT 'private literal'")['db.query.summary'], 'SELECT')

    async def test_blocked_export_does_not_gate_following_api_response(self):
        exporting = Event()
        release = Event()

        class BlockedExporter(SpanExporter):
            def export(self, spans):
                exporting.set()
                release.wait(timeout=5)
                return SpanExportResult.FAILURE

            def shutdown(self):
                release.set()

        provider = TracerProvider(shutdown_on_exit=False)
        self.addCleanup(provider.shutdown)
        self.addCleanup(release.set)
        provider.add_span_processor(TailSampler(BatchSpanProcessor(
            BlockedExporter(), max_queue_size=8, max_export_batch_size=1, schedule_delay_millis=1000)))
        await self.invoke(scope(), lambda: None, 401, provider=provider)
        self.assertTrue(await asyncio.to_thread(exporting.wait, 2))
        self.assertFalse(release.is_set())
        await asyncio.wait_for(self.invoke(scope(), lambda: None, 401, provider=provider), timeout=2)
        self.assertFalse(release.is_set())

    def test_settings_disable_invalid_nonlocal_export(self):
        for environment in (
            {},
            {'WEGOH_TRACES_ENDPOINT': 'https://external.invalid/insert/opentelemetry/v1/traces'},
            {'WEGOH_TRACES_ENDPOINT': 'http://127.0.0.1:65536/insert/opentelemetry/v1/traces'},
            {'WEGOH_TRACES_ENDPOINT': 'http://127.0.0.1:10428/insert/opentelemetry/v1/traces',
             'WEGOH_TRACES_SAMPLE_RATE': 'nan'},
            {'WEGOH_TRACES_ENDPOINT': 'http://127.0.0.1:10428/insert/opentelemetry/v1/traces',
             'WEGOH_TRACES_SAMPLE_RATE': '1.5'},
        ):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertIsNone(tracer_from_environment())
        # Rate 0 still exports must-keep traces (errors, slow, WebSocket, client reports).
        with patch.dict(os.environ, {'WEGOH_TRACES_ENDPOINT': 'http://127.0.0.1:10428/insert/opentelemetry/v1/traces',
                                     'WEGOH_TRACES_SAMPLE_RATE': '0'}, clear=True):
            tracing = tracing_from_environment()
            self.assertEqual(tracing.sample_rate, 0)
            self.assertEqual(tracing.keep(1, status=500, error_class='server', dur_ms=1), (True, 'error'))


if __name__ == '__main__':
    unittest.main()
