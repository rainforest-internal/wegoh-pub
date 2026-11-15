"""Owned temporary files and real asyncio/loopback transport; no DB, credentials or TLS claim.

Counters prove ASGI admission/drain only. They do not prove worker threads or
separate services stopped, nor authorize deployment or database migration.
"""
import asyncio
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import deployment_gate as gate_module
from deployment_gate import DeploymentGate, read_gate

SOURCE = 'a' * 40
TARGET = 'b' * 40
OPERATION = '12345678-1234-4123-8123-123456789abc'


def gate_value(state='open', **changes):
    value = dict(format=1, state=state, currentRevision=SOURCE,
                 targetRevision=TARGET, operationId=OPERATION)
    value.update(changes)
    return value


def write_gate(path, value):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def http_scope(path='/business', method='GET'):
    return dict(type='http', asgi={'version': '3.0'}, http_version='1.1',
                method=method, scheme='http', path=path, raw_path=path.encode(),
                query_string=b'', headers=[(b'host', b'127.0.0.1:18082')], server=('127.0.0.1', 80), client=('127.0.0.1', 1))


def websocket_scope():
    return dict(type='websocket', asgi={'version': '3.0'}, scheme='ws', path='/events',
                raw_path=b'/events', query_string=b'', headers=[], subprotocols=[])


