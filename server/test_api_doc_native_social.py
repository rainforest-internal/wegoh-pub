"""Five current social contracts against mounted OAS and synthetic private PG.

The fixture injects verified edge metadata; it is not a live TLS/CF/OEM test.
"""
import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import psycopg
from api_doc_social import NATIVE_SOCIAL_OPERATIONS
from api_doc_models import SCHEMAS
from native_functional_policy import WIRE
from team_api_docs import BODY, build_schema
import test_team_auth as fixture
import test_native_functional_business as business_fixture


class NativeSocialDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.factory = business_fixture.FunctionalBusinessTests('test_native_friend_request_respond_scope_withdrawal_and_original_authority')
        self.factory.setUp()
        self.h = self.factory.h

    def schema(self):
        return build_schema(fixture.TeamTests.module.app, fixture.TeamTests.module.TEAM_AUTH)

    def expect(self, result, status):
        self.assertEqual(result[0], status, result[2])
        return result[2]

    def room(self, owner):
        value = self.expect(self.h.call('/v1/social/rooms', dict(name='Synthetic documentation room', courseId=None, courseVersion=None, expiresInHours=1), 'POST', session=owner), 201)
        flags = {key: key == 'status' for key in ('status','location','visits','music','voice','control')}
        self.expect(self.h.call('/v1/social/rooms/'+value['id']+'/consents', dict(consents=flags), 'PATCH', session=owner), 200)
        return value['id']

    def record(self):
        return dict(title='Synthetic documentation history', startedAt=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat(), endedAt=None, courseId=None, courseVersion=None)

    def count(self, table):
        with psycopg.connect(self.h.dsn) as conn:
            return conn.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def projection(self, schema, name, value):
        model = schema['components']['schemas'][name]
        self.assertEqual(set(value), set(model['required']))
        self.assertTrue(set(value) <= set(model['properties']))
        self.assertFalse(model['additionalProperties'])

    def test_mounted_five_contracts_security_closed_bodies_and_browser_preservation(self):
        original = copy.deepcopy(SCHEMAS)
        schema = self.schema()
        with patch('api_doc_social.apply_native_social_documentation', side_effect=lambda value, auth: value):
            before_overlay = self.schema()
        rules = {(r['method'].lower(),r['path']): r for r in WIRE['nativeRoutes']}
        self.assertEqual(len(NATIVE_SOCIAL_OPERATIONS), 5)
        self.assertEqual(sum(method == 'post' for method,path in NATIVE_SOCIAL_OPERATIONS), 2)
        for method,path in NATIVE_SOCIAL_OPERATIONS:
            op = schema['paths'][path][method]
            browser = dict(CloudflareAccess=[], TeamSession=[])
            if method == 'post': browser['CurrentSessionCSRF'] = []
            self.assertEqual(op['security'], [browser, dict(NativeMTLS=[], DeviceBearer=[])])
            self.assertEqual(op['servers'][0]['url'], self.h.module.TEAM_AUTH.public_origin)
            self.assertEqual(op['servers'][1]['url'], self.h.module.TEAM_AUTH.native_origin)
            self.assertEqual(op['x-wegoh-native-functional-purposes'], dict(all=rules[(method,path)]['all'], any=rules[(method,path)]['any']))
            self.assertIn('차량 로그인', op['description'])
            if method == 'post':
                content = op['requestBody']['content']['application/json']
                browser_body,native_ref = content['schema']['oneOf']
                self.assertEqual(browser_body, before_overlay['paths'][path][method]['requestBody']['content']['application/json']['schema'])
                native = schema['components']['schemas'][native_ref['$ref'].rsplit('/',1)[1]]
                self.assertFalse(native['additionalProperties'])
                self.assertEqual(set(native['required']),set(browser_body['required'])|{'functionalRevision'})
                self.assertEqual(native['properties']['functionalRevision']['minimum'],1)
                self.assertNotIn('operationId', native['properties'])
                self.assertEqual(set(op['responses']) & {'200','201'}, {'201'})
                self.assertIn('별도 항목',op['description'])
                self.assertEqual(content['examples']['native']['value'], dict(content['examples']['browser']['value'], functionalRevision=1))
        self.assertEqual(SCHEMAS, original, 'Shared Browser model definitions must not mutate')
        self.assertNotIn('/v1/social/rooms/{room}/invite-qr.svg',schema['paths'])
        auth = copy.copy(self.h.module.TEAM_AUTH)
        feature = copy.copy(auth.functional_access);feature.enabled = False;auth.functional_access = feature
        disabled = build_schema(self.h.module.app, auth)
        self.assertTrue(all(not disabled['paths'][path][method]['x-wegoh-feature-enabled'] for method,path in NATIVE_SOCIAL_OPERATIONS))

    def test_account_views_and_separate_history_trace_access(self):
        owner,bob = self.h.login(),self.h.login('bob')
        credential = self.factory.connect(owner)
        room = self.room(owner)
        self.expect(self.h.call('/v1/social/friends/requests',dict(targetId=bob['user']['id']),'POST',session=owner),201)
        self.expect(self.h.call('/v1/social/friends/requests/'+owner['user']['id']+'/respond',dict(accept=True),'POST',session=bob,who='bob'),200)
        self.expect(self.h.call('/v1/social/history',self.record(),'POST',session=owner),201)
        schema = self.schema()
        self.factory.approve(owner,credential,[])
        overview = self.expect(self.factory.native(credential,'/v1/social/overview'),200)
        self.projection(schema,'NativeSocialOverview',overview)
        self.assertEqual(overview['capabilities'],dict(friends=True,rooms=True,history=True,nativeReadOnly=False))
        self.assertEqual([friend['id'] for friend in overview['friends']], [bob['user']['id']])
        self.assertEqual([member_room['id'] for member_room in overview['rooms']], [room])
        for key in ('people','requests','blocks','history'):self.assertEqual(overview[key],[])
        detail = self.expect(self.factory.native(credential,'/v1/social/rooms/'+room),200)
        self.projection(schema,'NativeSocialRoom',detail)
        self.assertFalse(detail['nativeReadOnly'])
        self.assertFalse({'code','inviteUri','consents','availableConsentKeys','agreedStop'} & set(detail))
        for trace in (False,True):
            if trace:self.factory.approve(owner,credential,['history:write'])
            page = self.expect(self.factory.native(credential,'/v1/social/history'),200)
            self.projection(schema,'NativeSocialHistoryPage',page)
            self.assertEqual(page['nativeReadOnly'],not trace);self.assertEqual(page['friends'],[])
            self.assertEqual(page['capabilities']['historyTraceIngest'],trace)
            self.assertEqual(set(page['capabilities']),set(schema['components']['schemas']['NativeSocialHistoryPage']['properties']['capabilities']['required']))
            self.assertIsNone(page['nextCursor'])
            self.assertEqual(len(page['history']),1)
            summary = page['history'][0]
            self.projection(schema,'NativeSocialHistorySummary',summary)
            self.assertIsNone(summary['permissionRevision']);self.assertEqual(summary['sharedWith'],[])
        browser_overview = self.expect(self.h.call('/v1/social/overview',session=owner),200)
        self.assertNotIn('nativeReadOnly',browser_overview['capabilities'])
        for path in ('/v1/social/rooms/'+room,'/v1/social/history'):
            self.assertNotIn('nativeReadOnly',self.expect(self.h.call(path,session=owner),200))

    def test_actual_both_posts_require_json_revision_create_201_and_repeat_as_new_items(self):
        owner = self.h.login(); credential = self.factory.connect(owner); room = self.room(owner)
        revision = self.factory.approve(owner,credential,[])
        cases = [('/v1/social/rooms/'+room+'/signals',dict(kind='rest'),'team_room_signals'),('/v1/social/history',self.record(),'team_histories')]
        for path,body,table in cases:
            before = self.count(table)
            self.expect(self.factory.native(credential,path,body,'POST'),400)
            self.expect(self.factory.native(credential,path,dict(body,functionalRevision=revision+1),'POST'),409)
            self.expect(self.factory.native(credential,path,dict(body,functionalRevision=revision,operationId='a'*32),'POST'),400)
            self.assertEqual(self.count(table),before)
            first = self.expect(self.factory.native(credential,path,dict(body,functionalRevision=revision),'POST'),201)
            second = self.expect(self.factory.native(credential,path,dict(body,functionalRevision=revision),'POST'),201)
            self.assertNotEqual(first['id'],second['id']);self.assertEqual(self.count(table),before+2)
            if path.endswith('/signals'):
                self.assertEqual(first['status'],'sent')
                values = self.expect(self.factory.native(credential,'/v1/social/rooms/'+room),200)['signals']
            else:
                self.assertEqual(first,dict(id=first['id'],revision=1,permissionRevision=1))
                values = self.expect(self.factory.native(credential,'/v1/social/history'),200)['history']
                detail = self.expect(self.h.call('/v1/social/history/'+first['id'],session=owner),200)
                self.assertEqual(detail['source']['kind'],'device-reported')
                self.assertFalse(detail['permissions']['collectTrace']);self.assertEqual(detail['grants'],[])
            self.assertTrue({first['id'],second['id']} <= {value['id'] for value in values})
            # Browser still rejects the Native-only field in its closed body.
            self.expect(self.h.call(path,dict(body,functionalRevision=revision),'POST',session=owner),400)


if __name__ == '__main__':
    unittest.main()
