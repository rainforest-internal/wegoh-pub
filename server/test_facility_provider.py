"""Synthetic isolated snapshot/road-contract tests, not actual facility access."""
import copy,unittest
from road_provider import Coordinate,GraphSource,RoadMetric,RoadProviderError
from place_provider import PlaceCatalogError
from facility_provider import OfficialRestCatalog,dataset_digest,FACILITIES
class FacilityTests(unittest.TestCase):
    def setUp(self):
        self.rows=[]
        for i,direction in enumerate(['up','both',None]):
            self.rows.append(dict(id='synthetic-'+str(i),name='합성 · 휴식 '+str(i),latitude=37.1+i*.1,longitude=127,routeNumber='1',roadKind='합성 원문 도로',direction=direction,reportedDirection=direction,facilities={k:(None if i==2 else True) for k in FACILITIES},foodNames=[],dataAsOf='2026-09-17'))
        self.data=dict(source=dict(datasetId='15025446',csvSha256='a'*64,rowCount=3,license='Synthetic source metadata',dataAsOf=['2026-09-17']),items=self.rows)
    def catalog(self):return OfficialRestCatalog(self.data,expected_dataset_sha256=dataset_digest(self.data))
    def engine(self):
        class Engine:
            source=GraphSource('synthetic','b'*64,'2026-10-29T00:00:00Z',(126,37,128,38))
            calls=[]
            def matrix(self,origin,targets):
                self.calls.append(targets);return tuple(RoadMetric(True,float(1000-i*100),80,self.source)for i,_ in enumerate(targets))
        return Engine()
    def test_all_source_facility_filters_are_and_unknowns_not_true(self):
        catalog=self.catalog();engine=self.engine();out=catalog.road_order(engine,Coordinate(37.01,127),bounds=(126,37,128,38),required_facilities=('nursing','toilet'),direction='up')
        self.assertEqual(out.eligible_count,2);self.assertEqual(len(engine.calls[0]),2)
        self.assertEqual([p.source_id for p,m in out.items],['synthetic-1','synthetic-0']);self.assertEqual(out.items[0][0].name,'합성 · 휴식 1')
        self.assertEqual(out.items[0][0].food_names,());self.assertFalse(out.nearest_verified);self.assertFalse(out.entrance_verified);self.assertFalse(out.direction_verified);self.assertIsNone(out.current_price)
        with self.assertRaises(TypeError):out.items[0][0].facilities['toilet']=False
    def test_pin_tampering_and_boolean_flag_as_number_rejected(self):
        pin=dataset_digest(self.data);self.data['items'][0]['name']='changed'
        with self.assertRaises(PlaceCatalogError):OfficialRestCatalog(self.data,expected_dataset_sha256=pin)
        self.data['items'][0]['facilities']['nursing']=1
        with self.assertRaises(PlaceCatalogError):self.catalog()
    def test_unsupported_smoking_or_national_route_not_invented(self):
        catalog=self.catalog();engine=self.engine()
        with self.assertRaises(PlaceCatalogError):catalog.road_order(engine,Coordinate(37.01,127),bounds=(126,37,128,38),required_facilities=('smoking',))
        self.assertFalse(engine.calls)
        out=catalog.road_order(engine,Coordinate(37.01,127),bounds=(126,37,128,38),route_number='no-such-source-label')
        self.assertEqual(out.eligible_count,0);self.assertEqual(engine.calls,[()])
    def test_snap_rejection_propagates_without_straight_fallback(self):
        catalog=self.catalog();engine=self.engine()
        def fail(*args):raise RoadProviderError('ROAD_PROVIDER_SNAP_REJECTED')
        engine.matrix=fail
        with self.assertRaisesRegex(RoadProviderError,'SNAP_REJECTED'):catalog.road_order(engine,Coordinate(37.01,127),bounds=(126,37,128,38))
if __name__=='__main__':unittest.main()
