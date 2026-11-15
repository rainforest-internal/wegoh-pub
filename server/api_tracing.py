"""Opt-in OpenTelemetry spans for every API request, its PostgreSQL queries and outbound HTTP calls.

Every request is recorded in process. When its server span ends, the access
middleware decides whether the whole trace is exported: failures that need
action (401, 403, 5xx), slow requests, WebSocket sessions and client failure
reports are always kept (bounded by per-second budgets; 5xx and exceptions have
their own so an authentication flood cannot crowd them out), other requests by a
trace-id ratio. The unit of decision is the server root span, so two requests
that continue the same caller trace id are kept or dropped independently. Span attributes never contain identifiers, SQL text, URLs,
coordinates or bodies.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import logging
from math import isfinite
import os
import re
from threading import Lock
from time import monotonic

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.trace import (NonRecordingSpan, SpanContext, SpanKind, StatusCode, TraceFlags,
                                 format_span_id, format_trace_id)


_LOG = logging.getLogger('uvicorn.error.wegoh_api_tracing')
_ACTIVE_TRACER = ContextVar('wegoh_api_tracer', default=None)
_LOOPBACK_OTLP = re.compile(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})/insert/opentelemetry/v1/traces')
KEEP_ATTRIBUTE = 'wegoh.trace.kept'
SLOW_MS = 1000
# Classes whose every occurrence needs a reachable trace. 404/409/422 stay ratio-sampled.
MUST_KEEP_CLASSES = frozenset(('auth', 'forbidden', 'server'))
_RATIO_MASK = (1 << 64) - 1


class TraceBudget:
    """Token bucket for always-kept traces so a 401 flood cannot exhaust trace storage."""

    def __init__(self, per_second=1.0, burst=600.0, clock=monotonic):
        self.per_second, self.burst, self.clock = per_second, burst, clock
        self.tokens, self.updated = burst, clock()
        self.lock = Lock()
        self.exhausted = 0

    def take(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.per_second)
            self.updated = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            self.exhausted += 1
            return False


class Tracing:
    def __init__(self, tracer, sample_rate, budget=None, error_budget=None):
        self.tracer = tracer
        self.sample_rate = sample_rate
        self.bound = round(sample_rate * (_RATIO_MASK + 1))
        # 401/403, slow, WebSocket and forced traces share one budget; 5xx and exceptions have their own.
        self.budget = budget or TraceBudget()
        self.error_budget = error_budget or TraceBudget()

    def keep(self, trace_id, *, status, error_class, dur_ms, forced=False):
        """Return the export decision and the reason recorded on the server span."""
        budget = self.budget
        if status >= 500 or error_class == 'server':
            reason, budget = 'error', self.error_budget
        elif forced:
            reason = 'forced'
        elif error_class in MUST_KEEP_CLASSES:
            reason = 'error'
        elif dur_ms >= SLOW_MS:
            reason = 'slow'
        elif (trace_id & _RATIO_MASK) < self.bound:
            return True, 'ratio'
        else:
            return False, 'ratio'
        if budget.take():
            return True, reason
        return (trace_id & _RATIO_MASK) < self.bound, 'budget_exhausted'


class TailSampler(SpanProcessor):
    """Buffer child spans until their local root ends, then export or drop that root's spans.

    A root is a span without a parent or with a remote one, keyed by (trace_id, span_id): callers may
    reuse a trace id, so each server span decides only for the spans started beneath it. Pending
    buffers are evicted least recently active first, so a long WebSocket session that keeps adding
    spans is not pushed out by short requests, and its own spans are capped by max_spans.
    """

    def __init__(self, delegate, *, max_traces=1024, max_spans=128):
        self.delegate, self.max_traces, self.max_spans = delegate, max_traces, max_spans
        self.max_open = max_traces * 8
        self.pending, self.decided, self.owner = {}, {}, {}
        self.lock = Lock()
        self.dropped_spans = 0

    def on_start(self, span, parent_context=None):
        context, parent = span.context, span.parent
        key = (context.trace_id, context.span_id)
        with self.lock:
            if parent is None or parent.is_remote:
                root = key
            else:
                root = self.owner.get((context.trace_id, parent.span_id))
            self.owner[key] = root
            while len(self.owner) > self.max_open:
                self.owner.pop(next(iter(self.owner)))

    def on_end(self, span):
        context, parent = span.context, span.parent
        key = (context.trace_id, context.span_id)
        forward = ()
        with self.lock:
            root = self.owner.pop(key, None)
            if parent is None or parent.is_remote:
                kept = span.attributes.get(KEEP_ATTRIBUTE) is True
                children = self.pending.pop(key, [])
                self.decided[key] = kept
                while len(self.decided) > self.max_traces:
                    self.decided.pop(next(iter(self.decided)))
                if kept:
                    forward = (*children, span)
            elif root is None:
                # Its root is unknown (started before this processor or evicted): never guess a trace.
                self.dropped_spans += 1
            elif root in self.decided:
                if self.decided[root]:
                    forward = (span,)
            else:
                children = self.pending.pop(root, None)
                if children is None:
                    if len(self.pending) >= self.max_traces:
                        self.dropped_spans += len(self.pending.pop(next(iter(self.pending))))
                    children = []
                self.pending[root] = children
                if len(children) < self.max_spans:
                    children.append(span)
                else:
                    self.dropped_spans += 1
        for item in forward:
            self.delegate.on_end(item)

    def shutdown(self):
        self.delegate.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.delegate.force_flush(timeout_millis)


def tracing_from_environment():
    endpoint = os.environ.get('WEGOH_TRACES_ENDPOINT', '')
    if not endpoint:
        return None
    try:
        address = _LOOPBACK_OTLP.fullmatch(endpoint)
        sample_rate = float(os.environ.get('WEGOH_TRACES_SAMPLE_RATE', '0.1'))
        if not address or int(address[1]) > 65535 or not isfinite(sample_rate) or not 0 <= sample_rate <= 1:
            raise ValueError()
    except ValueError:
        _LOG.warning('API tracing disabled: invalid loopback endpoint or sample rate')
        return None

    try:
        from opentelemetry.exporter.otlp.proto.http import Compression
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON
        import requests

        class LoopbackSession(requests.Session):
            def get_redirect_target(self, response):
                return None

        session = LoopbackSession()
        session.trust_env = False
        exporter = OTLPSpanExporter(endpoint=endpoint, timeout=2, session=session,
                                    compression=Compression.Gzip, max_request_size=262_144)
        service = os.environ.get('WEGOH_TRACES_SERVICE_NAME', 'wegoh-live-api')
        if service not in ('wegoh-live-api', 'wegoh-live-enrollment'):
            service = 'wegoh-live-api'
        # ALWAYS_ON ignores a caller's sampled flag; TailSampler makes the export decision.
        provider = TracerProvider(resource=Resource({'service.name': service}), sampler=ALWAYS_ON)
        provider.add_span_processor(TailSampler(BatchSpanProcessor(
            exporter, max_queue_size=2048, max_export_batch_size=256, schedule_delay_millis=1000)))
    except Exception:
        _LOG.warning('API tracing disabled: could not initialize OTLP/HTTP export')
        return None
    return Tracing(provider.get_tracer('wegoh.api'), sample_rate)


def tracer_from_environment():
    tracing = tracing_from_environment()
    return None if tracing is None else tracing.tracer


def remote_parent(trace_id, span_id):
    """A validated W3C traceparent continues the caller's trace id, never its sampling decision.

    The caller's flags are replaced: the span is always recorded and TailSampler decides export.
    """
    parent = SpanContext(trace_id, span_id, is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED))
    return trace.set_span_in_context(NonRecordingSpan(parent), Context())


@contextmanager
def server_span(tracer, name, *, parent=None, attributes=None):
    """Start the request's server span and make it current for handlers, threads and dependencies."""
    span = tracer.start_span(name, context=parent if parent is not None else Context(), kind=SpanKind.SERVER,
                             attributes=attributes, record_exception=False, set_status_on_exception=False)
    token = _ACTIVE_TRACER.set(tracer)
    try:
        with trace.use_span(span, end_on_exit=False, record_exception=False, set_status_on_exception=False):
            yield span
    finally:
        _ACTIVE_TRACER.reset(token)


