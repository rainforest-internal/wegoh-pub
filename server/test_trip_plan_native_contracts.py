import unittest
from unittest.mock import patch

from fastapi import FastAPI
from api_doc_catalog import OPERATIONS
from api_doc_trip_merge import FEATURE_OPS
from api_doc_trip_plan import NATIVE
from native_functional_policy import WIRE
from team_api_docs import build_schema
from team_trip_routes import TeamTripRoutes
from team_trips import TeamTrips
from test_trip_merge_native_contracts import fixture


class TripPlanNativeContractTests(unittest.TestCase):
    def test_effective_routes_have_authored_fields_security_and_revision_once(self):
        auth, _ = fixture()
        auth.trip_service = TeamTrips(auth)
        app = FastAPI()
        routers = (auth.trip_service.router(), TeamTripRoutes(auth).router())
        for router in routers:
            app.include_router(router)
        mounted = {(method.lower(), route.path) for router in routers for route in router.routes for method in route.methods}
        all_ops = dict(OPERATIONS)
        for group in FEATURE_OPS.values():
            all_ops.update(group)
        def endpoint():
            return {}
        for method,path in all_ops:
            if (method,path) not in mounted:
                app.add_api_route(path,endpoint,methods=[method.upper()])
        with patch.dict(OPERATIONS):
            schema=build_schema(app,auth)
        from scripts.check_api_documentation import check
        check(schema)
        models=schema['components']['schemas']
        rules={(row['method'].lower(),row['path']):row for row in WIRE['nativeRoutes']}
        for method,path in NATIVE:
            op=schema['paths'][path][method]
            self.assertEqual(op['security'],[{'NativeMTLS':[],'DeviceBearer':[]}])
            self.assertEqual(op['x-wegoh-native-functional-purposes'],dict(all=rules[method,path]['all'],any=[]))
            if method!='get':
                content=op['requestBody']['content']['application/json']
                body=models[content['schema']['$ref'].split('/')[-1]]
                self.assertEqual(body['required'].count('functionalRevision'),1)
                self.assertFalse(body['additionalProperties'])
                self.assertEqual(content['example']['functionalRevision'],1)
        self.assertNotIn('/v1/native/trips/{id}/cars/{carId}/places/{placeId}/select',schema['paths'])
        self.assertNotIn('/v1/native/trips/{id}/cars/{carId}/ride-invites/{inviteId}/respond',schema['paths'])


if __name__ == '__main__':
    unittest.main()
