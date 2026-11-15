"""Opt-in vehicle error reports written once to the API journal.

The vehicle app sends one report only after the user turns on "오류 보고하기" and taps
"전송하기" on an error screen. The report holds the app's own recent diagnostic lines,
already masked on the device. The server masks them again, never stores them in the
database and writes a single ``wegoh_client_report_v1`` journal line. The observability
collector copies that line into VictoriaLogs, whose retention bounds how long it is kept.
No account, device or grant identifier enters the line; a random report id is returned
so the user can quote it to the team.
"""
from collections import deque
from datetime import datetime
import json
import logging
import re
import secrets
from threading import Lock

from native_access_codec import CodecError, decode_json
from native_functional_policy import FunctionalError


PATH = '/v1/device/client-reports'
PREFIX = 'wegoh_client_report_v1 '
MAX_BYTES = 8192
MAX_LINES = 60
MAX_LINE_CHARS = 240
MAX_TEXT_BYTES = 6144
# The collector skips journal JSON lines over 8192 bytes; keep each report well under it.
MAX_JOURNAL_BYTES = 7600
WINDOW_SECONDS = 600
PER_GRANT = 5
TOTAL = 120

_LOG = logging.getLogger('uvicorn.error.wegoh_client_report')
_JOURNAL_LINE = re.compile(r'(?:INFO:\s+)?' + re.escape(PREFIX) + r'(.{1,7600})')
_SCREEN = re.compile(r'[a-z][a-z0-9_.]{1,47}')
_REASON = re.compile(r'[A-Za-z0-9_.-]{1,48}')
_TEMPLATE = re.compile(r'(GET|POST|PUT|PATCH|DELETE|OTHER) /[A-Za-z0-9/{}_?=&.-]{0,159}')
_VERSION = re.compile(r'[0-9A-Za-z._+-]{1,32}')
_REPORT_ID = re.compile(r'[a-f0-9]{16}')
_UTC_TIMESTAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z')
_FIELDS = {'reportVersion', 'screen', 'reason', 'requestTemplate', 'appVersion', 'appBuild', 'lines'}
_RECORD_FIELDS = {'schema_version', 'report_id', 'screen', 'reason', 'request_template',
                  'app_version', 'app_build', 'truncated', 'lines'}

# Same rules as the vehicle app's ClientDiagnostics.mask: the server does not trust the device.
_SENSITIVE_KEY = re.compile(r'\b((?:account|device|grant|owner|user|member|friend|email|phone|plate|title|name|'
                            r'nickname|address|query|token|secret|password|lat|lng|lon|latitude|longitude)'
                            r'[A-Za-z_]*)=("[^"]*"|\S+)', re.IGNORECASE)