def span_ids(span):
    context = span.get_span_context()
    if not context.is_valid:
        return {}
    return {'trace_id': format_trace_id(context.trace_id), 'span_id': format_span_id(context.span_id)}


def _mark_internal_error(span, error=None):
    span.set_attribute('error.type', 'internal_error' if error is None else type(error).__name__)
    span.set_status(StatusCode.ERROR)


def observe_response(span, status):
    if not span.is_recording():
        return {}
    span.set_attribute('http.response.status_code', status)
    if status >= 500:
        span.set_attribute('error.type', str(status))
        span.set_status(StatusCode.ERROR)
    return span_ids(span)


@contextmanager
def traced_operation(name, *, kind=SpanKind.INTERNAL, attributes=None):
    tracer = _ACTIVE_TRACER.get()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name, kind=kind, attributes=attributes,
                                      record_exception=False, set_status_on_exception=False) as span:
        try:
            yield span
        except Exception as error:
            # Expected HTTP rejections are covered by the request's status, not dependency failures.
            status = getattr(error, 'status_code', getattr(error, 'status', None))
            if type(status) is not int or not 400 <= status < 500:
                _mark_internal_error(span, error)
            raise


def _traced_method(method, name, *, kind=SpanKind.INTERNAL, attributes=None):
    @wraps(method)
    def invoke(*args, **kwargs):
        with traced_operation(name, kind=kind, attributes=attributes):
            return method(*args, **kwargs)
    return invoke


