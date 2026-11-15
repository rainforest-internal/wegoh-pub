"""Owner-only profile changes with isolated PostgreSQL and synthetic credentials."""
import unittest
import psycopg
from test_native_authorization_http import NativeAuthorizationHttpTests
from native_access_codec import disclosure_snapshot
from team_api_docs import build_schema

class AccountProfileTests(NativeAuthorizationHttpTests):
 def test_profile_owner_scopes_cas_and_encrypted_persistence(self):
  receipt=self.connected();token=receipt['accessToken']
  body=dict(displayName='바닷길',expectedDisplayName='alice')
  self.assertEqual(self.native('/v1/account',body,'PUT',token)[0],200)
  self.assertEqual(self.api.call('/v1/profile',body,'PUT',session=self.session,csrf=False)[0],403)
  self.assertEqual(self.api.call('/v1/profile',dict(body,accountId='other'),'PUT',session=self.session)[0],400)
  self.assertEqual(self.api.call('/v1/profile',body,'PUT',session=self.session)[0],409)
  self.assertEqual(self.native('/v1/account',token=token)[2]['user']['displayName'],'바닷길')
  self.assertEqual(self.api.call('/v1/auth/session',session=self.session)[2]['user']['displayName'],'바닷길')
  self.assertEqual(self.api.call('/v1/profile',body,'PUT',session=self.session)[0],409)
  fresh=self.api.login();self.assertEqual(fresh['user']['displayName'],'바닷길')
  bob=self.api.login('bob');self.assertEqual(bob['user']['displayName'],'bob')
  with psycopg.connect(self.auth.dsn)as conn:
   protected=conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s',(receipt['accountId'],)).fetchone()[0]
   self.assertNotIn('바닷길'.encode(),bytes(protected))
  self.assertEqual(self.native('/v1/profile',body,'PUT',token)[0],404)
  self.assertEqual(self.api.call('/v1/account',body,'PUT',session=fresh)[0],404)

 def test_profile_explicit_native_write_and_validation(self):
  self.scopes=sorted(self.scopes+['account:write']);receipt=self.connected();token=receipt['accessToken']
  for value in ['', ' ', ' 앞', '뒤 ', 'a'*31, '이름\n', 'a\u202eb', '\ue000']:
   self.assertEqual(self.native('/v1/account',dict(displayName=value,expectedDisplayName='alice'),'PUT',token)[0],400)
  body=dict(displayName='숲길 친구',expectedDisplayName='alice')
  status,headers,value=self.native('/v1/account',body,'PUT',token)
  self.assertEqual(status,200,value);self.assertEqual(value['user']['displayName'],'숲길 친구')
  self.assertEqual(headers.get('cache-control'),'private, no-store')
  self.assertEqual(self.native('/v1/account',token=token)[2]['user']['displayName'],'숲길 친구')
  self.assertEqual(self.native('/v1/device',method='DELETE',token=token)[0],200)
  self.assertEqual(self.native('/v1/account',dict(body,displayName='거절',expectedDisplayName='숲길 친구'),'PUT',token)[0],401)

 def test_profile_schema_and_unchanged_legacy_disclosures(self):
  from native_access_policy import authorize_route,KNOWN_SCOPES,MANDATORY_SCOPES,RouteDenied,ScopeDenied
  for version in [True,False,0,2,'1',None]:
   with self.assertRaises(ScopeDenied):authorize_route(version,'GET','/v1/account',KNOWN_SCOPES)
  for verb,path in [('POST','/v1/account'),('PUT','/v1/account/'),('PUT','/v1/account/other'),('PUT','/v1/profile')]:
   with self.assertRaises(RouteDenied):authorize_route(1,verb,path,KNOWN_SCOPES)
  self.assertEqual(authorize_route(1,'PUT','/v1/account',MANDATORY_SCOPES),'account:read')
  self.assertEqual(authorize_route(1,'PUT','/v1/account',KNOWN_SCOPES),'account:read')
  schema=build_schema(self.api.module.app,self.auth)
  for path in ['/v1/account','/v1/profile']:
   operation=schema['paths'][path]['put'];self.assertEqual(set(operation['requestBody']['content']['application/json']['schema']['required']),{'displayName','expectedDisplayName'})
  self.assertEqual(schema['paths']['/v1/account']['put']['x-wegoh-required-scopes'],['account:read','device:self:manage'])
  expected={
   ('account:read','device:self:manage'):'848c508a5bb93b42170b57f353f00c3fc5406decd564a01cce48943286187e57',
   ('account:read','courses:read','device:self:manage','playlists:read'):'52798d8bf090a9a33f6a4c5ecc9c677441b82c62a60542c7de226c3551a3a11f'}
  for scopes,digest in expected.items():self.assertEqual(disclosure_snapshot(list(scopes))['disclosureSha256'],digest)
