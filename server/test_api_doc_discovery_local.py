"""Actual isolated Browser OpenAPI plus local-road response contract projection.

Shared-writer integration is applied in memory while the parent merges the
provided narrow patch. No shared catalog file or operating configuration changes.
"""
from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch
import test_team_auth as fixture
import test_discovery_local as local_fixture
import api_doc_discovery_local as local_docs
from discovery_local import prepare

class DiscoveryDocsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
    def test_actual_browser_oas_closed_modes_current_response_unknown_and_separate_room_flow(self):
        import team_api_docs as docs
        import api_doc_catalog as catalog
        from check_api_documentation import check
        # Exact narrow integration that the shared writer will apply.
        with ExitStack() as stack:
            stack.enter_context(patch.dict(docs.BODY,local_docs.BODY))
            stack.enter_context(patch.dict(catalog.OPERATIONS,local_docs.OPS))
            stack.enter_context(patch.dict(catalog.DISCOVERY_MODELS,local_docs.MODELS))
            status,_,schema=self.h.call('/openapi.json')
        self.assertEqual(status,200,schema)
        # The isolated ebaa base includes unrelated unfinished Native authoring.
        # Inspect only these two operations; preserve the original broad failure
        # in the first smoke log rather than editing unrelated Native contracts.
        selected=deepcopy(schema)
        selected['paths']={path:deepcopy(schema['paths'][path]) for _,path in (local_docs.REST,local_docs.PLACES)}
        selected['x-wegoh-documentation-coverage']={'operations':2,'genericCatalogOperations':2,'authorizationOverlayOperations':0,'iphoneOperations':0}
        check(selected)
        for method,path in (local_docs.REST,local_docs.PLACES):
            operation=schema['paths'][path][method]
            self.assertFalse(operation['x-wegoh-native-access'])
            self.assertEqual(operation['security'],[{'CloudflareAccess':[],'TeamSession':[],'CurrentSessionCSRF':[]}])
            self.assertIn('504',operation['responses'])
            self.assertIn('502',operation['responses'])
            self.assertIn('oneOf',operation['responses']['503']['content']['application/json']['schema'])
        rest=schema['paths'][local_docs.REST[1]]['post']['requestBody']['content']['application/json']['schema']
        self.assertEqual(len(rest['oneOf']),2)
        self.assertEqual(set(rest['oneOf'][1]['required']),{'anchor','roadSearch'})
        self.assertFalse(rest['oneOf'][1]['additionalProperties'])
        self.assertNotIn('radiusMeters',rest['oneOf'][1]['properties'])
        places=schema['paths'][local_docs.PLACES[1]]['post']
        example=places['requestBody']['content']['application/json']['example']
        prepare(example,'places')
        self.assertEqual(set(places['requestBody']['content']['application/json']['schema']['required']),{'anchor','bounds','category'})
        # Current runtime result and the published DTO agree on every object key.
        factory=local_fixture.LocalDiscoveryTests('test_all_candidates_before_limit_distance_duration_and_unreachable');factory.setUp()
        result=factory.service.query(local_fixture.query(limit=20),'places',now=local_fixture.NOW)
        models=schema['components']['schemas']
        self.assertEqual(set(result),set(models['DiscoveryRoadResult']['required']))
        self.assertEqual(set(result['items'][0]),set(models['DiscoveryRoadCandidate']['required']))
        self.assertEqual(set(result['source']),set(models['DiscoveryRoadSource']['required']))
        self.assertEqual(set(result['graph']),set(models['DiscoveryRoadGraph']['required']))
        self.assertEqual(result['items'][-1]['road'],dict(reachable=False,distanceMeters=None,estimatedDurationSeconds=None))
        self.assertEqual(result['unknown'],{key:row['const'] for key,row in models['DiscoveryRoadResult']['properties']['unknown']['properties'].items()})
        self.assertIn('provenance',places['description'])
        self.assertIn('201',places['description'])
        # Search documentation grants no room write or implicit query permission.
        self.assertEqual(places['requestBody']['content']['application/json']['schema']['additionalProperties'],False)

if __name__=='__main__':unittest.main()