def instrument_iphone_dependencies(auth):
    """Bind observers to live instances without changing the auth transition contract."""
    sessions = auth.iphone_sessions
    sessions.authenticate = _traced_method(sessions.authenticate, 'iphone.session.authenticate')
    auth.current_account = _traced_method(auth.current_account, 'account.read')
    auth.rate = _traced_method(auth.rate, 'rate_limit.check')


_SQL_OPERATIONS = frozenset(('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH', 'CREATE', 'ALTER', 'DROP', 'LOCK',
                             'BEGIN', 'COMMIT', 'ROLLBACK', 'SET', 'DO', 'TRUNCATE', 'COPY', 'SAVEPOINT', 'RELEASE'))
_SQL_KEYWORD = re.compile(r'\s*\(?\s*([A-Za-z]+)')
_SQL_TABLE = re.compile(r'\b(?:FROM|INTO|UPDATE|JOIN|TABLE)\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]{0,62})\b', re.I)
# Set-returning functions and keywords that can follow FROM/JOIN but are not tables.
_SQL_SKIP = frozenset(('select', 'only', 'lateral', 'unnest', 'jsonb_to_recordset', 'jsonb_array_elements',
                       'jsonb_each', 'generate_series', 'values'))


def query_attributes(query):
    """Statement shape only: first keyword, first table and a short hash of the placeholder text."""
    if isinstance(query, bytes):
        text = query.decode('utf-8', 'replace')
    elif isinstance(query, str):
        text = query
    else:
        text = None
    attributes = {'db.system.name': 'postgresql'}
    if text is None:
        attributes['db.operation.name'] = 'COMPOSED'
        return attributes
    keyword = _SQL_KEYWORD.match(text)
    operation = keyword[1].upper() if keyword and keyword[1].upper() in _SQL_OPERATIONS else 'OTHER'
    attributes['db.operation.name'] = operation
    table = next((match[1].lower() for match in _SQL_TABLE.finditer(text) if match[1].lower() not in _SQL_SKIP), None)
    if table:
        attributes['db.collection.name'] = table
    attributes['db.query.summary'] = operation + (' ' + table if table else '')
    attributes['wegoh.db.statement_hash'] = hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]
    return attributes


