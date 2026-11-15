"""Authored Swagger overlay: actual strict decoder examples and OAS security facts."""
import copy
import json
from types import SimpleNamespace
import unittest
import api_doc_native_access as docs
import native_access_codec as codec


class NativeAccessDocumentationTest(unittest.TestCase):
    def auth(self):
        return SimpleNamespace(enabled=True,native_origin=codec.wire_contract()['origins']['native'])

    def schema(self):
        wire=codec.wire_contract()
        paths={}
        for item in wire['operations']:
            if item['action']=='CERTIFICATE_RECOVER':continue  # Unimplemented route must remain visibly contract-only.
            paths.setdefault(docs._path(item['path']),{})[item['method'].lower()]={}
        for item in wire['phoneOperations']:
            paths.setdefault(docs._path(item['path']),{})[item['method'].lower()]={}
        for path in ('/v1/account','/v1/packs','/v1/playlists'):
            paths[path]={'get':{'security':[{'CloudflareAccess':[],'TeamSession':[]}],'description':'Existing browser contract.'}}
        return {'openapi':'3.1.0','info':{'title':'WegoH','version':'test'},'paths':paths}

    def test_overlay_preserves_input_and_marks_unavailable_routes_nonexecutable(self):
        original=self.schema();before=copy.deepcopy(original)
        value=docs.apply_native_access_documentation(original,self.auth())
        self.assertEqual(original,before)
        path='/v1/installations/certificate-recover'
        self.assertFalse(value['paths'][path]['post']['x-wegoh-handler-present'])
        self.assertFalse(value['paths'][path]['post']['x-wegoh-executable'])
        operations=[op for methods in value['paths'].values() for method,op in methods.items() if method in ('get','post','delete') and method!='parameters']
        identifiers=[op['operationId'] for op in operations if 'operationId' in op]
        self.assertEqual(len(set(identifiers)),len(identifiers))
        self.assertTrue(value['info']['description'].startswith('## 차량 연결 기본: 단일 v1'))
        self.assertEqual(value['tags'][0]['name'],docs.TAG)
        self.assertIn('connect',value['info']['description'])
        self.assertNotIn('oauth2',json.dumps(value['components']['securitySchemes']))
        self.assertNotIn('bearerFormat',value['components']['securitySchemes']['DeviceBearer'])
        self.assertNotIn('NativeAccessBoundaryError',value['components']['schemas'])

    def test_native_read_alternative_uses_configured_host_and_stays_closed_without_it(self):
        configured='https://synthetic-native.example.invalid'
        present=docs.apply_native_access_documentation(self.schema(),SimpleNamespace(enabled=True,native_origin=configured))
        absent=docs.apply_native_access_documentation(self.schema(),SimpleNamespace(enabled=True,native_origin=''))
        for path in ('/v1/packs','/v1/playlists'):
            self.assertIn({'NativeMTLS':[],'DeviceBearer':[]},present['paths'][path]['get']['security'])
            self.assertEqual(present['paths'][path]['get']['servers'],[{'url':configured}])
            self.assertTrue(present['paths'][path]['get']['x-wegoh-native-configured'])
            self.assertNotIn({'NativeMTLS':[],'DeviceBearer':[]},absent['paths'][path]['get']['security'])
            self.assertFalse(absent['paths'][path]['get']['x-wegoh-native-configured'])
            self.assertNotIn('servers',absent['paths'][path]['get'])

    def test_retired_authentication_routes_fail_instead_of_being_documented_or_hidden(self):
        for path in ('/v2/connections','/v1/devices/pairings','/v1/devices/token','/v1/devices/token/refresh','/v1/enrollments','/v1/enrollments/abc/claim'):
            with self.subTest(path=path):
                schema=self.schema();schema['paths'][path]={'post':{}}
                with self.assertRaisesRegex(RuntimeError,'Retired public authentication route'):
                    docs.apply_native_access_documentation(schema,self.auth())

    def test_each_request_and_success_example_passes_the_authoritative_decoder(self):
        value=docs.apply_native_access_documentation(self.schema(),self.auth())
        wire=codec.wire_contract();count=0
        snapshot=docs._kind('DisclosureSnapshot',wire)
        policies=snapshot['properties']['scopeDisclosures']
        self.assertTrue(policies['uniqueItems'])
        self.assertEqual(policies['maxItems'],len(wire['disclosureRegistry']['scopePolicies']))
        complete=codec.disclosure_snapshot(sorted(row['scope']for row in wire['disclosureRegistry']['scopePolicies']))
        self.assertLessEqual(len(complete['scopeDisclosures']),policies['maxItems'])
        self.assertEqual([item['const'] for item in policies['items']['oneOf']],wire['disclosureRegistry']['scopePolicies'])
        for operation in wire['operations']:
            action=operation['action'];target=value['paths'][docs._path(operation['path'])]['post']
            example=target['requestBody']['content']['application/json']['examples'][action]['value']
            codec.decode_request(action,example)
            for variant in operation['responseVariants']:
                key=action+'_'+variant['state']+'_'+variant['disposition']
                response=target['responses'][str(variant['httpStatus'])]['content']['application/json']['examples'][key]['value']
                codec.decode_response(action,variant['httpStatus'],response,
                    expected_operation_id=example['operationId'],expected_installation_key_id=docs.PUBLIC_EXAMPLE['keyId'])
                count+=1
        self.assertGreater(count,20)
        for operation in wire['phoneOperations']:
            action=operation['action'];target=value['paths'][docs._path(operation['path'])][operation['method'].lower()]
            if 'requestBody' in target:
                body=target['requestBody']['content']['application/json']['examples']['selectedPurposes']['value']
                codec.decode_phone_request(action,body,requested_scopes=sorted(item.value for item in codec.REQUIRED_SCOPES))
            response=target['responses']['200']['content']['application/json']['examples']['synthetic']['value']
            codec.decode_phone_response(action,response,expected_user_code='ABCD2345')

    def test_security_is_and_for_native_and_session_csrf_without_fake_jwt_or_key_input(self):
        value=docs.apply_native_access_documentation(self.schema(),self.auth())
        native=value['paths']['/v1/device-sessions/exchange']['post']
        self.assertEqual(native['security'],[{'NativeMTLS':[]}])
        self.assertFalse(native['x-wegoh-executable'])
        self.assertEqual(value['paths']['/v1/connections']['post']['security'],[])
        phone=value['paths']['/v1/connections/{user_code}']
        self.assertEqual(phone['post']['security'],[{'CloudflareAccess':[],'TeamSession':[],'CurrentSessionCSRF':[]}])
        self.assertEqual(phone['get']['security'],[{'CloudflareAccess':[],'TeamSession':[]}])
        self.assertIn({'NativeMTLS':[],'DeviceBearer':[]},value['paths']['/v1/packs']['get']['security'])
        self.assertNotIn({'NativeMTLS':[]},value['paths']['/v1/packs']['get']['security'])
        self.assertEqual(value['paths']['/v1/packs']['get']['x-wegoh-required-scopes'],['account:read','courses:read','device:self:manage'])

    def test_closed_models_and_references_resolve_and_errors_have_real_next_actions(self):
        value=docs.apply_native_access_documentation(self.schema(),self.auth())
        models=value['components']['schemas']
        def visit(item):
            if isinstance(item,dict):
                if '$ref' in item:
                    prefix='#/components/schemas/'
                    self.assertTrue(item['$ref'].startswith(prefix))
                    self.assertIn(item['$ref'][len(prefix):],models)
                if item.get('type')=='object' and 'properties' in item:
                    self.assertIs(item.get('additionalProperties'),False)
                    self.assertTrue(set(item.get('required',[]))<=set(item['properties']))
                for child in item.values():visit(child)
            elif isinstance(item,list):
                for child in item:visit(child)
        visit(value)
        wire=codec.wire_contract()
        for methods in value['paths'].values():
            for method,operation in methods.items():
                if not operation.get('operationId','').startswith('nativeAccess'):continue
                self.assertIn('호출 주체',operation['description'])
                self.assertIn('부작용',operation['description'])
                self.assertIn('실패·재시도',operation['description'])
                for status,response in operation['responses'].items():
                    if int(status)>=400:
                        self.assertIn('description',response)
                        for example in response['content']['application/json'].get('examples',{}).values():
                            if 'authorizationVersion' in example['value']:
                                codec.decode_error(int(status),example['value'])
                            else:
                                self.assertEqual(set(example['value']),{'detail'})
                                self.assertIs(type(example['value']['detail']),str)

    def test_new_unknown_handler_is_not_approved_by_generated_fallback(self):
        schema=self.schema();schema['paths']['/v1/connections/undocumented']={'post':{}}
        with self.assertRaisesRegex(RuntimeError,'lacks authored wire documentation'):
            docs.apply_native_access_documentation(schema,self.auth())

    def test_disabled_feature_never_promises_browser_execution(self):
        auth=SimpleNamespace(enabled=True,native_authorization=SimpleNamespace(enabled=False))
        value=docs.apply_native_access_documentation(self.schema(),auth)
        self.assertFalse(value['paths']['/v1/connections/{user_code}']['post']['x-wegoh-executable'])
        self.assertFalse(value['paths']['/v1/connections/{user_code}']['post']['x-wegoh-feature-enabled'])
        auth.native_authorization.enabled=True
        enabled=docs.apply_native_access_documentation(self.schema(),auth)
        self.assertTrue(enabled['paths']['/v1/connections/{user_code}']['post']['x-wegoh-executable'])
        self.assertFalse(enabled['paths']['/v1/device-sessions/exchange']['post']['x-wegoh-executable'])

    def test_renewal_same_claim_shape_is_not_duplicate_oneof_and_examples_are_next_generation(self):
        value=docs.apply_native_access_documentation(self.schema(),self.auth())
        begin=value['paths']['/v1/installations/certificate-renew']['post']
        self.assertEqual(begin['security'],[])
        self.assertEqual(begin['requestBody']['content']['application/json']['schema']['properties']['proofNonce']['const'],'certificate-renewal')
        claim=value['paths']['/v1/connections/{connection_id}/claim']['post']
        self.assertEqual(set(claim['x-wegoh-contract-actions']),{'CONNECTION_CLAIM','CERTIFICATE_RENEW_CLAIM'})
        self.assertNotIn('oneOf',claim['requestBody']['content']['application/json']['schema'])
        receipt=claim['responses']['200']['content']['application/json']['examples']['CERTIFICATE_RENEW_CLAIM_ISSUED_CERTIFICATE_RECEIPT']['value']['certificateReceipt']
        self.assertEqual(receipt['generation'],2)
        rebind=value['paths']['/v1/device-sessions/rebind']['post']
        self.assertEqual(rebind['security'],[{'NativeMTLS':[]}])
        self.assertFalse(rebind['x-wegoh-executable'])
        receipt=rebind['responses']['200']['content']['application/json']['examples']['CREDENTIAL_REBIND_TOKEN_ISSUED_CREDENTIAL_RECEIPT']['value']['credentialReceipt']
        self.assertEqual(receipt['generation'],2)
        self.assertEqual(receipt['credentialEpoch'],2)

    def test_browser_management_replaces_retired_body_with_one_exact_current_scope_contract(self):
        original=self.schema()
        old_request={'type':'object','required':['revision','permissions'],'properties':{'revision':{'type':'integer'},'permissions':{'type':'object'}}}
        old_response={'type':'object','required':['deviceId','permissions'],'properties':{'deviceId':{'type':'string'},'permissions':{'type':'object'}}}
        response=lambda value:{'200':{'content':{'application/json':{'schema':copy.deepcopy(value)}}}}
        original['paths']['/v1/devices']={'get':{'description':'Legacy list.','responses':response({'type':'object','properties':{'devices':{'type':'array','items':{'type':'object','required':['lastUsedAt'],'properties':{'lastUsedAt':{'type':'string'}}}}}})}}
        original['paths']['/v1/devices/{device_id}']={'delete':{'description':'Legacy revoke.'}}
        original['paths']['/v1/devices/{device}/permissions']={method:{'description':'Legacy purposes.','responses':response(old_response)} for method in ('get','put')}
        original['paths']['/v1/devices/{device}/permissions']['put']['requestBody']={'required':True,'content':{'application/json':{'schema':old_request}}}
        value=docs.apply_native_access_documentation(original,self.auth())
        models=value['components']['schemas'];snapshot=models['NativeAccessBrowserPermissions']
        self.assertEqual(set(snapshot['properties']),{'authorizationVersion','deviceId','name','revision','consentVersion','scopes','keepSignedIn','expiresAt','grantExpiresAt'})
        self.assertEqual(models['NativeAccessBrowserDevice']['properties']['lastUsedAt'],{'type':'null','description':'Current contract does not collect last-used timestamps.'})
        target=value['paths']['/v1/devices/{device}/permissions']['put']
        self.assertEqual(target['requestBody']['content']['application/json']['schema'],docs._ref('NativeAccessScopeReduction'))
        self.assertEqual(target['responses']['200']['content']['application/json']['schema']['oneOf'],[docs._ref('NativeAccessBrowserPermissions'),docs._ref('NativeAccessBrowserRevoked')])
        self.assertNotIn('permissions',str(target['requestBody']))
        self.assertEqual(set(models['NativeAccessBrowserRevoked']['properties']),{'authorizationVersion','deviceId','status'})
        self.assertEqual(models['NativeAccessScopeReduction']['properties']['scopes']['minItems'],0)
        self.assertNotIn('permissions',snapshot['properties'])

    def test_preexchange_revoke_commitment_and_grant_only_revoke_match_codec(self):
        value=docs.apply_native_access_documentation(self.schema(),self.auth())
        for operation in codec.wire_contract()['operations']:
            if 'revokeCommitment' not in operation['requestRequired']:continue
            body=value['paths'][docs._path(operation['path'])]['post']['requestBody']['content']['application/json']['examples'][operation['action']]['value']
            self.assertEqual(body['revokeCommitment'],codec.revoke_commitment(codec.derive_revoke_capability(docs.EXAMPLE_VERIFIER,docs.PUBLIC_EXAMPLE['keyId'],body['operationId'])))
        revoke=value['paths']['/v1/device-sessions/revoke']['post']
        self.assertEqual(revoke['security'],[{'NativeMTLS':[]}])
        self.assertNotIn('deviceId',revoke['requestBody']['content']['application/json']['schema']['properties'])
        self.assertEqual(set(revoke['requestBody']['content']['application/json']['schema']['required']),{'authorizationVersion','operationId','grantId','revokeCapability'})

    def test_all_public_version_fields_and_uri_use_only_current_contract(self):
        value=docs.apply_native_access_documentation(self.schema(),self.auth())
        import re
        rule=docs._kind('FixedPhoneUri',codec.wire_contract())['pattern']
        self.assertIsNotNone(re.fullmatch(rule,'https://wegoh.devforest.io/enroll.html?user_code=ABCD2345'))
        self.assertIsNone(re.fullmatch(rule,'https://wegoh.devforest.io/enroll.html?authorization_version=2&user_code=ABCD2345'))
        self.assertEqual(docs._kind('Version',codec.wire_contract()),{'type':'integer','const':1})
        self.assertNotIn('legacyDeviceId',docs.FIELD)
        self.assertTrue(all(not name.startswith('NativeV2') for name in value['components']['schemas']))
        def inspect(item):
            if isinstance(item,dict):
                for key,child in item.items():
                    if key=='authorizationVersion':
                        self.assertTrue(child==1 or isinstance(child,dict) and child.get('const')==1)
                    inspect(child)
            elif isinstance(item,list):
                for child in item:inspect(child)
        inspect(value)

    def test_websocket_extension_preserves_minimal_scope_and_no_private_payload(self):
        value=docs.apply_native_access_documentation(self.schema(),self.auth())
        events=value['x-wegoh-native-events']
        self.assertEqual(events['security'],[{'NativeMTLS':[],'DeviceBearer':[]}])
        self.assertEqual(events['scopeProjection']['mandatoryOnly'],['devices'])
        self.assertEqual(events['frameFields']['heartbeat'],['type','epoch','seq'])
        self.assertEqual(set(events['example']),{'type','epoch','seq','resources'})
        self.assertNotIn('deviceId',events['example'])


if __name__=='__main__':unittest.main()
