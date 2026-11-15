"""Mounted OAS finalization and exact legacy409 boundary; synthetic private PG only."""
import copy
import unittest
from pathlib import Path
import sys
from fastapi.routing import iter_route_contexts
from fastapi.openapi.utils import _get_api_route_for_openapi
import test_team_auth as fixture
from api_doc_finalization import finalize_documentation
from native_access_codec import wire_contract, disclosure_snapshot
from api_doc_native_access import _path
from api_doc_catalog import OPERATIONS
from api_doc_iphone import mounted_iphone_operations
from api_doc_reviewer import mounted_reviewer_operations
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_api_documentation import check, METHODS, TERMINAL_OPERATIONS


class FinalDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.h = fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        self.h.setUp()

    def schema(self):
        status, _, schema = self.h.call('/openapi.json')
        self.assertEqual(status, 200)
        return schema

    def test_final_set_is_actual_mount_not_generic_catalog_count(self):
        schema = self.schema()
        routes = list(iter_route_contexts(self.h.module.app.routes))
        routes += list(iter_route_contexts(self.h.module.TEAM_AUTH.native_authorization.issuer_router().routes))
        mounted = set()
        for context in routes:
            route = _get_api_route_for_openapi(context)
            if route is not None and route.include_in_schema and route.path.startswith('/v1/'):
                mounted.update((method.lower(), route.path) for method in route.methods
                               if method.lower() in METHODS)
        iphone = mounted_iphone_operations(self.h.module.app)
        mounted |= iphone
        reviewer = mounted_reviewer_operations(self.h.module.app)
        mounted |= reviewer
        described = {(method, path) for path, methods in schema['paths'].items()
                     for method in methods if method in METHODS}
        self.assertEqual(described, mounted)
        coverage = schema['x-wegoh-documentation-coverage']
        self.assertEqual(coverage['operations'], len(mounted))
        self.assertEqual(coverage['genericCatalogOperations'], len(OPERATIONS))
        self.assertEqual(coverage['iphoneOperations'], len(iphone))
        self.assertEqual(coverage['reviewerOperations'], len(reviewer))
        wire = wire_contract()
        authored = {(item['method'].lower(), _path(item['path']))
                    for item in wire['operations'] + wire['phoneOperations']}
        self.assertEqual(coverage['authorizationOverlayOperations'], len(described & authored))
        self.assertEqual(check(schema)['operations'], len(mounted))
        before = copy.deepcopy(schema)
        self.assertEqual(finalize_documentation(schema), before, 'Finalization must be idempotent')
        self.assertEqual(schema, before, 'Finalization must preserve input')

    def test_missing_presence_counts_and_active_or_fake_terminal_are_rejected(self):
        original = self.schema()
        check(original)  # Every mutation starts from an actually valid current document.
        cases = ('field', 'path', 'marker', 'total', 'provenance', 'active-success',
                 'active-terminal', 'terminal-marker', 'terminal-deprecated',
                 'terminal-409', 'terminal-success')
        for case in cases:
            broken = copy.deepcopy(original)
            active = broken['paths']['/v1/playlists']['get']
            terminal = broken['paths']['/v1/devices/{device}/music-permission']['put']
            if case == 'field':
                broken['components']['schemas']['NativeAccessError']['properties']['authorizationVersion'].pop('description')
            elif case == 'path':
                broken['paths']['/v1/devices/{device}/functional-permissions']['get']['parameters'][0].pop('description')
            elif case == 'marker':
                broken['paths']['/v1/connections']['post'].pop('x-wegoh-documentation')
            elif case == 'total':
                broken['x-wegoh-documentation-coverage']['operations'] -= 1
            elif case == 'provenance':
                broken['x-wegoh-documentation-coverage']['genericCatalogOperations'] -= 1
            elif case == 'active-success':
                active['responses'] = {k: v for k, v in active['responses'].items() if not k.startswith('2')}
            elif case == 'active-terminal':
                active['responses'] = {'409': copy.deepcopy(terminal['responses']['409'])}
                active.update(deprecated=True, **{'x-wegoh-terminal-contract': 'functional-permissions-required'})
            elif case == 'terminal-marker':
                terminal.pop('x-wegoh-terminal-contract')
            elif case == 'terminal-deprecated':
                terminal['deprecated'] = False
            elif case == 'terminal-409':
                terminal['responses'].pop('409')
            elif case == 'terminal-success':
                terminal['responses']['200'] = copy.deepcopy(terminal['responses']['409'])
            with self.subTest(case=case), self.assertRaises(ValueError):
                check(broken)

    def test_authored_snapshot_fields_keep_actual_fixed_values_and_hash_scope(self):
        schema = self.schema()
        from api_doc_native_access import _kind
        wire = wire_contract()
        model = _kind('DisclosureSnapshot', wire)
        snapshot = disclosure_snapshot(['account:read', 'device:self:manage'])
        self.assertEqual(snapshot['disclosureVersion'], model['properties']['disclosureVersion']['const'])
        self.assertEqual(snapshot['bindingMaxSeconds'], model['properties']['bindingMaxSeconds']['const'])
        self.assertEqual(snapshot['keepSignedInDisclosure'], model['properties']['keepSignedInDisclosure']['const'])
        policies = model['properties']['scopeDisclosures']['items']['oneOf']
        for value in snapshot['scopeDisclosures']:
            matching = next(branch for branch in policies if branch['const'] == value)
            self.assertFalse(matching['additionalProperties'])
            self.assertEqual(set(matching['required']), set(value))
            self.assertTrue(all(prop.get('description') for prop in matching['properties'].values()))
        for name in ('NativeRoomMusicSnapshot', 'NativeRoomMusicConsent',
                     'NativeSocialOverview', 'NativeSocialHistoryPage'):
            key = 'permissions' if 'Music' in name else 'capabilities'
            self.assertTrue(schema['components']['schemas'][name]['properties'][key]['description'])

    def test_terminal_real_409_preserves_snapshot_and_auth_boundaries(self):
        owner = self.h.login()
        _, _, credential = self.h.pair(owner)
        path = '/v1/devices/' + credential['deviceId'] + '/music-permission'
        before = self.h.call(path, session=owner)
        self.assertEqual(before[0], 200, before[2])
        for method, body in (('PUT', dict(revision=0, enabled=True)), ('DELETE', None)):
            actual = self.h.call(path, body, method, session=owner)
            self.assertEqual(actual[0], 409, actual[2])
            self.assertEqual(actual[2], {'detail': 'Use current functional permissions'})
            self.assertEqual(self.h.call(path, session=owner)[2], before[2])
            self.assertEqual(self.h.call(path, body, method, session=owner, csrf=False)[0], 403)
        self.assertEqual(self.h.call(path, dict(revision=True, enabled=True), 'PUT', session=owner)[0], 400)
        other = self.h.login('bob')
        self.assertEqual(self.h.call(path, method='DELETE', session=other, who='bob')[0], 404)
        schema = self.schema()
        for method, endpoint in TERMINAL_OPERATIONS:
            op = schema['paths'][endpoint][method]
            self.assertTrue(op['deprecated'])
            self.assertFalse(op['x-wegoh-executable'])
            self.assertEqual(op['security'], [{'CloudflareAccess': [], 'TeamSession': [], 'CurrentSessionCSRF': []}])
            media = op['responses']['409']['content']['application/json']
            self.assertEqual(media['example'], {'detail': 'Use current functional permissions'})

    def test_shared_error_text_only_where_the_handler_can_answer_it(self):
        schema = self.schema()
        operations = {(method, path): operation for path, methods in schema['paths'].items()
                      for method, operation in methods.items() if method in METHODS}

        def response(method, path, code):
            return operations[(method, path)]['responses'].get(code)

        for (method, path), operation in operations.items():
            # GET handlers read no request body, so body timeout/size statuses cannot occur.
            if method == 'get':
                self.assertFalse({'408', '413'} & set(operation['responses']), (method, path))
            for code, value in operation['responses'].items():
                text = value.get('description', '')
                if '사진 수신' in text or 'Image upload timed out' in text:
                    self.assertEqual((method, path, code), ('post', '/v1/social/history/{item}/visits/{visit}/photos', '408'))
                if 'Command lease expired' in text or 'lease가 만료' in text:
                    self.assertIn(path, ('/v1/device/requests/{identifier}/claim', '/v1/device/requests/{identifier}/ack'))
        for path in ('/v1/social/trips/{trip}/vehicle-remotes/{device}/commands',
                     '/v1/iphone/trips/{trip}/vehicle-remotes/{device}/commands'):
            unsupported = response('post', path, '422')
            self.assertIn('VEHICLE_CONTROL_AREA_UNSUPPORTED', unsupported['description'])
            self.assertEqual(unsupported['content']['application/json']['schema'], {'$ref': '#/components/schemas/ApiError'})
            self.assertIsNone(response('post', path, '410'))
        # The login routes are mounted only when an iPhone host is configured.
        for method, path in (('get', '/iphone-login'), ('post', '/v1/iphone/browser/login/decision')):
            if (method, path) not in operations:
                continue
            self.assertIn('IPHONE_LOGIN_REQUIRED', response(method, path, '401')['description'])
            self.assertNotIn('IPHONE_SESSION', response(method, path, '401')['description'])
            self.assertIn('IPHONE_ROUTE_NOT_FOUND', response(method, path, '404')['description'])
        if ('post', '/v1/iphone/browser/login/decision') in operations:
            self.assertIn('Origin denied', response('post', '/v1/iphone/browser/login/decision', '403')['description'])
        deny = response('delete', '/v1/iphone/connections/{user_code}', '409')['description']
        self.assertIn('OPERATION_CONFLICT', deny)
        self.assertNotIn('CONSENT_CHANGED', deny)
        self.assertNotIn('VEHICLE_CONNECTION_LIMIT', deny)
        self.assertNotIn('409', operations[('get', '/v1/iphone/connections/{user_code}')]['responses'])
        clips = operations[('get', '/v1/iphone/trips/{trip}/voice-clips')]['description']
        self.assertNotIn('차단 발화자', clips)
        self.assertIn('VOICE_CLIP_UNAVAILABLE', clips)
        for path in ('/v1/operations/deployment', '/v1/operations/deployment-plan', '/v1/operations/releases'):
            self.assertIsNone(response('get', path, '409'))
        busy = response('post', '/v1/operations/deployments', '409')['content']['application/json']['schema']
        self.assertEqual(busy['properties']['error']['const'], 'BUSY')
        self.assertIn('MANAGEMENT_SERVICE_REQUIRED', response('get', '/v1/operations/deployment', '503')['description'])
        self.assertFalse(operations[('post', '/v1/social/trips/{id}/link')]['requestBody']['required'])
        for method in ('get', 'put'):
            self.assertIn('GRANT_EXPIRED', response(method, '/v1/devices/{device}/vehicle-profile', '410')['description'])
        self.assertIsNone(response('get', '/v1/devices/{device}/vehicle-profile', '409'))

    def test_public_host_login_routes_use_their_own_error_codes(self):
        from api_doc_iphone import OPS as IPHONE_OPS
        for key in (('get', '/iphone-login'), ('post', '/v1/iphone/browser/login/decision'),
                    ('delete', '/v1/iphone/browser/sessions')):
            errors = IPHONE_OPS[key]['errors']
            self.assertIn('IPHONE_LOGIN_REQUIRED', errors['401'])
            self.assertNotIn('IPHONE_SESSION', errors['401'])
            self.assertIn('IPHONE_ROUTE_NOT_FOUND', errors['404'])
        self.assertIn('Origin denied', IPHONE_OPS[('post', '/v1/iphone/browser/login/decision')]['errors']['403'])
