"""Synthetic directions, shared transport limits and browser/iPhone route contracts."""
import asyncio
import json
import logging
from pathlib import Path
from threading import Event
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from route_preview import (RoutePreview, RoutePreviewError, KakaoRoutePreview, MockRoutePreview,
                           route_input, route_transport, MAX_BYTES, MAX_PATH_POINTS, MAX_CONCURRENT_ROUTES)

KEY = 'synthetic-route-key-1234567890'
POINTS = [dict(lat=37.5, lng=127), dict(lat=37.6, lng=127.1), dict(lat=37.7, lng=127.2)]
ORIGIN = dict(lat=37.4, lng=126.9)


def response(vertices=None, code=0):
    return dict(routes=[dict(result_code=code, summary=dict(distance=12345, duration=789),
        sections=[dict(roads=[dict(vertexes=vertices if vertices is not None else [127,37.5,127.1,37.6])])])])


class ProviderTests(unittest.TestCase):
    def error(self, action, code, status):
        with self.assertRaises(RoutePreviewError) as caught:
            action()
        self.assertEqual((caught.exception.code, caught.exception.status), (code, status))
        self.assertNotIn(KEY, str(caught.exception))

    def test_input_exact_fields_counts_finite_numeric_korea(self):
        self.assertEqual(route_input(dict(origin=ORIGIN, points=POINTS)), (ORIGIN, POINTS))
        self.assertEqual(route_input(dict(origin=None, points=POINTS))[0], None)
        for value in [None, [], {}, dict(points=[]), dict(points=POINTS*2), dict(points=POINTS, url='x'),
                      dict(points=POINTS, origin={}), dict(points=[dict(lat=True,lng=127)]),
                      dict(points=[dict(lat='37',lng=127)]), dict(points=[dict(lat=float('nan'),lng=127)]),
                      dict(points=[dict(lat=31,lng=127)]), dict(points=[dict(lat=37,lng=133)]),
                      dict(points=[dict(lat=37,lng=127,name='x')])]:
            with self.subTest(value=value):
                self.error(lambda: route_input(value), 'ROUTE_INPUT_INVALID', 400)

    def test_huge_json_integers_are_rejected_as_input(self):
        huge = int('1' * 310)
        for value in [dict(points=[dict(lat=huge, lng=127)]), dict(points=[dict(lat=37, lng=-huge)]),
                      dict(origin=dict(lat=-huge, lng=127), points=POINTS), dict(origin=dict(lat=37, lng=huge), points=POINTS)]:
            with self.subTest(value=str(value)[:40]):
                self.error(lambda: route_input(json.loads(json.dumps(value))), 'ROUTE_INPUT_INVALID', 400)

    def test_fixed_endpoint_origin_waypoints_and_no_cache(self):
        calls=[]
        def transport(url, headers, timeout, maximum):
            calls.append((url, headers, timeout, maximum))
            return json.dumps(response()).encode()
        provider=KakaoRoutePreview(KEY, transport)
        self.assertEqual(provider.preview(ORIGIN,POINTS)['path'], [[37.5,127],[37.6,127.1]])
        params=parse_qs(urlsplit(calls[-1][0]).query)
        self.assertEqual(urlsplit(calls[-1][0]).netloc, 'apis-navi.kakaomobility.com')
        self.assertEqual(urlsplit(calls[-1][0]).path, '/v1/directions')
        self.assertEqual(params, dict(origin=['126.9,37.4'], destination=['127.2,37.7'],
                                     waypoints=['127,37.5|127.1,37.6'], summary=['false']))
        provider.preview(None,POINTS)
        self.assertEqual(parse_qs(urlsplit(calls[-1][0]).query)['waypoints'], ['127.1,37.6'])
        provider.preview(None,POINTS[:2])
        self.assertNotIn('waypoints', parse_qs(urlsplit(calls[-1][0]).query))
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[0][1], {'Authorization':'KakaoAK '+KEY})
        self.assertEqual(calls[0][3], MAX_BYTES)
        self.assertTrue(0<calls[0][2]<=4)

    def test_sections_deduplicate_axis_order_and_cap_preserves_endpoints(self):
        raw=response()
        raw['routes'][0]['sections'].append(dict(roads=[dict(vertexes=[127.1,37.6,127.2,37.7])]))
        provider=KakaoRoutePreview(KEY,lambda *args:json.dumps(raw).encode())
        self.assertEqual(provider.preview(None,POINTS)['path'], [[37.5,127],[37.6,127.1],[37.7,127.2]])
        vertices=[number for i in range(5000) for number in (127+i/10000,37+i/10000)]
        provider=KakaoRoutePreview(KEY,lambda *args:json.dumps(response(vertices)).encode())
        path=provider.preview(None,POINTS)['path']
        self.assertEqual(len(path),MAX_PATH_POINTS)
        self.assertEqual(path[0],[37,127]);self.assertEqual(path[-1],[37.4999,127.4999])

    def test_result_codes_malformed_oversize_and_key_never_escape(self):
        for code in (101,104,999):
            provider=KakaoRoutePreview(KEY,lambda *args:json.dumps(response(code=code)).encode())
            self.error(lambda:provider.preview(None,POINTS),'ROUTE_NOT_FOUND',422)
        bad=[b'not-json',json.dumps(response([127])).encode(),json.dumps(response([])).encode(),
             json.dumps(response([127,True,127,37])).encode(),KEY.encode(),b'x'*(MAX_BYTES+1)]
        for raw in bad:
            provider=KakaoRoutePreview(KEY,lambda *args:raw)
            self.error(lambda:provider.preview(None,POINTS),'ROUTE_PROVIDER_UNAVAILABLE',502)
        class Broken:
            def preview(self,*args):raise ValueError(KEY)
        with self.assertLogs('route_preview',level=logging.INFO) as logs:
            self.error(lambda:RoutePreview(Broken()).preview('a',dict(points=POINTS)), 'ROUTE_PROVIDER_UNAVAILABLE',502)
        self.assertNotIn(KEY,' '.join(logs.output))

    def test_deadline_covers_transport_and_decoding(self):
        now=[0]
        def transport(*args):now[0]=5;return json.dumps(response()).encode()
        with self.assertRaises(TimeoutError):KakaoRoutePreview(KEY,transport,clock=lambda:now[0]).preview(None,POINTS)

    def test_single_point_without_origin_does_not_call_provider(self):
        self.assertEqual(RoutePreview().preview('a',dict(points=POINTS[:1])),
                         dict(distanceMeters=0,durationSeconds=0,path=[]))
        self.error(lambda:RoutePreview().preview('a',dict(points=POINTS)), 'ROUTE_UNAVAILABLE',503)

    def test_account_rate_limit_and_rolling_window(self):
        now=[0];service=RoutePreview(MockRoutePreview(),clock=lambda:now[0])
        for _ in range(20):service.preview('a',dict(points=POINTS))
        self.error(lambda:service.preview('a',dict(points=POINTS)),'ROUTE_RATE_LIMITED',429)
        service.preview('b',dict(points=POINTS))
        now[0]=60;service.preview('a',dict(points=POINTS))

    def test_busy_timeout_keeps_slots_until_workers_finish(self):
        entered=[];release=Event()
        class Slow:
            def preview(self,*args):
                from threading import current_thread
                entered.append(current_thread());release.wait();return MockRoutePreview().preview(None,POINTS)
        service=RoutePreview(Slow(),timeout=.005,limit=100)
        try:
            for _ in range(MAX_CONCURRENT_ROUTES):
                self.error(lambda:service.preview('a',dict(points=POINTS)),'ROUTE_TIMEOUT',504)
            before=time.monotonic()
            self.error(lambda:service.preview('b',dict(points=POINTS)),'ROUTE_BUSY',503)
            self.assertLess(time.monotonic()-before,.03)
            self.assertEqual(len(entered),MAX_CONCURRENT_ROUTES)
        finally:
            release.set()
            for worker in entered:worker.join(1)
        service.provider=MockRoutePreview();service.preview('a',dict(points=POINTS))

    def test_thread_start_failure_releases_slot(self):
        service=RoutePreview(MockRoutePreview())
        with patch('web_provider.Thread.start',side_effect=RuntimeError(KEY)):
            self.error(lambda:service.preview('a',dict(points=POINTS)),'ROUTE_BUSY',503)
        service.preview('a',dict(points=POINTS))

    def test_shared_transport_rejects_redirect_size_and_maps_failure(self):
        from unittest.mock import MagicMock
        for status,raw in [(302,b''),(401,b''),(200,b'x'*20)]:
            connection=MagicMock();reply=connection.getresponse.return_value.__enter__.return_value
            reply.status=status;reply.read1.return_value=raw
            with patch('web_provider.HTTPSConnection',return_value=connection):
                # Explicit factory verifies the common implementation also used by route_transport.
                from web_provider import bounded_get
                self.error(lambda:bounded_get('https://apis-navi.kakaomobility.com/v1/directions',{},1,10,
                    connection_factory=lambda *a,**k:connection,
                    error=lambda:RoutePreviewError('ROUTE_PROVIDER_UNAVAILABLE',502)), 'ROUTE_PROVIDER_UNAVAILABLE',502)
            connection.close.assert_called_once()
        with patch('route_preview.bounded_get',side_effect=TimeoutError):
            service=RoutePreview(KakaoRoutePreview(KEY))
            self.error(lambda:service.preview('a',dict(points=POINTS)),'ROUTE_TIMEOUT',504)


