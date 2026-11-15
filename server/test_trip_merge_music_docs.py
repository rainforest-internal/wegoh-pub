import copy
from types import SimpleNamespace
import unittest

from api_doc_catalog import OPERATIONS, apply_documentation
from api_doc_native_room_music import apply_room_music_documentation
from api_doc_native_room_voice import apply_room_voice_documentation
from team_api_docs import BODY as CORE_BODY
from api_doc_room_music import BODY as MUSIC_BODY
from api_doc_voice import BODY as VOICE_BODY
from api_doc_native_room_music import BODY as MUSIC_ACCESS_BODY
from api_doc_native_room_voice import BODY as VOICE_ACCESS_BODY
BODY={**CORE_BODY,**MUSIC_BODY,**VOICE_BODY,**MUSIC_ACCESS_BODY,**VOICE_ACCESS_BODY}


class TripMediaDocumentationTests(unittest.TestCase):
    def test_new_trip_contracts_and_legacy_exact_models_stay_separate(self):
        schema=dict(paths={},info={},components=dict(schemas={},securitySchemes={}),**{'x-wegoh-voice':{}})
        for method,path in OPERATIONS:
            operation=dict(responses={},parameters=[])
            if (method,path) in BODY:
                operation['requestBody']=dict(content={'application/json':dict(schema=copy.deepcopy(BODY[(method,path)]))})
            schema['paths'].setdefault(path,{})[method]=operation
        schema=apply_documentation(schema,BODY)
        auth=SimpleNamespace(public_origin='https://web.example.invalid',native_origin='https://api.example.invalid',functional_access=SimpleNamespace(enabled=True,base=SimpleNamespace(enabled=True)))
        schema=apply_room_voice_documentation(apply_room_music_documentation(schema,auth),auth)
        def described_fields(node, seen=()):
            if not isinstance(node, dict):
                return
            if '$ref' in node:
                reference=node['$ref']
                if reference in seen:
                    return
                described_fields(schema['components']['schemas'][reference.rsplit('/',1)[1]],seen+(reference,))
                return
            for name,field in node.get('properties',{}).items():
                if name in ('tripId','contractVersion','kind','provider','url','title','rightsConfirmed','functionalRevision','roomMusicRevision'):
                    self.assertTrue(field.get('description'), 'Missing trip music field description: '+name)
                described_fields(field,seen)
            for key in ('oneOf','anyOf','allOf'):
                for branch in node.get(key,[]):
                    described_fields(branch,seen)
            described_fields(node.get('items'),seen)
        for path,operations in schema['paths'].items():
            if not path.startswith('/v1/social/trips/{trip}/music'):
                continue
            for operation in operations.values():
                for content in operation.get('requestBody',{}).get('content',{}).values():
                    described_fields(content['schema'])
                for response in operation['responses'].values():
                    for content in response.get('content',{}).values():
                        described_fields(content['schema'])
        for kind in ('Music','Voice'):
            for model in ('Snapshot','Consent'):
                old=schema['components']['schemas']['NativeRoom'+kind+model]
                trip=schema['components']['schemas']['NativeTrip'+kind+model]
                self.assertNotIn('tripId',old['properties'])
                self.assertNotIn('contractVersion',old['properties'])
                self.assertNotIn('roomId',trip['properties'])
                self.assertIn('tripId',trip['required'])
                self.assertEqual(trip['properties']['contractVersion']['const'],1)
        path='/v1/social/trips/{trip}/music'
        body=schema['paths'][path]['put']['requestBody']['content']['application/json']['schema']
        self.assertEqual(len(body['oneOf']),2)
        self.assertEqual(body['oneOf'][1]['properties']['kind']['const'],'playlist-link')
        self.assertEqual(schema['x-wegoh-trip-voice']['path'],'/v1/social/trips/{trip}/voice')
        self.assertEqual(schema['x-wegoh-trip-voice']['native']['path'],'/v1/social/trips/{trip}/voice')


if __name__=='__main__':unittest.main()
