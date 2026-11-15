"""In-process course originals contract; synthetic metadata and content, no live DB."""
import asyncio
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException, Request, Response
from fastapi.openapi.utils import _get_api_route_for_openapi
from fastapi.routing import iter_route_contexts
from studio import create_router


class CourseOriginalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.content = Path(self.temporary.name)
        self.raw = json.dumps({'id': 'synthetic-course', 'version': 1, 'title': '합성 코스'}).encode()
        self.checksum = hashlib.sha256(self.raw).hexdigest()
        (self.content / self.checksum).write_bytes(self.raw)
        auth = SimpleNamespace(enabled=True, browser=Mock(return_value={'id': 'synthetic-creator'}))
        self.router = create_router('synthetic-dsn', self.content, auth)
        self.request = Request({'type': 'http', 'method': 'GET', 'scheme': 'https',
                                'server': ('review.invalid', 443), 'path': '/', 'headers': []})
        self.connect = self.enterContext(patch('studio.psycopg.connect'))
        self.connection = self.connect.return_value.__enter__.return_value

    def endpoint(self, path):
        # Included routers stay lazy; resolve the effective routes FastAPI itself serves.
        routes = (_get_api_route_for_openapi(context) for context in iter_route_contexts(self.router.routes))
        return next(route.endpoint for route in routes if route is not None and route.path == path and 'GET' in route.methods)

    def test_original_routes_preserve_exact_bytes_and_prevent_transforms(self):
        self.connection.execute.return_value.fetchone.return_value = (self.checksum,)
        for prefix in ('moderation/', 'studio/', ''):
            with self.subTest(prefix=prefix):
                endpoint = self.endpoint('/v1/' + prefix + 'packs/{pack_id}/versions/{version}')
                args = {'pack_id': 'synthetic-course', 'version': 1}
                if prefix:
                    args['request'] = self.request
                response = endpoint(**args)
                self.assertEqual(response.body, self.raw)
                self.assertIn('no-transform', response.headers['cache-control'].split(', '))
                if prefix != 'studio/':
                    self.assertEqual(response.headers['etag'], '"' + self.checksum + '"')
                if prefix == 'studio/':
                    self.assertIn('private', response.headers['cache-control'])

    def test_moderation_queue_includes_stored_title(self):
        title = '<img src=x onerror=alert(1)> 합성 코스'
        self.connection.execute.return_value.fetchall.return_value = [
            ('synthetic-course', 1, self.checksum, 'quarantined', title)]
        response = Response()
        result = self.endpoint('/v1/moderation/packs')(self.request, response)
        self.assertEqual(result['packs'], [{'id': 'synthetic-course', 'version': 1,
                                          'checksum': self.checksum, 'state': 'quarantined', 'title': title}])
        self.assertIn('p.title', self.connection.execute.call_args.args[0])
        self.assertEqual(response.headers['cache-control'], 'private, no-store')


class CourseOriginalApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.raw = json.dumps({'id': 'synthetic-course', 'version': 1, 'title': '합성 코스'}).encode()
        self.checksum = hashlib.sha256(self.raw).hexdigest()
        (directory / self.checksum).write_bytes(self.raw)
        members = directory / 'members.json'
        members.write_text(json.dumps([{'email': 'synthetic@example.invalid', 'name': 'Synthetic', 'role': 'admin'}]))
        members.chmod(0o600)
        self.enterContext(patch.dict(os.environ, {
            'WEGOH_AUTH_MODE': 'cloudflare', 'WEGOH_API_KEY': 'synthetic-application-test-key-' + 'x' * 32,
            'WEGOH_DATABASE_DSN': 'synthetic-dsn', 'WEGOH_CONTENT_DIR': str(directory),
            'WEGOH_PUBLIC_ORIGIN': 'https://web.wegoh.invalid',
            'WEGOH_ACCESS_ISSUER': 'https://synthetic.cloudflareaccess.com',
            'WEGOH_ACCESS_AUD': 'synthetic-audience-for-isolated-tests',
            'WEGOH_TEAM_MEMBERS_FILE': str(members),
        }, clear=True))
        spec = importlib.util.spec_from_file_location('course_original_application', Path(__file__).with_name('app.py'))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.boundary = self.enterContext(patch.object(self.module.TEAM_AUTH, 'boundary'))
        self.enterContext(patch.object(self.module.TEAM_AUTH, 'browser', return_value={'id': 'synthetic-creator'}))
        self.connect = self.enterContext(patch('studio.psycopg.connect'))
        connection = self.connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = (self.checksum,)
        connection.execute.return_value.fetchall.return_value = []

    def get(self, path):
        async def request():
            messages = []
            received = False

            async def receive():
                nonlocal received
                if not received:
                    received = True
                    return {'type': 'http.request', 'body': b'', 'more_body': False}
                await asyncio.Future()

            async def send(message):
                messages.append(message)

            await self.module.app({
                'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                'http_version': '1.1', 'scheme': 'https', 'method': 'GET', 'path': path,
                'raw_path': path.encode(), 'query_string': b'', 'root_path': '',
                'server': ('web.wegoh.invalid', 443), 'client': ('127.0.0.1', 12345),
                'headers': [(b'host', b'web.wegoh.invalid')],
            }, receive, send)
            start = next(message for message in messages if message['type'] == 'http.response.start')
            headers = {key.decode(): value.decode() for key, value in start['headers']}
            body = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
            return start['status'], headers, body

        return asyncio.run(request())

    def test_shared_originals_keep_no_transform_after_actual_app_middleware(self):
        for prefix in ('moderation/', 'studio/', ''):
            with self.subTest(prefix=prefix):
                status, headers, raw = self.get('/v1/' + prefix + 'packs/synthetic-course/versions/1')
                self.assertEqual(status, 200)
                self.assertEqual(raw, self.raw)
                self.assertEqual(headers['cache-control'], 'private, no-store, no-transform')
                self.assertEqual(headers['x-content-type-options'], 'nosniff')
                if prefix != 'studio/':
                    self.assertEqual(headers['etag'], '"' + self.checksum + '"')
        self.assertEqual(self.boundary.call_count, 3)

    def test_other_shared_responses_keep_existing_private_cache_policy(self):
        for path in ('/health/live', '/v1/packs', '/v1/studio/packs', '/v1/moderation/packs'):
            with self.subTest(path=path):
                status, headers, _ = self.get(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers['cache-control'], 'private, no-store')

    def test_denied_originals_keep_existing_private_cache_policy(self):
        self.boundary.side_effect = HTTPException(403, 'Synthetic denial')
        for prefix in ('moderation/', 'studio/', ''):
            with self.subTest(prefix=prefix):
                status, headers, _ = self.get('/v1/' + prefix + 'packs/synthetic-course/versions/1')
                self.assertEqual(status, 403)
                self.assertEqual(headers['cache-control'], 'private, no-store')
                self.assertNotIn('etag', headers)


if __name__ == '__main__':
    unittest.main()