class WebContractTests(unittest.TestCase):
    def setUp(self):
        from team_auth import TeamAuth
        from fastapi import FastAPI
        from studio import create_router
        self.auth=object.__new__(TeamAuth)
        self.auth.enabled=True;self.auth.dsn='unused';self.auth.secret=b'test-secret';self.auth.public_origin='https://web.test'
        self.auth.current_account=lambda account:dict(displayName='Tester',role='viewer',handle='tester')
        self.service=RoutePreview(MockRoutePreview())
        self.app=FastAPI()
        @self.app.middleware('http')
        async def identity(request, call_next):
            if request.headers.get('x-native'):request.state.device_identity={'id':'native'}
            if request.headers.get('x-account'):request.state.team_identity={'id':'alice','role':'viewer'}
            return await call_next(request)
        self.app.include_router(create_router('unused',Path('/tmp/unused'),self.auth,route_preview=self.service))

    def call(self,value=None,*,path='/v1/routes/preview',**overrides):
        headers={'host':'web.test','origin':'https://web.test','cookie':'__Host-wegoh_team=test',
                 'x-wegoh-csrf':self.auth.csrf('test'),'x-account':'alice'}
        for name,value_ in overrides.items():
            name=name.replace('_','-')
            if value_ is None:headers.pop(name,None)
            else:headers[name]=value_
        raw=json.dumps(value if value is not None else dict(points=POINTS)).encode()
        async def exchange():
            sent=False;messages=[]
            async def receive():
                nonlocal sent
                if not sent:sent=True;return dict(type='http.request',body=raw,more_body=False)
                await asyncio.Event().wait()
            async def send(message):messages.append(message)
            await self.app(dict(type='http',asgi={'version':'3.0','spec_version':'2.4'},http_version='1.1',
                method='POST',scheme='https',path=path,raw_path=path.encode(),query_string=b'',
                headers=[(key.encode(),value.encode()) for key,value in headers.items()],server=('web.test',443),client=('127.0.0.1',1),root_path=''),receive,send)
            start=next(message for message in messages if message['type']=='http.response.start')
            data=json.loads(b''.join(message.get('body',b'') for message in messages if message['type']=='http.response.body'))
            return start['status'],data,dict((k.decode(),v.decode()) for k,v in start['headers'])
        with patch('team_auth.psycopg.connect') as connect:
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=('alice',)
            return asyncio.run(exchange())

    def test_native_scope_remains_closed(self):
        from native_access_policy import required_scope, RouteDenied
        for path in ('/v1/routes/preview', '/v1/iphone/routes/preview'):
            with self.assertRaises(RouteDenied):required_scope('POST',path)

    def test_real_team_csrf_origin_session_native_and_viewer(self):
        status,data,headers=self.call()
        self.assertEqual(status,200);self.assertEqual(data['distanceMeters'],12000)
        self.assertIn('no-store',headers['cache-control'])
        for kwargs,status in [({'x_wegoh_csrf':None},403),({'origin':'https://other.test'},403),
                              ({'cookie':None},401),({'x_account':None},401),({'x_native':'1'},404)]:
            self.assertEqual(self.call(**kwargs)[0],status)
        self.assertEqual(self.call(dict(points=[]))[0],400)
        self.service.limit=1;self.service._attempts.clear();self.call()
        status,data,headers=self.call()
        self.assertEqual((status,data['detail'],headers['retry-after']),(429,'ROUTE_RATE_LIMITED','60'))

    def test_iphone_waypoints_and_shared_web_account_limit(self):
        def authenticate(request, scope):
            self.assertEqual(scope, 'maps:read')
            self.assertEqual(request.headers['authorization'], 'Bearer synthetic-session')
            self.assertNotIn('origin', request.headers)
            self.assertNotIn('cookie', request.headers)
            self.assertNotIn('x-wegoh-csrf', request.headers)
            return {'id': 'alice'}

        body = dict(origin=ORIGIN, points=POINTS)
        with patch.object(self.auth, 'iphone', create=True, side_effect=authenticate) as iphone:
            self.service.limit = 2
            self.assertEqual(self.call()[0], 200)
            status, data, headers = self.call_iphone(body)
            self.assertEqual((status, data, headers['cache-control']), (200, {
                'distanceMeters': 12000, 'durationSeconds': 1800,
                'path': [[37.4, 126.9], [37.5, 127], [37.6, 127.1], [37.7, 127.2]]}, 'private, no-store'))
            self.assertEqual(iphone.call_count, 2)
            status, data, headers = self.call_iphone(body)
            self.assertEqual((status, data['detail'], headers['retry-after']), (429, 'ROUTE_RATE_LIMITED', '60'))

    def test_iphone_authentication_and_provider_errors(self):
        from fastapi import HTTPException

        with patch.object(self.auth, 'iphone', create=True) as iphone:
            for status, code in ((401, 'IPHONE_SESSION_EXPIRED'), (403, 'IPHONE_SCOPE_DENIED')):
                iphone.side_effect = HTTPException(status, code)
                self.assertEqual(self.call_iphone()[:2], (status, {'detail': code}))
            self.assertFalse(self.service._attempts)
            iphone.side_effect = [{'id': 'alice'}, HTTPException(401, 'IPHONE_SESSION_REVOKED')]
            self.assertEqual(self.call_iphone()[:2], (401, {'detail': 'IPHONE_SESSION_REVOKED'}))
            iphone.side_effect = None
            iphone.return_value = {'id': 'alice'}
            for raw, status, code in ((json.dumps(response(code=104)).encode(), 422, 'ROUTE_NOT_FOUND'),
                                      (b'malformed', 502, 'ROUTE_PROVIDER_UNAVAILABLE')):
                self.service.provider = KakaoRoutePreview(KEY, lambda *_: raw)
                self.assertEqual(self.call_iphone()[:2], (status, {'detail': code}))

    def call_iphone(self, value=None):
        return self.call(value, path='/v1/iphone/routes/preview', host='iphone.test', origin=None,
                         cookie=None, x_wegoh_csrf=None, x_account=None, authorization='Bearer synthetic-session')

    def test_local_post_exact_origin_and_cookie(self):
        from studio import create_router
        from starlette.requests import Request
        from fastapi import Response, HTTPException
        router=create_router('unused',Path('/tmp/unused'),route_preview=RoutePreview(MockRoutePreview()))
        route=next(route for route in router.routes if route.path=='/v1/routes/preview')
        def request(origin):
            async def receive():return dict(type='http.request',body=json.dumps(dict(points=POINTS)).encode())
            return Request(dict(type='http',method='POST',scheme='http',path='/v1/routes/preview',query_string=b'',
                headers=[(b'host',b'localhost'),(b'cookie',b'wegoh_studio=test'),(b'origin',origin.encode())],server=('localhost',80)),receive)
        with patch('studio.psycopg.connect') as connect:
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=('local',)
            self.assertEqual(asyncio.run(route.endpoint(request('http://localhost'),Response()))['distanceMeters'],12000)
            with self.assertRaises(HTTPException) as caught:asyncio.run(route.endpoint(request('http://evil'),Response()))
            self.assertEqual(caught.exception.status_code,403)

    def test_openapi_body_response_and_browser_csrf_contract(self):
        from api_doc_core import OPS
        from team_api_docs import BODY
        contract=OPS[('post','/v1/routes/preview')]
        schema=self.app.openapi()['paths']['/v1/routes/preview']['post']
        self.assertFalse(schema['x-wegoh-native-access'])
        self.assertEqual(BODY[('post','/v1/routes/preview')]['properties']['points']['maxItems'],3)
        self.assertEqual(contract['responses']['200']['content']['application/json']['schema']['properties']['path']['maxItems'],2000)
        self.assertTrue({'422','429','502','503','504'}<=set(contract['errorDescriptions']))
        self.assertIn('X-WegoH-CSRF',contract['prerequisites'])


if __name__=='__main__':unittest.main()