_MASKS = (
    (re.compile(r'(?i)\bbearer\s+\S+'), 'Bearer {token}'),
    (re.compile(r'(?i)\b[a-z][a-z0-9+.-]*://\S+'), '{url}'),
    (re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'), '{email}'),
    (re.compile(r'(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b'), '{id}'),
    (re.compile(r'\b(?=[A-Za-z0-9_-]*[0-9])(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{24,}={0,2}'), '{token}'),
    (re.compile(r'(?i)\b[0-9a-f]{12,}\b'), '{hex}'),
    (re.compile(r'-?\b[0-9]{1,3}\.[0-9]{4,}\b'), '{num}'),
    (re.compile(r'[^\x20-\x7e]+'), '{text}'),
)


class ReportRateLimited(FunctionalError):
    def __init__(self, retry_after):
        super().__init__(429, 'CLIENT_REPORT_RATE_LIMITED')
        self.retry_after = retry_after


def fail(status=400, code='INVALID_CLIENT_REPORT'):
    raise FunctionalError(status, code)


def mask(line):
    """Drop values that could identify a person, account, vehicle, place or credential."""
    value = _SENSITIVE_KEY.sub(lambda match: match[1] + '={masked}', line)
    for pattern, replacement in _MASKS:
        value = pattern.sub(replacement, value)
    return value[:MAX_LINE_CHARS]


def _text(value, pattern):
    if type(value) is not str or not pattern.fullmatch(value):
        fail()
    return value


def report_body(raw):
    if type(raw) in (bytes, bytearray) and len(raw) > MAX_BYTES:
        fail(413, 'CLIENT_REPORT_TOO_LARGE')
    try:
        value = decode_json(bytes(raw), maximum_bytes=MAX_BYTES)
    except CodecError:
        fail()
    if type(value) is not dict or set(value) != _FIELDS or value['reportVersion'] != 1 or type(value['reportVersion']) is not int:
        fail()
    template = value['requestTemplate']
    if template is not None:
        _text(template, _TEMPLATE)
    build = value['appBuild']
    if type(build) is not int or not 1 <= build <= 2147483647:
        fail()
    lines = value['lines']
    if type(lines) is not list or len(lines) > MAX_LINES or any(type(line) is not str or len(line) > MAX_LINE_CHARS for line in lines):
        fail()
    masked = [mask(line) for line in lines]
    if sum(len(line.encode('utf-8')) for line in masked) > MAX_TEXT_BYTES:
        fail(413, 'CLIENT_REPORT_TOO_LARGE')
    return dict(screen=_text(value['screen'], _SCREEN), reason=_text(value['reason'], _REASON),
                requestTemplate=template, appVersion=_text(value['appVersion'], _VERSION), appBuild=build, lines=masked)


def _journal_size(message):
    # Approximate the journalctl --output=json line the collector reads.
    return len(json.dumps({'__CURSOR': 'x' * 160, '__REALTIME_TIMESTAMP': '0' * 16,
                           '_SYSTEMD_UNIT': 'wegoh-live-api.service', 'MESSAGE': 'INFO:     ' + message}))


def journal_payload(report, report_id):
    lines, truncated = list(report['lines']), False
    while True:
        payload = dict(schema_version=1, report_id=report_id, screen=report['screen'], reason=report['reason'],
                       request_template=report['requestTemplate'], app_version=report['appVersion'],
                       app_build=report['appBuild'], truncated=truncated, lines=lines)
        message = PREFIX + json.dumps(payload, separators=(',', ':'))
        if _journal_size(message) <= MAX_JOURNAL_BYTES:
            return message
        # Keep the newest lines: the failure is at the end of the buffer.
        lines, truncated = lines[1:], True


class ReportLimit:
    """At most PER_GRANT reports per grant and TOTAL overall in WINDOW_SECONDS (single API worker)."""

    def __init__(self):
        self.lock = Lock()
        self.by_grant = {}
        self.all = deque()

    def admit(self, grant, now):
        with self.lock:
            start = now - WINDOW_SECONDS
            while self.all and self.all[0] <= start:
                self.all.popleft()
            for key in [key for key, times in self.by_grant.items() if not times or times[-1] <= start]:
                del self.by_grant[key]
            times = self.by_grant.setdefault(grant, deque())
            while times and times[0] <= start:
                times.popleft()
            if len(times) >= PER_GRANT or len(self.all) >= TOTAL:
                oldest = min(times[0] if len(times) >= PER_GRANT else now, self.all[0] if len(self.all) >= TOTAL else now)
                return max(1, int(oldest + WINDOW_SECONDS - now) + 1)
            times.append(now)
            self.all.append(now)
            return None


LIMIT = ReportLimit()


def submit_report(service, request, raw):
    """Authenticate the current vehicle grant, then write one masked journal line."""
    snapshot = service.native_get(request)
    report = report_body(raw)
    retry = LIMIT.admit(snapshot['grantId'], service.base.now())
    if retry is not None:
        raise ReportRateLimited(retry)
    report_id = secrets.token_hex(8)
    _LOG.info('%s', journal_payload(report, report_id))
    return dict(status='accepted', reportId=report_id)


def register_client_reports(router, auth):
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    from native_authorization import NativeAuthorizationError, read_body

    @router.post(PATH)
    async def client_report(request: Request):
        headers = {'Cache-Control': 'no-store'}
        try:
            try:
                raw = await read_body(request)
            except NativeAuthorizationError as error:
                raise FunctionalError(error.status, error.code) from None
            value = await run_in_threadpool(submit_report, auth.functional_access, request, raw)
            return JSONResponse(value, headers=headers)
        except FunctionalError as error:
            retry = getattr(error, 'retry_after', None)
            return JSONResponse(dict(authorizationVersion=1, error=error.code), status_code=error.status,
                                headers=dict(headers, **({'Retry-After': str(retry)} if retry else {})))


def decode_journal_message(line):
    """Recognize only this report schema, never arbitrary journal messages."""
    match = _JOURNAL_LINE.fullmatch(line.rstrip('\r\n'))
    if not match:
        return None
    try:
        value = json.loads(match[1])
    except (ValueError, RecursionError):
        return None
    return _validate_record(value)


def _validate_record(value):
    if type(value) is not dict or set(value) != _RECORD_FIELDS or value['schema_version'] != 1:
        return None
    checks = ((value['report_id'], _REPORT_ID), (value['screen'], _SCREEN), (value['reason'], _REASON),
              (value['app_version'], _VERSION))
    if any(type(item) is not str or not pattern.fullmatch(item) for item, pattern in checks):
        return None
    template = value['request_template']
    if template is not None and (type(template) is not str or not _TEMPLATE.fullmatch(template)):
        return None
    lines = value['lines']
    if (type(value['app_build']) is not int or type(value['truncated']) is not bool or type(lines) is not list
            or len(lines) > MAX_LINES or any(type(line) is not str or mask(line) != line for line in lines)):
        return None
    return value


def analysis_record(record, observed_at):
    """Encode a validated report for VictoriaLogs JSONL storage."""
    if _validate_record({key: record.get(key) for key in _RECORD_FIELDS} if type(record) is dict else None) is None:
        return None
    if type(observed_at) is not str or not _UTC_TIMESTAMP.fullmatch(observed_at):
        return None
    try:
        datetime.fromisoformat(observed_at)
    except ValueError:
        return None
    return {
        'schema_version': 2,
        '@timestamp': observed_at,
        'service.name': 'wegoh-live-api',
        'event.name': 'wegoh.client.report',
        'wegoh.client.report_id': record['report_id'],
        'wegoh.client.screen': record['screen'],
        'wegoh.client.reason': record['reason'],
        'wegoh.client.request_template': record['request_template'],
        'wegoh.client.app_version': record['app_version'],
        'wegoh.client.app_build': record['app_build'],
        'wegoh.client.truncated': record['truncated'],
        'wegoh.client.line_count': len(record['lines']),
        'wegoh.client.lines': '\n'.join(record['lines']),
    }
