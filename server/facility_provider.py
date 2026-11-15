"""Road ordering of a pinned official rest-stop snapshot, never entry proof.

Reuse the existing CSV normalizer and pass its full DATASET plus a separately
pinned canonical dataset digest. No ranking by air distance, query persistence,
public routing, current facility/price inference or consent authority lives here.
"""
from dataclasses import dataclass
from types import MappingProxyType
from datetime import date
import hashlib,json,re
from road_provider import Coordinate,GraphSource,number
from place_provider import PlaceCatalogError

FACILITIES=frozenset(('toilet','nursing','evCharger','gasStation','lpg','restaurant','restSpace'))
def _fail(code='REST_SNAPSHOT_INVALID'):
    raise PlaceCatalogError(code)
def dataset_digest(dataset):
    return hashlib.sha256(json.dumps(dataset,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
@dataclass(frozen=True)
class RestStop:
    source_id:str
    name:str
    coordinate:Coordinate
    route_number:str
    road_kind:str
    direction:str|None
    reported_direction:str|None
    facilities:object
    food_names:tuple
    data_as_of:str
@dataclass(frozen=True)
class RestRoadOrder:
    items:tuple
    source:object
    eligible_count:int
    basis:str='auto-road-to-reported-snapshot-coordinate'
    nearest_verified:bool=False
    entrance_verified:bool=False
    direction_verified:bool=False
    current_open:object=None
    current_price:object=None
class OfficialRestCatalog:
    def __init__(self,dataset,*,expected_dataset_sha256):
        if not isinstance(expected_dataset_sha256,str) or not re.fullmatch('[a-f0-9]{64}',expected_dataset_sha256):_fail('REST_SNAPSHOT_PIN_REQUIRED')
        try:
            if dataset_digest(dataset)!=expected_dataset_sha256:_fail('REST_SNAPSHOT_PIN_MISMATCH')
            source=dataset['source'];rows=dataset['items']
            if source['datasetId']!='15025446' or not re.fullmatch('[a-f0-9]{64}',source['csvSha256']) or not source['license'] or type(rows)is not list or type(source['rowCount'])is not int or source['rowCount']!=len(rows) or len(rows)>1000:_fail()
            points=[];seen=set()
            for row in rows:
                identity=row['id']
                if not isinstance(identity,str) or identity in seen or not identity or not isinstance(row['name'],str) or not row['name']:_fail()
                seen.add(identity);facilities=row['facilities']
                if set(facilities)!=FACILITIES or any(v is not None and type(v)is not bool for v in facilities.values()):_fail()
                if row['direction'] not in (None,'up','down','both') or type(row['foodNames'])is not list or any(not isinstance(v,str)for v in row['foodNames']):_fail()
                date.fromisoformat(row['dataAsOf'])
                points.append(RestStop(identity,row['name'],Coordinate(row['latitude'],row['longitude']),row['routeNumber'],row['roadKind'],row['direction'],row['reportedDirection'],MappingProxyType(dict(facilities)),tuple(row['foodNames']),row['dataAsOf']))
            # Do not retain a caller-mutable metadata tree as current provenance.
            self.source=MappingProxyType({k:tuple(v) if isinstance(v,list) else v for k,v in source.items()})
            self.places=tuple(points)
        except PlaceCatalogError:raise
        except (KeyError,TypeError,ValueError):_fail()
    def road_order(self,provider,origin,*,bounds,required_facilities=(),direction=None,route_number=None):
        if not isinstance(provider.source,GraphSource) or not isinstance(origin,Coordinate):_fail('REST_QUERY_INVALID')
        if type(bounds)not in(tuple,list) or len(bounds)!=4 or not all(number(x) for x in bounds):_fail('REST_QUERY_INVALID')
        west,south,east,north=bounds
        if not west<east or not south<north:_fail('REST_QUERY_INVALID')
        if not provider.source.contains(origin) or not provider.source.contains(Coordinate(south,west)) or not provider.source.contains(Coordinate(north,east)):_fail('REST_QUERY_OUTSIDE_GRAPH')
        if type(required_facilities)not in(tuple,list) or any(not isinstance(k,str)for k in required_facilities) or len(set(required_facilities))!=len(required_facilities) or any(k not in FACILITIES for k in required_facilities):_fail('REST_FACILITY_UNSUPPORTED')
        if direction not in(None,'up','down','both') or (route_number is not None and (not isinstance(route_number,str)or not 1<=len(route_number)<=20)):_fail('REST_QUERY_INVALID')
        candidates=tuple(p for p in self.places if west<=p.coordinate.longitude<=east and south<=p.coordinate.latitude<=north
            and all(p.facilities[k] is True for k in required_facilities)
            and (direction is None or p.direction in ((direction,'both') if direction!='both' else ('both',)))
            and (route_number is None or p.route_number==route_number))
        metrics=provider.matrix(origin,tuple(p.coordinate for p in candidates))
        if len(metrics)!=len(candidates):_fail('REST_ROAD_RESPONSE_INVALID')
        ordered=tuple(sorted(zip(candidates,metrics),key=lambda x:(not x[1].reachable,x[1].distance_meters if x[1].reachable else float('inf'),x[0].source_id)))
        return RestRoadOrder(ordered,self.source,len(candidates))
