"""Fixed installed ASGI barrier, run by the existing unprivileged service UID.

The operator installs this same module outside releases so old and rollback
applications are covered. An unconfigured ordinary dev server is unchanged.
Health proof is observation, never authorization or evidence of DB migration.
"""
import asyncio
import importlib
import json
import os
import pwd
from pathlib import Path
import re
import stat
import sys
import uuid

VERSION = 1
REVISION = re.compile(r'[a-f0-9]{40}')
OPERATION = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}')
GATE_PATH = Path('/opt/wegoh-live/traffic-gate.json')
HEALTH = frozenset(('/health/live', '/health/ready'))
OPERATION_READS = frozenset(('/v1/operations/deployment', '/v1/operations/releases', '/v1/operations/deployment-plan'))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate gate field')
        result[key] = value
    return result


def trusted_owners(path):
    path = Path(path)
    if path == GATE_PATH:
        owners = {0, pwd.getpwnam('wegohdeploy').pw_uid}
        directories = path.parents
    else:
        # Explicit constructor paths are isolated developer/test instances.
        owners = {os.geteuid()}
        if path.parent.absolute() != path.parent.resolve(strict=True):
            return None
        directories = (path.parent,)
    for directory in directories:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in owners:
            return None
    return owners


def read_gate(path):
    try:
        owners = trusted_owners(path)
        if owners is None:
            return None
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_mode & 0o022 or info.st_uid not in owners or not 0 < info.st_size <= 2048):
                return None
            raw = stream.read(2049)
        if len(raw) != info.st_size:
            return None
        value = json.loads(raw, object_pairs_hook=_unique)
        if (type(value) is not dict
                or set(value) != {'format', 'state', 'currentRevision', 'targetRevision', 'operationId'}
                or type(value['format']) is not int or value['format'] != 1
                or value['state'] not in ('open', 'closed')
                or any(type(value[k]) is not str or not REVISION.fullmatch(value[k])
                       for k in ('currentRevision', 'targetRevision'))
                or type(value['operationId']) is not str or not OPERATION.fullmatch(value['operationId'])):
            return None
        return value
    except (OSError, ValueError, TypeError, KeyError):
        return None


def local_probe(scope):
    # No forwarded header grants probe access. Fixed units disable proxy headers.
    client = scope.get('client')
    hosts = [value for key,value in scope.get('headers',()) if key.lower() == b'host']
    return (client is not None and client[0] in ('127.0.0.1','::1')
            and len(hosts) == 1 and hosts[0] in (
                b'127.0.0.1:18082',b'127.0.0.1:18083',
                b'[::1]:18082',b'[::1]:18083'))


