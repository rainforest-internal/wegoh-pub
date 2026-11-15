"""Per-request access, error and client failure records for the journal, VictoriaLogs and traces.

Every HTTP request and WebSocket connection of the API and enrollment apps gets
one ``wegoh_access_v1`` JSON line, including rejections before routing,
exceptions and streamed responses. Exceptions additionally get a
``wegoh_error_v1`` line, and authenticated client failure reports a
``wegoh_client_event_v1`` line. All three share ``req_id`` and ``trace_id``.

Lines carry route templates, status, machine error codes and short HMAC
pseudonyms only: never raw account/device/trip IDs, IPs, tokens, query
strings, coordinates, titles, bodies or exception messages.

This module stays standard-library only at import time: the collector and the
archive job load its decoders from the release with the system Python.
"""
from contextlib import nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import secrets
import traceback
from time import monotonic_ns


ACCESS_PREFIX = 'wegoh_access_v1 '
ERROR_PREFIX = 'wegoh_error_v1 '
CLIENT_EVENT_PREFIX = 'wegoh_client_event_v1 '
_ACCESS_LOG = logging.getLogger('uvicorn.error.wegoh_access')
_ERROR_LOG = logging.getLogger('uvicorn.error.wegoh_error')
_CLIENT_LOG = logging.getLogger('uvicorn.error.wegoh_client_event')

REQUEST_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{7,63}')
TRACE_ID = re.compile(r'[0-9a-f]{32}')
SPAN_ID = re.compile(r'[0-9a-f]{16}')
_TRACEPARENT = re.compile(r'00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}')
_CLIENT_HEADER = re.compile(r'(android|ios|web)/([0-9][0-9A-Za-z.+-]{0,31})')
_IOS_AGENT = re.compile(r'WegoH/([0-9][0-9A-Za-z.+-]{0,31}) CFNetwork/')
_ERROR_CODE = re.compile(r'[A-Z][A-Z0-9_]{1,63}')
_SERVER_DIR = Path(__file__).resolve().parent
# Observation wrappers are never the failure location.
_OBSERVER_FILES = frozenset(('api_observability.py', 'api_quality_metrics.py', 'api_tracing.py'))

SURFACES = ('native', 'iphone', 'web', 'enroll', 'social', 'internal')
ERROR_CLASSES = ('auth', 'forbidden', 'not_found', 'validation', 'conflict', 'rate_limited', 'server',
                 'client_closed')
PLATFORMS = ('android', 'ios', 'web')
_SURFACE_PLATFORM = {'native': 'android', 'iphone': 'ios'}
_STATUS_CLASSES = {401: 'auth', 403: 'forbidden', 404: 'not_found', 405: 'not_found', 409: 'conflict',
                   410: 'conflict', 412: 'conflict', 428: 'conflict', 429: 'rate_limited', 499: 'client_closed'}
_WS_CLOSE_CLASSES = {1008: 'forbidden', 1011: 'server', 1013: 'server', 1006: 'client_closed',
                     4401: 'auth', 4403: 'forbidden', 4404: 'not_found', 4409: 'conflict', 4429: 'rate_limited'}
STATIC_ROUTE = '/{static_file}'
UNMATCHED_ROUTE = 'unmatched'


class RequestRecord:
    """Mutable per-request context shared with handlers, worker threads and tracing."""

    __slots__ = ('app', 'surface', 'method', 'route', 'req_id', 'trace_id', 'span_id', 'account', 'device',
                 'client_platform', 'client_version', 'force_trace', 'logged_errors', 'pending_errors')

    def __init__(self, app, surface, method, req_id):
        self.app, self.surface, self.method, self.req_id = app, surface, method, req_id
        self.route = None
        self.trace_id = self.span_id = None
        self.account = self.device = None
        self.client_platform = self.client_version = None
        self.force_trace = False
        self.logged_errors = set()
        self.pending_errors = []


_CURRENT = ContextVar('wegoh_request_record', default=None)


