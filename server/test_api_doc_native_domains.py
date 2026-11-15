"""Mounted first-four OAS contracts and their real Native boundary; synthetic private PG."""
import copy
import unittest
from fastapi.openapi.utils import _get_api_route_for_openapi
from fastapi.routing import iter_route_contexts
from api_doc_native_domains import selected, NATIVE
from native_functional_policy import WIRE
from api_doc_recommendation_learning import BODY as LEARNING_BODY
from api_doc_recommendations import MODELS as RULE_MODELS
from team_api_docs import build_schema
import test_team_auth as fixture
import test_native_functional_business as business_fixture

EXPECTED_ROUTES = {
    ('GET', '/v1/social/trips/{trip}/voice-clips'),
    ('POST', '/v1/social/trips/{trip}/voice-clips'),
    ('GET', '/v1/social/trips/{trip}/voice-clips/{identifier}'),
    ('GET', '/v1/social/trips/{room}/voice/filters'),
    ('GET', '/v1/native/trips/{id}/driving-versus'),
    ('GET', '/v1/native/trips/{id}/driving-score'),
    ('PUT', '/v1/native/trips/{id}/cars/{carId}/driving-score'),
    ('POST', '/v1/native/trips/{id}/cars/{carId}/route-arrivals'),
    ('PUT', '/v1/native/trips/{id}/cars/{carId}/courses/{packId}/driving-score'),
    ('GET', '/v1/social/trips'),
    ('GET', '/v1/social/trips/{id}'),
    ('POST', '/v1/social/trips/{id}/respond'),
    ('GET', '/v1/device/vehicle-domain'),
    ('GET', '/v1/native/rooms/{room}/device-reports'),
    ('POST', '/v1/native/rooms/{room}/reports/location'),
    ('POST', '/v1/native/rooms/{room}/reports/visits'),
    ('GET', '/v1/device/command-inbox'),
    ('POST', '/v1/device/requests/{identifier}/claim'),
    ('POST', '/v1/device/requests/{identifier}/ack'),
    ('GET', '/v1/social/rooms/{room}/device-command-access'),
    ('GET', '/v1/social/rooms/{room}/device-requests'),
    ('POST', '/v1/social/rooms/{room}/device-requests'),
    ('DELETE', '/v1/social/rooms/{room}/device-requests/{identifier}'),
    ('GET', '/v1/native/rooms/{room}/missions'),
    ('GET', '/v1/native/trips/{room}/missions'),
    ('POST', '/v1/native/rooms/{room}/missions/{mission}/progress'),
    ('GET', '/v1/recommendations/settings'),
    ('POST', '/v1/recommendations/query'),
    ('POST', '/v1/recommendations/feedback'),
    ('GET', '/v1/social/cautions'),
    ('GET', '/v1/social/cautions/{item}'),
    ('GET', '/v1/social/trips/{id}/workspace'),
    ('GET', '/v1/social/trips/{trip}/music/saved-playlists'),
    ('POST', '/v1/social/trips/{trip}/music/saved-playlists'),
    ('PATCH', '/v1/social/trips/{trip}/music/saved-playlists/{item}/position'),
    ('PUT', '/v1/social/trips/{trip}/music/now-playing'),
    ('GET', '/v1/social/trips/{id}/signals'),
    ('GET', '/v1/social/trips/{id}/places'),
    ('POST', '/v1/social/trips/{id}/signals'),
    ('POST', '/v1/social/trips/{id}/signals/{signal}/vote'),
    ('POST', '/v1/social/trips/{id}/signals/{signal}/finish'),
    ('DELETE', '/v1/social/trips/{id}/signals/{signal}/vote'),
    ('GET', '/v1/native/trips/{trip}/vehicle-domain'),
    ('GET', '/v1/native/trips/{trip}/device-reports'),
    ('POST', '/v1/native/trips/{trip}/reports/location'),
    ('POST', '/v1/native/trips/{trip}/reports/visits'),
    ('GET', '/v1/native/trips/{id}'),
    ('GET', '/v1/native/trips/{id}/friends'),
    ('GET', '/v1/native/trips/{id}/location-sharing'),
    ('PATCH', '/v1/native/trips/{id}/location-sharing'),
    ('POST', '/v1/native/trips/{id}/signals/candidates'),
    ('GET', '/v1/native/trips/{id}/cars/{carId}/places'),
    ('PATCH', '/v1/native/trips/{id}'),
    ('POST', '/v1/native/trips/{id}/start'),
    ('POST', '/v1/native/trips/{id}/finish'),
    ('POST', '/v1/native/trips/{id}/members'),
    ('DELETE', '/v1/native/trips/{id}/members/{accountId}'),
    ('POST', '/v1/native/trips/{id}/link'),
    ('DELETE', '/v1/native/trips/{id}/link'),
    ('POST', '/v1/native/trips/{id}/cars'),
    ('PATCH', '/v1/native/trips/{id}/cars/{carId}'),
    ('DELETE', '/v1/native/trips/{id}/cars/{carId}'),
    ('PUT', '/v1/native/trips/{id}/cars/{carId}/ride'),
    ('DELETE', '/v1/native/trips/{id}/ride'),
    ('POST', '/v1/native/trips/{id}/courses'),
    ('DELETE', '/v1/native/trips/{id}/courses/{packId}'),
    ('POST', '/v1/native/trips/{id}/cars/{carId}/places'),
    ('DELETE', '/v1/native/trips/{id}/cars/{carId}/places/{placeId}'),
    ('PUT', '/v1/native/trips/{id}/cars/{carId}/route-order'),
    ('PUT', '/v1/native/trips/{id}/cars/{carId}/route-progress'),
    ('POST', '/v1/native/trips/{id}/cars/{carId}/ride-invites'),
    ('DELETE', '/v1/native/trips/{id}/cars/{carId}/ride-invites/{inviteId}'),
    ('DELETE', '/v1/native/trips/{id}/cars/{carId}/riders/{accountId}'),
    ('POST', '/v1/native/trips/{id}/cars/{carId}/courses/{packId}/complete'),
}

class NativeDomainDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')
    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()
    def schema(self):
        return build_schema(fixture.TeamTests.module.app, fixture.TeamTests.module.TEAM_AUTH)
    def test_mounted_four_domain_routes_have_exact_authority_and_no_owner_write_expansion(self):
        schema = self.schema()
        rules = [row for row in WIRE['nativeRoutes'] if selected(row)]
        self.assertEqual(len(rules), len(EXPECTED_ROUTES))
        self.assertEqual({(row['method'], row['path']) for row in rules}, EXPECTED_ROUTES)
        for rule in rules:
            method, path = rule['method'].lower(), rule['path']
            operation = schema['paths'][path][method]
            self.assertEqual(operation['x-wegoh-native-functional-purposes'], dict(all=rule['all'], any=rule['any']))
            self.assertIn(NATIVE, operation['security'])
            # Voice clips are mounted on /v1/social but reject browser sessions (team_voice_clips._actor).
            native_only = '/voice-clips' in path or path.startswith(('/v1/device/', '/v1/native/'))
            if native_only:
                self.assertEqual(operation['security'], [NATIVE])
                self.assertFalse(operation['x-wegoh-executable'])
            else:
                expected = dict(CloudflareAccess=[], TeamSession=[])
                if method != 'get':
                    expected['CurrentSessionCSRF'] = []
                self.assertEqual(operation['security'][0], expected)
            self.assertIn('같은 업무 transaction', operation['description'])
        for path, method in [('/v1/recommendations/learning','put'),('/v1/recommendations/settings','put'),('/v1/social/cautions','post')]:
            self.assertNotIn(NATIVE, schema['paths'][path][method]['security'])
        self.assertEqual(RULE_MODELS['RecommendationSettings']['required'], list(RULE_MODELS['RecommendationSettings']['properties']))
        self.assertNotIn('learning', RULE_MODELS['RecommendationSettings']['properties'])
    def test_every_wire_native_route_names_its_mounted_route_template(self):
        # The policy matches request paths, so a stale placeholder name still authorizes; the
        # published wire must nevertheless name the exact template the router serves.
        routes = (_get_api_route_for_openapi(context)
                  for context in iter_route_contexts(fixture.TeamTests.module.app.routes))
        mounted = {(method, route.path) for route in routes if route is not None for method in route.methods}
        missing = [(row['method'], row['path']) for row in WIRE['nativeRoutes']
                   if (row['method'], row['path']) not in mounted]
        self.assertEqual(missing, [])
    def test_native_revision_bodies_and_learning_projection_preserve_browser_variants(self):
        schema = self.schema(); models = schema['components']['schemas']
        operation = schema['paths']['/v1/social/trips/{trip}/music/saved-playlists']['post']
        browser, native = operation['requestBody']['content']['application/json']['schema']['oneOf']
        self.assertEqual(set(browser['required']), {'playlistId', 'playlistRevision', 'trackId', 'rightsConfirmed', 'reviewConsent'})
        self.assertEqual(set(models[native['$ref'].rsplit('/',1)[1]]['required']), set(browser['required']) | {'functionalRevision'})
        for path in ['/v1/recommendations/query','/v1/recommendations/feedback']:
            content = schema['paths'][path]['post']['requestBody']['content']['application/json']
            browser, native = content['schema']['oneOf']
            self.assertEqual(browser, LEARNING_BODY[('post',path)])
            native = models[native['$ref'].rsplit('/',1)[1]]
            for variant in native['oneOf']:
                self.assertIn('functionalRevision', variant['required'])
                self.assertFalse(variant['additionalProperties'])
                self.assertEqual(variant['properties']['functionalRevision']['minimum'],1)
                if path.endswith('/query'):
                    anchors = variant['properties']['anchor']['oneOf']
                    self.assertEqual([x['properties']['kind']['const'] for x in anchors], ['selected-place','device-location'])
        for path in ['/v1/device/requests/{identifier}/claim','/v1/device/requests/{identifier}/ack','/v1/native/rooms/{room}/missions/{mission}/progress']:
            native = models[schema['paths'][path]['post']['requestBody']['content']['application/json']['schema']['$ref'].rsplit('/',1)[1]]
            self.assertIn('functionalRevision',native['required']); self.assertFalse(native['additionalProperties'])
        settings = models['NativeRecommendationSettings']
        self.assertEqual(set(settings['required']),set(RULE_MODELS['RecommendationSettings']['required'])|{'learning'})
        self.assertEqual(set(settings['properties']['learning']['required']), {'enabled','learningRevision','settingsRevision','modelVersion','status','eligibleSamples'})
        self.assertFalse(settings['additionalProperties']); self.assertFalse(settings['properties']['learning']['additionalProperties'])
        self.assertEqual(models['NativeRecommendationResult']['properties']['anchor']['properties']['kind']['enum'], ['selected-place','device-reported'])

    def test_only_three_trip_routes_document_native_and_revision_body(self):
        from api_doc_trips import BODY, NATIVE_TRIPS, OPS
        schema = self.schema()
        for method, path in OPS:
            operation = schema['paths'][path][method]
            with self.subTest(method=method, path=path):
                self.assertEqual(NATIVE in operation['security'], (method, path) in NATIVE_TRIPS)
                if (method, path) in NATIVE_TRIPS:
                    self.assertIn('owner/invite 권한자에게만 link의 active·expiresAt', operation['description'])
                    self.assertIn('/v1/events에서 wegoh.events.v1', operation['description'])
                    self.assertEqual(operation['x-wegoh-native-functional-purposes'],
                        dict(all=['rooms:read', 'rooms:interact'] if method == 'post' else ['rooms:read'], any=[]))
        key = ('post', '/v1/social/trips/{id}/respond')
        operation = schema['paths'][key[1]][key[0]]
        browser, native = operation['requestBody']['content']['application/json']['schema']['oneOf']
        self.assertEqual(browser, BODY[key])
        native = schema['components']['schemas'][native['$ref'].rsplit('/', 1)[1]]
        self.assertEqual(set(native['required']), {'accept', 'functionalRevision'})
        self.assertFalse(native['additionalProperties'])
        self.assertNotIn('functionalRevision', BODY[key]['properties'])
        paths = schema['paths']
        for request in (browser, native, paths['/v1/social/trips']['post']['requestBody']['content']['application/json']['schema'],
                        paths['/v1/social/trip-links/join']['post']['requestBody']['content']['application/json']['schema']):
            self.assertNotIn('locationConsent', request['required'])
            self.assertEqual(request['properties']['locationConsent']['type'], 'boolean')
            self.assertIs(request['properties']['locationConsent']['default'], False)
        location = paths['/v1/social/trips/{id}/location-sharing']
        self.assertEqual(location['patch']['requestBody']['content']['application/json']['schema']['required'], ['locationConsent'])
        result = location['get']['responses']['200']['content']['application/json']['schema']
        self.assertEqual(set(result['required']), {'locationConsent', 'locationShareId', 'revision'})
    def test_actual_caution_native_query_error_and_learning_keys_match_conditional_docs(self):
        factory = business_fixture.FunctionalBusinessTests('test_native_friend_request_respond_scope_withdrawal_and_original_authority')
        factory.setUp(); h = factory.h; owner = h.login(); credential = factory.connect(owner)
        factory.approve(owner,credential,['cautions:read','recommendations:use'])
        schema = self.schema(); operation = schema['paths']['/v1/social/cautions']['get']
        parameters = {x['name']:x for x in operation['parameters']}
        self.assertIn('Native',parameters['cursor']['description'])
        self.assertTrue(parameters['eventId']['x-wegoh-browser-only'])
        documented = operation['responses']['400']['content']['application/json']['examples']['nativeInvalidQuery']['value']
        for query in ['?cursor=broken','?eventId='+'a'*32,'?cursor=a&cursor=b','?access_token=synthetic']:
            result = factory.native(credential,'/v1/social/cautions'+query)
            print('QA_NATIVE_CAUTION_QUERY',query.split('=')[0],result[0],sorted(result[2]),flush=True)
            self.assertEqual(result[0],400); self.assertEqual(result[2],documented)
        actual = factory.native(credential,'/v1/recommendations/settings')
        self.assertEqual(actual[0],200)
        model = schema['components']['schemas']['NativeRecommendationSettings']
        self.assertEqual(set(actual[2]),set(model['required']))
        self.assertEqual(set(actual[2]['learning']),set(model['properties']['learning']['required']))
        self.assertEqual(actual[2]['learning']['settingsRevision'],actual[2]['revision'])

if __name__ == '__main__':
    unittest.main()