class DeploymentGate:
    def __init__(self, app, *, path=None, source_revision=None, readiness=None):
        self.app = app
        self.readiness = readiness
        self.path = os.environ.get('WEGOH_DEPLOYMENT_GATE') if path is None else path
        self.installed = path is None
        self.source_revision = source_revision
        self.instance_id = str(uuid.uuid4())
        self.http = set()
        self.websockets = set()
        self.traffic_admitted = False
        self.watcher = None

    def state(self):
        if self.installed and self.path and Path(self.path) != GATE_PATH:
            return None
        value = read_gate(self.path) if self.path else None
        return value

    def allowed(self, value):
        return (value is not None and value['state'] == 'open'
                and self.source_revision is not None
                and value['currentRevision'] == self.source_revision)

    def proof(self, value):
        return dict(version=VERSION, sourceRevision=self.source_revision,
                    instanceId=self.instance_id, state=value['state'] if value else 'invalid',
                    operationId=value['operationId'] if value else None,
                    activeHTTP=len(self.http), activeWS=len(self.websockets),
                    trafficAdmitted=self.traffic_admitted)

    async def watch(self):
        try:
            while self.websockets:
                if not self.allowed(self.state()):
                    for task in tuple(self.websockets):
                        task.cancel()
                await asyncio.sleep(.1)
        finally:
            self.watcher = None

    async def __call__(self, scope, receive, send):
        kind = scope['type']
        if not self.path or kind not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        value = self.state()
        health = kind == 'http' and scope.get('method') in ('GET', 'HEAD') and scope.get('path') in HEALTH
        if health and scope['path'] == '/health/live' and local_probe(scope):
            body = json.dumps({'status':'alive','deploymentGate':self.proof(value)}, separators=(',', ':')).encode()
            headers = [(b'content-type',b'application/json'),(b'cache-control',b'no-store'),
                       (b'x-wegoh-gate-version',str(VERSION).encode())]
            if self.source_revision:
                headers.append((b'x-wegoh-release',self.source_revision.encode()))
            await send({'type':'http.response.start','status':200,'headers':headers})
            await send({'type':'http.response.body','body':b'' if scope['method']=='HEAD' else body})
            return
        if health and self.readiness is not None and local_probe(scope):
            # Only the imported enrollment app's SELECT-only scope/config check.
            # Never submit a CSR or call the issuer's external API for readiness.
            try:
                issuer_enabled = await asyncio.wait_for(asyncio.to_thread(self.readiness), 2.5)
                if type(issuer_enabled) is not bool:
                    raise RuntimeError('Enrollment readiness unavailable')
                status, body = 200, json.dumps({'status':'ready','checks':'database-scope-and-issuer-configuration',
                    'issuerEnabled':issuer_enabled,'issuerUpstream':'unverified'},separators=(',', ':')).encode()
            except Exception:
                status, body = 503, b'{"status":"unavailable","code":"ENROLLMENT_READINESS_UNAVAILABLE"}'
            headers = [(b'content-type',b'application/json'),(b'cache-control',b'no-store'),(b'x-wegoh-gate-version',b'1')]
            if self.source_revision:
                headers.append((b'x-wegoh-release',self.source_revision.encode()))
            await send({'type':'http.response.start','status':status,'headers':headers})
            await send({'type':'http.response.body','body':b'' if scope['method']=='HEAD' else body})
            return
        if health:
            return await self.app(scope, receive, send)
        if kind == 'http' and scope.get('method') == 'GET' and scope.get('path') in OPERATION_READS:
            # Keep the actual app Host/Access/current-admin/session/query guards.
            # These exact routes perform SELECT-only authority checks and fixed
            # broker reads; they do not admit business traffic or credentials.
            return await self.app(scope, receive, send)
        if not self.allowed(value):
            if kind == 'websocket':
                await send({'type':'websocket.close','code':1013})
            else:
                await send({'type':'http.response.start','status':503,'headers':[
                    (b'content-type',b'application/json'),(b'cache-control',b'no-store'),(b'retry-after',b'5')]})
                await send({'type':'http.response.body','body':b'{"detail":"Service temporarily unavailable"}'})
            return
        task = asyncio.current_task()
        active = self.http if kind == 'http' else self.websockets
        active.add(task)
        self.traffic_admitted = True
        accepted = False
        ended = False
        async def guarded_send(message):
            nonlocal accepted, ended
            if kind == 'websocket':
                if message['type'] == 'websocket.accept':
                    accepted = True
                elif message['type'] == 'websocket.close':
                    ended = True
            await send(message)
        if kind == 'websocket' and self.watcher is None:
            self.watcher = asyncio.create_task(self.watch())
        try:
            await self.app(scope, receive, guarded_send)
        except asyncio.CancelledError:
            if kind == 'websocket' and not self.allowed(self.state()):
                if not ended:
                    try:
                        await send({'type':'websocket.close','code':1012 if accepted else 1013})
                    except (OSError, RuntimeError):
                        pass
                return
            raise
        finally:
            active.discard(task)


def install(app, source_revision=None, readiness=None):
    # The fixed factory has already installed the outer barrier for all releases.
    if os.environ.get('_WEGOH_FIXED_GATE_LOADING') != '1' and os.environ.get('WEGOH_DEPLOYMENT_GATE'):
        app.add_middleware(DeploymentGate, source_revision=source_revision, readiness=readiness)


def enrollment_readiness(entry):
    # These members exist in both the preserved 8ca entrypoint and new releases.
    check_scope = entry.verify_database_scope
    authorization = entry.app.state.native_authorization
    dsn = os.environ.get('WEGOH_DATABASE_DSN','')
    mode = os.environ.get('WEGOH_ENROLLMENT_ISSUER_ENABLED','0')
    def check():
        if not dsn or mode not in ('0','1'):
            raise RuntimeError('Enrollment readiness unavailable')
        check_scope(dsn)
        if mode == '1':
            if authorization.enabled is not True or authorization.auth.enabled is not True or authorization.issuer is None:
                raise RuntimeError('Enrollment readiness unavailable')
            # The actual configured app revalidates its local private credential;
            # the returned value is neither retained, logged nor serialized.
            authorization.issuer._token()
        return mode == '1'
    return check


def _application(module):
    if os.geteuid() == 0:
        raise RuntimeError('Application service must be unprivileged')
    server = Path.cwd().resolve(strict=True)
    release = server.parent
    if server.name != 'server' or not REVISION.fullmatch(release.name):
        raise RuntimeError('Immutable release required')
    manifest = json.loads((release/'RELEASE.json').read_text())
    if manifest.get('commit') != release.name:
        raise RuntimeError('Release identity mismatch')
    if not os.environ.get('WEGOH_DEPLOYMENT_GATE'):
        raise RuntimeError('Installed deployment gate must be configured')
    sys.path.insert(0,str(server))
    os.environ['_WEGOH_FIXED_GATE_LOADING'] = '1'
    try:
        entry = importlib.import_module(module)
        app = entry.app
    finally:
        os.environ.pop('_WEGOH_FIXED_GATE_LOADING',None)
    check = enrollment_readiness(entry) if module == 'enrollment_application' else None
    return DeploymentGate(app, source_revision=release.name, readiness=check)


def api():
    return _application('api_application')


def enrollment():
    return _application('enrollment_application')
