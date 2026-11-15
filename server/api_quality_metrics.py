"""Fixed-dimension API time-to-headers observations and journal summarization."""
from bisect import bisect_left
from collections import Counter
from datetime import datetime
import json
import logging
import re
import sys
from time import monotonic_ns


_LOG = logging.getLogger('uvicorn.error.wegoh_api_quality')
_PREFIX = 'wegoh_api_quality_v1 '
_JOURNAL_LINE = re.compile(r'(?:INFO:\s+)?' + _PREFIX + r'(.{1,256})')
_OBSERVATION_FIELDS = {'route', 'method', 'status', 'ttfb_ms'}
TRACE_FIELDS = ('trace_id', 'span_id')
_TRACED_OBSERVATION_FIELDS = _OBSERVATION_FIELDS.union(TRACE_FIELDS)
_TRACE_ID = re.compile(r'[0-9a-f]{32}')
_SPAN_ID = re.compile(r'[0-9a-f]{16}')
_ARCHIVE_V1_FIELDS = {'schema_version', '@timestamp', 'route', 'method', 'status', 'ttfb_ms'}
_UTC_TIMESTAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z')
_BUCKETS_MS = (5, 10, 20, 30, 50, 75, 100, 150, 200, 250, 350, 500, 750,
               1000, 1500, 2000, 3000, 5000, 10000, 20000, 30000, 60000)

_IPHONE_ROUTES = {
    ('GET', '/v1/iphone/session'): 'iphone.session',
    ('GET', '/v1/iphone/profile'): 'iphone.profile',
    ('GET', '/v1/iphone/vehicles'): 'iphone.vehicles',
    ('GET', '/v1/iphone/trips'): 'iphone.trips',
    ('GET', '/v1/iphone/courses'): 'iphone.my_courses',
    ('GET', '/v1/iphone/courses/library'): 'iphone.course_library',
    ('GET', '/v1/iphone/places/search'): 'iphone.place_search',
    ('POST', '/v1/iphone/routes/preview'): 'iphone.route_preview',
}
_WEB_ROUTES = {
    ('POST', '/v1/routes/preview'): 'web.route_preview',
}
_COURSE_VERSION = r'[a-z0-9][a-z0-9_-]{0,79}/versions/[0-9]{1,10}'
_IPHONE_DETAIL_ROUTES = (
    (re.compile(r'/v1/iphone/trips/[a-f0-9]{32}'), 'iphone.trip_detail', '/v1/iphone/trips/{id}'),
    (re.compile(r'/v1/iphone/vehicles/[a-f0-9]{32}/profile'), 'iphone.vehicle_profile',
     '/v1/iphone/vehicles/{device}/profile'),
    (re.compile(r'/v1/iphone/courses/' + _COURSE_VERSION), 'iphone.my_course_detail',
     '/v1/iphone/courses/{pack_id}/versions/{version}'),
    (re.compile(r'/v1/iphone/courses/public/' + _COURSE_VERSION), 'iphone.public_course_detail',
     '/v1/iphone/courses/public/{pack_id}/versions/{version}'),
    (re.compile(r'/v1/iphone/courses/public/' + _COURSE_VERSION + '/cover'), 'iphone.public_course_cover',
     '/v1/iphone/courses/public/{pack_id}/versions/{version}/cover'),
)
_ROUTE_TEMPLATES = {route: (method, path) for (method, path), route in (_IPHONE_ROUTES | _WEB_ROUTES).items()}
_ROUTE_TEMPLATES.update({route: ('GET', template) for _, route, template in _IPHONE_DETAIL_ROUTES})