def current_request():
    return _CURRENT.get()


def note_identity(account=None, device=None):
    """Record the authenticated principal; only its pseudonym is ever written."""
    record = _CURRENT.get()
    if record is None:
        return
    if isinstance(account, str) and account:
        record.account = account
    if isinstance(device, str) and device:
        record.device = device


class Pseudonyms:
    """Short keyed pseudonyms: stable per server secret, not reversible without it."""

    def __init__(self, secret):
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError('Pseudonym secret unavailable')
        self.key = hmac.new(secret.encode('utf-8'), b'WegoH observability pseudonym v1', hashlib.sha256).digest()

    def __call__(self, kind, value):
        if not isinstance(value, str) or not value:
            return None
        return hmac.new(self.key, kind.encode('ascii') + b'\0' + value.encode('utf-8'), hashlib.sha256).hexdigest()[:12]


def new_request_id():
    return secrets.token_hex(16)


def request_id(value):
    return value if isinstance(value, str) and REQUEST_ID.fullmatch(value) else new_request_id()


def parse_traceparent(value):
    match = _TRACEPARENT.fullmatch(value) if isinstance(value, str) else None
    if not match or not int(match[1], 16) or not int(match[2], 16):
        return None
    return int(match[1], 16), int(match[2], 16)


def client_identity(headers, surface):
    """Platform and app version from X-WegoH-Client, else the surface and the iOS user agent."""
    match = _CLIENT_HEADER.fullmatch(headers.get('x-wegoh-client', ''))
    if match:
        return match[1], match[2]
    platform = _SURFACE_PLATFORM.get(surface)
    agent = headers.get('user-agent', '')
    version = None
    ios = _IOS_AGENT.search(agent)
    if ios:
        platform, version = 'ios', ios[1]
    elif platform is None and agent.startswith('Mozilla/'):
        platform = 'web'
    return platform, version


def error_class(status):
    if status >= 500:
        return 'server'
    if status < 400:
        return None
    return _STATUS_CLASSES.get(status, 'validation')