async def invoke(app, scope):
    messages = []
    async def receive():
        return {'type': 'websocket.connect'} if scope['type'] == 'websocket' else {
            'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message):
        messages.append(message)
    await app(scope, receive, send)
    return messages


def body(messages):
    return b''.join(message.get('body', b'') for message in messages
                    if message['type'] == 'http.response.body')


class DeploymentGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wegoh-gate-test-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'gate.json'
        self.calls = []
        async def app(scope, receive, send):
            self.calls.append(scope['type'])
            if scope['type'] == 'http':
                await send({'type': 'http.response.start', 'status': 209, 'headers': []})
                await send({'type': 'http.response.body', 'body': b'application-ready'})
            elif scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1000})
        self.app = app
        self.gate = DeploymentGate(app, path=str(self.path), source_revision=SOURCE)

    async def asyncTearDown(self):
        if self.gate.watcher is not None:
            self.gate.watcher.cancel()
            await asyncio.gather(self.gate.watcher, return_exceptions=True)

    async def assertDenied(self, gate=None):
        gate = gate or self.gate
        messages = await invoke(gate, http_scope())
        self.assertEqual(503, messages[0]['status'])
        self.assertEqual(b'5', dict(messages[0]['headers'])[b'retry-after'])
        self.assertEqual({'detail': 'Service temporarily unavailable'}, json.loads(body(messages)))
        self.assertEqual([{'type': 'websocket.close', 'code': 1013}],
                         await invoke(gate, websocket_scope()))
        self.assertEqual([], self.calls)
        self.assertEqual(0, len(gate.http))
        self.assertEqual(0, len(gate.websockets))

    async def testMissingCorruptAndUnsafeGateFilesFailClosedBeforeWebsocketAccept(self):
        await self.assertDenied()
        invalid = [b'', b'{' , b' ' * 2049,
                   json.dumps(gate_value(format=True)).encode(),
                   json.dumps(gate_value(state='OPEN')).encode(),
                   json.dumps(gate_value(currentRevision=SOURCE.upper())).encode(),
                   json.dumps(gate_value(operationId='12345678-1234-1123-8123-123456789abc')).encode(),
                   json.dumps(gate_value(extra='private-value')).encode(),
                   b'{"format":1,"format":1,"state":"open"}']
        missing = gate_value(); missing.pop('targetRevision')
        invalid.append(json.dumps(missing).encode())
        for raw in invalid:
            with self.subTest(raw=raw[:80]):
                self.path.write_bytes(raw); self.path.chmod(0o600)
                self.assertIsNone(read_gate(self.path))
                await self.assertDenied()
        write_gate(self.path, gate_value())
        self.path.chmod(0o660)
        await self.assertDenied()
        self.path.chmod(0o600)
        actual = self.path.with_name('actual.json'); self.path.rename(actual)
        self.path.symlink_to(actual)
        await self.assertDenied()
        self.path.unlink(); actual.rename(self.path)
        alias = self.path.with_name('hardlink.json'); os.link(self.path, alias)
        await self.assertDenied()
        alias.unlink(); self.path.unlink(); self.path.mkdir()
        await self.assertDenied()

    async def testUnsafeParentAndForeignFileOrParentOwnersFailClosed(self):
        write_gate(self.path, gate_value())
        self.assertEqual(gate_value(), read_gate(self.path))
        parent = self.path.parent
        original_mode = parent.stat().st_mode & 0o777
        try:
            parent.chmod(0o777)
            await self.assertDenied()
        finally:
            parent.chmod(original_mode)
        linked = parent / 'linked-parent'
        linked.symlink_to(parent, target_is_directory=True)
        via_link = DeploymentGate(self.app, path=str(linked / self.path.name), source_revision=SOURCE)
        await self.assertDenied(via_link)
        linked.unlink()

        def foreign_owner(info):
            # Controlled metadata only: no chown or privileged filesystem mutation.
            values = list(info)
            values[4] = os.geteuid() + 10000
            return os.stat_result(values)
        original_fstat = os.fstat
        with patch('deployment_gate.os.fstat', side_effect=lambda fd: foreign_owner(original_fstat(fd))):
            self.assertIsNone(read_gate(self.path))
            await self.assertDenied()
        original_lstat = Path.lstat
        def parent_foreign(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            return foreign_owner(info) if path == parent else info
        with patch.object(Path, 'lstat', parent_foreign):
            self.assertIsNone(read_gate(self.path))
            await self.assertDenied()
        self.assertEqual(gate_value(), read_gate(self.path))

    async def testInstalledEnvironmentMustSelectExactProductionPathWhileExplicitTempStaysUsable(self):
        write_gate(self.path, gate_value())
        with patch.dict(os.environ, {'WEGOH_DEPLOYMENT_GATE': str(self.path)}):
            installed = DeploymentGate(self.app, source_revision=SOURCE)
            self.assertTrue(installed.installed)
            self.assertIsNone(installed.state())
            await self.assertDenied(installed)
            proof = json.loads(body(await invoke(installed, http_scope('/health/live'))))['deploymentGate']
            self.assertEqual('invalid', proof['state'])
            explicit = DeploymentGate(self.app, path=str(self.path), source_revision=SOURCE)
            self.assertFalse(explicit.installed)
            self.assertEqual(gate_value(), explicit.state())
        # Verify exact selector delegation without creating or reading any /opt path.
        with patch.dict(os.environ, {'WEGOH_DEPLOYMENT_GATE': str(gate_module.GATE_PATH)}):
            with patch('deployment_gate.read_gate', return_value=gate_value('closed')) as reader:
                installed = DeploymentGate(self.app, source_revision=SOURCE)
                self.assertEqual(gate_value('closed'), installed.state())
                reader.assert_called_once_with(str(gate_module.GATE_PATH))

    async def testClosedAndOpenWrongSourceRevisionCannotAdmitTraffic(self):
        for value in (gate_value('closed'), gate_value(currentRevision=TARGET)):
            write_gate(self.path, value)
            self.assertEqual(value, read_gate(self.path))
            await self.assertDenied()
        write_gate(self.path, gate_value())
        messages = await invoke(self.gate, http_scope())
        self.assertEqual(209, messages[0]['status'])
        self.assertEqual(['http'], self.calls)
        self.assertTrue(self.gate.traffic_admitted)
        self.assertEqual(0, len(self.gate.http))

    async def testOnlyExactGetHeadHealthBypassesClosedGateAndReadyIsActualApp(self):
        write_gate(self.path, gate_value('closed'))
        for method in ('GET', 'HEAD'):
            messages = await invoke(self.gate, http_scope('/health/live', method))
            self.assertEqual(200, messages[0]['status'])
            headers = dict(messages[0]['headers'])
            self.assertEqual(b'no-store', headers[b'cache-control'])
            self.assertEqual(b'1', headers[b'x-wegoh-gate-version'])
            self.assertEqual(SOURCE.encode(), headers[b'x-wegoh-release'])
            if method == 'HEAD':
                self.assertEqual(b'', body(messages))
            else:
                proof = json.loads(body(messages))['deploymentGate']
                self.assertEqual({'version', 'sourceRevision', 'instanceId', 'state',
                                  'operationId', 'activeHTTP', 'activeWS', 'trafficAdmitted'}, set(proof))
                self.assertEqual(1, proof['version']); self.assertEqual(SOURCE, proof['sourceRevision'])
                self.assertEqual(4, uuid.UUID(proof['instanceId']).version)
                self.assertEqual('closed', proof['state']); self.assertEqual(OPERATION, proof['operationId'])
                self.assertEqual(0, proof['activeHTTP']); self.assertEqual(0, proof['activeWS'])
                self.assertFalse(proof['trafficAdmitted'])
        self.assertEqual([], self.calls)
        for method in ('GET', 'HEAD'):
            messages = await invoke(self.gate, http_scope('/health/ready', method))
            self.assertEqual(209, messages[0]['status'])
            self.assertEqual(b'application-ready', body(messages))
        self.assertEqual(['http', 'http'], self.calls)
        for path, method in (('/health/live', 'POST'), ('/health/ready', 'POST'),
                             ('/health/live/', 'GET'), ('/health/lively', 'GET')):
            messages = await invoke(self.gate, http_scope(path, method))
            self.assertEqual(503, messages[0]['status'])
        self.assertEqual(['http', 'http'], self.calls)
        self.path.unlink()
        proof = json.loads(body(await invoke(self.gate, http_scope('/health/live'))))['deploymentGate']
        self.assertEqual('invalid', proof['state']); self.assertIsNone(proof['operationId'])
        self.assertEqual(0, proof['activeHTTP'])

    async def testUntrustedHealthCannotObtainSyntheticProofThroughHostOrForwardedSpoof(self):
        write_gate(self.path, gate_value('closed'))
        seen = []
        async def original_guard(scope, receive, send):
            seen.append(scope)
            await send({'type': 'http.response.start', 'status': 400, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'original-host-auth-guard'})
        gate = DeploymentGate(original_guard, path=str(self.path), source_revision=SOURCE)
        cases = [
            {'headers': [(b'host', b'evil.invalid')]},
            {'headers': []},
            {'headers': [(b'host', b'127.0.0.1:18082'), (b'host', b'evil.invalid')]},
            {'headers': [(b'host', b'127.0.0.1:18082'), (b'host', b'127.0.0.1:18082')]},
            {'headers': [(b'host', b'127.0.0.1:8080')]},
            {'client': ('203.0.113.7', 1234)},
            {'client': None},
            {'client': ('203.0.113.7', 1234), 'headers': [(b'host', b'127.0.0.1:18082'),
                (b'x-forwarded-for', b'127.0.0.1'), (b'forwarded', b'for=127.0.0.1')]},
            {'headers': [(b'host', b'evil.invalid'), (b'x-forwarded-host', b'127.0.0.1:18082')]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                scope = http_scope('/health/live'); scope.update(changes)
                messages = await invoke(gate, scope)
                self.assertEqual(400, messages[0]['status'])
                self.assertNotIn(b'x-wegoh-gate-version', dict(messages[0]['headers']))
                self.assertEqual(b'original-host-auth-guard', body(messages))
        self.assertEqual(len(cases), len(seen))
        self.assertFalse(gate.traffic_admitted)
        for host, client in ((b'127.0.0.1:18083', '127.0.0.1'), (b'[::1]:18082', '::1')):
            scope = http_scope('/health/live')
            scope.update(headers=[(b'Host', host)], client=(client, 1234))
            messages = await invoke(gate, scope)
            self.assertEqual(200, messages[0]['status'])
            self.assertIn('deploymentGate', json.loads(body(messages)))

    async def testClosedGateDelegatesOnlyExactOperationGetsToOriginalGuardsWithoutAdmission(self):
        write_gate(self.path, gate_value('closed'))
        seen, response_status = [], [401]
        async def original_guard(scope, receive, send):
            # Controlled guard outcomes; this does not simulate TeamAuth or prove admin authority.
            seen.append(scope)
            await send({'type': 'http.response.start', 'status': response_status[0],
                        'headers': [(b'x-original-guard', b'preserved')]})
            await send({'type': 'http.response.body', 'body': b'original-guard-response'})
        gate = DeploymentGate(original_guard, path=str(self.path), source_revision=SOURCE)
        paths = ('/v1/operations/deployment', '/v1/operations/releases', '/v1/operations/deployment-plan')
        for path in paths:
            for status in (401, 403, 200):
                with self.subTest(path=path, original_status=status):
                    scope = http_scope(path)
                    scope['query_string'] = b'currentRevision=synthetic%2Fquery&detail=1&detail=2'
                    scope['headers'] = [(b'host', b'original-app-host.invalid')]
                    response_status[0] = status
                    messages = await invoke(gate, scope)
                    self.assertEqual(status, messages[0]['status'])
                    self.assertEqual(b'preserved', dict(messages[0]['headers'])[b'x-original-guard'])
                    self.assertNotIn(b'x-wegoh-gate-version', dict(messages[0]['headers']))
                    self.assertEqual(b'original-guard-response', body(messages))
                    self.assertIs(scope, seen[-1])
                    self.assertEqual(b'currentRevision=synthetic%2Fquery&detail=1&detail=2', seen[-1]['query_string'])
                    self.assertEqual([(b'host', b'original-app-host.invalid')], seen[-1]['headers'])
                    self.assertEqual((0, 0), (len(gate.http), len(gate.websockets)))
                    self.assertFalse(gate.traffic_admitted)
        delegated = len(seen)
        blocked = [(path, method) for path in paths for method in ('HEAD', 'POST')]
        blocked += [(path, 'GET') for path in (
            '/v1/operations/deployment/', '/v1/operations/deployment/extra',
            '/prefix/v1/operations/deployment', '/v1/operations/deployment-plan-extra',
            '/v1/social/overview')]
        blocked.append(('/v1/auth/login', 'POST'))
        for path, method in blocked:
            with self.subTest(blocked_path=path, method=method):
                self.assertEqual(503, (await invoke(gate, http_scope(path, method)))[0]['status'])
        for path in paths:
            scope = websocket_scope(); scope['path'] = path; scope['raw_path'] = path.encode()
            self.assertEqual([{'type': 'websocket.close', 'code': 1013}], await invoke(gate, scope))
        self.assertEqual(delegated, len(seen))
        proof = json.loads(body(await invoke(gate, http_scope('/health/live'))))['deploymentGate']
        self.assertEqual((0, 0), (proof['activeHTTP'], proof['activeWS']))
        self.assertFalse(proof['trafficAdmitted'])

    async def testHttpCountRemainsUntilAppReturnsWhileNewTrafficIsDenied(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def held(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'response-already-sent'})
            entered.set()
            await finish.wait()
        gate = DeploymentGate(held, path=str(self.path), source_revision=SOURCE)
        write_gate(self.path, gate_value())
        task = asyncio.create_task(invoke(gate, http_scope()))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            write_gate(self.path, gate_value('closed'))
            proof = json.loads(body(await invoke(gate, http_scope('/health/live'))))['deploymentGate']
            self.assertEqual(1, proof['activeHTTP']); self.assertTrue(proof['trafficAdmitted'])
            self.assertFalse(task.done())
            self.assertEqual(503, (await invoke(gate, http_scope()))[0]['status'])
            finish.set()
            self.assertEqual(200, (await asyncio.wait_for(task, 1))[0]['status'])
            self.assertEqual(0, gate.proof(gate.state())['activeHTTP'])
        finally:
            finish.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def testAcceptedWebsocketCloses1012AndRunsAppFinallyWhenGateCloses(self):
        accepted, cleaned = asyncio.Event(), asyncio.Event()
        messages = []
        async def application(scope, receive, send):
            await receive()
            try:
                await send({'type': 'websocket.accept'})
                accepted.set()
                await asyncio.Future()
            finally:
                cleaned.set()
        async def receive(): return {'type': 'websocket.connect'}
        async def send(message): messages.append(message)
        gate = DeploymentGate(application, path=str(self.path), source_revision=SOURCE)
        write_gate(self.path, gate_value())
        task = asyncio.create_task(gate(websocket_scope(), receive, send))
        try:
            await asyncio.wait_for(accepted.wait(), 1)
            self.assertEqual(1, gate.proof(gate.state())['activeWS'])
            write_gate(self.path, gate_value('closed'))
            await asyncio.wait_for(task, 2)
            self.assertTrue(cleaned.is_set())
            self.assertEqual([{'type': 'websocket.accept'}, {'type': 'websocket.close', 'code': 1012}], messages)
            self.assertEqual(0, gate.proof(gate.state())['activeWS'])
            await asyncio.sleep(.15)
            self.assertIsNone(gate.watcher)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if gate.watcher:
                gate.watcher.cancel(); await asyncio.gather(gate.watcher, return_exceptions=True)

    async def testUnsetEnvironmentRetainsOrdinaryDevelopmentAppBehavior(self):
        with patch.dict(os.environ):
            os.environ.pop('WEGOH_DEPLOYMENT_GATE', None)
            gate = DeploymentGate(self.app, source_revision=None)
            self.assertIsNone(gate.path)
            self.assertEqual(209, (await invoke(gate, http_scope('/health/live', 'POST')))[0]['status'])
            self.assertEqual([{'type': 'websocket.close', 'code': 1000}], await invoke(gate, websocket_scope()))
            self.assertFalse(gate.traffic_admitted)
            class App:
                def add_middleware(self, *args, **kwargs):
                    raise AssertionError('Unconfigured development must not add a gate')
            gate_module.install(App(), SOURCE)


class EnrollmentReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wegoh-readiness-test-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'gate.json'
        write_gate(self.path, gate_value('closed'))

    async def testLocalReadinessUsesWorkerAndFixedSafeFailureWhilePublicUsesOriginalGuard(self):
        calls, original = [], []
        main_thread = threading.get_ident()
        def check():
            calls.append(threading.get_ident())
            return True
        async def original_app(scope, receive, send):
            original.append(scope)
            await send({'type': 'http.response.start', 'status': 400, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'original-host-auth-guard'})
        gate = DeploymentGate(original_app, path=str(self.path), source_revision=SOURCE, readiness=check)
        messages = await invoke(gate, http_scope('/health/ready'))
        self.assertEqual(200, messages[0]['status'])
        self.assertEqual({'status': 'ready', 'checks': 'database-scope-and-issuer-configuration',
                          'issuerEnabled': True, 'issuerUpstream': 'unverified'}, json.loads(body(messages)))
        self.assertNotEqual(main_thread, calls[0])
        headers = dict(messages[0]['headers'])
        self.assertEqual(b'no-store', headers[b'cache-control'])
        self.assertEqual(SOURCE.encode(), headers[b'x-wegoh-release'])
        messages = await invoke(gate, http_scope('/health/ready', 'HEAD'))
        self.assertEqual(200, messages[0]['status']); self.assertEqual(b'', body(messages))
        self.assertEqual(2, len(calls))
        self.assertFalse(gate.traffic_admitted)
        for changes in ({'headers': [(b'host', b'public.invalid')]},
                        {'client': ('203.0.113.7', 1234)},
                        {'headers': [(b'host', b'127.0.0.1:18082'), (b'host', b'public.invalid')]}):
            scope = http_scope('/health/ready'); scope.update(changes)
            messages = await invoke(gate, scope)
            self.assertEqual(400, messages[0]['status'])
            self.assertEqual(b'original-host-auth-guard', body(messages))
        self.assertEqual(3, len(original)); self.assertEqual(2, len(calls))
        self.assertEqual(503, (await invoke(gate, http_scope('/health/ready', 'POST')))[0]['status'])
        self.assertEqual(200, (await invoke(gate, http_scope('/health/live')))[0]['status'])
        self.assertEqual(2, len(calls))
        def failed(): raise RuntimeError('synthetic-private-credential-and-dsn-must-not-leak')
        failed_gate = DeploymentGate(original_app, path=str(self.path), source_revision=SOURCE, readiness=failed)
        messages = await invoke(failed_gate, http_scope('/health/ready'))
        self.assertEqual(503, messages[0]['status'])
        self.assertEqual({'status': 'unavailable', 'code': 'ENROLLMENT_READINESS_UNAVAILABLE'}, json.loads(body(messages)))
        self.assertNotIn(b'synthetic-private', body(messages))
        messages = await invoke(failed_gate, http_scope('/health/ready', 'HEAD'))
        self.assertEqual(503, messages[0]['status']); self.assertEqual(b'', body(messages))
        disabled_gate = DeploymentGate(original_app, path=str(self.path), source_revision=SOURCE,
                                       readiness=lambda: False)
        disabled = await invoke(disabled_gate, http_scope('/health/ready'))
        self.assertEqual(200, disabled[0]['status'])
        self.assertIs(False, json.loads(body(disabled))['issuerEnabled'])
        for non_boolean in (None, 0, 1, 'true'):
            with self.subTest(non_boolean=non_boolean):
                invalid_gate = DeploymentGate(original_app, path=str(self.path), source_revision=SOURCE,
                    readiness=lambda value=non_boolean: value)
                messages = await invoke(invalid_gate, http_scope('/health/ready'))
                self.assertEqual(503, messages[0]['status'])
                self.assertEqual({'status': 'unavailable', 'code': 'ENROLLMENT_READINESS_UNAVAILABLE'},
                                 json.loads(body(messages)))

    async def testTimeoutBoundsResponseWithoutClaimingBackgroundWorkerStopped(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        def held_check():
            entered.set()
            try:
                release.wait(5)
                return True
            finally: done.set()
        async def no_app(scope, receive, send): raise AssertionError('Local readiness must not call application')
        gate = DeploymentGate(no_app, path=str(self.path), source_revision=SOURCE, readiness=held_check)
        pending = asyncio.create_task(invoke(gate, http_scope('/health/ready')))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            # A live probe remains responsive while the local configuration callback is held.
            self.assertEqual(200, (await invoke(gate, http_scope('/health/live')))[0]['status'])
            messages = await asyncio.wait_for(pending, 4)
            self.assertEqual(503, messages[0]['status'])
            self.assertEqual('ENROLLMENT_READINESS_UNAVAILABLE', json.loads(body(messages))['code'])
            self.assertFalse(done.is_set(), 'A timeout is not evidence that a worker thread or DB operation stopped')
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
            self.assertTrue(await asyncio.to_thread(done.wait, 1))

    async def testCapturedReadinessContextIsStableAndExplicitDisabledModeNeedsNoIssuer(self):
        scopes = []
        disabled = SimpleNamespace(enabled=False, auth=SimpleNamespace(enabled=False), issuer=None)
        entry = SimpleNamespace(verify_database_scope=lambda dsn: scopes.append(dsn),
                                app=SimpleNamespace(state=SimpleNamespace(native_authorization=disabled)))
        with patch.dict(os.environ, {'WEGOH_DATABASE_DSN': 'synthetic-original-scope',
                                    'WEGOH_ENROLLMENT_ISSUER_ENABLED': '0'}):
            check = gate_module.enrollment_readiness(entry)
            os.environ['WEGOH_DATABASE_DSN'] = 'synthetic-replaced-scope'
            os.environ['WEGOH_ENROLLMENT_ISSUER_ENABLED'] = '1'
            entry.verify_database_scope = lambda dsn: self.fail('Must use captured scope verifier')
            entry.app.state.native_authorization = None
            self.assertIs(False, check())
        self.assertEqual(['synthetic-original-scope'], scopes)

    async def testModeOneRequiresLocalAuthorizationAndCredentialWithoutClaimingIssuerUpstream(self):
        scopes, credentials = [], []
        class LocalIssuer:
            def _token(self):
                credentials.append('local-file-check')
                return object()  # The result is ignored; never serialized or logged.
            def issue(self, *args, **kwargs):
                raise AssertionError('Readiness must not send a CSR or call an upstream CA')
        issuer = LocalIssuer()
        def entry_for(authorization):
            return SimpleNamespace(verify_database_scope=lambda dsn: scopes.append(dsn),
                app=SimpleNamespace(state=SimpleNamespace(native_authorization=authorization)))
        good = SimpleNamespace(enabled=True, auth=SimpleNamespace(enabled=True), issuer=issuer)
        with patch.dict(os.environ, {'WEGOH_DATABASE_DSN': 'synthetic-select-only-scope',
                                    'WEGOH_ENROLLMENT_ISSUER_ENABLED': '1'}):
            self.assertIs(True, gate_module.enrollment_readiness(entry_for(good))())
            self.assertEqual(['local-file-check'], credentials)
            bad = [SimpleNamespace(enabled=False, auth=good.auth, issuer=issuer),
                   SimpleNamespace(enabled=True, auth=SimpleNamespace(enabled=False), issuer=issuer),
                   SimpleNamespace(enabled=True, auth=good.auth, issuer=None)]
            for authorization in bad:
                with self.subTest(authorization=authorization):
                    with self.assertRaises(RuntimeError):
                        gate_module.enrollment_readiness(entry_for(authorization))()
            class BadLocalIssuer(LocalIssuer):
                def _token(self): raise RuntimeError('Local credential unavailable')
            with self.assertRaises(RuntimeError):
                gate_module.enrollment_readiness(entry_for(SimpleNamespace(
                    enabled=True, auth=good.auth, issuer=BadLocalIssuer())))()
            self.assertEqual(['local-file-check'], credentials)
            for dsn, mode in (('', '1'), ('synthetic-select-only-scope', 'unexpected')):
                before = list(scopes)
                os.environ['WEGOH_DATABASE_DSN'] = dsn
                os.environ['WEGOH_ENROLLMENT_ISSUER_ENABLED'] = mode
                with self.assertRaises(RuntimeError):
                    gate_module.enrollment_readiness(entry_for(good))()
                self.assertEqual(before, scopes)
        self.assertEqual(['synthetic-select-only-scope'] * 5, scopes)


class DeploymentGateFactoryTests(unittest.TestCase):
    def testFixedFactoriesImportOnlyTheirEntryModulesWithinImmutableRelease(self):
        with tempfile.TemporaryDirectory(prefix='wegoh-factory-test-') as directory:
            release = Path(directory) / SOURCE
            server = release / 'server'; server.mkdir(parents=True)
            (release / 'RELEASE.json').write_text(json.dumps({'commit': SOURCE}))
            for module in ('api_application', 'enrollment_application'):
                (server / (module + '.py')).write_text('\n'.join([
                    'import os', 'from types import SimpleNamespace',
                    'loading = os.environ.get("_WEGOH_FIXED_GATE_LOADING")',
                    'scope_calls = []',
                    'def verify_database_scope(dsn): scope_calls.append(dsn)',
                    'async def app(scope, receive, send): pass',
                    'app.state = SimpleNamespace(native_authorization=SimpleNamespace(',
                    '    enabled=False, auth=SimpleNamespace(enabled=False), issuer=None))',
                ]))
            before, paths = Path.cwd(), sys.path[:]
            try:
                os.chdir(server)
                with patch.dict(os.environ, {'WEGOH_DEPLOYMENT_GATE': str(release / 'gate.json'),
                        'WEGOH_DATABASE_DSN': 'synthetic-factory-scope',
                        'WEGOH_ENROLLMENT_ISSUER_ENABLED': '0'}), patch.dict(sys.modules):
                    sys.modules.pop('api_application', None); sys.modules.pop('enrollment_application', None)
                    for factory, module in ((gate_module.api, 'api_application'),
                                            (gate_module.enrollment, 'enrollment_application')):
                        app = factory()
                        self.assertIsInstance(app, DeploymentGate)
                        self.assertEqual(SOURCE, app.source_revision)
                        self.assertEqual(module, app.app.__module__)
                        self.assertEqual('1', sys.modules[module].loading)
                        if module == 'enrollment_application':
                            self.assertTrue(callable(app.readiness)); self.assertIs(False, app.readiness())
                            self.assertEqual(['synthetic-factory-scope'], sys.modules[module].scope_calls)
                        else:
                            self.assertIsNone(app.readiness)
                        self.assertNotIn('_WEGOH_FIXED_GATE_LOADING', os.environ)
                    with patch('deployment_gate.os.geteuid', return_value=0):
                        with self.assertRaisesRegex(RuntimeError, 'unprivileged'):
                            gate_module.api()
                    (release / 'RELEASE.json').write_text(json.dumps({'commit': TARGET}))
                    with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                        gate_module.enrollment()
                    (release / 'RELEASE.json').write_text(json.dumps({'commit': SOURCE}))
                    os.environ.pop('WEGOH_DEPLOYMENT_GATE')
                    with self.assertRaisesRegex(RuntimeError, 'configured'):
                        gate_module.api()
                    os.chdir(release)
                    with self.assertRaisesRegex(RuntimeError, 'Immutable release'):
                        gate_module.api()
            finally:
                os.chdir(before); sys.path[:] = paths


class DeploymentGateLoopbackTests(unittest.TestCase):
    def testActualHttpDrainAndWebsocket1012OverLoopback(self):
        import uvicorn
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect
        with tempfile.TemporaryDirectory(prefix='wegoh-gate-loopback-') as directory:
            path = Path(directory) / 'gate.json'
            write_gate(path, gate_value())
            entered, release, ws_cleaned = threading.Event(), threading.Event(), threading.Event()
            async def application(scope, receive, send):
                if scope['type'] == 'websocket':
                    await receive()
                    try:
                        await send({'type': 'websocket.accept'})
                        await send({'type': 'websocket.send', 'text': 'accepted'})
                        await asyncio.Future()
                    finally:
                        ws_cleaned.set()
                else:
                    if scope['path'] == '/held':
                        entered.set()
                        while not release.is_set(): await asyncio.sleep(.01)
                    await send({'type': 'http.response.start', 'status': 200, 'headers': []})
                    await send({'type': 'http.response.body', 'body': b'actual-app'})
            gate = DeploymentGate(application, path=str(path), source_revision=SOURCE)
            listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(8)
            port = listener.getsockname()[1]
            config = uvicorn.Config(gate, host='127.0.0.1', port=port, loop='asyncio',
                                    ws='websockets', lifespan='off', proxy_headers=False, access_log=False, log_level='critical')
            server = uvicorn.Server(config)
            worker = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            responses, failures = [], []
            def request(path):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=4)
                try:
                    connection.request('GET', path, headers={'Host': '127.0.0.1:18082'})
                    response = connection.getresponse()
                    return response.status, response.read()
                finally:
                    connection.close()
            def held_request():
                try: responses.append(request('/held'))
                except Exception as failure: failures.append(failure)
            held = threading.Thread(target=held_request, daemon=True)
            worker.start()
            try:
                deadline = time.monotonic() + 4
                while not server.started and worker.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(server.started, 'Owned loopback server must actually listen')
                held.start(); self.assertTrue(entered.wait(2))
                with connect('ws://127.0.0.1:%s/events' % port, proxy=None, open_timeout=2, close_timeout=2) as websocket:
                    self.assertEqual('accepted', websocket.recv(timeout=2))
                    status, raw = request('/health/live')
                    self.assertEqual(200, status)
                    proof = json.loads(raw)['deploymentGate']
                    self.assertEqual((1, 1), (proof['activeHTTP'], proof['activeWS']))
                    write_gate(path, gate_value('closed'))
                    self.assertEqual(503, request('/new')[0])
                    with self.assertRaises(ConnectionClosed) as closed:
                        websocket.recv(timeout=2)
                    self.assertEqual(1012, closed.exception.rcvd.code)
                self.assertTrue(ws_cleaned.wait(1))
                proof = json.loads(request('/health/live')[1])['deploymentGate']
                self.assertEqual((1, 0), (proof['activeHTTP'], proof['activeWS']))
                self.assertTrue(held.is_alive())
                release.set(); held.join(2)
                self.assertFalse(held.is_alive()); self.assertEqual([], failures)
                self.assertEqual([(200, b'actual-app')], responses)
                proof = json.loads(request('/health/live')[1])['deploymentGate']
                self.assertEqual((0, 0), (proof['activeHTTP'], proof['activeWS']))
                self.assertTrue(proof['trafficAdmitted'])
            finally:
                release.set()
                if held.ident is not None: held.join(5)
                server.should_exit = True; worker.join(5)
                listener.close()
            self.assertFalse(worker.is_alive(), 'Owned loopback server must stop')


if __name__ == '__main__':
    unittest.main()
