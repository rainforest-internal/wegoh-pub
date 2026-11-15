"""Synthetic provider/transport and protected Studio route tests; no Kakao calls."""
import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import tempfile
from threading import Event, Lock, current_thread, enumerate as threads
import time
import unittest
from unittest.mock import patch
from http.client import HTTPConnection, HTTPException
from urllib.parse import parse_qs, urlencode, urlsplit

from place_search import (KakaoPlaceSearch, MockPlaceSearch, PlaceSearch, PlaceSearchError,
                          load_key, search_query, kakao_transport, MAX_BYTES, MAX_CONCURRENT_SEARCHES)

KEY = 'synthetic-kakao-test-key-12345678'


def keyword(**overrides):
    return dict(dict(id='123', place_name='서울숲', address_name='서울 성동구 성수동1가 685',
                     road_address_name='서울 성동구 뚝섬로 273', category_name='여행 > 공원',
                     x='127.037', y='37.544', place_url='http://place.map.kakao.com/123'), **overrides)


def address(**overrides):
    return dict(dict(address_name='서울 성동구 성수동1가 685', x='127.037', y='37.544',
                     address={'address_name':'서울 성동구 성수동1가 685'},
                     road_address={'address_name':'서울 성동구 뚝섬로 273'}), **overrides)


class ProviderTests(unittest.TestCase):
    def error(self, status, action, code=None):
        with self.assertRaises(PlaceSearchError) as result:
            action()
        self.assertEqual(result.exception.status, status)
        if code:self.assertEqual(result.exception.code, code)
        self.assertNotIn(KEY, str(result.exception))

    def provider(self, keywords=None, addresses=None):
        calls = []
        def transport(url, headers, timeout, max_bytes):
            calls.append((url, headers, timeout, max_bytes))
            return json.dumps({'documents': (keywords if keywords is not None else [keyword()])
                               if 'keyword.json' in url else (addresses if addresses is not None else [address()])}).encode()
        return KakaoPlaceSearch(KEY, transport), calls

    def test_normalization_dedup_both_requests_and_no_cache(self):
        provider, calls = self.provider([keyword(), keyword()], [address(), address(x='127.1', road_address=None)])
        result = provider.search('서울숲', 127, 37)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], dict(id='kakao-123',name='서울숲',address='서울 성동구 성수동1가 685',
            roadAddress='서울 성동구 뚝섬로 273', category='여행 > 공원', lat=37.544,lng=127.037,
            source='kakao',placeUrl='https://place.map.kakao.com/123'))
        self.assertEqual(result[1]['name'], '서울 성동구 성수동1가 685')
        self.assertTrue(result[1]['id'].startswith('kakao-address-'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(parse_qs(urlsplit(calls[0][0]).query),dict(query=['서울숲'],size=['15'],page=['1'],x=['127'],y=['37']))
        self.assertNotIn('x', parse_qs(urlsplit(calls[1][0]).query))
        self.assertTrue(all(h=={'Authorization':'KakaoAK '+KEY} and 0<t<=3 and size==MAX_BYTES for _,h,t,size in calls))
        provider.search('서울숲'); self.assertEqual(len(calls), 4)

    def test_address_road_name_limit_empty_and_bad_payloads(self):
        provider, _ = self.provider([], [address()])
        self.assertEqual(provider.search('뚝섬로')[0]['name'], '서울 성동구 뚝섬로 273')
        provider, _ = self.provider([keyword(id=str(i), x=str(127+i/10000)) for i in range(20)], [])
        self.assertEqual(len(provider.search('서울숲')),15)
        provider, _ = self.provider([], [])
        self.assertEqual(provider.search('없는곳'), [])
        for doc in [keyword(x='nan'),keyword(y='91'),keyword(place_url='https://evil.invalid'),keyword(place_name=KEY)]:
            provider, _ = self.provider([doc], [])
            self.error(502, lambda:provider.search('서울숲'))
        for raw in [b'{}',b'broken',b'x'*(MAX_BYTES+1),b'{"documents":{}}']:
            self.error(502,lambda:KakaoPlaceSearch(KEY,lambda *args:raw).search('서울숲'))

    def test_input_validation(self):
        self.assertEqual(search_query({'q':['  서울숲  '],'x':['180'],'y':['-90']}), ('서울숲',180,-90))
        self.assertEqual(search_query({'q':['가'*60]}),('가'*60,None,None))
        for value in [{},{'q':['가']},{'q':['가'*61]},{'q':['서울\n숲']},{'q':['\t서울숲']},
                      {'q':['서울\x7f숲']},{'q':['서울\u200b숲']},{'q':['서울숲','부산역']},
                      {'q':['서울숲'],'url':['https://evil.invalid']},{'q':['서울숲'],'x':['127']},
                      {'q':['서울숲'],'x':['181'],'y':['37']},{'q':['서울숲'],'x':['127'],'y':['91']},
                      {'q':['서울숲'],'x':['nan'],'y':['37']},{'q':['서울숲'],'x':['127'],'y':['inf']}]:
            self.error(400, lambda:search_query(value))

    def test_missing_unsafe_and_valid_key(self):
        with patch.dict(os.environ, {}, clear=True):self.assertIsNone(load_key())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'credential';path.write_text(KEY+'\n');path.chmod(0o600)
            self.assertEqual(load_key(str(path)),KEY)
            with patch.dict(os.environ, {'WEGOH_KAKAO_REST_KEY_FILE':str(path)}):
                self.assertIsInstance(PlaceSearch.from_environment().provider,KakaoPlaceSearch)
            for mode in [0o644,0o400,0o660,0o604]:
                path.chmod(mode);self.assertIsNone(load_key(str(path)))
            path.chmod(0o600);link=Path(directory)/'link';link.symlink_to(path)
            self.assertIsNone(load_key(str(link)))
            path.write_text(KEY+'\nInvalid header');self.assertIsNone(load_key(str(path)))
            self.assertIsNone(load_key(str(path.parent)))
            path.unlink();self.assertIsNone(load_key(str(path)))

    def test_account_rate_limit_rolling_window_and_safe_logging(self):
        now=[0];service=PlaceSearch(MockPlaceSearch(),clock=lambda:now[0])
        with self.assertLogs('place_search',level=logging.INFO) as logs:
            for _ in range(30):self.assertEqual(len(service.search('alice', {'q':['서울숲']})),1)
            self.error(429, lambda:service.search('alice',{'q':['서울숲']}))
            service.search('bob',{'q':['서울숲']});now[0]=60;service.search('alice',{'q':['서울숲']})
            self.error(503, lambda:PlaceSearch().search('alice',{'q':['서울숲']}))
        self.assertNotIn(KEY, '\n'.join(logs.output));self.assertNotIn('서울숲','\n'.join(logs.output))
        self.assertIn('place.search: loaded count=1','\n'.join(logs.output))

    def test_errors_and_hard_timeout_never_expose_key(self):
        for error,status in [(RuntimeError(KEY),502),(TimeoutError(KEY),504)]:
            def fail(*args):raise error
            provider=KakaoPlaceSearch(KEY,fail)
            with self.assertLogs('place_search',level=logging.INFO) as logs:
                self.error(status,lambda:PlaceSearch(provider).search('alice',{'q':['서울숲']}))
            self.assertNotIn(KEY,'\n'.join(logs.output))

    def test_keyword_and_address_share_deadline(self):
        now=[0.0];budgets=[]
        def transport(url,headers,timeout,max_bytes):
            budgets.append(timeout)
            now[0]+=.02
            return b'{"documents":[]}'
        provider=KakaoPlaceSearch(KEY,transport,clock=lambda:now[0])
        self.error(504,lambda:provider.search('서울숲',timeout=.03),'PLACE_SEARCH_TIMEOUT')
        self.assertEqual(len(budgets),2)
        self.assertAlmostEqual(budgets[0],.03)
        self.assertAlmostEqual(budgets[1],.01)
        now[0]=0;budgets.clear()
        self.error(504,lambda:provider.search('서울숲',timeout=.01))
        self.assertEqual(len(budgets),1)


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.release=Event();self.lock=Lock();self.workers=[]
        owner=self
        class Blocked:
            def search(self,*args):
                with owner.lock:owner.workers.append(current_thread())
                owner.release.wait()
                return []
        self.provider=Blocked()
        self.addCleanup(self.stop_workers)

    def stop_workers(self):
        self.release.set()
        workers=set(self.workers)|{worker for worker in threads() if worker.name=='place-search'}
        for worker in workers:
            worker.join(1)
            self.assertFalse(worker.is_alive())

    def assert_error(self,service,code,status):
        with self.assertRaises(PlaceSearchError) as raised:
            service.search('alice',{'q':['서울숲']})
        self.assertEqual((raised.exception.code,raised.exception.status),(code,status))

    def test_global_slots_survive_timeout_and_rolling_window_then_recover(self):
        now=[0];service=PlaceSearch(self.provider,clock=lambda:now[0],timeout=.01,limit=3)
        for index in range(MAX_CONCURRENT_SEARCHES):
            now[0]=(index//3)*60
            self.assert_error(service,'PLACE_SEARCH_TIMEOUT',504)
        self.assertEqual(len(self.workers),MAX_CONCURRENT_SEARCHES)
        other=PlaceSearch(self.provider,timeout=.5)
        before=time.monotonic()
        self.assert_error(other,'PLACE_SEARCH_BUSY',503)
        self.assertLess(time.monotonic()-before,.1)
        for minute in range(1,5):
            now[0]=minute*60
            self.assert_error(service,'PLACE_SEARCH_BUSY',503)
            self.assertLessEqual(sum(worker.name=='place-search' for worker in threads()),MAX_CONCURRENT_SEARCHES)
        self.assertEqual(len(self.workers),MAX_CONCURRENT_SEARCHES)
        self.stop_workers()
        self.assertEqual(other.search('alice',{'q':['서울숲']}),[])

    def test_failed_thread_start_and_provider_failure_release_slots(self):
        service=PlaceSearch(MockPlaceSearch())
        with patch('place_search.Thread.start',side_effect=RuntimeError(KEY)):
            for _ in range(MAX_CONCURRENT_SEARCHES+1):
                self.assert_error(service,'PLACE_SEARCH_BUSY',503)
        self.assertEqual(len(service.search('alice',{'q':['서울숲']})),1)
        class Failed:
            def search(self,*args):raise RuntimeError(KEY)
        service.provider=Failed()
        for _ in range(MAX_CONCURRENT_SEARCHES+1):
            self.assert_error(service,'PLACE_SEARCH_PROVIDER_UNAVAILABLE',502)
        service.provider=MockPlaceSearch()
        self.assertEqual(len(service.search('alice',{'q':['서울숲']})),1)


class TransportTests(unittest.TestCase):
    def setUp(self):
        patcher=patch('place_search.HTTPSConnection')
        self.factory=patcher.start();self.addCleanup(patcher.stop)
        self.connection=self.factory.return_value
        self.response=self.connection.getresponse.return_value
        self.response.__enter__.return_value=self.response
        def close_response(*args):
            self.response.close()
            return False
        self.response.__exit__.side_effect=close_response
        self.response.status=200
        self.response.isclosed.return_value=False

    def transport(self,**kwargs):
        return kakao_transport('https://fixed.invalid/search?q=test',{'Authorization':'KakaoAK '+KEY},
                               kwargs.pop('timeout',1),kwargs.pop('max_bytes',MAX_BYTES),**kwargs)

    def test_no_redirect_and_provider_error_mapping(self):
        for status in [302,401,429,500]:
            with self.subTest(status=status):
                self.response.status=status
                with self.assertRaises(PlaceSearchError) as raised:self.transport()
                self.assertEqual((raised.exception.status,raised.exception.code),(502,'PLACE_SEARCH_PROVIDER_UNAVAILABLE'))
                self.response.read1.assert_not_called()
        self.assertEqual(self.factory.call_count,4)
        self.assertEqual(self.response.close.call_count,4)
        for error in [OSError(KEY),HTTPException(KEY),TimeoutError(KEY)]:
            self.connection.connect.side_effect=error
            with self.assertRaises(TimeoutError if isinstance(error,TimeoutError) else PlaceSearchError) as raised:
                self.transport()
            self.assertNotIn(KEY,str(raised.exception))
        self.assertEqual(self.connection.close.call_count,7)

    def test_chunked_body_size_limit_and_eof(self):
        self.response.read1.side_effect=[b'x'*16384]*16+[b'']
        self.assertEqual(len(self.transport()),MAX_BYTES)
        self.assertTrue(all(call.args[0]<=16384 for call in self.response.read1.call_args_list))
        self.response.read1.reset_mock(side_effect=True)
        self.response.read1.side_effect=[b'x'*16384]*16+[b'x']
        with self.assertRaises(PlaceSearchError) as raised:self.transport()
        self.assertEqual(raised.exception.status,502)
        self.response.read1.assert_called_with(1)
        self.assertEqual(self.response.close.call_count,2)
        self.assertEqual(self.connection.close.call_count,2)

    def test_known_length_body_closes_on_last_read(self):
        self.response.read1.return_value=b'{}'
        self.response.isclosed.return_value=True
        self.assertEqual(self.transport(),b'{}')
        self.response.read1.assert_called_once()
        self.response.close.assert_called_once()

    def test_real_http_response_framing_and_connection_close(self):
        for body in [b'Content-Length: 2\r\n\r\n{}',b'Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n']:
            with self.subTest(body=body):
                reader,writer=socket.socketpair()
                self.addCleanup(reader.close);self.addCleanup(writer.close)
                connection=HTTPConnection('fixed.invalid')
                connection.connect=lambda:setattr(connection,'sock',reader)
                self.factory.return_value=connection
                writer.sendall(b'HTTP/1.1 200 OK\r\nConnection: close\r\n'+body)
                self.assertEqual(self.transport(),b'{}')
                self.assertEqual(reader.fileno(),-1)

    def test_slow_chunks_use_remaining_timeout_and_close_at_deadline(self):
        now=[0.0]
        def read(size):
            budget=self.connection.sock.settimeout.call_args.args[0]
            now[0]+=min(.01,budget)
            return b'x'
        self.response.read1.side_effect=read
        with self.assertRaises(TimeoutError):self.transport(timeout=.025,clock=lambda:now[0])
        self.assertAlmostEqual(now[0],.025)
        self.assertEqual(self.response.read1.call_count,3)
        budgets=[call.args[0] for call in self.connection.sock.settimeout.call_args_list]
        self.assertEqual(budgets,sorted(budgets,reverse=True))
        self.assertAlmostEqual(budgets[-1],.005)
        self.response.close.assert_called_once()
        self.connection.close.assert_called_once()

    def test_deadline_interrupts_a_blocked_body_or_headers(self):
        for stage in ['body','headers']:
            with self.subTest(stage=stage):
                reader,writer=socket.socketpair()
                self.addCleanup(reader.close);self.addCleanup(writer.close)
                self.connection.sock=reader
                self.response.close.reset_mock();self.connection.close.reset_mock()
                def blocked(*args):
                    reader.settimeout(1)
                    chunk=reader.recv(1)
                    if stage=='headers':raise HTTPException()
                    return chunk
                self.connection.getresponse.side_effect=blocked if stage=='headers' else None
                self.response.read1.side_effect=blocked
                before=time.monotonic()
                with self.assertRaises(TimeoutError):self.transport(timeout=.03)
                self.assertLess(time.monotonic()-before,.2)
                self.connection.close.assert_called_once()
                if stage=='body':self.response.close.assert_called_once()


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI, HTTPException
        from studio import create_router
        class Auth:
            enabled=True
            def browser(self,request,**kwargs):
                if request.cookies.get('session')!='test':raise HTTPException(401,'Authentication required')
                return {'id':request.headers.get('x-test-account','alice'),'role':'creator'}
        cls.auth=Auth()
        cls.service=PlaceSearch(MockPlaceSearch())
        app=FastAPI()
        @app.middleware('http')
        async def native(request,call_next):
            if request.headers.get('x-test-native'):request.state.device_identity={'id':'native'}
            return await call_next(request)
        app.include_router(create_router('unused',Path('/tmp/unused'),cls.auth,cls.service))
        cls.app=app

    def get(self,query='q=%EC%84%9C%EC%9A%B8%EC%88%B2',headers=None,path='/v1/places/search'):
        headers=headers if headers is not None else {'Cookie':'session=test'}
        scope=dict(type='http',asgi={'version':'3.0','spec_version':'2.4'},http_version='1.1',method='GET',
                   scheme='http',path=path,raw_path=path.encode(),query_string=query.encode(),
                   headers=[(key.lower().encode(),value.encode())for key,value in headers.items()],
                   server=('testserver',80),client=('127.0.0.1',1234),root_path='')
        async def exchange():
            messages=[];sent=False
            async def receive():
                nonlocal sent
                if not sent:
                    sent=True
                    return {'type':'http.request','body':b'','more_body':False}
                await asyncio.Event().wait()
            async def send(message):messages.append(message)
            await self.app(scope,receive,send)
            start=next(message for message in messages if message['type']=='http.response.start')
            raw=b''.join(message.get('body',b'')for message in messages if message['type']=='http.response.body')
            return start['status'],json.loads(raw),{key.decode().title():value.decode() for key,value in start['headers']}
        return asyncio.run(exchange())

    def setUp(self):
        self.service.provider=MockPlaceSearch();self.service._attempts.clear()

    def test_contract_auth_native_and_invalid_query(self):
        status,data,headers=self.get();self.assertEqual(status,200);self.assertEqual(data['places'][0]['source'],'kakao')
        self.assertEqual(headers['Cache-Control'],'private, no-store');self.assertNotIn(KEY,json.dumps(data))
        self.assertEqual(self.get(headers={})[0],401)
        self.assertEqual(self.get(headers={'Cookie':'session=test','X-Test-Native':'yes'})[0],404)
        self.assertEqual(self.get(path='/v1/native/places/search')[0],404)
        from native_access_policy import required_scope, RouteDenied
        with self.assertRaises(RouteDenied):required_scope('GET','/v1/places/search')
        for query in ['q=x','q=hello&q=world','q=hello&x=181&y=0','q=hello%0A']:
            self.assertEqual(self.get(query)[0],400)

    def test_unavailable_rate_and_provider_errors(self):
        self.service.provider=None
        status,data,headers=self.get();self.assertEqual((status,data['detail']),(503,'PLACE_SEARCH_UNAVAILABLE'))
        self.assertEqual(headers['Cache-Control'],'private, no-store')
        self.service.provider=MockPlaceSearch()
        for _ in range(30):self.assertEqual(self.get()[0],200)
        status,data,headers=self.get();self.assertEqual(status,429);self.assertEqual(headers['Retry-After'],'60')
        self.assertEqual(self.get(headers={'Cookie':'session=test','X-Test-Account':'bob'})[0],200)
        class Failure:
            def search(self,*args):raise RuntimeError(KEY)
        self.service.provider=Failure();self.service._attempts.clear()
        with self.assertLogs('place_search',level=logging.INFO) as logs:
            status,data,_=self.get()
        self.assertEqual(status,502);self.assertNotIn(KEY,json.dumps(data)+'\n'.join(logs.output))

    def test_busy_response_contract(self):
        with patch('place_search._SEARCH_SLOTS') as slots:
            slots.acquire.return_value=False
            status,data,headers=self.get()
        self.assertEqual((status,data),(503,{'detail':'PLACE_SEARCH_BUSY'}))
        self.assertEqual(headers['Cache-Control'],'private, no-store')
        self.assertNotIn('Retry-After',headers)

    def test_iphone_address_empty_and_shared_web_account_limit(self):
        from fastapi import HTTPException

        def authenticate(request, scope):
            self.assertEqual(scope, 'maps:read')
            if request.headers.get('authorization') != 'Bearer synthetic-session':
                raise HTTPException(401, 'IPHONE_SESSION_REQUIRED')
            return {'id': 'alice'}

        road_name = '가상시 예시로 10'
        address_result = address(x='126.978', y='37.5665', address={'address_name': '가상시 예시동 20'},
                                 road_address={'address_name': road_name})

        def transport(url, *_):
            parsed = urlsplit(url)
            found = parsed.path.endswith('address.json') and parse_qs(parsed.query)['query'] == [road_name]
            return json.dumps({'documents': [address_result] if found else []}).encode()

        self.service.provider = KakaoPlaceSearch(KEY, transport)
        path = '/v1/iphone/places/search'
        headers = {'Authorization': 'Bearer synthetic-session'}
        with patch.object(self.auth, 'iphone', create=True, side_effect=authenticate) as iphone, \
                patch.object(self.service, 'limit', 3):
            status, data, response_headers = self.get(urlencode({'q': road_name}), headers, path)
            self.assertEqual((status, data, response_headers['Cache-Control']), (200, {'places': [{
                'id': 'kakao-address-afa5823097531c1d1ddefaf1', 'name': road_name, 'address': '가상시 예시동 20',
                'roadAddress': road_name, 'category': '주소', 'lat': 37.5665, 'lng': 126.978, 'source': 'kakao',
                'placeUrl': 'https://map.kakao.com/link/map/37.5665,126.978'}]}, 'private, no-store'))
            self.assertEqual(iphone.call_count, 2)
            self.assertEqual(self.get(urlencode({'q': '가상시 없는로 99'}), headers, path)[:2], (200, {'places': []}))
            self.assertEqual(self.get(path=path)[:2], (401, {'detail': 'IPHONE_SESSION_REQUIRED'}))
            self.assertEqual(self.get()[0], 200)
            status, data, response_headers = self.get(headers=headers, path=path)
            self.assertEqual((status, data['detail'], response_headers['Retry-After']),
                             (429, 'PLACE_SEARCH_RATE_LIMITED', '60'))

    def test_search_has_authored_openapi_contract(self):
        from api_doc_core import OPS
        from studio import create_router
        from fastapi import FastAPI
        from fastapi.openapi.utils import get_openapi
        app=FastAPI();app.include_router(create_router('unused',Path('/tmp/unused')))
        schema=get_openapi(title='Test',version='1',routes=app.routes)
        operation=schema['paths']['/v1/places/search']['get']
        self.assertFalse(operation['x-wegoh-native-access'])
        self.assertEqual([p['name']for p in operation['parameters']],['q','x','y'])
        contract=OPS[('get','/v1/places/search')]
        self.assertEqual(contract['responses']['200']['content']['application/json']['schema']['properties']['places']['maxItems'],15)
        self.assertTrue({'502','503','504'}<=set(contract['errorDescriptions']))

    def test_local_studio_session(self):
        from studio import create_router
        router=create_router('unused',Path('/tmp/unused'),place_search=PlaceSearch(MockPlaceSearch()))
        route=next(route for route in router.routes if route.path=='/v1/places/search')
        from starlette.requests import Request as ASGIRequest
        from fastapi import Response,HTTPException
        scope=dict(type='http',method='GET',scheme='http',path='/v1/places/search',query_string=b'q=hello',
                   headers=[(b'host',b'localhost'),(b'cookie',b'wegoh_studio=test')],server=('localhost',80))
        with patch('studio.psycopg.connect') as connect:
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=('local-creator',)
            self.assertEqual(len(route.endpoint(ASGIRequest(scope),Response())['places']),1)
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=None
            with self.assertRaises(HTTPException) as result:route.endpoint(ASGIRequest(scope),Response())
            self.assertEqual(result.exception.status_code,401)


if __name__=='__main__':unittest.main()
