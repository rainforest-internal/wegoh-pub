"""Every mounted API route writes one access line and one server span with its own template."""
import asyncio
import re
import unittest
from urllib.parse import urlsplit

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from api_observability import ACCESS_PREFIX, AccessLog, HostSurfaces, Pseudonyms, RouteTemplates
from api_tracing import TailSampler, Tracing
from client_diagnostics import NATIVE_PATH
from test_api_observability import SECRET, call, lines, scope
import test_team_auth as fixture

SAMPLE = 'a' * 32


def concrete(template):
    return re.sub(r'\{[^}]+\}', SAMPLE, template)


class MountedRouteTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    async def test_every_route_is_logged_and_traced_with_its_template(self):
        module = fixture.TeamTests.module
        auth = module.TEAM_AUTH
        exporter = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        self.addCleanup(provider.shutdown)
        provider.add_span_processor(TailSampler(SimpleSpanProcessor(exporter)))
        routes = RouteTemplates(module.app)
        web_host = urlsplit(auth.public_origin).hostname
        native_host = urlsplit(auth.native_origin).hostname
        # Ratio 1 exports every trace so each request's server span is observable.
        served = AccessLog(module.app, application='api', routes=routes, pseudonyms=Pseudonyms(SECRET),
                           surfaces=HostSurfaces(native=(native_host,), web=(web_host,)),
                           tracing=Tracing(provider.get_tracer('routes'), 1.0))
        rows = routes.rows()
        self.assertIn(('POST', NATIVE_PATH), routes.templates())
        self.assertGreater(len(rows), 300)
        checked, shadowed = 0, set()
        for kind, _, methods, template in rows:
            path = concrete(template)
            for method in sorted(methods - {'HEAD', 'OPTIONS'}) or ['WS']:
                host = native_host if template.startswith(('/v1/native/', '/v1/device')) else web_host
                request = scope(path, method='GET' if method == 'WS' else method, host=host,
                                kind='websocket' if method == 'WS' else 'http')
                # When an earlier template also matches the sample path, Starlette serves that one.
                expected = routes.match(kind, method, path)
                if expected != template:
                    shadowed.add(template)
                with self.subTest(method=method, template=template):
                    exporter.clear()
                    with self.assertLogs('uvicorn.error', 'INFO') as logs:
                        await call(served, request, timeout=3)
                    access = lines(logs, ACCESS_PREFIX)
                    self.assertGreaterEqual(len(access), 1)
                    final = access[-1]
                    self.assertEqual((final['route'], final['method']), (expected, method))
                    self.assertNotIn(SAMPLE, '\n'.join(record.getMessage() for record in logs.records))
                    servers = [span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]
                    self.assertEqual(len(servers), 1)
                    self.assertEqual(servers[0].attributes['http.route'], final['route'])
                    self.assertEqual(format(servers[0].context.trace_id, '032x'), final['trace_id'])
                    checked += 1
        self.assertGreater(checked, 300)
        self.assertLess(len(shadowed), len(rows) // 10, sorted(shadowed))

    async def test_vehicle_request_to_real_app_records_database_spans(self):
        from api_tracing import instrument_psycopg

        instrument_psycopg()
        module = fixture.TeamTests.module
        exporter = InMemorySpanExporter()
        provider = TracerProvider(shutdown_on_exit=False)
        self.addCleanup(provider.shutdown)
        provider.add_span_processor(TailSampler(SimpleSpanProcessor(exporter)))
        served = AccessLog(module.app, application='api', routes=RouteTemplates(module.app),
                           pseudonyms=Pseudonyms(SECRET), surfaces=HostSurfaces(),
                           tracing=Tracing(provider.get_tracer('db'), 1.0))
        with self.assertLogs('uvicorn.error', 'INFO'):
            request = scope('/health/ready', host='127.0.0.1')
            request['client'] = ('127.0.0.1', 50000)
            await call(served, request)
        names = [span.name for span in exporter.get_finished_spans()]
        self.assertIn('GET /health/ready', names)
        self.assertIn('postgresql.connect', names)
        self.assertIn('postgresql SELECT dev_assets', names)


if __name__ == '__main__':
    unittest.main()
