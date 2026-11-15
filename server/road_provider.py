"""Bounded, self-hosted Valhalla road metrics. Never a nearest/traffic claim.

The authenticated caller must separately authorize location use. This adapter has
no account, history, consent, storage or navigation side effects. It sends POST
bodies only to the explicitly configured loopback engine and never uses a public
routing service, environment proxy, coordinate query string or straight fallback.
"""
from dataclasses import dataclass
from datetime import datetime
import ipaddress
import http.client
import socket
import threading
import json
import math
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

class RoadProviderError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def fail(code):
    raise RoadProviderError(code)

def number(value):
    return type(value) in (int, float) and math.isfinite(value)

@dataclass(frozen=True, repr=False)
class Coordinate:
    latitude: float
    longitude: float
    def __post_init__(self):
        if not number(self.latitude) or not number(self.longitude) or not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            fail('ROAD_COORDINATE_INVALID')
    def __repr__(self):
        return 'Coordinate(redacted)'
    def request(self):
        return {'lat': self.latitude, 'lon': self.longitude}

@dataclass(frozen=True)
class GraphSource:
    source_id: str
    source_sha256: str
    data_as_of: str
    bounds: tuple[float, float, float, float]
    attribution: str = '© OpenStreetMap contributors'
    license: str = 'ODbL-1.0'
    def __post_init__(self):
        import re
        if not re.fullmatch('[a-f0-9]{64}', self.source_sha256) or not self.source_id or not self.data_as_of:
            fail('ROAD_SOURCE_INVALID')
        try:
            if not isinstance(self.data_as_of, str):
                raise ValueError()
            datetime.fromisoformat(self.data_as_of.replace('Z', '+00:00'))
        except ValueError:
            fail('ROAD_SOURCE_INVALID')
        if type(self.bounds) is not tuple or len(self.bounds) != 4 or not all(number(x) for x in self.bounds):
            fail('ROAD_SOURCE_INVALID')
        west, south, east, north = self.bounds
        if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
            fail('ROAD_SOURCE_INVALID')
    def contains(self, point):
        west, south, east, north = self.bounds
        return west <= point.longitude <= east and south <= point.latitude <= north

@dataclass(frozen=True)
class RoadMetric:
    reachable: bool
    distance_meters: float | None
    estimated_duration_seconds: float | None
    source: GraphSource
    basis: str = 'valhalla-auto-road-graph'
    live_traffic: bool = False
    globally_shortest: bool = False

class _DeadlineGuard:
    # A socket timeout limits inactivity, not a whole response. A peer can drip
    # headers/body indefinitely unless the entire request has its own deadline.
    def __init__(self, deadline):
        self.deadline = deadline
        self.expired = threading.Event()
        self.timer = None
    def arm(self, connection):
        def interrupt():
            self.expired.set()
            try: connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        self.timer = threading.Timer(max(0,self.deadline-time.monotonic()),interrupt)
        self.timer.daemon = True
        self.timer.start()
    def finish(self):
        if self.timer is not None:
            self.timer.cancel()

class _DeadlineConnection(http.client.HTTPConnection):
    def __init__(self, *args, guard, **kwargs):
        self.guard = guard
        super().__init__(*args, **kwargs)
    def connect(self):
        super().connect()
        # Keep this exact socket, including the file-backed response lifetime.
        # A request never reuses another request's socket or deadline guard.
        self.guard.arm(self.sock)

class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(lambda *args, **kwargs:
            _DeadlineConnection(*args,guard=request.wegoh_deadline_guard,**kwargs),request)

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        fail('ROAD_PROVIDER_REDIRECT_REJECTED')

def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('ROAD_PROVIDER_RESPONSE_INVALID')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: fail('ROAD_PROVIDER_RESPONSE_INVALID'))
    except (ValueError, UnicodeError):
        fail('ROAD_PROVIDER_RESPONSE_INVALID')

def _separation(a, b):
    # Used only to reject excessive graph snapping, never as road distance.
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2-lat1
    dlon = math.radians(b.longitude-a.longitude)
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371008.8*2*math.asin(min(1, math.sqrt(h)))

