"""Actual app OAS slice for functional consent; no full OAS/product claim."""
import copy,unittest
from types import SimpleNamespace
from native_functional_policy import WIRE,decode_consent,validate_snapshot
from api_doc_native_functional import apply_native_functional_documentation
from team_api_docs import build_schema
import test_team_auth as fixture
class FunctionalDocumentationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def test_actual_four_handlers_have_auth_and_hosts_and_current_models(self):
  auth=fixture.TeamTests.module.TEAM_AUTH;schema=build_schema(fixture.TeamTests.module.app,auth)
  for key,api in WIRE['apis'].items():
   operation=schema['paths'][api['path']][api['method'].lower()]
   self.assertTrue(operation['operationId'].startswith('nativeFunctional'))
   native=key=='nativeGet';expected={'NativeMTLS':[],'DeviceBearer':[]}if native else{'CloudflareAccess':[],'TeamSession':[]}
   if api['method']!='GET':expected['CurrentSessionCSRF']=[]
   self.assertEqual(operation['security'],[expected]);self.assertEqual(operation['servers'][0]['url'],auth.native_origin if native else auth.public_origin)
   self.assertEqual(operation['x-wegoh-executable'],not native)
   self.assertTrue(operation['x-wegoh-feature-enabled'])
   for label in ['호출 주체','선행 조건','부작용','실패·재시도']:self.assertIn(label,operation['description'])
   self.assertIn('404',operation['responses']);self.assertIn('503',operation['responses'])
  models=schema['components']['schemas']
  self.assertEqual(set(models['NativeFunctionalSnapshot']['properties']),set(WIRE['apis']['nativeGet']['responseFields']))
  self.assertEqual(set(models['NativeFunctionalConsent']['properties']),set(WIRE['apis']['ownerPut']['requestFields']))
  self.assertFalse(models['NativeFunctionalSnapshot']['additionalProperties']);self.assertFalse(models['NativeFunctionalConsent']['additionalProperties'])
  purpose=models['NativeFunctionalConsent']['properties']['approvedPurposes'];self.assertEqual(purpose['maxItems'],20);self.assertEqual(purpose['items']['enum'],[r['id']for r in WIRE['purposeRegistry']])
  self.assertEqual(models['NativeFunctionalSnapshot']['properties']['expiresAt']['type'],'integer')
  self.assertTrue(models['NativeFunctionalError']['properties']['authorizationVersion']['description'])
  put=schema['paths'][WIRE['apis']['ownerPut']['path']]['put'];delete=schema['paths'][WIRE['apis']['ownerDelete']['path']]['delete']
  self.assertIn('5초',put['responses']['408']['description'])
  self.assertIn('FUNCTIONAL_REVISION_EXHAUSTED',delete['responses']['409']['description'])
  self.assertIn('초기화',delete['responses']['409']['description'])
 def test_native_presentation_is_explicit_and_keeps_current_authority_model(self):
  schema=build_schema(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH)
  op=schema['paths']['/v1/device/functional-permissions']['get']
  header=next(row for row in op['parameters'] if row['name']=='X-WegoH-Functional-Presentation')
  self.assertEqual(header['schema'],dict(type='string',enum=['2','3','4','5'],default='2'))
  current=schema['components']['schemas']['NativeFunctionalSnapshot']
  legacy=schema['components']['schemas']['NativeFunctionalLegacySnapshot']
  frozen=schema['components']['schemas']['NativeFunctionalV4Snapshot']
  self.assertEqual(current['properties']['functionalDisclosureVersion']['const'],WIRE['disclosureVersion'])
  self.assertEqual(frozen['properties']['functionalDisclosureVersion']['const'],4)
  self.assertNotEqual(frozen['properties']['functionalDisclosureSha256']['const'],WIRE['disclosureSha256'])
  self.assertEqual(legacy['properties']['functionalDisclosureVersion']['const'],2)
  self.assertEqual(legacy['properties']['approvedPurposes']['maxItems'],19)
  self.assertNotIn('driving-score:report',legacy['properties']['approvedPurposes']['items']['enum'])
  self.assertEqual(op['responses']['200']['content']['application/json']['schema'],
   {'oneOf':[{'$ref':'#/components/schemas/NativeFunctionalCurrentPresentation'},{'$ref':'#/components/schemas/NativeFunctionalLegacySnapshot'},{'$ref':'#/components/schemas/NativeFunctionalV3Snapshot'},{'$ref':'#/components/schemas/NativeFunctionalV4Snapshot'}]})
 def test_actual_examples_pass_strict_codec_and_retries_are_not_auto_approval(self):
  schema=build_schema(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH)
  for key,api in WIRE['apis'].items():
   operation=schema['paths'][api['path']][api['method'].lower()]
   validate_snapshot(operation['responses']['200']['content']['application/json']['example'])
   if key=='ownerPut':
    decode_consent(operation['requestBody']['content']['application/json']['example'])
    self.assertIn('409',operation['responses']);self.assertIn('자동 재승인',operation['description'])
   else:self.assertNotIn('requestBody',operation)
  self.assertNotIn('NativeMTLS',schema['paths'][WIRE['apis']['ownerPut']['path']]['put']['security'][0])
 def test_disabled_never_promises_execution_or_mutates_input(self):
  paths={}
  for api in WIRE['apis'].values():paths.setdefault(api['path'],{})[api['method'].lower()]={}
  original=dict(paths=paths);before=copy.deepcopy(original)
  auth=SimpleNamespace(public_origin='https://web.wegoh.invalid',native_origin='https://api.wegoh.invalid',functional_access=SimpleNamespace(enabled=False,base=SimpleNamespace(enabled=True)))
  schema=apply_native_functional_documentation(original,auth);self.assertEqual(original,before)
  for api in WIRE['apis'].values():self.assertFalse(schema['paths'][api['path']][api['method'].lower()]['x-wegoh-executable'])
if __name__=='__main__':unittest.main()
