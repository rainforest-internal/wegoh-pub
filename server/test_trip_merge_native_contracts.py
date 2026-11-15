import copy
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from api_doc_catalog import OPERATIONS
from api_doc_native_domains import FR, NATIVE, native_body
from api_doc_trip_merge import FEATURE_OPS
from native_functional_policy import WIRE, FunctionalError, authorize, is_functional_route
from native_room_music_authority import NativeRoomMusicAuthority
from native_room_voice_authority import NativeRoomVoiceAuthority
from team_trip_routes import TeamTripRoutes
from team_vehicle import TeamVehicle
from team_api_docs import build_schema

TRIP = '/v1/social/trips/{id}'
NATIVE_TRIP = '/v1/native/trips/{trip}'
EQUIVALENTS = {
    ('GET', TRIP + '/workspace'): '/v1/social/rooms/{room}',
    ('GET', TRIP + '/signals'): '/v1/social/rooms/{room}',
    ('GET', TRIP + '/places'): '/v1/social/rooms/{room}',
    ('POST', TRIP + '/signals'): '/v1/social/rooms/{room}/signals',
    ('POST', TRIP + '/signals/{signal}/vote'): '/v1/social/rooms/{room}/signals/{identifier}/vote',
    ('DELETE', TRIP + '/signals/{signal}/vote'): '/v1/social/rooms/{room}/signals/{identifier}/vote',
    ('GET', NATIVE_TRIP + '/vehicle-domain'): '/v1/device/vehicle-domain',
    ('GET', NATIVE_TRIP + '/device-reports'): '/v1/native/rooms/{room}/device-reports',
    ('POST', NATIVE_TRIP + '/reports/location'): '/v1/native/rooms/{room}/reports/location',
    ('POST', NATIVE_TRIP + '/reports/visits'): '/v1/native/rooms/{room}/reports/visits',
    ('GET', NATIVE_TRIP + '/music-permissions'): '/v1/native/rooms/{room}/music-permissions',
    ('GET', NATIVE_TRIP + '/voice-permissions'): '/v1/native/rooms/{room}/voice-permissions',
}
OWNER = ('GET', '/v1/devices/{device}/trips/{trip}/vehicle-domain')


def fixture():
    auth = SimpleNamespace(enabled=True, dsn='synthetic', trip_service=object(),
        trip_signal_contexts=object(), trip_places_service=object(),
        public_origin='https://web.example.invalid', native_origin='https://api.example.invalid',
        trip_feature_routes={key: True for key in FEATURE_OPS})
    auth.functional_access = SimpleNamespace(auth=auth, enabled=True, base=SimpleNamespace(enabled=True))
    return auth, SimpleNamespace(enabled=True)


class TripNativeContractTests(unittest.TestCase):
    def test_exact_paths_are_mounted_and_owner_snapshot_stays_browser_only(self):
        auth, rooms = fixture()
        routers = [TeamTripRoutes(auth).router(), TeamVehicle(auth, rooms).trip_router(),
            NativeRoomMusicAuthority(auth.functional_access, rooms).trip_router(),
            NativeRoomVoiceAuthority(auth.functional_access, rooms).trip_router()]
        app = FastAPI()
        for router in routers:
            app.include_router(router)
        mounted = {(method.upper(), path) for path, operations in app.openapi()['paths'].items()
                   for method in operations if method in ('get', 'post', 'put', 'patch', 'delete')}
        self.assertTrue(set(EQUIVALENTS) | {OWNER} <= mounted)
        rules = {(row['method'], row['path']): row for row in WIRE['nativeRoutes']}
        self.assertEqual(len(rules), len(WIRE['nativeRoutes']))
        self.assertNotIn(OWNER, rules)
        for method, template in EQUIVALENTS:
            with self.subTest(method=method, path=template):
                rule = rules[method, template]
                original = rules[method, EQUIVALENTS[method, template]]
                expected = (['rooms:read'], []) if template in (NATIVE_TRIP + '/device-reports', NATIVE_TRIP + '/voice-permissions') else (original['all'], original['any'])
                self.assertEqual((rule['all'], rule['any']), expected)
                path = re.sub(r'\{[^}]+\}', 'a' * 32, template)
                approved = frozenset(rule['all'] + rule['any'])
                self.assertTrue(authorize(method, path, approved))
                self.assertFalse(is_functional_route(method, path + '/extra'))
                self.assertFalse(is_functional_route(method, path.replace('a' * 32, 'A' * 32)))
                for missing in rule['all']:
                    with self.assertRaises(FunctionalError):
                        authorize(method, path, approved - {missing})
                if rule['any']:
                    with self.assertRaises(FunctionalError):
                        authorize(method, path, frozenset(rule['all']))

    def test_revision_schema_is_preserved_and_required_once(self):
        authored = dict(type='integer', minimum=5, description='Authored revision constraint.')
        for present, required in ((False, False), (True, False), (False, True), (True, True)):
            source = dict(type='object', properties={'functionalRevision': authored} if present else {},
                required=['functionalRevision'] if required else [])
            before = copy.deepcopy(source)
            result = native_body(source)
            self.assertEqual(result['properties']['functionalRevision'], authored if present else FR)
            self.assertEqual(result['required'], ['functionalRevision'])
            self.assertEqual(native_body(result), result)
            self.assertEqual(source, before)
        alternatives = dict(oneOf=[before, result])
        self.assertEqual(native_body(native_body(alternatives)), native_body(alternatives))

    def test_catalog_overlay_describes_native_writes_without_duplicate_requirements(self):
        auth, _ = fixture()
        all_ops = dict(OPERATIONS)
        for group in FEATURE_OPS.values():
            all_ops.update(group)
        app = FastAPI()
        def endpoint():
            return {}
        for method, path in all_ops:
            app.add_api_route(path, endpoint, methods=[method.upper()])
        with patch.dict(OPERATIONS):
            schema = build_schema(app, auth)
        models = schema['components']['schemas']
        for method, path in EQUIVALENTS:
            operation = schema['paths'][path][method.lower()]
            self.assertIn(NATIVE, operation['security'], path)
            if method != 'GET':
                body = operation['requestBody']['content']['application/json']['schema']
                native = body['oneOf'][1] if 'oneOf' in body else body
                model = models[native['$ref'].rsplit('/', 1)[1]]
                self.assertEqual(model['required'].count('functionalRevision'), 1, path)
        owner = schema['paths'][OWNER[1]]['get']
        self.assertNotIn(NATIVE, owner['security'])
        for model in models.values():
            def unique_required(value):
                if isinstance(value, dict):
                    required = value.get('required', [])
                    self.assertEqual(len(required), len(set(required)))
                    for child in value.values():
                        unique_required(child)
                elif isinstance(value, list):
                    for child in value:
                        unique_required(child)
            unique_required(model)
