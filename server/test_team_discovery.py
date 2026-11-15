"""Owned synthetic HTTP/PG contracts for public fixed-data proximity; no real GPS."""
import copy,hashlib,json,math,sys,unittest
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
import psycopg
import test_team_auth as fixture
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import normalize_rest_stops as normalizer
import team_discovery as discovery
from rest_stop_data import DATASET

class DiscoveryTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.fixture=fixture.TeamTests;cls.fixture.setUpClass();__import__('api_application')
 @classmethod
 def tearDownClass(cls):cls.fixture.tearDownClass()
 def setUp(self):
  self.api=self.fixture(methodName='test_01_jwt_verification_and_exact_hosts');self.api.setUp();self.session=self.api.login();self.path='/v1/discovery/rest-stops/query'
 def selected(self,item=None,**options):
  item=item or DATASET['items'][0]
  return dict(anchor=dict(kind='selected-place',place=dict(id='map-synthetic',provider='map',name='Synthetic selected public point',address='',latitude=item['latitude'],longitude=item['longitude'])),radiusMeters=1,limit=20,**options)
 def call(self,value,**options):return self.api.call(self.path,value,'POST',session=self.session,**options)
 def ids(self,value):
  status,_,body=self.call(value);self.assertEqual(status,200,body);return {x['id']for x in body['items']}
 def test_01_pinned_public_source_exact_normalization_and_unknowns(self):
  raw=(ROOT/'docs/reference/discovery/public-rest-15025446.csv').read_bytes();meta=json.loads((ROOT/'docs/discovery-source.json').read_text());value=normalizer.normalize(raw,meta)
  self.assertEqual(hashlib.sha256(raw).hexdigest(),normalizer.EXPECTED);self.assertEqual(len(value['items']),215);self.assertEqual(len({x['id']for x in value['items']}),215)
  self.assertEqual(Counter(x['roadKind']for x in value['items']),{'고속국도':215});self.assertEqual(sum(x['direction']is None for x in value['items']),7);self.assertEqual(sum(bool(x['foodNames'])for x in value['items']),0)
  self.assertEqual(Counter(x['facilities']['nursing']for x in value['items']),{True:212,False:3});self.assertEqual(Counter(x['facilities']['lpg']for x in value['items']),{True:167,False:48})
  self.assertEqual(normalizer.render(value).encode(),(ROOT/'server/rest_stop_data.py').read_bytes())
  with self.assertRaises(ValueError):normalizer.normalize(raw+b'\n',meta)
 def test_02_real_auth_origin_csrf_and_native_closed(self):
  value=self.selected()
  self.assertEqual(self.api.call(self.path,value,'POST')[0],401)
  self.assertEqual(self.call(value,csrf=False)[0],403);self.assertEqual(self.call(value,origin='https://wrong.invalid')[0],403)
  self.assertEqual(self.api.native(self.path,value,'POST')[0],404)
  bob=self.api.login('bob');self.assertEqual(self.api.call(self.path,value,'POST',who='bob',session=bob)[0],200)
 def test_03_selected_place_returns_real_compatible_public_candidate(self):
  item=DATASET['items'][0];status,headers,body=self.call(self.selected(item));self.assertEqual(status,200);self.assertIn('no-store',headers['cache-control'])
  target=next(x for x in body['items']if x['id']==item['id']);self.assertEqual(target['straightLineDistanceMeters'],0);self.assertEqual(set(target['place']),{'id','provider','name','address','latitude','longitude'});self.assertEqual(target['place']['address'],'')
  self.assertEqual(body['source']['csvSha256'],normalizer.EXPECTED);self.assertEqual(body['source']['dataAsOf'],['2026-09-17']);self.assertEqual(body['basis'],'great-circle-straight-line');self.assertNotIn('latitude',body['anchor'])
  self.assertIsNone(target['routeDistanceMeters']);self.assertIsNone(target['travelSeconds']);self.assertIsNone(target['currentOpen']);self.assertIsNone(target['price']);self.assertIsNone(target['coordinateVerifiedAt']);self.assertFalse(target['roadAccessVerified']);self.assertEqual(target['foodNames'],[])
 def test_04_five_and_filters_do_not_fabricate_facility_presence(self):
  for key in('nursing','gasStation','lpg'):
   item=next(x for x in DATASET['items']if x['facilities'][key]is False)
   self.assertIn(item['id'],self.ids(self.selected(item)));self.assertNotIn(item['id'],self.ids(self.selected(item,requiredFacilities=[key])))
  item=next(x for x in DATASET['items']if all(x['facilities'][key]is True for key in discovery.FACILITIES));self.assertIn(item['id'],self.ids(self.selected(item,requiredFacilities=list(discovery.FACILITIES))))
  self.assertEqual(self.call(self.selected(item,requiredFacilities=['restaurant']))[0],400)
 def test_05_reported_direction_unknown_and_both_policy(self):
  unknown=next(x for x in DATASET['items']if x['direction']is None)
  self.assertIn(unknown['id'],self.ids(self.selected(unknown)));self.assertNotIn(unknown['id'],self.ids(self.selected(unknown,roadFilter={'direction':'up'})))
  both=next(x for x in DATASET['items']if x['direction']=='both')
  for label in('up','down','both'):self.assertIn(both['id'],self.ids(self.selected(both,roadFilter={'direction':label})))
  self.assertEqual(self.ids(self.selected(both,roadFilter={'routeNumber':'not-a-source-route'})),set())
 def test_06_gps_is_explicit_fresh_report_not_implied_permission(self):
  now=datetime.now(timezone.utc);value=dict(anchor=dict(kind='browser-location',consent=True,position=dict(latitude=0,longitude=0,accuracyMeters=20,capturedAt=now.isoformat())))
  status,_,body=self.call(value);self.assertEqual(status,200);self.assertEqual(body['items'],[]);self.assertEqual(body['anchor']['kind'],'browser-reported');self.assertNotIn('latitude',body['anchor'])
  changed=copy.deepcopy(value);changed['anchor']['position']['accuracyMeters']=10**400;self.assertEqual(self.call(changed)[0],400)
  for update in({'consent':False},{'consent':None}):
   changed=copy.deepcopy(value);changed['anchor'].update(update);self.assertEqual(self.call(changed)[0],400)
  for moment in((now-timedelta(minutes=6)).isoformat(),(now+timedelta(minutes=2)).isoformat(),now.replace(tzinfo=None).isoformat()):
   changed=copy.deepcopy(value);changed['anchor']['position']['capturedAt']=moment;self.assertEqual(self.call(changed)[0],400)
 def test_07_exact_bounds_nonfinite_and_body_cap(self):
  base=self.selected()
  for update in({'radiusMeters':True},{'radiusMeters':0},{'radiusMeters':200001},{'limit':21},{'limit':'10'},{'requiredFacilities':['toilet','toilet']},{'roadFilter':{'direction':[]}},{'profileId':'inferred-profile'},{'url':'https://example.invalid/'}):
   value=copy.deepcopy(base);value.update(update);self.assertEqual(self.call(value)[0],400,update)
  value=copy.deepcopy(base);value['anchor']['place']['latitude']=math.nan;self.assertEqual(self.call(value)[0],400)
  for field in('latitude','longitude'):
   value=copy.deepcopy(base);value['anchor']['place'][field]=10**400;self.assertEqual(self.call(value)[0],400)
  value=copy.deepcopy(base);value['extra']='x'*5000;self.assertEqual(self.call(value)[0],413)
 def test_08_known_distance_stable_tie_no_location_records_and_typed_docs(self):
  a=copy.deepcopy(DATASET['items'][0]);a.update(id='a',latitude=0,longitude=1);b=copy.deepcopy(a);b.update(id='b',longitude=-1)
  request=self.selected();request['anchor']['place'].update(latitude=0,longitude=0);request['radiusMeters']=120000
  with patch.object(discovery,'DATASET',dict(source=DATASET['source'],items=[b,a])):
   result=discovery.query(request);self.assertEqual([x['id']for x in result['items']],['a','b']);self.assertEqual([x['straightLineDistanceMeters']for x in result['items']],[111195,111195])
  tables=('visited_places','team_histories','team_history_trace_batches','team_room_signals')
  with psycopg.connect(self.api.module.DSN)as conn:before={t:conn.execute('SELECT count(*)FROM '+t).fetchone()[0]for t in tables}
  self.call(self.selected())
  with psycopg.connect(self.api.module.DSN)as conn:after={t:conn.execute('SELECT count(*)FROM '+t).fetchone()[0]for t in tables}
  self.assertEqual(before,after)
  status,_,schema=self.api.call('/openapi.json');self.assertEqual(status,200);op=schema['paths'][self.path]['post'];self.assertIn('X-WegoH-CSRF',schema['components']['securitySchemes']['CurrentSessionCSRF']['name']);self.assertEqual(op['x-wegoh-surface'],'browser');self.assertNotIn('DeviceBearer',op['security'][0])
  body=op['requestBody']['content']['application/json']['schema'];self.assertEqual(len(body['oneOf']),2)
  for branch in body['oneOf']:self.assertEqual(len(branch['properties']['anchor']['oneOf']),2)
  self.assertNotIn('roadSearch',body['oneOf'][0]['properties']);self.assertIn('roadSearch',body['oneOf'][1]['required'])

if __name__=='__main__':unittest.main(verbosity=2)
