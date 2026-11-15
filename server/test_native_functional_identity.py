"""Business-transaction gates on owned PrivatePG; no live/CF/physical vehicle."""
import json,unittest,time
from concurrent.futures import ThreadPoolExecutor
import psycopg
from starlette.requests import Request
import test_team_auth as fixture
from native_functional_policy import WIRE,FunctionalError
from native_functional_defaults import INITIAL_PURPOSES, account_purposes
from native_functional_identity import revalidate_native,functional_body

class FunctionalIdentityTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):
  self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
  self.session=self.h.login();_,_,self.credential=self.h.pair(self.session)
  self.certificate=self.h._native_fingerprint
  self.path='/v1/devices/'+self.credential['deviceId']+'/functional-permissions'
 def approve(self,purposes):
  current=self.h.call(self.path,session=self.session)[2]
  body={key:value for key,value in current.items()if key not in ('deviceId','expiresAt')};body['approvedPurposes']=self.h.web_purposes(current,purposes)
  code,_,result=self.h.call(self.path,body,'PUT',session=self.session);self.assertEqual(code,200,result);return result
 def request(self,method='GET',path=None):
  headers={'host':'api.wegoh.invalid','authorization':'Bearer '+self.credential['accessToken'],'cf-cert-sha256':self.certificate,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'}
  scope=dict(type='http',method=method,path=path or '/v1/native/rooms/'+'a'*32+'/device-reports',raw_path=b'/',root_path='',query_string=b'',scheme='http',server=('api.wegoh.invalid',80),client=('127.0.0.1',1234),headers=[(k.encode(),v.encode())for k,v in headers.items()])
  request=Request(scope);request.state.device_identity=self.h.module.TEAM_NATIVE_AUTHORIZATION.authenticate(request,enforce_route=False);return request
 def test_receive_default_and_exact_other_purpose_denial(self):
  request=self.request()
  with psycopg.connect(self.h.dsn)as conn:
   with self.assertRaises(FunctionalError)as error:revalidate_native(self.h.module.TEAM_AUTH,request,conn)
   self.assertEqual(error.exception.status,403)
  with psycopg.connect(self.h.dsn)as conn:
   _,empty=revalidate_native(self.h.module.TEAM_AUTH,self.request(path='/v1/device/vehicle-domain'),conn)
   self.assertEqual(empty['approvedPurposes'],account_purposes(INITIAL_PURPOSES));self.assertEqual(empty['revision'],1)
   self.assertEqual(conn.execute('SELECT count(*)FROM native_functional_authorizations').fetchone()[0],1)
  self.approve(['vehicle-reports:read'])
  with psycopg.connect(self.h.dsn)as conn:
   actor,snapshot=revalidate_native(self.h.module.TEAM_AUTH,request,conn)
   self.assertEqual(actor['deviceId'],self.credential['deviceId']);self.assertEqual(snapshot['revision'],2);self.assertEqual(snapshot['approvedPurposes'],account_purposes(['device-commands:receive','vehicle-reports:read']))
  for path in ['/v1/social/rooms/'+'a'*32+'/secret','/v2/social/rooms/'+'a'*32]:
   with psycopg.connect(self.h.dsn)as conn:
    with self.assertRaises(FunctionalError)as error:revalidate_native(self.h.module.TEAM_AUTH,self.request(path=path),conn)
    self.assertEqual(error.exception.status,404)
 def test_write_revision_and_withdrawal_serializes_actual_transaction(self):
  self.approve(['vehicle-location:report']);request=self.request('POST','/v1/native/rooms/'+'a'*32+'/reports/location')
  for invalid in [None,True,0,1,3]:
   with psycopg.connect(self.h.dsn)as conn:
    with self.assertRaises(FunctionalError):revalidate_native(self.h.module.TEAM_AUTH,request,conn,functional_revision=invalid)
  with ThreadPoolExecutor(max_workers=1)as pool:
   with psycopg.connect(self.h.dsn)as conn:
    _,snapshot=revalidate_native(self.h.module.TEAM_AUTH,request,conn,functional_revision=2)
    future=pool.submit(lambda:self.h.call(self.path+'/vehicle-location:report',method='DELETE',session=self.session))
    time.sleep(.1);self.assertFalse(future.done(),'Withdrawal must wait for the actual authorized transaction to commit')
   self.assertEqual(future.result(timeout=4)[0],200)
  with psycopg.connect(self.h.dsn)as conn:
   with self.assertRaises(FunctionalError)as error:revalidate_native(self.h.module.TEAM_AUTH,request,conn,functional_revision=2)
   self.assertEqual(error.exception.status,409)
  with psycopg.connect(self.h.dsn)as conn:
   with self.assertRaises(FunctionalError)as error:revalidate_native(self.h.module.TEAM_AUTH,request,conn,functional_revision=3)
   self.assertEqual(error.exception.status,403)
 def test_wrong_key_forged_actor_and_strict_body(self):
  self.approve(['vehicle-reports:read']);request=self.request()
  scope=dict(request.scope);scope['headers']=[(k,b'c'*64 if k==b'cf-cert-sha256'else v)for k,v in request.scope['headers']];request=Request(scope)
  with psycopg.connect(self.h.dsn)as conn:
   with self.assertRaises(FunctionalError)as error:revalidate_native(self.h.module.TEAM_AUTH,request,conn)
   self.assertEqual(error.exception.status,401)
  request=self.request();request.state.device_identity=dict(request.state.device_identity)
  with psycopg.connect(self.h.dsn)as conn:
   with self.assertRaises(FunctionalError):revalidate_native(self.h.module.TEAM_AUTH,request,conn)
  self.assertEqual(functional_body(dict(functionalRevision=1,name='synthetic')),({'name':'synthetic'},1))
  for bad in [{},{'functionalRevision':True},{'functionalRevision':0},{'functionalRevision':2147483648}]:
   with self.assertRaises(FunctionalError):functional_body(bad)
 def test_typed_target_reference_requires_current_owner_slot_and_function(self):
  from native_functional_identity import resolve_current_device,CurrentDeviceReference
  request=self.request();owner=request.state.device_identity['id'];device=self.credential['deviceId']
  with psycopg.connect(self.h.dsn)as conn:
   reference=resolve_current_device(self.h.module.TEAM_AUTH,conn,owner,device)
   self.assertIsInstance(reference,CurrentDeviceReference);self.assertEqual(reference.approved_purposes,account_purposes(INITIAL_PURPOSES))
   self.assertEqual(int(reference.expires_at.timestamp()),self.credential['grantExpiresAt'])
   with self.assertRaises(FunctionalError):resolve_current_device(self.h.module.TEAM_AUTH,conn,owner,device,required=frozenset({'vehicle-reports:read'}))
  self.approve(['vehicle-reports:read'])
  with psycopg.connect(self.h.dsn)as conn:
   reference=resolve_current_device(self.h.module.TEAM_AUTH,conn,owner,device,required=frozenset({'vehicle-reports:read'}))
   self.assertEqual(reference.functional_revision,2)
   self.assertEqual(reference.grant_id,self.credential['grantId'])
   for bad_owner,bad_device in [('team-'+'e'*40,device),(owner,'f'*32)]:
    with self.assertRaises(FunctionalError)as error:resolve_current_device(self.h.module.TEAM_AUTH,conn,bad_owner,bad_device)
    self.assertEqual(error.exception.status,404)
   conn.execute('UPDATE native_v2_installations SET active_grant_id=NULL')
   with self.assertRaises(FunctionalError)as error:resolve_current_device(self.h.module.TEAM_AUTH,conn,owner,device)
   self.assertEqual(error.exception.status,404);conn.rollback()
if __name__=='__main__':unittest.main()


class BusinessJsonTests(unittest.TestCase):
 def test_domain_bound_above_authorization_limit_is_preserved_without_duplicate_or_nonfinite_fields(self):
  from native_functional_identity import business_json
  from fastapi import HTTPException
  request=Request(dict(type='http',method='POST',path='/v1/social/history',headers=[]))
  raw=json.dumps(dict(notes='a'*70000)).encode()
  self.assertEqual(len(business_json(request,raw,maximum=262144)['notes']),70000)
  for value,limit in [(raw,65536),(b'{"a":1,"a":2}',262144),(b'{"a":{"b":1,"b":2}}',262144),(b'{"n":NaN}',262144),(b'{"n":1e999}',262144),(b'[]',262144)]:
   with self.subTest(rawLength=len(value)),self.assertRaises(HTTPException)as rejected:business_json(request,value,maximum=limit)
   self.assertEqual(rejected.exception.status_code,400)

 def test_query_contract_uses_real_http_and_websocket_objects_without_http_method_assumptions(self):
  import base64
  from starlette.websockets import WebSocket
  from native_functional_query import native_query_allowed
  cursor=base64.urlsafe_b64encode(json.dumps(dict(updatedAt='2026-01-01T00:00:00Z',id='a'*32)).encode()).decode().rstrip('=')
  def scope(kind,path,query):return dict(type=kind,method='GET',path=path,raw_path=path.encode(),root_path='',query_string=query.encode(),scheme='wss'if kind=='websocket'else'https',server=('api.wegoh.invalid',443),client=('127.0.0.1',1),headers=[])
  self.assertTrue(native_query_allowed(Request(scope('http','/v1/social/history','cursor='+cursor))))
  self.assertTrue(native_query_allowed(Request(scope('http','/v1/social/cautions','cursor='+cursor))))
  self.assertFalse(native_query_allowed(Request(scope('http','/v1/account','cursor='+cursor))))
  self.assertTrue(native_query_allowed(Request(scope('http','/v1/device/vehicle-domain','roomId='+'a'*32))))
  for path,query in [('/v1/device/vehicle-domain','roomId='+'a'*32+'&roomId='+'a'*32),('/v1/device/vehicle-domain','roomId='+'a'*33),('/v1/device/vehicle-domain','roomId='+'A'*32),('/v1/device/vehicle-domain','roomId='),('/v1/device/vehicle-domain','room='+'a'*32),('/v1/device/vehicle-domain','roomId='+'a'*32+'&access_token=synthetic-forbidden'),('/v1/social/cautions','eventId='+'a'*32),('/v1/moderation/content','cursor='+cursor)]:
   with self.subTest(path=path,query=query):self.assertFalse(native_query_allowed(Request(scope('http',path,query))))
  post=scope('http','/v1/device/vehicle-domain','roomId='+'a'*32);post['method']='POST';self.assertFalse(native_query_allowed(Request(post)))
  async def receive():return dict(type='websocket.connect')
  async def send(message):pass
  for query in ['', 'access_token=synthetic-not-authority','cursor='+cursor,'roomId='+'a'*32]:
   with self.subTest(queryPresent=bool(query)):
    value=scope('websocket','/v1/events',query);value.pop('method')
    self.assertEqual(native_query_allowed(WebSocket(value,receive,send)),not bool(query))
