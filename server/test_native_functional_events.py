"""Owned synthetic HTTP/WSS: functional invalidation without base authority mutation."""
import unittest,json,socket
import psycopg
from websockets.sync.client import connect
import test_team_auth as fixture
from native_functional_defaults import account_purposes

class FunctionalEventsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):
  self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
 def base(self):
  with psycopg.connect(self.h.dsn)as conn:return {name:conn.execute('SELECT row_to_json(t)::text FROM '+name+' t ORDER BY row_to_json(t)::text').fetchall()for name in ['native_v2_grants','native_v2_credentials','native_v2_installations','native_v2_approvals','native_v2_certificates','native_v2_operations']}
 def approve(self,session,c,purposes,who='alice'):
  path='/v1/devices/'+c['deviceId']+'/functional-permissions';code,_,old=self.h.call(path,session=session,who=who);self.assertEqual(code,200,old)
  body={k:v for k,v in old.items()if k not in('deviceId','expiresAt')};body['approvedPurposes']=self.h.web_purposes(old,purposes)
  code,_,current=self.h.call(path,body,'PUT',session=session,who=who);self.assertEqual(code,200,current);return current
 def test_own_functional_revision_withdrawal_expiry_invalidate_without_other_device_or_base_mutation(self):
  a,b=self.h.login(),self.h.login('bob');_,_,ca=self.h.pair(a);fingerprint=self.h._native_fingerprint;_,_,cb=self.h.pair(b,'bob');before=self.base()
  raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=5)
  with connect('ws://api.wegoh.invalid/v1/events',sock=raw,origin=None,open_timeout=3,close_timeout=1,additional_headers={'Authorization':'Bearer '+ca['accessToken'],'cf-cert-sha256':fingerprint,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'})as channel:
   first=json.loads(channel.recv(timeout=3));self.assertEqual(first['type'],'snapshot');self.assertEqual(first['resources'],['courses','devices','playlists']);seq=0
   def invalidated():
    nonlocal seq
    event=json.loads(channel.recv(timeout=3));seq+=1;self.assertEqual(event,dict(type='invalidate',epoch=first['epoch'],seq=seq,resources=['devices']))
   self.approve(b,cb,['history:write'],'bob')
   with self.assertRaises(TimeoutError):channel.recv(timeout=1.2)
   current=self.approve(a,ca,['history:write']);self.assertEqual(current['revision'],2);invalidated()
   path='/v1/devices/'+ca['deviceId']+'/functional-permissions/history:write'
   code,_,cut=self.h.call(path,method='DELETE',session=a);self.assertEqual(code,200,cut);self.assertEqual(cut['approvedPurposes'],sorted(account_purposes(['device-commands:receive'])));invalidated()
   self.approve(a,ca,['history:write']);invalidated()
   with psycopg.connect(self.h.dsn)as conn:conn.execute('UPDATE native_functional_authorizations SET expires_at=1 WHERE grant_id=%s',(ca['grantId'],))
   invalidated()
   code,_,empty=self.h.native('/v1/device/functional-permissions',token=ca['accessToken'],certificate=fingerprint);self.assertEqual(code,200,empty);self.assertEqual(empty['approvedPurposes'],[])
   self.assertEqual(self.h.native('/v1/account',token=ca['accessToken'],certificate=fingerprint)[0],200)
  self.assertEqual(self.base(),before)
