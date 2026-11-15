"""Pinned local OSM POI snapshots and explicit regional road ordering.

Named nodes are a partial public map catalog, not food quality, open-now,
facility entrance, complete nearest search or live traffic evidence. No network
fetch, account access, consent decision, history write or navigation occurs here.
The authenticated caller must authorize location use before calling road_order.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from types import MappingProxyType
from road_provider import Coordinate, RoadProviderError, GraphSource, number

CATEGORIES = frozenset(('restaurant', 'cafe', 'fast_food', 'food_court',
                       'fuel', 'toilets', 'charging_station', 'rest_area'))
COVERAGE = 'named tagged nodes only; ways and relations not covered'

class PlaceCatalogError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def _fail(code='PLACE_CATALOG_INVALID'):
    raise PlaceCatalogError(code)

def _bounds(value):
    if type(value) not in (tuple, list) or len(value) != 4 or not all(number(x) for x in value):
        _fail()
    west, south, east, north = value
    if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
        _fail()
    return tuple(value)

def _contains(bounds, point):
    west, south, east, north = bounds
    return west <= point.longitude <= east and south <= point.latitude <= north

def _text(value, maximum=512):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        _fail()
    return value

@dataclass(frozen=True)
class OsmPlace:
    source_id: str
    name: str
    category: str
    coordinate: Coordinate
    tags: object

@dataclass(frozen=True)
class CatalogSource:
    source_sha256: str
    catalog_sha256: str
    data_as_of: str
    bounds: tuple
    publisher: str
    url: str
    attribution: str
    license: str = 'ODbL-1.0'
    geometry_coverage: str = COVERAGE
    live: bool = False

@dataclass(frozen=True)
class RankedPlace:
    place: OsmPlace
    road: object

@dataclass(frozen=True)
class RoadOrder:
    items: tuple
    eligible_count: int
    source: CatalogSource
    nearest_verified: bool = False
    entrance_verified: bool = False

class OsmPlaceCatalog:
    MAX_BYTES = 8 * 1024 * 1024
    MAX_PLACES = 10000
    MAX_QUERY = 1000
    def __init__(self, source, places):
        self.source, self.places = source, tuple(places)
    @classmethod
    def load(cls, path, *, expected_sha256):
        if not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256):
            _fail('PLACE_CATALOG_PIN_REQUIRED')
        with open(path, 'rb') as handle:
            raw = handle.read(cls.MAX_BYTES+1)
        if len(raw) > cls.MAX_BYTES:
            _fail('PLACE_CATALOG_SIZE_LIMIT')
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            _fail('PLACE_CATALOG_PIN_MISMATCH')
        def pairs(items):
            obj = {}
            for key, value in items:
                if key in obj:
                    _fail()
                obj[key] = value
            return obj
        try:
            doc = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: _fail())
            if type(doc) is not dict or type(doc.get('schemaVersion')) is not int or doc.get('schemaVersion') != 1 or type(doc.get('source')) is not dict or type(doc.get('places')) is not list:
                _fail()
            meta = doc['source']
            required = {'sourceSha256','dataAsOf','bounds','publisher','url','attribution','license','geometryCoverage','live'}
            if set(meta) != required or meta['license'] != 'ODbL-1.0' or meta['geometryCoverage'] != COVERAGE or meta['live'] is not False:
                _fail()
            if not isinstance(meta['sourceSha256'], str) or not re.fullmatch('[a-f0-9]{64}', meta['sourceSha256']):
                _fail()
            stamp = datetime.fromisoformat(_text(meta['dataAsOf']).replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                _fail()
            bounds = _bounds(meta['bounds'])
            source = CatalogSource(meta['sourceSha256'], expected_sha256, meta['dataAsOf'], bounds,
                _text(meta['publisher']), _text(meta['url']), _text(meta['attribution']))
            if not source.url.startswith('https://download.geofabrik.de/'):
                _fail()
            if len(doc['places']) > cls.MAX_PLACES:
                _fail('PLACE_CATALOG_SIZE_LIMIT')
            places, seen = [], set()
            for row in doc['places']:
                if type(row) is not dict or set(row) != {'osmType','osmId','name','latitude','longitude','tags'} or row['osmType'] != 'node' or type(row['osmId']) is not int or row['osmId'] <= 0:
                    _fail()
                identity = 'osm:node:'+str(row['osmId'])
                if identity in seen or type(row['tags']) is not dict:
                    _fail()
                seen.add(identity)
                tags = row['tags']
                if not all(isinstance(k,str) and _text(v,2048) for k,v in tags.items()):
                    _fail()
                category = 'rest_area' if tags.get('highway') == 'rest_area' else tags.get('amenity')
                if category not in CATEGORIES:
                    _fail()
                point = Coordinate(row['latitude'], row['longitude'])
                if not _contains(bounds, point):
                    _fail()
                places.append(OsmPlace(identity, _text(row['name']), category, point, MappingProxyType(dict(tags))))
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, RoadProviderError, ValueError) as error:
            if isinstance(error, PlaceCatalogError):
                raise
            _fail()
        return cls(source, places)
    def candidates(self, category, bounds):
        if category not in CATEGORIES:
            _fail('PLACE_CATEGORY_UNSUPPORTED')
        bounds = _bounds(bounds)
        west, south, east, north = bounds
        if not _contains(self.source.bounds, Coordinate(south,west)) or not _contains(self.source.bounds, Coordinate(north,east)):
            _fail('PLACE_CATALOG_OUTSIDE_COVERAGE')
        result = tuple(p for p in self.places if p.category == category and _contains(bounds,p.coordinate))
        if len(result) > self.MAX_QUERY:
            _fail('PLACE_QUERY_LIMIT')
        return result
    def road_order(self, provider, origin, *, category, bounds):
        if not isinstance(origin, Coordinate) or not _contains(self.source.bounds, origin):
            _fail('PLACE_CATALOG_OUTSIDE_COVERAGE')
        if not isinstance(provider.source, GraphSource) or provider.source.source_sha256 != self.source.source_sha256:
            _fail('PLACE_GRAPH_SOURCE_MISMATCH')
        candidates = self.candidates(category,bounds)
        metrics = provider.matrix(origin, tuple(p.coordinate for p in candidates))
        if len(metrics) != len(candidates):
            _fail('PLACE_ROAD_RESPONSE_INVALID')
        # Evaluate every explicit-region candidate; retain unreachable entries.
        # The engine's auto-costing route length orders these entries, not a
        # straight-line prefilter or a globally-shortest/complete-nearest claim.
        items = tuple(sorted((RankedPlace(p,m) for p,m in zip(candidates,metrics)),
            key=lambda item: (not item.road.reachable,
                item.road.distance_meters if item.road.reachable else float('inf'), item.place.source_id)))
        return RoadOrder(items,len(candidates),self.source)