def error_code(body):
    """Machine code from {"detail": CODE}, {"error": CODE} or {"error": {"code": CODE}} only."""
    try:
        value = json.loads(bytes(body))
    except (ValueError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    for candidate in (value.get('error'), value.get('detail'), value.get('code')):
        if isinstance(candidate, dict):
            candidate = candidate.get('code')
        if isinstance(candidate, str) and _ERROR_CODE.fullmatch(candidate):
            return candidate
    return None


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _emit(logger, prefix, payload):
    logger.info('%s%s', prefix, json.dumps({key: value for key, value in payload.items() if value is not None},
                                           separators=(',', ':'), ensure_ascii=True))


def _frames(error):
    rows = []
    for frame in traceback.extract_tb(error.__traceback__):
        path = Path(frame.filename)
        try:
            relative = path.resolve().relative_to(_SERVER_DIR).as_posix()
        except (ValueError, OSError):
            relative = None
        if relative not in _OBSERVER_FILES:
            rows.append((relative, frame))
    return rows


def log_error(error, *, handled, status=None, record=None):
    """One wegoh_error_v1 per exception: type, innermost server frame and a short frame list.

    Inside a request the line is written when the request ends, with its final route and status.
    """
    record = record or _CURRENT.get()
    if record is not None:
        if id(error) in record.logged_errors:
            return
        record.logged_errors.add(id(error))
        record.pending_errors.append((error, handled))
        return
    _write_error(error, handled=handled, status=status, record=None)


def _write_error(error, *, handled, status, record):
    frames = _frames(error)
    own = [(path, frame) for path, frame in frames if path is not None]
    location = own[-1] if own else (frames[-1] if frames else None)
    cause = error.__cause__ or error.__context__
    sqlstate = getattr(error, 'sqlstate', None) or getattr(cause, 'sqlstate', None)
    payload = dict(
        ts=_timestamp(), app=None if record is None else record.app,
        surface=None if record is None else record.surface,
        method=None if record is None else record.method, route=None if record is None else record.route,
        req_id=None if record is None else record.req_id, trace_id=None if record is None else record.trace_id,
        span_id=None if record is None else record.span_id,
        exc_type=type(error).__name__[:64], cause_type=None if cause is None else type(cause).__name__[:64],
        sqlstate=sqlstate if isinstance(sqlstate, str) and re.fullmatch(r'[0-9A-Z]{5}', sqlstate) else None,
        status=status, handled=handled,
        location=None if location is None else f'{location[0] or Path(location[1].filename).name}:{location[1].lineno}',
        function=None if location is None else location[1].name[:64],
        stack=[f'{path or Path(frame.filename).name}:{frame.name}:{frame.lineno}'[:120]
               for path, frame in (own or frames)[-12:]])
    _emit(_ERROR_LOG, ERROR_PREFIX, payload)


def log_client_event(fields):
    record = _CURRENT.get()
    payload = dict(ts=_timestamp())
    if record is not None:
        payload.update(app=record.app, surface=record.surface, req_id=record.req_id, trace_id=record.trace_id,
                       client_platform=record.client_platform, client_version=record.client_version)
    payload.update(fields)
    _emit(_CLIENT_LOG, CLIENT_EVENT_PREFIX, payload)


class RouteTemplates:
    """FastAPI path templates resolved from the app's effective routes, never from raw paths."""

    def __init__(self, app):
        self.app = app
        self._rows = None

    def rows(self):
        if self._rows is None:
            from fastapi.routing import iter_route_contexts
            from starlette.routing import Mount, compile_path

            rows = []
            for context in iter_route_contexts(self.app.routes):
                path = context.path
                if not isinstance(path, str) or not path.startswith('/') or isinstance(context.original_route, Mount):
                    continue
                methods = context.methods
                rows.append(('websocket' if methods is None else 'http', compile_path(path)[0],
                             frozenset(methods or ()), path))
            self._rows = rows
        return self._rows

    def templates(self):
        return {(method, path) for kind, _, methods, path in self.rows() if kind == 'http'
                for method in methods if method not in ('HEAD', 'OPTIONS')} | {
               ('WS', path) for kind, _, _, path in self.rows() if kind == 'websocket'}

    def match(self, kind, method, path):
        partial = None
        for row_kind, pattern, methods, template in self.rows():
            if row_kind != kind or not pattern.match(path):
                continue
            if kind == 'websocket' or method in methods:
                return template
            partial = partial or template
        return partial


def _headers(scope):
    values = {}
    for name, value in scope.get('headers') or ():
        key = name.decode('latin-1').lower()
        if key not in values:
            values[key] = value.decode('latin-1')
    return values


def _host(headers):
    host = headers.get('host', '').lower()
    if host.startswith('['):
        return host.split(']', 1)[0] + ']'
    return host.rsplit(':', 1)[0] if host.count(':') == 1 else host


class HostSurfaces:
    """Surface from the exact configured host; social is the /v1/social API on web or native hosts."""

    def __init__(self, *, iphone=(), native=(), web=(), default='web'):
        self.iphone = frozenset(host.lower() for host in iphone if host)
        self.native = frozenset(host.lower() for host in native if host)
        self.web = frozenset(host.lower() for host in web if host)
        self.default = default

    def __call__(self, host, path):
        if host in self.iphone:
            return 'iphone'
        if path == '/v1/social' or path.startswith('/v1/social/'):
            return 'social'
        if host in self.native:
            return 'native'
        if host in ('127.0.0.1', 'localhost', '[::1]'):
            return 'internal'
        return self.default


class AccessLog:
    """Outermost ASGI middleware: request id, trace continuation, access line and server span."""

    def __init__(self, app, *, application, routes, surfaces, pseudonyms, tracing=None):
        self.app, self.application, self.routes = app, application, routes
        self.surfaces, self.pseudonyms, self.tracing = surfaces, pseudonyms, tracing

    async def __call__(self, scope, receive, send):
        kind = scope['type']
        if kind not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        headers = _headers(scope)
        method = scope.get('method', 'GET') if kind == 'http' else 'WS'
        path = scope.get('path', '')
        record = RequestRecord(self.application, self.surfaces(_host(headers), path), method,
                               request_id(headers.get('x-request-id')))
        record.client_platform, record.client_version = client_identity(headers, record.surface)
        parent = parse_traceparent(headers.get('traceparent'))
        started = monotonic_ns()
        state = dict(status=None, complete=False, disconnected=False, capture=False, body=bytearray(),
                     accepted_at=None, close_code=None, ws_event=None)

        async def tracked_receive():
            message = await receive()
            if message['type'] == 'http.disconnect':
                state['disconnected'] = True
            elif message['type'] == 'websocket.disconnect':
                state['disconnected'] = True
                if state['close_code'] is None:
                    state['close_code'] = message.get('code', 1005)
            return message

        def response_headers(message):
            extra = [(b'x-request-id', record.req_id.encode('ascii'))]
            if record.trace_id:
                extra.append((b'traceresponse', f'00-{record.trace_id}-{record.span_id}-00'.encode('ascii')))
            return dict(message, headers=[*message.get('headers', ()), *extra])

        async def tracked_send(message):
            kind_ = message['type']
            accepted = False
            if kind_ == 'http.response.start':
                state['status'] = message['status']
                content_type = next((value for name, value in message.get('headers', ())
                                     if name.lower() == b'content-type'), b'')
                state['capture'] = message['status'] >= 400 and b'json' in content_type.lower()
                message = response_headers(message)
            elif kind_ == 'http.response.body':
                if state['capture'] and len(state['body']) < 2048:
                    state['body'].extend(message.get('body', b'')[:2048 - len(state['body'])])
                if not message.get('more_body', False):
                    state['complete'] = True
            elif kind_ == 'websocket.accept':
                state['status'], state['accepted_at'], accepted = 101, monotonic_ns(), True
                self._route(record, state, scope, kind, path)
                message = response_headers(message)
            elif kind_ == 'websocket.close':
                state['close_code'] = message.get('code', 1000)
                if state['accepted_at'] is None:
                    state['status'] = 403
            elif kind_ == 'websocket.http.response.start':
                state['status'] = message['status']
                message = response_headers(message)
            try:
                await send(message)
            except OSError:
                state['disconnected'] = True
                raise
            if accepted:
                self._log(record, state, started, ws_event='accept')

        token = _CURRENT.set(record)
        span_context = nullcontext()
        if self.tracing is not None:
            from api_tracing import remote_parent, server_span

            span_context = server_span(self.tracing.tracer, method + ' request',
                                       parent=None if parent is None else remote_parent(*parent),
                                       attributes={'http.request.method': method, 'wegoh.app': self.application,
                                                   'wegoh.surface': record.surface,
                                                   'wegoh.request_id': record.req_id})
        error = None
        try:
            with span_context as span:
                if span is not None:
                    from api_tracing import span_ids

                    ids = span_ids(span)
                    record.trace_id, record.span_id = ids.get('trace_id'), ids.get('span_id')
                try:
                    await self.app(scope, tracked_receive, tracked_send)
                except BaseException as raised:
                    error = raised
                    raise
                finally:
                    self._finish(record, state, started, scope, kind, path, error, span)
        finally:
            _CURRENT.reset(token)

    def _route(self, record, state, scope, kind, path):
        route = getattr(scope.get('route'), 'path', None)
        if not isinstance(route, str) or not route.startswith('/'):
            route = self.routes.match(kind, record.method, path)
        if route is None:
            route = STATIC_ROUTE if kind == 'http' and state['status'] is not None and state['status'] < 400 \
                else UNMATCHED_ROUTE
        record.route = route

    def _finish(self, record, state, started, scope, kind, path, error, span):
        self._route(record, state, scope, kind, path)
        cancelled = error is not None and not isinstance(error, Exception)
        if error is not None and not cancelled:
            log_error(error, handled=False, record=record)
        if state['status'] is None:
            state['status'] = 499 if (cancelled or state['disconnected']) else 500
        for pending, handled in record.pending_errors:
            _write_error(pending, handled=handled, status=state['status'], record=record)
        if kind == 'websocket':
            state['ws_event'] = 'reject' if state['accepted_at'] is None else 'close'
        if span is not None:
            self._end_span(record, state, started, kind, span, error)
        self._log(record, state, started, ws_event=state['ws_event'])

    def _classify(self, record, state, kind):
        status = state['status']
        klass = error_class(status)
        if kind == 'http' and state['disconnected'] and not state['complete']:
            klass = 'client_closed'
        if kind == 'websocket' and state['accepted_at'] is not None:
            klass = _WS_CLOSE_CLASSES.get(state['close_code'])
        return klass

    def _end_span(self, record, state, started, kind, span, error):
        from opentelemetry.trace import StatusCode

        status = state['status']
        dur_ms = (monotonic_ns() - started) // 1_000_000
        klass = self._classify(record, state, kind)
        code = error_code(state['body']) if state['body'] else None
        span.update_name(f'{record.method} {record.route}')
        attributes = {'http.route': record.route, 'http.response.status_code': status,
                      'wegoh.error_class': klass, 'wegoh.error_code': code,
                      'wegoh.client.platform': record.client_platform, 'wegoh.client.version': record.client_version,
                      'wegoh.acct_h': self.pseudonyms('account', record.account),
                      'wegoh.device_h': self.pseudonyms('device', record.device),
                      'wegoh.ws.close_code': state['close_code']}
        span.set_attributes({key: value for key, value in attributes.items() if value is not None})
        if status >= 500 or (error is not None and isinstance(error, Exception)):
            span.set_attribute('error.type', type(error).__name__ if error is not None else str(status))
            span.set_status(StatusCode.ERROR)
        kept, reason = self.tracing.keep(span.get_span_context().trace_id, status=status, error_class=klass,
                                         dur_ms=dur_ms, forced=record.force_trace or kind == 'websocket')
        span.set_attribute('wegoh.trace.kept', kept)
        span.set_attribute('wegoh.trace.reason', reason)
        state['trace_kept'] = kept
        span.end()

    def _log(self, record, state, started, *, ws_event=None):
        now = monotonic_ns()
        kind = 'websocket' if record.method == 'WS' else 'http'
        status = state['status'] if state['status'] is not None else 101
        accepted_at = state['accepted_at']
        payload = dict(
            ts=_timestamp(), app=record.app, surface=record.surface, method=record.method,
            route=record.route or UNMATCHED_ROUTE,
            status=status, dur_ms=(now - started) // 1_000_000, req_id=record.req_id,
            trace_id=record.trace_id, span_id=record.span_id, trace_kept=state.get('trace_kept'),
            error_code=error_code(state['body']) if state['body'] else None,
            error_class=None if ws_event == 'accept' else self._classify(record, state, kind),
            client_platform=record.client_platform, client_version=record.client_version,
            acct_h=self.pseudonyms('account', record.account), device_h=self.pseudonyms('device', record.device),
            ws_event=ws_event, ws_close_code=state['close_code'] if ws_event in ('close', 'reject') else None,
            ws_dur_ms=(now - accepted_at) // 1_000_000 if ws_event == 'close' and accepted_at else None)
        _emit(_ACCESS_LOG, ACCESS_PREFIX, payload)


def capture_identities(auth):
    """Note the principal every authenticated request resolves, on the live auth instance."""
    def wrap(owner, name, extract):
        original = getattr(owner, name, None)
        if original is None:
            return

        def invoke(*args, **kwargs):
            identity = original(*args, **kwargs)
            if isinstance(identity, dict):
                note_identity(*extract(identity))
            return identity
        setattr(owner, name, invoke)

    wrap(auth, 'device', lambda identity: (identity.get('id'), identity.get('deviceId')))
    wrap(auth, 'edge_identity', lambda identity: (identity.get('id'), None))
    sessions = getattr(auth, 'iphone_sessions', None)
    if sessions is not None:
        wrap(sessions, 'authenticate', lambda identity: (identity.get('id'), None))


def record_boundary_errors(owner, name, *, expected=()):
    """Log non-HTTP exceptions a boundary raises before a middleware turns them into a 503."""
    original = getattr(owner, name)

    def invoke(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except Exception as error:
            if not _expected(error, expected):
                log_error(error, handled=True)
            raise
    setattr(owner, name, invoke)


def _expected(error, expected):
    status = getattr(error, 'status_code', getattr(error, 'status', None))
    return isinstance(error, expected) or (type(status) is int and status < 500)


def record_handled_errors(app, classes=()):
    """Log exceptions that exception handlers convert into responses.

    Existing handlers are wrapped; classes without a handler get one that logs
    and re-raises, so an outer middleware still produces its own response.
    HTTPException is logged only when it is a 5xx (its cause names the failure).
    """
    from fastapi.exceptions import ValidationException

    def wrap(handler):
        async def invoke(request, error):
            status = getattr(error, 'status_code', getattr(error, 'status', None))
            if not isinstance(error, ValidationException) and not _expected(error, ()):
                log_error(error, handled=True, status=status if type(status) is int else None)
            return await handler(request, error) if _is_coroutine(handler) else handler(request, error)
        return invoke

    for key, handler in list(app.exception_handlers.items()):
        if key in (Exception, 500):
            continue
        app.exception_handlers[key] = wrap(handler)
    for klass in classes:
        if klass not in app.exception_handlers:
            async def reraise(request, error):
                log_error(error, handled=True)
                raise error
            app.exception_handlers[klass] = reraise


def _is_coroutine(handler):
    import inspect

    return inspect.iscoroutinefunction(handler)


def install(app, *, application, secret, surfaces, tracing=None, auth=None, error_classes=(), serve=None):
    """Observe a FastAPI app; return the ASGI callable to serve (``serve`` wraps ``app`` when given)."""
    if auth is not None:
        capture_identities(auth)
    record_handled_errors(app, error_classes)
    if tracing is not None:
        from api_tracing import instrument_http_client, instrument_psycopg

        instrument_psycopg()
        instrument_http_client()
    access = AccessLog(serve or app, application=application, routes=RouteTemplates(app),
                       surfaces=surfaces, pseudonyms=Pseudonyms(secret), tracing=tracing)
    # Readiness checks read entry.app.state from the served object.
    access.state = app.state
    return access


# ---- Journal decoding for the collector (standard library only) ----

_JOURNAL_EVENT = re.compile(r'(?:INFO:\s+)?(wegoh_(?:access|error|client_event)_v1) (\{.{2,6000}\})')
_TS = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z')
_TEMPLATE = re.compile(r'/[A-Za-z0-9/_{}.:-]{0,199}|unmatched')
_METHOD = re.compile(r'GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS|WS')
_PSEUDONYM = re.compile(r'[0-9a-f]{12}')
_VERSION = re.compile(r'[0-9][0-9A-Za-z.+-]{0,31}')
_LOCATION = re.compile(r'[A-Za-z0-9_./-]{1,120}:[0-9]{1,6}')
_FRAME = re.compile(r'[A-Za-z0-9_./<>-]{1,100}:[A-Za-z0-9_<>]{1,64}:[0-9]{1,6}')
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
_DECODE_PATH = re.compile(r'[A-Za-z0-9_$.\[\]*-]{1,160}')


def _string(pattern):
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def _enum(values):
    return lambda value: value in values


def _integer(low, high):
    return lambda value: type(value) is int and low <= value <= high


def _boolean(value):
    return type(value) is bool


_COMMON = dict(ts=_string(_TS), app=_enum(('api', 'enroll')), surface=_enum(SURFACES),
               req_id=_string(REQUEST_ID), trace_id=_string(TRACE_ID), span_id=_string(SPAN_ID),
               client_platform=_enum(PLATFORMS), client_version=_string(_VERSION))
SCHEMAS = {
    'wegoh_access_v1': (frozenset(('ts', 'app', 'surface', 'method', 'route', 'status', 'dur_ms', 'req_id')), dict(
        _COMMON, method=_string(_METHOD), route=_string(_TEMPLATE), status=_integer(100, 599),
        dur_ms=_integer(0, 86_400_000), trace_kept=_boolean, error_code=_string(_ERROR_CODE),
        error_class=_enum(ERROR_CLASSES), acct_h=_string(_PSEUDONYM), device_h=_string(_PSEUDONYM),
        ws_event=_enum(('accept', 'reject', 'close')), ws_close_code=_integer(0, 4999),
        ws_dur_ms=_integer(0, 86_400_000 * 7))),
    'wegoh_error_v1': (frozenset(('ts', 'exc_type', 'handled')), dict(
        _COMMON, method=_string(_METHOD), route=_string(_TEMPLATE), exc_type=_string(_NAME),
        cause_type=_string(_NAME), sqlstate=_string(re.compile(r'[0-9A-Z]{5}')), status=_integer(100, 599),
        handled=_boolean, location=_string(_LOCATION), function=_string(re.compile(r'[A-Za-z0-9_<>]{1,64}')),
        stack=lambda value: type(value) is list and len(value) <= 12 and all(
            isinstance(item, str) and _FRAME.fullmatch(item) for item in value))),
    'wegoh_client_event_v1': (frozenset(('ts', 'kind', 'target_method', 'target_route')), dict(
        _COMMON, acct_h=_string(_PSEUDONYM), device_h=_string(_PSEUDONYM),
        kind=_enum(('network_error', 'timeout', 'invalid_response', 'http_error', 'cancelled')),
        target_method=_string(_METHOD), target_route=_string(_TEMPLATE), ref_req_id=_string(REQUEST_ID),
        ref_trace_id=_string(TRACE_ID), http_status=_integer(100, 599), decode_path=_string(_DECODE_PATH),
        decode_rule=_enum(('missing', 'type', 'format', 'range', 'enum', 'length', 'unknown', 'syntax')),
        elapsed_ms=_integer(0, 600_000))),
}
EVENT_NAMES = {'wegoh_access_v1': 'wegoh.access', 'wegoh_error_v1': 'wegoh.error',
               'wegoh_client_event_v1': 'wegoh.client_event'}


def decode_journal_event(message):
    """Return (schema, fields) for one of the three fixed schemas, else None."""
    if not isinstance(message, str):
        return None
    match = _JOURNAL_EVENT.fullmatch(message.rstrip('\r\n'))
    if not match:
        return None
    try:
        value = json.loads(match[2])
    except (ValueError, RecursionError):
        return None
    required, validators = SCHEMAS[match[1]]
    if type(value) is not dict or not required <= value.keys() or not value.keys() <= validators.keys():
        return None
    if not all(validators[key](item) for key, item in value.items()):
        return None
    return match[1], value


def log_record(schema, fields, service):
    """VictoriaLogs JSON line for a decoded event; the API's own ts is kept as event time."""
    if schema not in SCHEMAS or service not in ('wegoh-live-api', 'wegoh-live-enrollment'):
        return None
    row = {'@timestamp': fields['ts'], 'service.name': service, 'event.name': EVENT_NAMES[schema],
           'schema': schema}
    row.update({key: value for key, value in fields.items() if key != 'ts'})
    if 'stack' in row:
        row['stack'] = ' < '.join(reversed(row['stack']))
    return row
