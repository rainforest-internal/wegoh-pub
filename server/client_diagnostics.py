"""Authenticated client failure reports: where the app gave up on a server exchange.

A vehicle or iPhone reports that a request it sent failed on the client side
(network, timeout, cancellation, an HTTP error it could not handle, or a
response it refused to decode). The report names the route template, the
server's X-Request-Id/trace id and, for decode failures, the key path and rule.
Values are never accepted. The server writes one wegoh_client_event_v1 line and
one span event per report so a server-side 200 can be matched to the app's
rejection.

An app built against another route table must not lose a whole batch to one
route this server does not mount: such events are skipped and counted, the
rest are accepted.
"""
import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from api_observability import REQUEST_ID, RouteTemplates, TRACE_ID, current_request, log_client_event, note_identity

NATIVE_PATH = '/v1/native/diagnostics'
IPHONE_PATH = '/v1/iphone/diagnostics'
MAX_BYTES = 8192
MAX_EVENTS = 20
RATE_PER_MINUTE = 30
KINDS = ('network_error', 'timeout', 'invalid_response', 'http_error', 'cancelled')
RULES = ('missing', 'type', 'format', 'range', 'enum', 'length', 'unknown', 'syntax')
METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'WS')
FIELDS = frozenset(('kind', 'method', 'route', 'requestId', 'traceId', 'status', 'decodePath', 'decodeRule',
                    'elapsedMs'))
DECODE_PATH = re.compile(r'[A-Za-z0-9_$.\[\]-]{1,160}')
# A map key or array element that looks like an identifier is replaced, never stored. Server IDs are
# uuid4 (with or without hyphens), token_hex(>=6), prefixed hex such as team-<40 hex> or
# trip-waypoint-<32 hex>, and token_urlsafe(32); long digit runs cover numeric IDs and timestamps.
# A segment (between '.', '[' and ']') of 16+ URL-safe characters is replaced when it has a digit,
# and at 40+ characters regardless; schema keys are shorter camelCase or snake_case words.
_IDENTIFIER_SEGMENT = re.compile(
    r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
    r'|(?<![A-Za-z0-9_-])(?:'
    r'(?:[A-Za-z]+-)*[0-9a-fA-F]{12,}'
    r'|(?=[A-Za-z_-]*[0-9])[A-Za-z0-9_-]{16,}'
    r'|[A-Za-z0-9_-]{40,}'
    r')(?![A-Za-z0-9_-])'
    r'|[0-9a-fA-F]{16,}|[0-9]{7,}')
_LOG = logging.getLogger('uvicorn.error.wegoh_client_diagnostics')


def _invalid():
    raise HTTPException(400, 'INVALID_DIAGNOSTIC')


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        _invalid()
    return value


def _decode_path(value):
    if not isinstance(value, str) or not DECODE_PATH.fullmatch(value):
        _invalid()
    return _IDENTIFIER_SEGMENT.sub('*', value)


def parse_events(raw, templates):
    """Valid events on mounted routes and the number of valid events skipped for an unmounted route.

    Any malformed event still rejects the batch; the skipped route itself is never kept.
    """
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        _invalid()
    if type(body) is not dict or body.keys() != {'events'} or type(body['events']) is not list:
        _invalid()
    events = body['events']
    if not 1 <= len(events) <= MAX_EVENTS:
        _invalid()
    rows, skipped = [], 0
    for event in events:
        if type(event) is not dict or not {'kind', 'method', 'route'} <= event.keys() or not event.keys() <= FIELDS:
            _invalid()
        kind, method, route = event['kind'], event['method'], event['route']
        if kind not in KINDS or method not in METHODS or not isinstance(route, str):
            _invalid()
        row = dict(kind=kind, target_method=method, target_route=route)
        if 'requestId' in event:
            if not isinstance(event['requestId'], str) or not REQUEST_ID.fullmatch(event['requestId']):
                _invalid()
            row['ref_req_id'] = event['requestId']
        if 'traceId' in event:
            if not isinstance(event['traceId'], str) or not TRACE_ID.fullmatch(event['traceId']) \
                    or not int(event['traceId'], 16):
                _invalid()
            row['ref_trace_id'] = event['traceId']
        if 'status' in event:
            row['http_status'] = _integer(event['status'], 100, 599)
        if 'decodePath' in event:
            row['decode_path'] = _decode_path(event['decodePath'])
        if 'decodeRule' in event:
            if event['decodeRule'] not in RULES:
                _invalid()
            row['decode_rule'] = event['decodeRule']
        if 'elapsedMs' in event:
            row['elapsed_ms'] = _integer(event['elapsedMs'], 0, 600_000)
        if kind == 'invalid_response' and 'decode_rule' not in row:
            _invalid()
        if (method, route) in templates:
            rows.append(row)
        else:
            skipped += 1
    return rows, skipped


async def _body(request):
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        _invalid()
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, 'DIAGNOSTIC_TOO_LARGE')
    return bytes(raw)


def create_router(auth, app):
    router = APIRouter()
    routes = RouteTemplates(app)

    def limit(account):
        try:
            auth.rate('client-diagnostics:' + account, limit=RATE_PER_MINUTE)
        except HTTPException as error:
            if error.status_code != 429:
                raise
            raise HTTPException(429, 'RATE_LIMITED', headers=error.headers) from None

    async def accept(request, account, device):
        note_identity(account, device)
        events, skipped = parse_events(await _body(request), routes.templates())
        await run_in_threadpool(limit, account)
        record = current_request()
        if skipped:
            _LOG.warning('client diagnostics: skipped unmounted=%d accepted=%d req_id=%s', skipped, len(events),
                         record.req_id if record is not None else '-')
        span = None
        if record is not None and record.trace_id:
            from opentelemetry import trace

            span = trace.get_current_span()
            # A client report is the only server-side evidence of an app-side failure; always export it.
            record.force_trace = True
        for event in events:
            log_client_event(event)
            if span is not None:
                span.add_event('wegoh.client_event', {'wegoh.client_event.' + key: value
                                                       for key, value in event.items()})
        return {'accepted': len(events), 'skipped': skipped}

    @router.post(NATIVE_PATH, status_code=202)
    async def native_diagnostics(request: Request):
        identity = getattr(request.state, 'device_identity', None)
        if not identity:
            raise HTTPException(404, 'Not found')
        return await accept(request, identity['id'], identity.get('deviceId'))

    @router.post(IPHONE_PATH, status_code=202, include_in_schema=False)
    async def iphone_diagnostics(request: Request):
        actor = await run_in_threadpool(auth.iphone, request, 'account:read')
        return await accept(request, actor['id'], None)

    return router
