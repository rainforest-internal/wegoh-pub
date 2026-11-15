"""Caller contracts, not mock claims of real graph or vehicle operation."""
from datetime import datetime, timezone, timedelta
import unittest
from fastapi import HTTPException
from discovery_local import LocalDiscovery, DiscoveryError, decode, prepare
from road_provider import Coordinate, GraphSource, RoadMetric, RoadProviderError
from place_provider import OsmPlaceCatalog, CatalogSource, OsmPlace
from facility_provider import OfficialRestCatalog, dataset_digest
from rest_stop_data import DATASET

NOW = datetime(2030,1,1,tzinfo=timezone.utc)
BOUNDS = dict(west=124,south=32,east=132,north=40)

def selected():
    return dict(kind='selected-place',place=dict(id='test',provider='synthetic',name='Synthetic selected place',address='',latitude=37.5,longitude=127.0))

def query(kind='places', **extra):
    value = dict(anchor=selected(),bounds=BOUNDS.copy(),category='cafe',limit=2)
    if kind == 'rest':
        value = dict(anchor=selected(),roadSearch=dict(bounds=BOUNDS.copy(),order='distance'),limit=2)
    return dict(value,**extra)

class Provider:
    def __init__(self):
        self.source = GraphSource('synthetic', 'a'*64, '2030-01-01T00:00:00+00:00', (124,32,132,40))
        self.calls = []
        self.error = None
    def matrix(self,origin,destinations):
        self.calls.append((origin,tuple(destinations)))
        if self.error: raise RoadProviderError(self.error)
        # Different actual road-order/duration outcomes and an unreachable cell.
        return tuple(RoadMetric(*((True,100.0,1.0) if n==0 else (True,20.0,10.0) if n==1 else (False,None,None)),self.source) for n,_ in enumerate(destinations))

class LocalDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.provider = Provider()
        source = CatalogSource('a'*64,'b'*64,'2030-01-01T00:00:00+00:00',(124,32,132,40),'synthetic OSM source','https://download.geofabrik.de/fixture','© OpenStreetMap contributors')
        self.catalog = OsmPlaceCatalog(source,tuple(OsmPlace('osm:node:'+str(n), 'Synthetic cafe '+str(n),'cafe',Coordinate(37.51+n/1000,127),{}) for n in range(1,4)))
        self.rest = OfficialRestCatalog(DATASET,expected_dataset_sha256=dataset_digest(DATASET))
        self.service = LocalDiscovery(self.provider,self.catalog,self.rest,official_dataset_sha256=dataset_digest(DATASET))
    def error(self,status,fn):
        with self.assertRaises((DiscoveryError,HTTPException)) as found: fn()
        actual = getattr(found.exception,'status',getattr(found.exception,'status_code',None))
        self.assertEqual(actual,status)
    def test_all_candidates_before_limit_distance_duration_and_unreachable(self):
        value = self.service.query(query(), 'places', now=NOW)
        self.assertEqual(len(self.provider.calls[0][1]),3)
        self.assertEqual([p['place']['id'] for p in value['items']],['osm:node:2','osm:node:1'])
        self.assertEqual(value['counts'],dict(eligible=3,reachable=2,returned=2))
        duration = self.service.query(query(order='duration',limit=20),'places',now=NOW)
        self.assertEqual([p['place']['id'] for p in duration['items']],['osm:node:1','osm:node:2','osm:node:3'])
        self.assertEqual(duration['items'][-1]['road'],dict(reachable=False,distanceMeters=None,estimatedDurationSeconds=None))
        self.assertEqual(duration['anchor'],dict(kind='selected-place',capturedAt=None,accuracyMeters=None))
        self.assertEqual(set(duration),{'items','source','graph','basis','queriedAt','anchor','applied','counts','unknown'})
        self.assertEqual(set(duration['items'][0]),{'place','category','road','facilities','reportedRoad','sourceAsOf'})
        self.assertIsNone(duration['items'][0]['facilities']);self.assertIsNone(duration['unknown']['currentPrice'])
        self.assertFalse(duration['graph']['liveTraffic']);self.assertFalse(duration['graph']['entranceVerified'])
        self.assertEqual(duration['source']['dataAsOf']['value'],'2030-01-01T00:00:00+00:00')
    def test_closed_duplicate_nonfinite_wrong_anchor_and_radius_denied_before_engine(self):
        self.error(400,lambda:decode(b'{"anchor":{},"anchor":{}}'))
        self.error(400,lambda:decode(b'{"latitude":NaN}'))
        for value in [query(functionalRevision=1),query(kind='rest',radiusMeters=50000),query(bounds=dict(BOUNDS,west=True)),query(category='unknown'),query(limit=True)]:
            self.error(400,lambda v=value:self.service.query(v,'rest' if 'roadSearch' in v else 'places',now=NOW))
        location=dict(kind='browser-location',consent=False,position=dict(latitude=37.5,longitude=127,accuracyMeters=10,capturedAt=NOW.isoformat()))
        self.error(400,lambda:self.service.query(query(anchor=location),'places',now=NOW))
        location['consent']=True;location['position']['capturedAt']=(NOW-timedelta(seconds=301)).isoformat()
        self.error(400,lambda:self.service.query(query(anchor=location),'places',now=NOW))
        self.assertEqual(self.provider.calls,[])
    def test_explicit_fresh_location_and_viewport_coverage(self):
        location=dict(kind='browser-location',consent=True,position=dict(latitude=37.5,longitude=127,accuracyMeters=10,capturedAt=NOW.isoformat()))
        value=self.service.query(query(anchor=location),'places',now=NOW)
        self.assertEqual(value['anchor'],dict(kind='browser-reported',capturedAt=NOW.isoformat(),accuracyMeters=10))
        self.provider.calls.clear()
        self.error(400,lambda:self.service.query(query(bounds=dict(BOUNDS,east=140)),'places',now=NOW))
        self.assertEqual(self.provider.calls,[])
    def test_official_source_filters_and_pin_preserve_unknown(self):
        value=self.service.query(query(kind='rest',requiredFacilities=['nursing'],roadFilter=dict(direction='up')),'rest',now=NOW)
        self.assertGreater(value['counts']['eligible'],0)
        self.assertEqual(len(self.provider.calls[0][1]),value['counts']['eligible'])
        self.assertEqual(value['source']['sourceSha256'],DATASET['source']['csvSha256'])
        self.assertEqual(value['source']['catalogSha256'],dataset_digest(DATASET))
        self.assertEqual(value['source']['dataAsOf'],dict(value='2026-09-17',precision='date'))
        for item in value['items']:
            self.assertTrue(item['facilities']['nursing']);self.assertIn(item['reportedRoad']['direction'],('up','both'))
        self.error(503,lambda:LocalDiscovery(self.provider,self.catalog,self.rest,official_dataset_sha256='0'*64))
    def test_engine_error_busy_and_source_mismatch_never_fallback(self):
        self.provider.error='ROAD_PROVIDER_RESPONSE_INVALID'
        self.error(502,lambda:self.service.query(query(),'places',now=NOW))
        self.provider.error='ROAD_PROVIDER_TIMEOUT'
        self.error(504,lambda:self.service.query(query(),'places',now=NOW))
        self.provider.error=None
        self.service._gate.acquire()
        try:self.error(429,lambda:self.service.query(query(),'places',now=NOW))
        finally:self.service._gate.release()
        self.assertEqual(len(self.provider.calls),2)
        self.provider.source=GraphSource('different','c'*64,'2030-01-01T00:00:00+00:00',(124,32,132,40))
        self.error(503,lambda:LocalDiscovery(self.provider,self.catalog,self.rest,official_dataset_sha256=dataset_digest(DATASET)))

if __name__=='__main__':unittest.main()