def instrument_psycopg():
    """Wrap psycopg's connect and cursor execution once per process."""
    import psycopg

    if getattr(psycopg.Cursor.execute, '_wegoh_traced', False):
        return
    execute, executemany = psycopg.Cursor.execute, psycopg.Cursor.executemany
    connect = psycopg.Connection.__dict__['connect'].__func__

    def traced_execute(self, query, params=None, **kwargs):
        attributes = query_attributes(query)
        with traced_operation('postgresql ' + attributes.get('db.query.summary', attributes['db.operation.name']),
                              kind=SpanKind.CLIENT, attributes=attributes) as span:
            result = execute(self, query, params, **kwargs)
            if span is not None and type(self.rowcount) is int and self.rowcount >= 0:
                span.set_attribute('db.response.returned_rows', self.rowcount)
            return result

    def traced_executemany(self, query, params_seq, **kwargs):
        attributes = query_attributes(query)
        with traced_operation('postgresql ' + attributes.get('db.query.summary', attributes['db.operation.name']),
                              kind=SpanKind.CLIENT, attributes=attributes):
            return executemany(self, query, params_seq, **kwargs)

    def traced_connect(cls, *args, **kwargs):
        with traced_operation('postgresql.connect', kind=SpanKind.CLIENT,
                              attributes={'db.system.name': 'postgresql'}):
            return connect(cls, *args, **kwargs)

    traced_execute._wegoh_traced = True
    psycopg.Cursor.execute = traced_execute
    psycopg.Cursor.executemany = traced_executemany
    psycopg.Connection.connect = classmethod(traced_connect)
    psycopg.connect = psycopg.Connection.connect


# Only fixed provider hosts are named; any other destination (for example a link preview) is "external".
_KNOWN_HOSTS = ('kakao.com', 'kakaomobility.com', 'api.cloudflare.com', 'data.go.kr', 'opinet.co.kr')


def _host_label(host):
    host = (host or '').lower()
    return host if any(host == known or host.endswith('.' + known) for known in _KNOWN_HOSTS) else 'external'


def instrument_http_client():
    """One CLIENT span per http.client request/response exchange; never the path or query."""
    import http.client

    connection = http.client.HTTPConnection
    if getattr(connection.request, '_wegoh_traced', False):
        return
    request, getresponse, close = connection.request, connection.getresponse, connection.close

    def finish(self, *, status=None, error=None):
        span = self.__dict__.pop('_wegoh_span', None)
        if span is None:
            return
        if status is not None:
            span.set_attribute('http.response.status_code', status)
            if status >= 400:
                span.set_attribute('error.type', str(status))
                span.set_status(StatusCode.ERROR)
        if error is not None:
            _mark_internal_error(span, error)
        span.end()

    def traced_request(self, method, url, *args, **kwargs):
        tracer = _ACTIVE_TRACER.get()
        if tracer is not None:
            finish(self)
            self._wegoh_span = tracer.start_span(
                'HTTP ' + str(method), kind=SpanKind.CLIENT, record_exception=False, set_status_on_exception=False,
                attributes={'http.request.method': str(method), 'server.address': _host_label(self.host),
                            'server.port': int(self.port or self.default_port)})
        try:
            return request(self, method, url, *args, **kwargs)
        except Exception as error:
            finish(self, error=error)
            raise

    def traced_getresponse(self):
        # getresponse closes a will-close connection itself; that close must not end the span early.
        self._wegoh_responding = True
        try:
            response = getresponse(self)
        except Exception as error:
            finish(self, error=error)
            raise
        finally:
            self.__dict__.pop('_wegoh_responding', None)
        finish(self, status=response.status)
        return response

    def traced_close(self):
        if not self.__dict__.get('_wegoh_responding'):
            finish(self)
        return close(self)

    traced_request._wegoh_traced = True
    connection.request = traced_request
    connection.getresponse = traced_getresponse
    connection.close = traced_close
