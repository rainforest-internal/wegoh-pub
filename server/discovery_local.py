"""Explicit Browser regional road queries over already pinned local catalogs.

No account authority, external service, raw-location persistence or navigation.
The HTTP owner authenticates before dispatch and again before returning results.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import threading
from road_provider import Coordinate, RoadProviderError, number
from place_provider import CATEGORIES, PlaceCatalogError

class DiscoveryError(ValueError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)

def fail(code='DISCOVERY_QUERY_INVALID', status=400):
    raise DiscoveryError(status, code)

def decode(raw):
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > 4096:
        fail('DISCOVERY_REQUEST_TOO_LARGE', 413)
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                fail('DISCOVERY_DUPLICATE_FIELD')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: fail('DISCOVERY_NUMBER_INVALID'))
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, DiscoveryError):
            raise
        fail()

def bounds(value):
    keys = ('west', 'south', 'east', 'north')
    if type(value) is not dict or set(value) != set(keys) or not all(number(value[k]) for k in keys):
        fail('DISCOVERY_BOUNDS_INVALID')
    west, south, east, north = (value[k] for k in keys)
    if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
        fail('DISCOVERY_BOUNDS_INVALID')
    return west, south, east, north

def bounds_json(value):
    return dict(zip(('west', 'south', 'east', 'north'), value))

@dataclass(frozen=True, repr=False)
class Query:
    origin: Coordinate
    anchor: dict
    bounds: tuple
    order: str
    limit: int
    category: str | None
    facilities: tuple
    road_filter: dict
    def __repr__(self):
        return 'DiscoveryQuery(redacted)'

def prepare(value, kind, now=None):
    from team_discovery import anchor, FACILITIES
    if type(value) is not dict:
        fail()
    if kind == 'rest':
        if not {'anchor', 'roadSearch'} <= set(value) or set(value) - {'anchor','roadSearch','requiredFacilities','roadFilter','limit'}:
            fail()
        search = value['roadSearch']
        if type(search) is not dict or set(search) != {'bounds','order'}:
            fail()
        rectangle, order = bounds(search['bounds']), search['order']
        facilities = value.get('requiredFacilities', [])
        if type(facilities) is not list or any(type(x) is not str or x not in FACILITIES for x in facilities) or len(set(facilities)) != len(facilities):
            fail('DISCOVERY_FACILITY_INVALID')
        road = value.get('roadFilter', {})
        if type(road) is not dict or set(road) - {'routeNumber','direction'}:
            fail()
        if 'routeNumber' in road and (type(road['routeNumber']) is not str or not 1 <= len(road['routeNumber']) <= 20 or any(ord(c) < 32 for c in road['routeNumber'])):
            fail()
        if 'direction' in road and road['direction'] not in ('up','down','both'):
            fail()
        category = None
    elif kind == 'places':
        if not {'anchor','bounds','category'} <= set(value) or set(value) - {'anchor','bounds','category','order','limit'}:
            fail()
        category = value['category']
        if type(category) is not str or category not in CATEGORIES:
            fail('DISCOVERY_CATEGORY_INVALID')
        rectangle, order = bounds(value['bounds']), value.get('order','distance')
        facilities, road = [], {}
    else:
        fail()
    if type(order) is not str or order not in ('distance','duration'):
        fail('DISCOVERY_ORDER_INVALID')
    limit = value.get('limit',10)
    if type(limit) is not int or not 1 <= limit <= 20:
        fail('DISCOVERY_LIMIT_INVALID')
    lat, lon, reported = anchor(value['anchor'], now or datetime.now(timezone.utc))
    return Query(Coordinate(lat,lon), dict(reported), rectangle, order, limit, category, tuple(facilities), dict(road))

class LocalDiscovery:
    MAX_RESULT_BYTES = 128 * 1024
    def __init__(self, provider, places, rest, *, official_dataset_sha256):
        from facility_provider import dataset_digest
        from rest_stop_data import DATASET
        if dataset_digest(DATASET) != official_dataset_sha256 or json.dumps(dict(rest.source),sort_keys=True,ensure_ascii=False) != json.dumps(DATASET['source'],sort_keys=True,ensure_ascii=False):
            fail('DISCOVERY_OFFICIAL_PIN_MISMATCH',503)
        self.provider, self.places, self.rest = provider, places, rest
        self.official_dataset_sha256 = official_dataset_sha256
        if provider.source.source_sha256 != places.source.source_sha256:
            fail('DISCOVERY_GRAPH_CATALOG_MISMATCH',503)
        self._gate = threading.Lock()

    def _graph(self):
        source = self.provider.source
        return dict(sourceId=source.source_id, sourceSha256=source.source_sha256,
            dataAsOf=source.data_as_of, bounds=bounds_json(source.bounds),
            attribution=source.attribution, license=source.license,
            liveTraffic=False, globallyShortest=False, entranceVerified=False,
            directionVerified=False)

    @staticmethod
    def _date(value):
        # The fixed official snapshot reports its source dates as an array.
        if isinstance(value,(tuple,list)):
            if len(value)!=1: fail('DISCOVERY_SOURCE_DATE_UNSUPPORTED',502)
            value=value[0]
        if not isinstance(value,str): fail('DISCOVERY_SOURCE_DATE_UNSUPPORTED',502)
        return dict(value=value, precision='datetime' if 'T' in value else 'date')

    @staticmethod
    def _place(identity, provider, name, point):
        # Preserve source names. Do not truncate into a different selected place.
        if not isinstance(name,str) or not 1 <= len(name) <= 80 or any(ord(c)<32 for c in name):
            fail('DISCOVERY_SOURCE_NAME_UNSUPPORTED',502)
        return dict(id=identity, provider=provider, name=name, address='',
            latitude=point.latitude, longitude=point.longitude)

    def _metric(self,value):
        if value.source != self.provider.source or value.live_traffic is not False or value.globally_shortest is not False:
            fail('DISCOVERY_ROAD_RESULT_INVALID',502)
        if type(value.reachable) is not bool:
            fail('DISCOVERY_ROAD_RESULT_INVALID',502)
        distance, seconds = value.distance_meters, value.estimated_duration_seconds
        if value.reachable:
            if not all(number(x) and x >= 0 for x in (distance,seconds)):
                fail('DISCOVERY_ROAD_RESULT_INVALID',502)
        elif distance is not None or seconds is not None:
            fail('DISCOVERY_ROAD_RESULT_INVALID',502)
        return dict(reachable=value.reachable, distanceMeters=distance,
            estimatedDurationSeconds=seconds)

    def query(self, value, kind, *, now=None):
        stamp = now or datetime.now(timezone.utc)
        query = prepare(value,kind,stamp)
        west,south,east,north = query.bounds
        if not all(self.provider.source.contains(p) for p in
                (query.origin,Coordinate(south,west),Coordinate(north,east))):
            fail('DISCOVERY_OUTSIDE_COVERAGE')
        if not self._gate.acquire(blocking=False):
            fail('DISCOVERY_BUSY',429)
        try:
            try:
                result = self._run(query,kind,stamp)
            except (RoadProviderError,PlaceCatalogError) as error:
                code = error.code
                if 'TIMEOUT' in code:
                    fail('DISCOVERY_ENGINE_TIMEOUT',504)
                if any(x in code for x in ('OUTSIDE','CANDIDATE_LIMIT','QUERY_LIMIT','UNSUPPORTED','INVALID_QUERY')):
                    fail('DISCOVERY_QUERY_UNSUPPORTED')
                if 'UNAVAILABLE' in code:
                    fail('DISCOVERY_ENGINE_UNAVAILABLE',503)
                fail('DISCOVERY_ENGINE_RESULT_INVALID',502)
            if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode()) > self.MAX_RESULT_BYTES:
                fail('DISCOVERY_RESULT_TOO_LARGE',502)
            return result
        finally:
            self._gate.release()

    def _run(self,query,kind,stamp):
        rows = []
        if kind == 'rest':
            ordered = self.rest.road_order(self.provider,query.origin,bounds=query.bounds,
                required_facilities=query.facilities,direction=query.road_filter.get('direction'),
                route_number=query.road_filter.get('routeNumber'))
            for place,metric in ordered.items:
                rows.append(dict(place=self._place(place.source_id,'official-rest-snapshot',place.name,place.coordinate),
                    category='official-rest',road=self._metric(metric),facilities=dict(place.facilities),
                    reportedRoad=dict(kind=place.road_kind,routeNumber=place.route_number,routeName=self._route_name(place.source_id),
                        direction=place.direction,reportedDirection=place.reported_direction),sourceAsOf=self._date(place.data_as_of)))
            raw = self.rest.source
            source = dict(id='official-rest-snapshot',publisher=raw['publisher'],catalogUrl=raw['catalogUrl'],
                license=raw['license'],sourceSha256=raw['csvSha256'],catalogSha256=self.official_dataset_sha256,
                dataAsOf=self._date(raw['dataAsOf']),coverage=dict(bounds=None,scope='reported expressway rest-stop snapshot',
                    excluded=['entrance and actual travel direction unverified','food names and live facility status unavailable']),
                attribution=dict(text=raw['publisher']+' / '+raw['name'],url=raw['catalogUrl']))
        else:
            ordered = self.places.road_order(self.provider,query.origin,category=query.category,bounds=query.bounds)
            for item in ordered.items:
                place,metric = item.place,item.road
                rows.append(dict(place=self._place(place.source_id,'osm-named-node',place.name,place.coordinate),
                    category=place.category,road=self._metric(metric),facilities=None,reportedRoad=None,
                    sourceAsOf=self._date(ordered.source.data_as_of)))
            raw = ordered.source
            source = dict(id='osm-named-nodes',publisher=raw.publisher,catalogUrl=raw.url,license=raw.license,
                sourceSha256=raw.source_sha256,catalogSha256=raw.catalog_sha256,dataAsOf=self._date(raw.data_as_of),
                coverage=dict(bounds=bounds_json(raw.bounds),scope=raw.geometry_coverage,
                    excluded=['ways','relations','unnamed nodes','live prices and availability']),
                attribution=dict(text=raw.attribution,url='https://www.openstreetmap.org/copyright'))
        key = 'distanceMeters' if query.order == 'distance' else 'estimatedDurationSeconds'
        rows.sort(key=lambda row:(not row['road']['reachable'],row['road'][key] if row['road']['reachable'] else float('inf'),row['place']['id']))
        return dict(items=rows[:query.limit],source=source,graph=self._graph(),
            basis='valhalla-auto-road-graph-to-reported-coordinate',queriedAt=stamp.isoformat(),anchor=query.anchor,
            applied=dict(bounds=bounds_json(query.bounds),order=query.order,limit=query.limit,category=query.category,
                requiredFacilities=list(query.facilities),roadFilter=query.road_filter),
            counts=dict(eligible=ordered.eligible_count,reachable=sum(x['road']['reachable'] for x in rows),returned=min(len(rows),query.limit)),
            unknown=dict(currentOpen=None,currentPrice=None,chargerAvailable=None,physicalEntranceVerified=False,physicalDirectionVerified=False))

    @staticmethod
    def _route_name(identity):
        from rest_stop_data import DATASET
        return next((row['routeName'] for row in DATASET['items'] if row['id']==identity),'')
