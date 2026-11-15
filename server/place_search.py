"""Bounded, uncached place search for authenticated Studio and iPhone clients."""
import hashlib
from http.client import HTTPSConnection
import json
import logging
import math
import os
import re
import stat
import time
import unicodedata
from threading import BoundedSemaphore, Lock, Thread
from typing import Protocol
from urllib.parse import urlencode
from web_provider import remaining_time, bounded_get, rate_attempt, bounded_call

LOG = logging.getLogger(__name__)
MAX_BYTES = 256 * 1024
MAX_CONCURRENT_SEARCHES = 4
_SEARCH_SLOTS = BoundedSemaphore(MAX_CONCURRENT_SEARCHES)


class PlaceSearchError(ValueError):
    def __init__(self, code='PLACE_SEARCH_UNAVAILABLE', status=503):
        self.code, self.status = code, status
        super().__init__(code)


class PlaceSearchProvider(Protocol):
    def search(self, query: str, x: float | None, y: float | None, timeout: float) -> list[dict]: ...


def search_query(value):
    if (not set(value) <= {'q', 'x', 'y'} or 'q' not in value
            or any(len(values) != 1 for values in value.values())):
        raise PlaceSearchError('PLACE_SEARCH_QUERY_INVALID', 400)
    raw = value['q'][0]
    query = raw.strip()
    if not 2 <= len(query) <= 60 or any(unicodedata.category(c).startswith('C') for c in raw):
        raise PlaceSearchError('PLACE_SEARCH_QUERY_INVALID', 400)
    x = y = None
    if ('x' in value) != ('y' in value):
        raise PlaceSearchError('PLACE_SEARCH_QUERY_INVALID', 400)
    if 'x' in value:
        try:
            x, y = float(value['x'][0]), float(value['y'][0])
            if not math.isfinite(x) or not math.isfinite(y) or not -180 <= x <= 180 or not -90 <= y <= 90:
                raise ValueError()
        except (TypeError, ValueError):
            raise PlaceSearchError('PLACE_SEARCH_QUERY_INVALID', 400) from None
    return query, x, y


def load_key(path=None):
    try:
        path = path or os.environ.get('WEGOH_KAKAO_REST_KEY_FILE')
        if not path:
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.geteuid() or info.st_size > 256):
                return None
            key = stream.read(257).decode('ascii').strip()
        return key if re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key) else None
    except (OSError, UnicodeError, ValueError):
        return None


def kakao_transport(url, headers, timeout, max_bytes, *, clock=time.monotonic):
    return bounded_get(url, headers, timeout, max_bytes, clock=clock, connection_factory=HTTPSConnection,
                       error=lambda: PlaceSearchError('PLACE_SEARCH_PROVIDER_UNAVAILABLE', 502))


def text(value, maximum=200):
    if not isinstance(value, str) or len(value) > maximum or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError()
    return value.strip()


class KakaoPlaceSearch:
    def __init__(self, key, transport=kakao_transport, *, clock=time.monotonic):
        self._key, self._transport, self._clock = key, transport, clock

    def search(self, query, x=None, y=None, timeout=3):
        try:
            deadline = self._clock() + timeout
            results, ids, locations = [], set(), set()
            for kind in ('keyword', 'address'):
                params = dict(query=query, size=15, page=1)
                if kind == 'keyword' and x is not None:
                    params.update(x=x, y=y)
                remaining = remaining_time(deadline, self._clock)
                raw = self._transport('https://dapi.kakao.com/v2/local/search/' + kind + '.json?' + urlencode(params),
                                      {'Authorization': 'KakaoAK ' + self._key}, remaining, MAX_BYTES)
                remaining_time(deadline, self._clock)
                if len(raw) > MAX_BYTES or self._key.encode() in raw:
                    raise ValueError()
                documents = json.loads(raw)['documents']
                if not isinstance(documents, list) or len(documents) > 30:
                    raise ValueError()
                for doc in documents:
                    lat, lng = float(doc['y']), float(doc['x'])
                    if not math.isfinite(lat) or not math.isfinite(lng) or abs(lat) > 90 or abs(lng) > 180:
                        raise ValueError()
                    if kind == 'keyword':
                        identifier = text(doc['id'], 100)
                        if not re.fullmatch(r'[0-9]+', identifier):
                            raise ValueError()
                        name, address = text(doc['place_name'], 80), text(doc.get('address_name', ''))
                        road, category = text(doc.get('road_address_name', '')), text(doc.get('category_name', ''))
                        place_url = text(doc.get('place_url', ''), 240)
                        if place_url and not re.fullmatch(r'https?://place\.map\.kakao\.com/[0-9]+', place_url):
                            raise ValueError()
                        place_url = place_url.replace('http://', 'https://', 1)
                        identifier = 'kakao-' + identifier
                    else:
                        address = text((doc.get('address') or {}).get('address_name') or doc.get('address_name', ''))
                        road = text((doc.get('road_address') or {}).get('address_name', ''))
                        name, category = road or address, '주소'
                        identifier = 'kakao-address-' + hashlib.sha256(f'{lat}:{lng}:{name}'.encode()).hexdigest()[:24]
                        place_url = f'https://map.kakao.com/link/map/{lat},{lng}'
                    if not name:
                        raise ValueError()
                    location = (round(lat, 5), round(lng, 5), road or address or name)
                    if identifier in ids or location in locations:
                        continue
                    ids.add(identifier); locations.add(location)
                    results.append(dict(id=identifier, name=name, address=address, roadAddress=road,
                                        category=category, lat=lat, lng=lng, source='kakao', placeUrl=place_url))
            remaining_time(deadline, self._clock)
            return results[:15]
        except PlaceSearchError:
            raise
        except TimeoutError:
            raise PlaceSearchError('PLACE_SEARCH_TIMEOUT', 504) from None
        except Exception:
            raise PlaceSearchError('PLACE_SEARCH_PROVIDER_UNAVAILABLE', 502) from None


class MockPlaceSearch:
    def search(self, query, x=None, y=None, timeout=3):
        return [dict(id='mock-place', name='가상 검색 장소', address='가상 지번 주소', roadAddress='가상 도로명 주소',
                     category='시험 장소', lat=37.5665, lng=126.978, source='kakao',
                     placeUrl='https://place.map.kakao.com/1')]


class PlaceSearch:
    def __init__(self, provider=None, *, clock=time.monotonic, timeout=3, limit=30):
        self.provider, self.clock, self.timeout, self.limit = provider, clock, timeout, limit
        self._attempts, self._lock = {}, Lock()

    @classmethod
    def from_environment(cls):
        key = load_key()
        return cls(KakaoPlaceSearch(key) if key else None)

    def search(self, account, value):
        try:
            query, x, y = search_query(value)
            if self.provider is None:
                raise PlaceSearchError()
            rate_attempt(account, self._attempts, self._lock, self.clock, self.limit,
                         lambda: PlaceSearchError('PLACE_SEARCH_RATE_LIMITED', 429))
            provider = self.provider
            value = bounded_call(lambda timeout: provider.search(query, x, y, timeout),
                                 _SEARCH_SLOTS, self.timeout, PlaceSearchError, 'PLACE_SEARCH',
                                 name='place-search', thread_factory=Thread)
            LOG.info('place.search: loaded count=%d', len(value))
            return value
        except PlaceSearchError as error:
            LOG.info('place.search: failed reason=%s', error.code)
            raise
