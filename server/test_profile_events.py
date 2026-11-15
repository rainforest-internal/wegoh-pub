"""A profile cache is invalidated by another client changing the account name."""
import json
import unittest
import test_climate_commands as fixtures

class ProfileEventTests(fixtures.ClimateHttpTests):
 def test_name_change_invalidates_native_feed(self):
  self.prepare(False)
  profile=self.a
  with self.tls.websocket(self.token['accessToken'])as ws:
   self.assertEqual(json.loads(ws.recv(timeout=3))['type'],'snapshot')
   status,_,result=self.web('/v1/profile',dict(displayName='Other account name',expectedDisplayName=self.b['user']['displayName']),'PUT',who='bob',session=self.b)
   self.assertEqual(status,200,result)
   with self.assertRaises(TimeoutError):ws.recv(timeout=1)
   status,_,result=self.web('/v1/profile',dict(displayName='Cache event name',expectedDisplayName=profile['user']['displayName']),'PUT',session=self.a)
   self.assertEqual(status,200,result)
   event=json.loads(ws.recv(timeout=4))
   self.assertEqual(event['type'],'invalidate');self.assertIn('devices',event['resources'])
   self.assertNotIn('Cache event name',json.dumps(event))
  status,account=self.native('/v1/account')
  self.assertEqual(status,200);self.assertEqual(account['user']['displayName'],'Cache event name')

def load_tests(loader,tests,pattern):
 return unittest.TestSuite([ProfileEventTests('test_name_change_invalidates_native_feed')])
