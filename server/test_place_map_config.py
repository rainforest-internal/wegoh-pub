"""Map public key and both server CSP variants; no network or credentials."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from place_map_config import public_map_config, studio_csp


class PlaceMapConfigTests(unittest.TestCase):
    def test_disabled_does_not_expand_existing_policy(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(public_map_config(),{'kakaoJsKey':None})
            for preview in (True,False):
                policy=studio_csp(preview=preview)
                self.assertNotIn('kakao.com',policy);self.assertNotIn('kakaocdn.net',policy)
                self.assertIn('https://tile.openstreetmap.org',policy)
            self.assertIn("media-src 'self' blob:",studio_csp())
            self.assertNotIn('media-src',studio_csp(preview=True))

    def test_enabled_has_only_required_origins_and_preserves_websocket(self):
        with patch.dict(os.environ,{'WEGOH_KAKAO_JS_KEY':'a'*32}):
            self.assertEqual(public_map_config(),{'kakaoJsKey':'a'*32})
            for preview in (True,False):
                policy=studio_csp("'self' wss://web.wegoh.invalid",preview=preview)
                directives={parts[0]:set(parts[1:]) for item in policy.split(';') if (parts:=item.split())}
                self.assertEqual(directives['script-src'],{"'self'",'https://dapi.kakao.com','https://t1.kakaocdn.net'})
                self.assertTrue({'https://mts.kakaocdn.net','https://t1.kakaocdn.net'}<=directives['img-src'])
                self.assertEqual(directives['connect-src'],{"'self'",'wss://web.wegoh.invalid','https://mts.kakaocdn.net'})
                self.assertEqual(directives['style-src'],{"'self'"})
                self.assertNotIn('unsafe-',policy);self.assertNotIn('*',policy)

    def test_invalid_key_cannot_inject_policy_and_rest_key_is_not_public(self):
        for key in ['',"a'*; unsafe-inline",'not-a-kakao-js-key']:
            with patch.dict(os.environ,{'WEGOH_KAKAO_JS_KEY':key,'WEGOH_KAKAO_REST_KEY_FILE':'/private/secret.key'}):
                self.assertEqual(public_map_config(),{'kakaoJsKey':None})
                self.assertNotIn('secret',str(public_map_config())+studio_csp())
                self.assertNotIn('kakao.com',studio_csp())

    def test_main_middleware_uses_conditional_policy(self):
        import asyncio
        from starlette.requests import Request
        from fastapi import Response
        import importlib,sys
        previous=sys.modules.pop('app',None)
        self.addCleanup(lambda:sys.modules.__setitem__('app',previous) if previous is not None else sys.modules.pop('app',None))
        with patch.dict(os.environ,{'WEGOH_AUTH_MODE':'local','WEGOH_API_KEY':'synthetic-operator-test-key-12345678'}):
            app=importlib.import_module('app')
        request=Request(dict(type='http',method='GET',scheme='http',path='/health/live',headers=[],query_string=b''))
        async def next_response(request):return Response('ok')
        for key in ('','a'*32):
            with patch.dict(os.environ,{'WEGOH_KAKAO_JS_KEY':key}):
                response=asyncio.run(app.security_headers(request,next_response))
                self.assertEqual(response.headers['Content-Security-Policy'],studio_csp())

    def test_team_session_reports_public_key(self):
        from team_auth import TeamAuth
        auth=TeamAuth('unused','synthetic-test-key'*3)
        auth.native_origin=''
        with patch.object(auth,'browser',return_value=None),patch.dict(os.environ,{'WEGOH_KAKAO_JS_KEY':'a'*32}):
            class Request: cookies={}
            self.assertEqual(auth.status(Request())['placeMap'],{'kakaoJsKey':'a'*32})

    def test_local_session_reports_public_key(self):
        from studio import create_router
        from starlette.requests import Request
        from fastapi import Response
        router=create_router('unused',Path('/tmp/unused'))
        route=next(route for route in router.routes if route.path=='/v1/auth/session' and 'GET' in route.methods)
        request=Request(dict(type='http',method='GET',scheme='http',path='/v1/auth/session',headers=[],query_string=b''))
        with patch.dict(os.environ,{'WEGOH_KAKAO_JS_KEY':'a'*32}):
            self.assertEqual(route.endpoint(request,Response())['placeMap'],{'kakaoJsKey':'a'*32})


if __name__=='__main__':unittest.main()
