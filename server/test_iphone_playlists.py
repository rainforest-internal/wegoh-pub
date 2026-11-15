import unittest
import json
import psycopg
import test_iphone_session as fixture

P='/v1/iphone/playlists'

class IPhonePlaylistsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.addClassCleanup(fixture.IphoneSessionTests.doClassCleanups)
  fixture.IphoneSessionTests.setUpClass()
 def setUp(self):
  self.phone=fixture.IphoneSessionTests();self.phone.setUp()
  self.token=self.phone.login()['accessToken']
 def call(self,path=P,body=None,method='GET',token=None):
  return self.phone.iphone(path,body,method,token=token or self.token)
 def payload(self):
  return dict(name='내 음악 링크',tracks=[dict(title='내 음악 링크',url='https://music.youtube.com/playlist?list=synthetic')])
 def test_phone_saved_link_is_the_same_account_playlist_and_notifies_vehicle(self):
  self.assertEqual(self.call()[2],dict(playlists=[]))
  web=self.phone.api.login()
  with self.phone.api.websocket(web)as events:
   self.assertEqual(json.loads(events.recv(timeout=2))['type'],'snapshot')
   code,headers,created=self.call(body=self.payload(),method='POST');self.assertEqual(code,201,created)
   event=json.loads(events.recv(timeout=2));self.assertEqual(event['resources'],['playlists'])
   self.assertNotIn('내 음악',json.dumps(event))
  self.assertIn('no-store',self.phone.header(headers,'cache-control'))
  self.assertEqual(self.phone.api.call('/v1/playlists',session=web)[2]['playlists'][0]['id'],created['id'])
  _,_,device=self.phone.api.pair(web)
  code,_,native=self.phone.api.native('/v1/playlists',token=device['accessToken'])
  self.assertEqual(code,200,native);self.assertEqual(native['playlists'][0]['id'],created['id'])
  path=P+'/'+created['id']
  updated=dict(name='수정한 링크',tracks=created['tracks'],revision=created['revision'])
  code,_,saved=self.call(path,updated,'PUT');self.assertEqual(code,200,saved)
  self.assertEqual(self.call(path,updated,'PUT')[0],409)
  self.assertEqual(self.call(path,dict(revision=created['revision']),'DELETE')[0],409)
  self.assertEqual(self.call(path,dict(revision=saved['revision']),'DELETE')[0],200)
  self.assertEqual(self.phone.api.native('/v1/playlists',token=device['accessToken'])[2]['playlists'],[])
 def test_owner_scopes_validation_and_revocation_are_preserved(self):
  created=self.call(body=self.payload(),method='POST')[2];path=P+'/'+created['id']
  bob=self.phone.login(who='bob')['accessToken']
  self.assertEqual(self.call(path,token=bob)[0],404)
  self.assertEqual(self.call(path,dict(revision=1),'DELETE',token=bob)[0],404)
  self.assertEqual(self.call(P+'?ignored=1')[0],400)
  self.assertEqual(self.call(body=dict(self.payload(),extra=True),method='POST')[0],400)
  with psycopg.connect(self.phone.api.dsn)as conn:
   conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read']")
  self.assertEqual(self.call()[0],200)
  self.assertEqual(self.call(body=self.payload(),method='POST')[0],403)