# Every fixed route below carries logs and traces; only _METRIC_ROUTE_IDS also gets histograms.
_IPHONE_LOG_ROUTES = {
    ('POST', '/v1/iphone/trips'): 'iphone.trip_create',
    ('POST', '/v1/iphone/courses'): 'iphone.course_save',
    ('GET', '/v1/iphone/friends'): 'iphone.friends',
    ('GET', '/v1/iphone/friends/search'): 'iphone.friend_search',
    ('POST', '/v1/iphone/friends/requests'): 'iphone.friend_request',
}
_TRIP_ID = r'/v1/iphone/trips/[a-f0-9]{32}'
_IPHONE_LOG_DETAIL_ROUTES = (
    ('POST', _TRIP_ID + '/members', 'iphone.trip_invite', '/v1/iphone/trips/{id}/members'),
    ('POST', _TRIP_ID + '/start', 'iphone.trip_start', '/v1/iphone/trips/{id}/start'),
    ('POST', _TRIP_ID + '/finish', 'iphone.trip_finish', '/v1/iphone/trips/{id}/finish'),
    ('POST', _TRIP_ID + '/courses', 'iphone.trip_course_add', '/v1/iphone/trips/{id}/courses'),
    ('GET', _TRIP_ID + '/music', 'iphone.trip_music', '/v1/iphone/trips/{trip}/music'),
    ('POST', _TRIP_ID + '/music/playlist', 'iphone.trip_music_add', '/v1/iphone/trips/{trip}/music/playlist'),
    ('POST', _TRIP_ID + '/music/saved-playlists', 'iphone.trip_music_saved_add',
     '/v1/iphone/trips/{trip}/music/saved-playlists'),
    ('POST', r'/v1/iphone/courses/public/' + _COURSE_VERSION + '/copy', 'iphone.public_course_copy',
     '/v1/iphone/courses/public/{pack_id}/versions/{version}/copy'),
    ('POST', _TRIP_ID + '/signals', 'iphone.hand_raise', '/v1/iphone/trips/{id}/signals'),
    ('POST', _TRIP_ID + '/signals/[a-f0-9]{32}/vote', 'iphone.hand_raise_reply',
     '/v1/iphone/trips/{id}/signals/{signal}/vote'),
    ('POST', _TRIP_ID + '/vehicle-remotes/[a-f0-9]{32}/commands', 'iphone.vehicle_remote_command',
     '/v1/iphone/trips/{trip}/vehicle-remotes/{device}/commands'),
)
_ROUTE_TEMPLATES.update({route: (method, path) for (method, path), route in _IPHONE_LOG_ROUTES.items()})
_ROUTE_TEMPLATES.update({route: (method, template) for method, _, route, template in _IPHONE_LOG_DETAIL_ROUTES})
# 19 routes * 4 status classes * 26 series = 1976 samples, inside the 2048 scrape limit.
# Reads, plus the demo flows: trip create/start/finish, course add or copy, hand raise, vehicle control.
_METRIC_ROUTE_IDS = frozenset((
    'iphone.session', 'iphone.profile', 'iphone.vehicles', 'iphone.trips', 'iphone.trip_detail',
    'iphone.my_courses', 'iphone.course_library', 'iphone.public_course_detail', 'iphone.place_search',
    'iphone.route_preview', 'web.route_preview', 'iphone.trip_create', 'iphone.trip_start', 'iphone.trip_finish',
    'iphone.trip_course_add', 'iphone.public_course_copy', 'iphone.hand_raise', 'iphone.hand_raise_reply',
    'iphone.vehicle_remote_command'))
_IPHONE_MATCHERS = {
    'GET': [(pattern, route) for pattern, route, _ in _IPHONE_DETAIL_ROUTES],
    'POST': [],
}
for _method, _path, _route, _template in _IPHONE_LOG_DETAIL_ROUTES:
    _IPHONE_MATCHERS[_method].append((re.compile(_path), _route))


def is_metric_route(route):
    return route in _METRIC_ROUTE_IDS


class ApiQualityMetrics:
    def __init__(self, app, *, iphone_host, web_host):
        self.app = app
        self.iphone_hosts = self._host_headers(iphone_host)
        self.web_hosts = self._host_headers(web_host)

    @staticmethod
    def _host_headers(host):
        value = host.encode('ascii')
        return ((value,), (value + b':443',))

    def _route(self, scope, method):
        if method not in ('GET', 'POST'):
            return None
        path = scope['path']
        if path.startswith('/v1/iphone/'):
            hosts = tuple(value.lower() for name, value in scope['headers'] if name == b'host')
            if hosts not in self.iphone_hosts:
                return None
            route = _IPHONE_ROUTES.get((method, path)) or _IPHONE_LOG_ROUTES.get((method, path))
            return route or next((label for pattern, label in _IPHONE_MATCHERS[method] if pattern.fullmatch(path)), None)
        route = _WEB_ROUTES.get((method, path))
        if route is None:
            return None
        hosts = tuple(value.lower() for name, value in scope['headers'] if name == b'host')
        return route if hosts in self.web_hosts else None

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        method = scope['method']
        route = self._route(scope, method)
        if route is None:
            return await self.app(scope, receive, send)
        started = monotonic_ns()
        emitted = False

        async def measured_send(message):
            nonlocal emitted
            if message['type'] != 'http.response.start' or emitted:
                return await send(message)
            elapsed_ms = (monotonic_ns() - started + 999_999) // 1_000_000
            await send(message)
            emitted = True
            payload = dict(route=route, method=method, status=message['status'], ttfb_ms=elapsed_ms)
            # The outer access middleware owns the request's trace; reuse its ids for drilldown.
            from api_observability import current_request

            record = current_request()
            if record is not None and record.trace_id:
                payload.update(trace_id=record.trace_id, span_id=record.span_id)
            _LOG.info('%s%s', _PREFIX, json.dumps(payload, separators=(',', ':')))

        return await self.app(scope, receive, measured_send)


