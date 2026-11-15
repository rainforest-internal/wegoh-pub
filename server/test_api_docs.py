"""Real isolated HTTP/database API-doc contracts; no real account/server is used."""
import importlib,inspect,json,sys,unittest
import test_team_auth as fixture

class ApiDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=fixture.TeamTests;cls.fixture.setUpClass()
        cls.application=importlib.import_module('api_application')
    @classmethod
    def tearDownClass(cls):cls.fixture.tearDownClass()
    def setUp(self):
        self.api=self.fixture(methodName='test_01_jwt_verification_and_exact_hosts');self.api.setUp()
    def test_01_exact_access_admin_host_and_no_local_operator_bypass(self):
        for path in ('/api-docs','/api-docs.html','/developer/docs','/openapi.json','/developer/openapi.json'):
            self.assertEqual(self.api.call(path,who=None)[0],401)
            self.assertEqual(self.api.call(path,who='bob')[0],403)
            self.assertEqual(self.api.call(path,who='eve')[0],403)
            self.assertEqual(self.api.native(path)[0],404)
            self.assertEqual(self.api.call(path,host='127.0.0.1',origin=None,bearer=self.fixture.api_key)[0],404)
        status,headers,body=self.api.call('/api-docs')
        self.assertEqual(status,200);self.assertIn(b'api-docs.js',body);self.assertIn('no-store',headers.get('cache-control',''))
    def test_02_actual_schema_uses_registered_first_route_and_exact_json_body(self):
        status,_,schema=self.api.call('/openapi.json');self.assertEqual(status,200)
        self.assertEqual(schema['openapi'],'3.1.0');self.assertEqual(schema['servers'],[{'url':fixture.WEB}])
        self.assertEqual(schema['x-wegoh-events']['path'],'/v1/events')
        self.assertEqual(schema['x-wegoh-events']['versionedProtocol']['subprotocol'],'wegoh.events.v1')
        self.assertEqual(schema['x-wegoh-events']['chatBrowserProtocol']['subprotocol'],'wegoh.events.v1.chat')
        chat=schema['paths']['/v1/social/trips/{id}/chat']
        self.assertEqual(set(chat),{'get','post'})
        self.assertEqual(set(chat['post']['requestBody']['content']['application/json']['schema']['required']),{'id','text'})
        self.assertEqual(chat['post']['security'],[{'CloudflareAccess':[],'TeamSession':[],'CurrentSessionCSRF':[]}])
        path=schema['paths']['/v1/playlists']['post'];body=path['requestBody']['content']['application/json']['schema']
        self.assertEqual(set(body['required']),{'name','tracks'});self.assertFalse(body['additionalProperties']);self.assertEqual(body['properties']['tracks']['maxItems'],100)
        self.assertTrue(path['x-wegoh-executable']);self.assertNotIn('/v1/devices/token',schema['paths'])
        self.assertFalse(schema['paths']['/v1/connections']['post']['x-wegoh-executable'])
        self.assertEqual(schema['components']['securitySchemes']['NativeMTLS']['type'],'mutualTLS')
        self.assertEqual(schema['paths']['/v1/account']['get']['security'],[{'NativeMTLS':[],'DeviceBearer':[]}])
        course_paths=('/v1/packs','/v1/packs/{pack_id}/versions/{version}')
        publication=schema['paths']['/v1/packs']['post']['requestBody']['content']['application/json']['schema']
        self.assertNotIn('tags',publication['required'])
        self.assertEqual(publication['properties']['tags']['maxItems'],8)
        self.assertNotIn('tags',publication['properties']['pack']['properties'])
        self.assertEqual(set(publication['required']),{'rightsConfirmed','pack'})
        cover_upload=publication['properties']['coverImage']
        self.assertEqual((cover_upload['type'],cover_upload['contentEncoding'],cover_upload['contentMediaType'],cover_upload['maxLength']),
                         ('string','base64','image/jpeg',163840))
        self.assertEqual(publication['properties']['copyCoverFromVersion']['minimum'],1)
        self.assertEqual(set(publication['not']['required']),{'coverImage','copyCoverFromVersion'})
        self.assertTrue({'coverImage','copyCoverFromVersion'}.isdisjoint(publication['properties']['pack']['properties']))
        for prefix in ('/v1/packs','/v1/studio/packs','/v1/moderation/packs'):
            with self.subTest(courseCover=prefix):
                cover=schema['paths'][prefix+'/{pack_id}/versions/{version}/cover']['get']
                expected={'CloudflareAccess':[]} if prefix=='/v1/packs' else {'CloudflareAccess':[],'TeamSession':[]}
                self.assertEqual(cover['security'],[expected])
                self.assertFalse(cover['x-wegoh-native-access'])
                self.assertFalse(cover['x-wegoh-executable'])
                self.assertNotIn(fixture.NATIVE,[server['url'] for server in cover.get('servers',schema['servers'])])
                self.assertEqual(cover['responses']['200']['content'],{'image/jpeg':{'schema':{'type':'string','format':'binary'}}})
                self.assertIn('404',cover['responses'])
        library=schema['paths']['/v1/studio/course-library']['get']
        self.assertTrue(any(parameter['name']=='tag' and not parameter['required'] for parameter in library['parameters']))
        for course_path in course_paths:
            with self.subTest(course=course_path,nativeConfigured=True):
                operation=schema['paths'][course_path]['get']
                self.assertEqual(operation['security'],[{'CloudflareAccess':[]},{'NativeMTLS':[],'DeviceBearer':[]}])
                self.assertEqual([server['url']for server in operation['servers']],[fixture.WEB,fixture.NATIVE])
                self.assertTrue(operation['x-wegoh-native-configured'])
                self.assertTrue(operation['x-wegoh-native-read-only'])
                self.assertTrue(operation['x-wegoh-executable']) # Browser same-origin Try remains guarded by api-docs.js.
                self.assertNotIn('CurrentSessionCSRF',operation['security'][0])
        for asset_path,method in (('/v1/assets','post'),('/v1/assets/{checksum}','get')):
            with self.subTest(nativeAssetDenied=asset_path):
                operation=schema['paths'][asset_path][method]
                self.assertFalse(operation['x-wegoh-executable'])
                self.assertEqual(operation['x-wegoh-surface'],'operator-or-local')
                self.assertFalse(any('NativeMTLS'in requirement or 'DeviceBearer'in requirement for requirement in operation['security']))
                self.assertNotIn(fixture.NATIVE,[server['url']for server in operation.get('servers',schema['servers'])])
        auth=self.fixture.module.TEAM_AUTH
        original_native=auth.native_origin
        try:
            auth.native_origin=''
            status,_,closed=self.api.call('/openapi.json')
            self.assertEqual(status,200)
            for course_path in course_paths:
                with self.subTest(course=course_path,nativeConfigured=False):
                    operation=closed['paths'][course_path]['get']
                    self.assertFalse(operation['x-wegoh-native-configured'])
                    self.assertEqual(operation['security'],[{'CloudflareAccess':[]}])
                    self.assertEqual([server['url']for server in operation['servers']],[fixture.WEB])
        finally:
            auth.native_origin=original_native
        self.assertNotIn('PairingCreated',schema['components']['schemas'])
        self.assertEqual(schema['components']['schemas']['NativeAccessError']['properties']['authorizationVersion']['const'],1)
        self.assertIn('CloudflareAccess',schema['paths']['/v1/auth/session']['post']['security'][0])
        permissions=schema['paths']['/v1/social/history/{item}/export-permissions']['get']['responses']['200']['content']['application/json']['schema']
        from api_doc_models import SCHEMAS
        self.assertEqual(permissions,{'$ref':'#/components/schemas/ExportPermissions'})
        self.assertEqual(set(SCHEMAS['ExportPermissions']['required']),{'historyId','historyRevision','permissions','serverNow'})
        self.assertEqual(SCHEMAS['ExportPermissions']['properties']['serverNow']['format'],'date-time')
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
        from check_api_documentation import check
        # Literal documentation maps must not silently shadow another route's meaning.
        import ast,api_doc_catalog
        def unique_literal_keys(node):
            keys=[key.value for key in node.keys if isinstance(key,ast.Constant)and isinstance(key.value,str)]
            self.assertEqual(len(keys),len(set(keys)),'Duplicate literal API documentation key')
        for node in ast.parse(Path(api_doc_catalog.__file__).read_text()).body:
            if isinstance(node,ast.Assign)and any(isinstance(target,ast.Name)and target.id in('FIELD_DOCS','PARAMS','TAG_DESCRIPTIONS')for target in node.targets):unique_literal_keys(node.value)
        with self.assertRaises(AssertionError):unique_literal_keys(ast.parse("{'identifier':1,'identifier':2}",mode='eval').body)
        for node in ast.parse("[{'identifier':1},{'identifier':2}]",mode='eval').body.elts:unique_literal_keys(node)
        self.assertEqual(schema['x-wegoh-documentation-coverage']['genericCatalogOperations'],len(api_doc_catalog.OPERATIONS))
        self.assertEqual(check(schema)['operations'],sum(method in {'get','post','put','patch','delete'}for methods in schema['paths'].values()for method in methods))
        import copy
        for mutation in ('summary','ref','security'):
            broken=copy.deepcopy(schema)
            if mutation=='summary':broken['paths']['/v1/playlists']['post'].pop('summary')
            elif mutation=='ref':broken['paths']['/v1/playlists']['post']['responses']['201']['content']['application/json']['schema']={'$ref':'#/components/schemas/Absent'}
            else:broken['paths']['/v1/playlists']['post']['security']=[{'Absent':[]}]
            with self.assertRaises(ValueError):check(broken)
        from api_doc_catalog import OPERATIONS,apply_documentation
        removed=OPERATIONS.pop(('get','/v1/playlists'))
        try:
            from team_api_docs import BODY
            with self.assertRaises(RuntimeError):apply_documentation(copy.deepcopy(schema),BODY)
        finally:OPERATIONS[('get','/v1/playlists')]=removed
        raw=json.dumps(schema);self.assertNotIn(self.fixture.api_key,raw);self.assertNotIn('@example.invalid',raw);self.assertNotIn('HTTPBearer',schema['components']['securitySchemes'])
        csrf=schema['components']['securitySchemes']['CurrentSessionCSRF']
        self.assertEqual((csrf['type'],csrf['in'],csrf['name']),('apiKey','header','X-WegoH-CSRF'))
        self.assertIn('CurrentSessionCSRF',path['security'][0])
        self.assertFalse(any(p['name']=='X-WegoH-CSRF'for p in path.get('parameters',[])))
    def test_03_real_get_post_and_original_origin_csrf_owner_boundary(self):
        alice=self.api.login();bob=self.api.login('bob')
        self.assertTrue(self.api.call('/v1/auth/session',session=alice)[2]['authenticated'])
        value={'name':'Synthetic developer request','tracks':[]}
        self.assertEqual(self.api.call('/v1/playlists',value,'POST',session=alice,csrf=False)[0],403)
        self.assertEqual(self.api.call('/v1/playlists',value,'POST',session=alice,origin='https://wrong.invalid')[0],403)
        status,_,created=self.api.call('/v1/playlists',value,'POST',session=alice);self.assertEqual(status,201);self.assertEqual(created['name'],value['name'])
        self.assertEqual(self.api.call('/v1/playlists',session=alice)[2]['playlists'][0]['id'],created['id'])
        self.assertEqual(self.api.call('/v1/playlists/'+created['id'],session=bob,who='bob')[0],404)
        self.assertEqual(self.api.call('/v1/playlists/'+created['id'],method='DELETE',session=alice)[0],200)
    def test_04_wrapper_route_precedes_static_mount_and_local_mode_closes_docs(self):
        from starlette.routing import Mount
        routes=self.application.app.routes;mount=next(i for i,r in enumerate(routes)if isinstance(r,Mount)and r.path in ('','/'))
        self.assertTrue(all(i<mount for i,r in enumerate(routes)if getattr(r,'path','')in ('/api-docs','/openapi.json')))
        auth=self.fixture.module.TEAM_AUTH
        original_native=auth.native_origin
        try:
            auth.native_origin=''
            self.assertFalse(auth.capabilities()['pairing'])
            self.assertFalse(self.api.call('/openapi.json')[2]['paths']['/v1/packs']['get']['x-wegoh-native-configured'])
        finally:auth.native_origin=original_native
        try:
            auth.enabled=False
            self.assertEqual(self.api.call('/api-docs')[0],404)
        finally:auth.enabled=True

def serve_fixture(path):
    import test_team_friends as friends
    class DocsFixture(friends.FriendTests):
        @classmethod
        def setUpClass(cls):
            super().setUpClass();importlib.import_module('api_application')
    original=friends.FriendTests
    try:
        if 'fixture_class' in inspect.signature(friends.serve_fixture).parameters:friends.serve_fixture(path,fixture_class=DocsFixture)
        else:
            friends.FriendTests=DocsFixture;friends.serve_fixture(path)
    finally:friends.FriendTests=original

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--serve-fixture':serve_fixture(sys.argv[2])
    else:unittest.main(verbosity=2)
