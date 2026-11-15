"""Mounted OAS contract for Native room music and phone-only explicit consent."""
import copy,unittest
from native_room_music_authority import CONTRACT
from api_doc_native_room_music import APIS,EXAMPLE,MODELS
from team_api_docs import build_schema,BODY
import test_team_auth as fixture
class RoomMusicDocumentationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def test_mounted_four_auth_host_closed_dto_and_meaningful_fields(self):
  auth=fixture.TeamTests.module.TEAM_AUTH;schema=build_schema(fixture.TeamTests.module.app,auth)
  for key,(method,path,_)in APIS.items():
   operation=schema['paths'][path][method];native=key=='nativeGet';security={'NativeMTLS':[],'DeviceBearer':[]}if native else{'CloudflareAccess':[],'TeamSession':[]}
   if method!='get':security['CurrentSessionCSRF']=[]
   self.assertEqual(operation['security'],[security]);self.assertEqual(operation['servers'][0]['url'],auth.native_origin if native else auth.public_origin)
   self.assertEqual(operation['x-wegoh-executable'],not native);self.assertIn('같은 transaction',schema['paths'][CONTRACT['ownerPath']]['put']['description'])
   value=operation['responses']['200']['content']['application/json']['example'];self.assertEqual(set(value),set(CONTRACT['snapshotFields']));self.assertEqual(value['permissions'],dict(receiveMusic=False,shareMusic=False))
  models=schema['components']['schemas']
  for name,keys in [('NativeRoomMusicSnapshot',CONTRACT['snapshotFields']),('NativeRoomMusicConsent',CONTRACT['ownerPutFields'])]:
   model=models[name];self.assertEqual(set(model['required']),set(keys));self.assertEqual(set(model['properties']),set(keys));self.assertFalse(model['additionalProperties'])
   for key,field in model['properties'].items():
    if key!='permissions':self.assertTrue(field.get('description'),key)
   self.assertEqual(model['properties']['permissions']['required'],['receiveMusic','shareMusic']);self.assertFalse(model['properties']['permissions']['additionalProperties'])
  put=schema['paths'][CONTRACT['ownerPath']]['put'];self.assertEqual(set(put['requestBody']['content']['application/json']['example']),set(CONTRACT['ownerPutFields']));self.assertIn('5초',put['responses']['408']['description']);self.assertIn('EXHAUSTED',put['responses']['409']['description'])
  self.assertNotIn('requestBody',schema['paths'][CONTRACT['ownerPath']]['delete'])
 def test_music_business_native_preconditions_and_no_false_legacy_success(self):
  schema=build_schema(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH);base='/v1/social/rooms/{room}/music'
  for method in ('put','delete'):
   op=schema['paths'][base][method];alternatives=op['requestBody']['content']['application/json']['schema']['oneOf'];self.assertEqual(len(alternatives),2)
   self.assertNotIn('functionalRevision',alternatives[0]['properties']);self.assertEqual(set(alternatives[1]['required'])-set(alternatives[0]['required']),{'functionalRevision','roomMusicRevision'});self.assertFalse(alternatives[1]['additionalProperties'])
   self.assertIn({'NativeMTLS':[],'DeviceBearer':[]},op['security'])
   old=schema['paths']['/v1/devices/{device}/music-permission'][method];self.assertNotIn('200',old['responses']);self.assertIn('409',old['responses']);self.assertFalse(old['x-wegoh-executable'])
  response=schema['paths'][base]['get']['responses']['200']['content']['application/json'];browser,native=response['schema']['oneOf']
  self.assertEqual(set(browser['properties']),{'revision','canEdit','selection','playlist'});self.assertEqual(browser['not'],{'required':['nativeReadOnly']})
  self.assertEqual(set(native['properties']),{'revision','canEdit','selection','nativeReadOnly'});self.assertIn('nativeReadOnly',native['required']);self.assertEqual(native['properties']['nativeReadOnly']['type'],'boolean')
  self.assertEqual(set(response['examples']['browser']['value']),set(browser['properties']));self.assertEqual(response['examples']['nativeReadOnly']['value']['nativeReadOnly'],True);self.assertEqual(response['examples']['nativeDJ']['value']['nativeReadOnly'],False)
  # Actual synthetic HTTP responses, not only a schema constant comparison.
  from test_native_functional_music import NativeMusicTests
  factory=NativeMusicTests('test_native_dj_current_purpose_room_consent_rights_review_and_withdrawal');factory.setUp();owner=factory.h.login();credential=factory.connect(owner)
  factory.approve(owner,credential,['rooms:read','room-music:read','room-music:control'])
  code,_,room=factory.h.call('/v1/social/rooms',dict(name='Synthetic OAS music contract',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner);self.assertEqual(code,201,room);path='/v1/social/rooms/'+room['id']
  flags={k:k=='music'for k in('status','location','visits','music','voice','control')};self.assertEqual(factory.h.call(path+'/consents',dict(consents=flags),'PATCH',session=owner)[0],200)
  self.assertEqual(factory.h.call(path+'/role',dict(accountId=owner['user']['id'],role='dj'),'PATCH',session=owner)[0],200);factory.room_approve(owner,credential,room['id'],share=True)
  code,_,actual=factory.native(credential,path+'/music');self.assertEqual(code,200,actual);self.assertEqual(set(actual),set(native['properties']));self.assertTrue(actual['canEdit']);self.assertFalse(actual['nativeReadOnly'])
  factory.approve(owner,credential,['rooms:read','room-music:read']);code,_,actual=factory.native(credential,path+'/music');self.assertEqual(code,200,actual);self.assertEqual(set(actual),set(native['properties']));self.assertFalse(actual['canEdit']);self.assertTrue(actual['nativeReadOnly'])
  code,_,actual=factory.h.call(path+'/music',session=owner);self.assertEqual(code,200,actual);self.assertEqual(set(actual),set(browser['properties']));self.assertTrue(actual['canEdit'])
  # Current CreateRoom explicitly requires both nullable course fields; no repair needed.
  create=schema['paths']['/v1/social/rooms']['post']['requestBody']['content']['application/json'];self.assertTrue({'courseId','courseVersion'}<=set(create['schema']['required']));self.assertIsNone(create['example']['courseId']);self.assertIsNone(create['example']['courseVersion'])
if __name__=='__main__':unittest.main()
