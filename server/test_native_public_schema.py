"""Actual main application schema, current isolated issuer and business coverage."""
import json,re
from pathlib import Path
from test_native_authorization_http import NativeAuthorizationHttpTests
from team_api_docs import build_schema
from native_access_policy import is_retired_authorization_path
import test_team_auth as fixture

class PublicSchemaTests(NativeAuthorizationHttpTests):
    def test_15_actual_schema_has_only_public1_authorization_and_business_routes(self):
        schema=build_schema(fixture.TeamTests.module.app,self.auth)
        wire=json.loads(Path(__file__).with_name('native_access_wire.json').read_text())
        self.assertFalse(any(is_retired_authorization_path(path) for path in schema['paths']))
        self.assertTrue(all(path.startswith('/v1/') for path in schema['paths']))
        for operation in wire['operations']:
            action=operation['action']
            with self.subTest(action=action):
                path=operation['path'];method=operation['method'].lower()
                matches=[value for key,value in schema['paths'].items() if re.sub(r'\{[^}]+\}', '{}',key)==re.sub(r'\{[^}]+\}', '{}',path)]
                self.assertEqual(len(matches),1);self.assertIn(method,matches[0])
        for path in ('/v1/playlists','/v1/packs','/v1/social/history'):
            self.assertIn('get',schema['paths'][path])
        self.assertEqual(schema['components']['securitySchemes']['NativeMTLS']['type'],'mutualTLS')
        self.assertNotIn('PairingCreated',schema['components']['schemas'])
        self.assertNotIn('PairingInfo',schema['components']['schemas'])
        self.assertNotIn('Tokens',schema['components']['schemas'])
        exchange=schema['paths']['/v1/device-sessions/exchange']['post']
        self.assertTrue(any('NativeMTLS' in item for item in exchange['security']))
        purposes={
            '/v1/social/history': (['history:read'], []),
            '/v1/social/overview': ([], ['friends:read','rooms:read','history:read']),
            '/v1/social/rooms/{room}': (['rooms:read'], []),
            '/v1/social/rooms/{room}/music': (['rooms:read','room-music:read'], []),
        }
        rules={row['path']: row for row in wire['functional']['nativeRoutes'] if row['method']=='GET'}
        for path,(required,alternatives) in purposes.items():
            with self.subTest(path=path):
                operation=schema['paths'][path]['get']
                self.assertTrue(operation['x-wegoh-native-access'])
                self.assertEqual((rules[path]['all'],rules[path]['any']),(required,alternatives))
                self.assertIn({'NativeMTLS':[],'DeviceBearer':[]},operation['security'])
                self.assertIn({'CloudflareAccess':[],'TeamSession':[]},operation['security'])
                self.assertEqual({server['url'] for server in operation['servers']},
                                 {self.auth.public_origin,self.auth.native_origin})
        web_session=schema['paths']['/v1/auth/session']['get']
        self.assertFalse(web_session['x-wegoh-native-access'])
        self.assertFalse(any('NativeMTLS' in item for item in web_session['security']))
        self.assertEqual(schema['x-wegoh-events']['nativePurposes']['resourceScopes'],{'courses':'courses:read','playlists':'playlists:read','devices':'device:self:manage'})
        account=schema['paths']['/v1/account']['get']['responses']['200']['content']['application/json']['schema']['properties']['user']
        self.assertEqual(set(account['properties']),{'id','displayName'})
        self.assertEqual(set(account['required']),{'id','displayName'})
        self.assertNotIn('role',account['properties'])
        self.assertEqual(self.issuer.calls,0)
