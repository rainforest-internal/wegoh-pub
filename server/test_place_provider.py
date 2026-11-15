import hashlib,json,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from road_provider import Coordinate,GraphSource,RoadMetric,RoadProviderError
from place_provider import OsmPlaceCatalog,PlaceCatalogError,COVERAGE

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'catalog.json'
        self.doc={'schemaVersion':1,'source':{'sourceSha256':'a'*64,'dataAsOf':'2026-10-29T00:00:00Z','bounds':[126,37,128,38],
            'publisher':'Synthetic public map fixture','url':'https://download.geofabrik.de/synthetic.osm.pbf','attribution':'Synthetic OSM attribution',
            'license':'ODbL-1.0','geometryCoverage':COVERAGE,'live':False},'places':[
            {'osmType':'node','osmId':1,'name':'합성 · 장소','latitude':37.01,'longitude':127,'tags':{'amenity':'restaurant'}},
            {'osmType':'node','osmId':2,'name':'다른 합성 장소','latitude':37.5,'longitude':127,'tags':{'amenity':'restaurant'}},
            {'osmType':'node','osmId':3,'name':'미연결 합성 장소','latitude':37.6,'longitude':127,'tags':{'amenity':'restaurant'}}]}
    def load(self):
        self.path.write_text(json.dumps(self.doc,ensure_ascii=False));pin=hashlib.sha256(self.path.read_bytes()).hexdigest()
        return OsmPlaceCatalog.load(self.path,expected_sha256=pin)
    def provider(self,metrics):
        class Engine:
            source=GraphSource('synthetic','a'*64,'2026-10-29T00:00:00Z',(126,37,128,38))
            calls=[]
            def matrix(self,origin,targets):self.calls.append(targets);return metrics
        return Engine()
    def test_all_candidates_road_order_and_explicit_unknowns_preserve_source(self):
        catalog=self.load();engine=self.provider((RoadMetric(True,900,70,None),RoadMetric(True,300,30,None),RoadMetric(False,None,None,None)))
        order=catalog.road_order(engine,Coordinate(37.001,127),category='restaurant',bounds=(126,37,128,38))
        self.assertEqual([x.place.source_id for x in order.items],['osm:node:2','osm:node:1','osm:node:3'])
        self.assertEqual(len(engine.calls[0]),3);self.assertEqual(order.eligible_count,3)
        self.assertFalse(order.nearest_verified);self.assertFalse(order.entrance_verified);self.assertFalse(order.source.live)
        self.assertEqual(order.items[1].place.name,'합성 · 장소');self.assertEqual(order.source.geometry_coverage,COVERAGE)
        with self.assertRaises(TypeError):catalog.places[0].tags['price']='invented'
    def test_pinning_duplicate_identity_source_and_bad_coordinates_fail(self):
        catalog=self.load()
        with self.assertRaisesRegex(PlaceCatalogError,'PIN_MISMATCH'):OsmPlaceCatalog.load(self.path,expected_sha256='0'*64)
        mutations=[lambda d:d['places'].append(dict(d['places'][0])),lambda d:d['source'].update(live=True),
            lambda d:d['source'].update(license='unknown'),lambda d:d['source'].update(geometryCoverage='complete nearest'),
            lambda d:d['places'][0].update(latitude=True),lambda d:d['places'][0].update(latitude=90)]
        original=json.dumps(self.doc)
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.doc=json.loads(original);mutate(self.doc)
                with self.assertRaises(PlaceCatalogError):self.load()
    def test_no_silent_truncation_or_straight_fallback(self):
        catalog=self.load();engine=self.provider(())
        with self.assertRaisesRegex(PlaceCatalogError,'OUTSIDE_COVERAGE'):catalog.road_order(engine,Coordinate(36,127),category='restaurant',bounds=(126,37,128,38))
        with self.assertRaisesRegex(PlaceCatalogError,'UNSUPPORTED'):catalog.candidates('best-food',(126,37,128,38))
        with self.assertRaisesRegex(PlaceCatalogError,'OUTSIDE_COVERAGE'):catalog.candidates('restaurant',(125,37,128,38))
        catalog.MAX_QUERY=2
        with self.assertRaisesRegex(PlaceCatalogError,'QUERY_LIMIT'):catalog.road_order(engine,Coordinate(37.001,127),category='restaurant',bounds=(126,37,128,38))
        self.assertFalse(engine.calls)
        catalog.MAX_QUERY=1000
        def broken(*args):raise RoadProviderError('ROAD_PROVIDER_SNAP_REJECTED')
        engine.matrix=broken
        with self.assertRaisesRegex(RoadProviderError,'SNAP_REJECTED'):catalog.road_order(engine,Coordinate(37.001,127),category='restaurant',bounds=(126,37,128,38))
    def test_graph_source_mismatch_before_location_request(self):
        catalog=self.load();engine=self.provider(())
        engine.source=replace(engine.source,source_sha256='b'*64)
        with self.assertRaisesRegex(PlaceCatalogError,'GRAPH_SOURCE_MISMATCH'):catalog.road_order(engine,Coordinate(37.001,127),category='restaurant',bounds=(126,37,128,38))
        self.assertFalse(engine.calls)

if __name__=='__main__':unittest.main()
