"""A mounted retired public generation must fail, never disappear from OAS."""
import unittest
from fastapi import FastAPI,APIRouter
from types import SimpleNamespace
from team_api_docs import build_schema

class PublicPrefixTests(unittest.TestCase):
 def test_mounted_retired_generation_fails_for_direct_and_lazy_included_routes(self):
  for path,nested in [('/v2/connections',False),('/v2/not-an-authorization-alias',True)]:
   with self.subTest(path=path,nested=nested):
    app=FastAPI();router=APIRouter()if nested else app
    router.add_api_route(path,lambda:{},methods=['GET'])
    if nested:app.include_router(router)
    with self.assertRaisesRegex(RuntimeError,'Retired public v2 route remains registered'):build_schema(app,SimpleNamespace(enabled=False))
