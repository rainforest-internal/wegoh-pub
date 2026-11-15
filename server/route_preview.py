"""Ephemeral driving route previews without course or location storage."""
import json
import logging
import math
import time
from threading import BoundedSemaphore, Lock
from urllib.parse import urlencode

from place_search import load_key
from web_provider import bounded_get, bounded_call, remaining_time, rate_attempt

LOG = logging.getLogger(__name__)
MAX_BYTES = 2 * 1024 * 1024
MAX_PATH_POINTS = 2000
MAX_CONCURRENT_ROUTES = 4
_ROUTE_SLOTS = BoundedSemaphore(MAX_CONCURRENT_ROUTES)

POINT_SCHEMA = dict(type='object', additionalProperties=False, required=['lat', 'lng'], properties={
    'lat': dict(type='number', minimum=32, maximum=39, description='대한민국 범위 위도.'),
    'lng': dict(type='number', minimum=124, maximum=132, description='대한민국 범위 경도.')})
ROUTE_REQUEST_SCHEMA = dict(type='object', additionalProperties=False, required=['points'], properties={
    'origin': dict(POINT_SCHEMA, type=['object', 'null'], description='미리보기 전용 출발지. 생략/null이면 첫 장소부터 계산합니다.'),
    'points': dict(type='array', minItems=1, maxItems=3, items=POINT_SCHEMA, description='코스 순서대로 1~3개 장소.')})


class RoutePreviewError(ValueError):
    def __init__(self, code='ROUTE_UNAVAILABLE', status=503):
        self.code, self.status = code, status
        super().__init__(code)


def coordinate(value):
    if not isinstance(value, dict) or set(value) != {'lat', 'lng'}:
        raise ValueError()
    for key, low, high in [('lat', 32, 39), ('lng', 124, 132)]:
        number = value[key]
        if type(number) not in (float, int) or not low <= number <= high or not math.isfinite(number):
            raise ValueError()
    return dict(lat=value['lat'], lng=value['lng'])


def route_input(value):
    try:
        if not isinstance(value, dict) or not {'points'} <= set(value) <= {'origin', 'points'}:
            raise ValueError()
        points = value['points']
        if not isinstance(points, list) or not 1 <= len(points) <= 3:
            raise ValueError()
        return (coordinate(value['origin']) if value.get('origin') is not None else None,
                [coordinate(point) for point in points])
    except (ValueError, TypeError, KeyError, OverflowError):
        raise RoutePreviewError('ROUTE_INPUT_INVALID', 400) from None


def route_transport(url, headers, timeout, max_bytes):
    return bounded_get(url, headers, timeout, max_bytes,
                       error=lambda: RoutePreviewError('ROUTE_PROVIDER_UNAVAILABLE', 502))


class KakaoRoutePreview:
    def __init__(self, key, transport=route_transport, *, clock=time.monotonic):
        self._key, self._transport, self._clock = key, transport, clock

    def preview(self, origin, points, timeout=4):
        try:
            deadline = self._clock() + timeout
            ordered = ([origin] if origin else []) + points
            xy = lambda point: f"{point['lng']},{point['lat']}"
            params = dict(origin=xy(ordered[0]), destination=xy(ordered[-1]), summary='false')
            if len(ordered) > 2:
                params['waypoints'] = '|'.join(xy(point) for point in ordered[1:-1])
            raw = self._transport('https://apis-navi.kakaomobility.com/v1/directions?' + urlencode(params),
                                  {'Authorization': 'KakaoAK ' + self._key},
                                  remaining_time(deadline, self._clock), MAX_BYTES)
            remaining_time(deadline, self._clock)
            if len(raw) > MAX_BYTES or self._key.encode() in raw:
                raise ValueError()
            route = json.loads(raw)['routes'][0]
            if type(route['result_code']) is not int:
                raise ValueError()
            if route['result_code'] != 0:
                raise RoutePreviewError('ROUTE_NOT_FOUND', 422)
            summary = route['summary']
            for key in ('distance', 'duration'):
                if type(summary[key]) not in (int, float) or not math.isfinite(summary[key]) or summary[key] < 0:
                    raise ValueError()
            path = []
            for section in route['sections']:
                for road in section['roads']:
                    vertices = road['vertexes']
                    if not isinstance(vertices, list) or len(vertices) % 2:
                        raise ValueError()
                    for index in range(0, len(vertices), 2):
                        point = coordinate(dict(lat=vertices[index + 1], lng=vertices[index]))
                        pair = [point['lat'], point['lng']]
                        if not path or path[-1] != pair:
                            path.append(pair)
            if len(path) < 2:
                raise ValueError()
            if len(path) > MAX_PATH_POINTS:
                path = [path[index * (len(path) - 1) // (MAX_PATH_POINTS - 1)] for index in range(MAX_PATH_POINTS)]
            remaining_time(deadline, self._clock)
            return dict(distanceMeters=summary['distance'], durationSeconds=summary['duration'], path=path)
        except (RoutePreviewError, TimeoutError):
            raise
        except Exception:
            raise RoutePreviewError('ROUTE_PROVIDER_UNAVAILABLE', 502) from None


class MockRoutePreview:
    def preview(self, origin, points, timeout=4):
        return dict(distanceMeters=12000, durationSeconds=1800,
                    path=[[point['lat'], point['lng']] for point in ([origin] if origin else []) + points])


class RoutePreview:
    def __init__(self, provider=None, *, clock=time.monotonic, timeout=4, limit=20):
        self.provider, self.clock, self.timeout, self.limit = provider, clock, timeout, limit
        self._attempts, self._lock = {}, Lock()

    @classmethod
    def from_environment(cls):
        key = load_key()
        return cls(KakaoRoutePreview(key) if key else None)

    def preview(self, account, value):
        try:
            origin, points = route_input(value)
            rate_attempt(account, self._attempts, self._lock, self.clock, self.limit,
                         lambda: RoutePreviewError('ROUTE_RATE_LIMITED', 429))
            if not origin and len(points) == 1:
                return dict(distanceMeters=0, durationSeconds=0, path=[])
            provider = self.provider
            if provider is None:
                raise RoutePreviewError()
            result = bounded_call(lambda timeout: provider.preview(origin, points, timeout),
                                  _ROUTE_SLOTS, self.timeout, RoutePreviewError, 'ROUTE', name='route-preview')
            LOG.info('route.preview: loaded count=%d', len(result['path']))
            return result
        except RoutePreviewError as error:
            LOG.info('route.preview: failed reason=%s', error.code)
            raise
