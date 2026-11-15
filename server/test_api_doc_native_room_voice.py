"""Exact mounted phone Voice and WS documentation; not full182/SDK/runtime approval."""
import unittest
from api_doc_native_room_voice import APIS,CONTRACT,EXAMPLE
from team_api_docs import build_schema
from team_voice import RELAY_QUEUE_LIMIT
import test_team_auth as fixture

class VoiceDocumentationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass();__import__('api_application')
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def test_four_handlers_closed_models_auth_and_independent_direction_contract(self):
  auth=fixture.TeamTests.module.TEAM_AUTH;schema=build_schema(fixture.TeamTests.module.app,auth);models=schema['components']['schemas']
  for key,(method,path,title)in APIS.items():
   operation=schema['paths'][path][method];native=key=='nativeGet'
   expected={'NativeMTLS':[],'DeviceBearer':[]}if native else {'CloudflareAccess':[],'TeamSession':[]}
   if not native and method!='get':expected['CurrentSessionCSRF']=[]
   self.assertEqual(operation['security'],[expected]);self.assertEqual(operation['servers'][0]['url'],auth.native_origin if native else auth.public_origin)
   self.assertIn('두 방향은 독립',operation['description']);self.assertIn('반대 목적을 요구하지',operation['description'])
   self.assertEqual(set(operation['responses']['200']['content']['application/json']['example']),set(CONTRACT['snapshotFields']))
  self.assertEqual(set(models['NativeRoomVoiceSnapshot']['required']),set(CONTRACT['snapshotFields']))
  self.assertFalse(models['NativeRoomVoiceSnapshot']['additionalProperties']);self.assertFalse(models['NativeRoomVoiceConsent']['additionalProperties'])
  self.assertEqual(set(models['NativeRoomVoiceConsent']['required']),set(CONTRACT['ownerPutFields']))
  flags=models['NativeRoomVoiceSnapshot']['properties']['permissions'];self.assertEqual(set(flags['required']),{'receiveVoice','transmitVoice'})
  put=schema['paths'][CONTRACT['ownerPath']]['put'];self.assertIn('408',put['responses']);self.assertIn('409',put['responses']);self.assertEqual(set(put['requestBody']['content']['application/json']['example']),set(CONTRACT['ownerPutFields']))
  self.assertIn('ROOM_VOICE_REVISION_EXHAUSTED',put['responses']['409']['description'])
 def test_voice_only_room_selector_closed_page_notice_and_nonsecret_cursor(self):
  schema=build_schema(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH)
  op=schema['paths']['/v1/native/voice-rooms']['get'];models=schema['components']['schemas']
  self.assertEqual(op['security'],[{'NativeMTLS':[],'DeviceBearer':[]}]);self.assertFalse(op['x-wegoh-executable'])
  self.assertIn('rooms:read',op['description']);self.assertIn('자동 승계하지',op['description'])
  self.assertEqual(set(models['NativeVoiceRoomPage']['required']),{'authorizationVersion','deviceId','grantId','functionalRevision','items','nextCursor'})
  self.assertEqual(set(models['NativeVoiceRoomItem']['required']),{'roomId','name','availableDirections','revision','memberJoinedAt','expiresAt'})
  for name in ('NativeVoiceRoomPage','NativeVoiceRoomItem'):self.assertFalse(models[name]['additionalProperties'])
  self.assertEqual(models['NativeVoiceRoomPage']['properties']['items']['maxItems'],20)
  self.assertEqual(op['parameters'][0]['name'],'cursor');self.assertEqual(op['parameters'][0]['schema']['pattern'],'^[a-f0-9]{32}$')
  self.assertEqual(CONTRACT['disclosureVersion'],2)
  self.assertTrue(all('음성을 나눌 여행방 이름'in p['dataCategories']for p in CONTRACT['disclosure']['permissions']))
 def test_ws_native_admission_header_limits_and_browser_boundary_remain_explicit(self):
  schema=build_schema(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH);voice=schema['x-wegoh-voice'];native=voice['native']
  self.assertTrue(voice['nativeAccess']);self.assertEqual(native['security'],[{'NativeMTLS':[],'DeviceBearer':[]}]);self.assertFalse(native['queryAllowed']);self.assertFalse(native['cookieOrOriginAllowed'])
  self.assertEqual(set(native['preconditions']),{'X-WegoH-Functional-Revision','X-WegoH-Room-Voice-Revision'})
  self.assertIn(' OR ',native['admission']);self.assertIn('no rooms:read',native['admission']);self.assertIn('No microphone',native['receive'])
  self.assertEqual(voice['leaseSeconds'],15);self.assertEqual(voice['pcm']['frameBytes'],644);self.assertEqual(voice['limits']['recipientQueueFrames'],RELAY_QUEUE_LIMIT)
  self.assertIn('public browser host/Origin',voice['authority']);self.assertFalse(native['audioPersisted']);self.assertFalse(voice['automaticTransmit'])

if __name__=='__main__':unittest.main()