def _validate_observation(value):
    if type(value) is not dict:
        return None
    if value.keys() == _TRACED_OBSERVATION_FIELDS:
        for field, pattern in zip(TRACE_FIELDS, (_TRACE_ID, _SPAN_ID)):
            identifier = value[field]
            if type(identifier) is not str or not pattern.fullmatch(identifier) or not int(identifier, 16):
                return None
    elif value.keys() != _OBSERVATION_FIELDS:
        return None
    route, method, status, duration = (value[key] for key in ('route', 'method', 'status', 'ttfb_ms'))
    if (type(route) is not str or type(method) is not str or route not in _ROUTE_TEMPLATES
            or method != _ROUTE_TEMPLATES[route][0] or type(status) is not int
            or not 200 <= status <= 599 or type(duration) is not int or duration < 0):
        return None
    return value


def decode_journal_message(line):
    """Recognize only the fixed metric schema, never arbitrary journal messages."""
    match = _JOURNAL_LINE.fullmatch(line.rstrip('\r\n'))
    if not match:
        return None
    try:
        return _validate_observation(json.loads(match[1]))
    except (ValueError, RecursionError):
        return None


def analysis_record(observation, observed_at):
    """Encode a validated response-headers observation for JSONL storage."""
    if _validate_observation(observation) is None:
        return None
    if type(observed_at) is not str or not _UTC_TIMESTAMP.fullmatch(observed_at):
        return None
    try:
        datetime.fromisoformat(observed_at)
    except ValueError:
        return None
    route = observation['route']
    return {
        'schema_version': 2,
        '@timestamp': observed_at,
        'service.name': 'wegoh-live-api',
        'event.name': 'wegoh.api.response_headers',
        'wegoh.api.route_template': _ROUTE_TEMPLATES[route][1],
        'http.request.method': observation['method'],
        'http.response.status_code': observation['status'],
        'wegoh.api.route_id': route,
        'wegoh.api.time_to_headers_ms': observation['ttfb_ms'],
        **{field: observation[field] for field in TRACE_FIELDS if field in observation},
    }


def _decode_report_line(line):
    if not line.startswith('{'):
        return decode_journal_message(line)
    if len(line) > 512:
        return None
    try:
        value = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if type(value) is not dict or type(value.get('schema_version')) is not int:
        return None
    if value['schema_version'] == 1 and value.keys() == _ARCHIVE_V1_FIELDS and len(line) <= 256:
        timestamp = value.pop('@timestamp')
        value.pop('schema_version')
        if type(timestamp) is str and _UTC_TIMESTAMP.fullmatch(timestamp):
            return _validate_observation(value)
    if value['schema_version'] == 2:
        observation = dict(route=value.get('wegoh.api.route_id'), method=value.get('http.request.method'),
                           status=value.get('http.response.status_code'), ttfb_ms=value.get('wegoh.api.time_to_headers_ms'))
        observation.update({field: value[field] for field in TRACE_FIELDS if field in value})
        if analysis_record(observation, value.get('@timestamp')) == value:
            return observation
    return None


def _percentile(histogram, total, percentile):
    if not total:
        return None
    rank = (total * percentile + 99) // 100
    count = 0
    for index, upper in enumerate(_BUCKETS_MS):
        count += histogram[index]
        if count >= rank:
            return upper
    return None


def _timing(histogram):
    total = sum(histogram.values())
    return dict(samples=total, over_max_bucket=histogram[len(_BUCKETS_MS)],
                p50_upper_bound_ms=_percentile(histogram, total, 50),
                p95_upper_bound_ms=_percentile(histogram, total, 95))


def summarize(lines):
    """Aggregate selected journal or archive lines without retaining individual observations."""
    routes = {}
    for line in lines:
        observation = _decode_report_line(line)
        if observation is None:
            continue
        route, status = observation['route'], observation['status']
        bucket = bisect_left(_BUCKETS_MS, observation['ttfb_ms'])
        if route not in routes:
            routes[route] = Counter(), Counter(), Counter()
        statuses, all_times, success_times = routes[route]
        statuses[status] += 1
        all_times[bucket] += 1
        if 200 <= status < 300:
            success_times[bucket] += 1

    report = {}
    for route, (statuses, all_times, success_times) in sorted(routes.items()):
        classes = Counter()
        for status, count in statuses.items():
            classes[status // 100] += count
        total = sum(statuses.values())
        report[route] = dict(
            method=_ROUTE_TEMPLATES[route][0], responses=total,
            status_classes={f'{code}xx': classes[code] for code in range(2, 6)},
            unauthorized_401=statuses[401], forbidden_403=statuses[403], rate_limited_429=statuses[429],
            server_error_rate=classes[5] / total,
            all_response_ttfb=_timing(all_times), successful_response_ttfb=_timing(success_times))
    return dict(version=1, status='observed' if report else 'no_observations',
                max_histogram_bucket_ms=_BUCKETS_MS[-1], routes=report)


if __name__ == '__main__':
    json.dump(summarize(sys.stdin), sys.stdout, indent=2)
    print()