class ValhallaRoadProvider:
    MAX_RESPONSE_BYTES = 1024*1024
    MAX_CANDIDATES = 1000
    # Actual small-host matrix32 exceeded the 3GiB service ceiling.
    # Keep bounded requests small while evaluating every supplied candidate.
    BATCH_SIZE = 4
    def __init__(self, endpoint, source, *, timeout_seconds=5, query_seconds=20,
                 max_snap_meters=50):
        try:
            url = urllib.parse.urlsplit(endpoint)
            host = ipaddress.ip_address(url.hostname)
            port = url.port
        except (ValueError, TypeError):
            fail('ROAD_PROVIDER_ENDPOINT_INVALID')
        if url.scheme != 'http' or not host.is_loopback or not port or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
            fail('ROAD_PROVIDER_ENDPOINT_INVALID')
        if not isinstance(source, GraphSource) or not all(number(x) and x > 0 for x in (timeout_seconds, query_seconds, max_snap_meters)):
            fail('ROAD_PROVIDER_CONFIGURATION_INVALID')
        self.endpoint = endpoint.rstrip('/')
        self.source = source
        self.timeout_seconds = min(timeout_seconds, 10)
        self.query_seconds = min(query_seconds, 60)
        self.max_snap_meters = min(max_snap_meters, 100)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(), _DeadlineHTTPHandler())
    def _point(self, point):
        if not isinstance(point, Coordinate):
            fail('ROAD_COORDINATE_INVALID')
        if not self.source.contains(point):
            fail('ROAD_PROVIDER_OUTSIDE_COVERAGE')
        return point.request()
    def _post(self, action, body, deadline):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            fail('ROAD_PROVIDER_TIMEOUT')
        body = dict(body, id=secrets.token_hex(16), units='kilometers', costing='auto')
        request = urllib.request.Request(self.endpoint+'/'+action,
            data=json.dumps(body, allow_nan=False, separators=(',', ':')).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        guard = _DeadlineGuard(deadline)
        request.wegoh_deadline_guard = guard
        try:
            with self._opener.open(request, timeout=min(remaining, self.timeout_seconds)) as response:
                # An interrupted drip header may parse as an incomplete response.
                if guard.expired.is_set() or time.monotonic() >= deadline:
                    fail('ROAD_PROVIDER_TIMEOUT')
                if response.status != 200 or response.headers.get_content_type() != 'application/json':
                    fail('ROAD_PROVIDER_RESPONSE_INVALID')
                raw = response.read(self.MAX_RESPONSE_BYTES+1)
        except TimeoutError:
            fail('ROAD_PROVIDER_TIMEOUT')
        except urllib.error.HTTPError as error:
            # HTTPError owns the response stream even when its body is rejected.
            error.close()
            fail('ROAD_PROVIDER_UNAVAILABLE')
        except urllib.error.URLError as error:
            # urllib wraps connect timeouts; do not label a timed-out road query
            # as a source outage or expose upstream exception/body/location.
            if isinstance(error.reason, TimeoutError) or guard.expired.is_set() or time.monotonic() >= deadline:
                fail('ROAD_PROVIDER_TIMEOUT')
            fail('ROAD_PROVIDER_UNAVAILABLE')
        except http.client.HTTPException:
            # Interrupted chunked reads raise IncompleteRead, not OSError.
            if guard.expired.is_set() or time.monotonic() >= deadline:
                fail('ROAD_PROVIDER_TIMEOUT')
            fail('ROAD_PROVIDER_RESPONSE_INVALID')
        except OSError:
            if guard.expired.is_set() or time.monotonic() >= deadline:
                fail('ROAD_PROVIDER_TIMEOUT')
            fail('ROAD_PROVIDER_UNAVAILABLE')
        finally:
            guard.finish()
        if guard.expired.is_set() or time.monotonic() >= deadline:
            fail('ROAD_PROVIDER_TIMEOUT')
        if len(raw) > self.MAX_RESPONSE_BYTES:
            fail('ROAD_PROVIDER_RESPONSE_LIMIT')
        value = _json(raw)
        if type(value) is not dict or value.get('id') != body['id'] or value.get('units') != 'kilometers':
            fail('ROAD_PROVIDER_RESPONSE_INVALID')
        return value
    def matrix(self, origin, destinations):
        """Evaluate every supplied candidate in order, including unreachable cells.

        The caller owns candidate search coverage/entrance and direction facts.
        No topN truncation, ranking, POI availability or national-road inference.
        Returned distances follow auto-costing paths, not a global shortest claim.
        """
        if type(destinations) not in (list, tuple) or len(destinations) > self.MAX_CANDIDATES:
            fail('ROAD_CANDIDATE_LIMIT')
        start = self._point(origin)
        targets = [self._point(p) for p in destinations]
        if not targets:
            return ()
        deadline = time.monotonic()+self.query_seconds
        metrics = []
        for offset in range(0, len(targets), self.BATCH_SIZE):
            batch = targets[offset:offset+self.BATCH_SIZE]
            value = self._post('sources_to_targets', {'sources': [start], 'targets': batch, 'verbose': True}, deadline)
            rows = value.get('sources_to_targets')
            if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not list or len(rows[0]) != len(batch):
                fail('ROAD_PROVIDER_RESPONSE_INVALID')
            for index, cell in enumerate(rows[0]):
                if type(cell) is not dict or type(cell.get('from_index')) is not int or type(cell.get('to_index')) is not int or cell.get('from_index') != 0 or cell.get('to_index') != index:
                    fail('ROAD_PROVIDER_RESPONSE_INVALID')
                distance, duration = cell.get('distance'), cell.get('time')
                if distance is None and duration is None:
                    metrics.append(RoadMetric(False, None, None, self.source)); continue
                if not number(distance) or not number(duration) or distance < 0 or duration < 0:
                    fail('ROAD_PROVIDER_RESPONSE_INVALID')
                try:
                    snapped_origin = Coordinate(cell['begin_lat'], cell['begin_lon'])
                    snapped_target = Coordinate(cell['end_lat'], cell['end_lon'])
                except (KeyError, RoadProviderError):
                    fail('ROAD_PROVIDER_RESPONSE_INVALID')
                if _separation(origin, snapped_origin) > self.max_snap_meters or _separation(destinations[offset+index], snapped_target) > self.max_snap_meters:
                    fail('ROAD_PROVIDER_SNAP_REJECTED')
                meters = distance*1000
                if not number(meters):
                    fail('ROAD_PROVIDER_RESPONSE_INVALID')
                metrics.append(RoadMetric(True, meters, duration, self.source))
        return tuple(metrics)
