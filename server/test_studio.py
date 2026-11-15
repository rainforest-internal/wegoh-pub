"""HTTP contract tests. Run against an isolated disposable database, never the demo library."""
import base64
import copy
import hashlib
import http.cookiejar
import json
import http.client
import ipaddress
import io
import os
import socket
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PIL import Image

BASE = os.environ['WEGOH_STUDIO_TEST_URL']


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.pack = dict(schemaVersion=1, id='contract-'+uuid.uuid4().hex, version=1,
                         title='합성 시험 팩', author='ignored caller author', description='가상 GPS 검증용 데이터',
                         stops=[dict(id='first', name='합성 지점', latitude=37.4979, longitude=127.0276,
                                     radiusMeters=100, action=dict(type='chime', message='합성 이벤트'))])

    def call(self, path, data=None, method=None, origin=BASE, raw=None, extra_headers=None):
        payload = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
        headers={'Origin':origin, 'Content-Type':'application/json'}
        headers.update(extra_headers or {})
        request = urllib.request.Request(BASE+path, data=payload, headers=headers, method=method)
        try:
            with self.client.open(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def login(self):
        status, headers, _ = self.call('/v1/studio/session', method='POST')
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=strict', headers['Set-Cookie'])

    def publish(self, pack=None):
        return self.call('/v1/packs', {'rightsConfirmed':True, 'pack':pack or self.pack})

    def operator(self,path,data=None,method=None):
        return self.call(path,data,method,extra_headers={'Authorization':'Bearer '+os.environ['WEGOH_API_KEY']})

    def approve_fixture(self,pack=None):
        # Only explicitly synthetic test content is approved here; never a product auto-filter.
        pack=pack or self.pack
        path=f"/v1/moderation/packs/{pack['id']}/versions/{pack['version']}"
        status,_,raw=self.operator(path);self.assertEqual(status,200)
        checksum=hashlib.sha256(raw).hexdigest()
        self.assertEqual(self.operator(path,dict(checksum=checksum,decision='approved',reviewer='isolated-contract-test',
                                               reviewNote='Synthetic one-stop GPS fixture reviewed in isolated test database'))[0],200)
        return checksum

    def test_no_anonymous_or_cross_origin_publication(self):
        self.assertEqual(self.publish()[0], 401)
        self.assertEqual(self.call('/v1/studio/session', method='POST', origin='https://other.invalid')[0], 403)
        self.login()
        self.assertEqual(self.call('/v1/packs', {'pack':self.pack, 'rightsConfirmed':True}, origin='https://other.invalid')[0], 403)

    def test_immutable_versions_and_original_bytes(self):
        self.login()
        status, _, data = self.publish(); self.assertEqual(status, 201)
        checksum = json.loads(data)['checksum']
        self.assertEqual(json.loads(data)['state'],'approved')
        self.assertEqual(self.call(f"/v1/packs/{self.pack['id']}/versions/1")[0],200)
        self.approve_fixture()
        self.assertEqual(self.publish()[0], 200)
        status, _, raw = self.call(f"/v1/packs/{self.pack['id']}/versions/1")
        self.assertEqual(status, 200); self.assertEqual(hashlib.sha256(raw).hexdigest(), checksum)
        self.assertEqual(json.loads(raw)['author'], 'WegoH 로컬 창작자')
        self.pack['title'] = '수정된 제목'; self.assertEqual(self.publish()[0], 409)
        self.pack['version'] = 3; self.assertEqual(self.publish()[0], 409)
        self.pack['version'] = 2; self.assertEqual(self.publish()[0], 201)
        self.approve_fixture()
        packs = json.loads(self.call('/v1/packs')[2])['packs']
        self.assertEqual(next(p for p in packs if p['id'] == self.pack['id'])['version'], 2)
        self.assertEqual(self.call(f"/v1/packs/{self.pack['id']}/versions/1")[2], raw)

    def test_invalid_input_cannot_publish(self):
        self.login()
        changes = [lambda p:p.update(version=True), lambda p:p.update(version=1.5),
                   lambda p:p['stops'][0].update(latitude=91),
                   lambda p:p['stops'][0]['action'].update(type='execute_code'),
                   lambda p:p['stops'].append(copy.deepcopy(p['stops'][0])),
                   lambda p:p.update(title='😀'*51)]
        for change in changes:
            candidate=copy.deepcopy(self.pack); change(candidate)
            self.assertEqual(self.publish(candidate)[0], 400)
        self.assertEqual(self.call('/v1/packs', {'rightsConfirmed':False,'pack':self.pack})[0], 400)
        self.assertEqual(self.call('/v1/packs', raw=b'x'*262145)[0], 413)
        self.assertEqual(self.call('/v1/packs', raw=b'{bad')[0], 400)

    def test_review_title_and_untransformed_originals(self):
        self.login()
        status, _, data = self.publish(); self.assertEqual(status, 201)
        checksum = json.loads(data)['checksum']
        status, _, data = self.operator('/v1/moderation/packs'); self.assertEqual(status, 200)
        item = next(p for p in json.loads(data)['packs'] if p['id'] == self.pack['id'])
        self.assertEqual(item['title'], self.pack['title'])
        self.assertEqual(item['checksum'], checksum)
        originals = []
        for prefix in ('studio/', 'moderation/'):
            path = f"/v1/{prefix}packs/{self.pack['id']}/versions/1"
            code, headers, raw = self.operator(path) if prefix == 'moderation/' else self.call(path)
            self.assertEqual(code, 200)
            self.assertIn('no-transform', headers['Cache-Control'].split(', '))
            self.assertEqual(hashlib.sha256(raw).hexdigest(), checksum)
            if prefix == 'moderation/': self.assertEqual(headers['ETag'], '"' + checksum + '"')
            originals.append(raw)
        self.approve_fixture()
        code, headers, raw = self.call(f"/v1/packs/{self.pack['id']}/versions/1")
        self.assertEqual(code, 200)
        self.assertIn('no-transform', headers['Cache-Control'].split(', '))
        self.assertEqual(headers['ETag'], '"' + checksum + '"')
        self.assertEqual(originals, [raw, raw])

    def test_cover_remains_versioned_and_separate_from_the_drive_pack(self):
        def image(color):
            stream = io.BytesIO()
            Image.new('RGB', (40, 30), color).save(stream, 'JPEG', comment=b'private fixture metadata')
            return base64.b64encode(stream.getvalue()).decode('ascii')

        self.login()
        pack_id = self.pack['id']
        path = f'/v1/packs/{pack_id}/versions'
        body = dict(pack=self.pack, rightsConfirmed=True, coverImage=image('blue'), tags=[' #coast ', 'DRIVE', 'drive'])
        self.assertIn(b'private fixture metadata', base64.b64decode(body['coverImage']))
        self.assertEqual(self.call('/v1/packs', {**body, 'coverImage': 'aGVsbG8='})[0], 400)
        status, _, response = self.call('/v1/packs', body)
        self.assertEqual(status, 201, response)
        checksum = json.loads(response)['checksum']
        self.assertEqual(self.call('/v1/packs', body)[0], 200)
        self.assertEqual(self.call('/v1/packs', {**body, 'coverImage': image('red')})[0], 409)
        self.assertEqual(self.call('/v1/packs', {**body, 'tags': ['other']})[0], 409)
        status, _, raw = self.call(f'{path}/1')
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), checksum)
        self.assertNotIn('coverImage', json.loads(raw))
        self.assertNotIn('origin', json.loads(raw))
        self.assertNotIn('tags', json.loads(raw))

        status, headers, cover = self.call(f'{path}/1/cover')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/jpeg')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertNotIn(b'private fixture metadata', cover)
        self.assertEqual(Image.open(io.BytesIO(cover)).size, (40, 30))
        version2 = {**self.pack, 'version': 2}
        edit = dict(pack=version2, rightsConfirmed=True, copyCoverFromVersion=1, tags=['#scenic'])
        self.assertEqual(self.call('/v1/packs', edit)[0], 201)
        self.assertEqual(self.call('/v1/packs', edit)[0], 200)
        self.assertEqual(self.call(f'{path}/2/cover')[2], cover)
        own_versions = json.loads(self.call('/v1/studio/packs')[2])['packs']
        self.assertEqual({entry['version']: entry['tags'] for entry in own_versions if entry['id'] == pack_id},
                         {1: ['coast', 'DRIVE'], 2: ['scenic']})
        self.assertEqual(self.publish({**self.pack, 'version': 3})[0], 201)
        self.assertEqual(self.call(f'{path}/3/cover')[0], 404)

        moderation = f'/v1/moderation/packs/{pack_id}/versions/1'
        self.assertEqual(self.operator(moderation + '/cover')[2], cover)
        decision = dict(checksum=checksum, decision='rejected', reviewer='fixture', reviewNote='Image test fixture')
        self.assertEqual(self.operator(moderation, decision)[0], 200)
        self.assertEqual(self.call(f'{path}/1/cover')[0], 404)
        self.assertEqual(self.call(f'/v1/studio/packs/{pack_id}/versions/1/cover')[2], cover)

    def test_logout_revokes_saved_cookie(self):
        self.login(); cookie = list(self.cookies)[0]
        self.assertEqual(self.call('/v1/studio/session', method='DELETE')[0], 200)
        self.cookies.set_cookie(cookie)
        self.assertEqual(self.publish()[0], 401)

    def test_public_read_and_static_security_headers(self):
        self.assertEqual(self.call('/v1/packs/unknown/versions/1')[0], 404)
        code, headers, html = self.call('/')
        self.assertEqual(code, 200)
        self.assertIn(b'url=/api-docs', html)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        policy=headers['Content-Security-Policy']
        config=json.loads(self.call('/v1/auth/session')[2]).get('placeMap',{})
        self.assertEqual('https://dapi.kakao.com' in policy,bool(config.get('kakaoJsKey')))
        self.assertEqual('https://mts.kakaocdn.net' in policy,bool(config.get('kakaoJsKey')))
        self.assertNotIn("'unsafe-inline'",policy)
        self.assertNotIn("'unsafe-eval'",policy)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.call('/api-docs.js')[0], 200)

    def test_consented_visits_are_private_and_deduplicated(self):
        place=dict(id='synthetic-place',provider='map',name='가상 방문 지점',address='합성 데이터',latitude=37.4979,longitude=127.0276)
        body=dict(consent=True,visits=[dict(id=uuid.uuid4().hex,place=place,visitedAt=1700000000000)])
        self.assertEqual(self.call('/v1/places/visited')[0],401)
        self.assertEqual(self.call('/v1/local/visits',body)[0],403)
        headers={'X-WegoH-Local-Visit':'1'}
        self.assertEqual(self.call('/v1/local/visits',body,origin='https://other.invalid',extra_headers=headers)[0],403)
        self.assertEqual(self.call('/v1/local/visits',dict(body,consent=False),extra_headers=headers)[0],400)
        self.assertEqual(self.call('/v1/local/visits',body,extra_headers=headers)[0],200)
        self.assertEqual(self.call('/v1/local/visits',body,extra_headers=headers)[0],200)
        import psycopg
        from private_records import VisitCipher
        with psycopg.connect(os.environ['WEGOH_DATABASE_DSN']) as conn:
            row=conn.execute('SELECT place,visited_at,protected FROM visited_places WHERE visit_id=%s',(body['visits'][0]['id'],)).fetchone()
        self.assertIsNone(row[0]);self.assertEqual(row[1],1)
        self.assertNotIn(place['name'].encode(),bytes(row[2]))
        self.assertEqual(VisitCipher().restore('local-creator',body['visits'][0]['id'],row[2])['place'],place)
        self.login()
        records=json.loads(self.call('/v1/places/visited')[2])['places']
        self.assertEqual(len(records),1); self.assertEqual(records[0]['name'],place['name'])
        original=bytes(row[2]);tampered=original[:-1]+bytes([original[-1]^1])
        visit_id=body['visits'][0]['id']
        try:
            with psycopg.connect(os.environ['WEGOH_DATABASE_DSN']) as conn:
                assert conn.info.dbname.startswith('wegohcheck_'),'Mutation is restricted to the disposable test DB'
                conn.execute('UPDATE visited_places SET protected=%s WHERE visit_id=%s',(tampered,visit_id))
            self.assertEqual(self.call('/health/ready')[0],503)
            code,_,error=self.call('/v1/places/visited')
            self.assertEqual(code,503);self.assertNotIn(place['name'].encode(),error)
        finally:
            with psycopg.connect(os.environ['WEGOH_DATABASE_DSN']) as conn:
                assert conn.info.dbname.startswith('wegohcheck_')
                conn.execute('UPDATE visited_places SET protected=%s WHERE visit_id=%s',(original,visit_id))
        self.assertEqual(self.call('/health/ready')[0],200)
        self.assertEqual(self.call('/v1/places/visited',method='DELETE')[0],200)
        self.assertEqual(json.loads(self.call('/v1/places/visited')[2])['places'],[])

    def test_place_objects_survive_publication(self):
        self.login()
        self.pack['stops'][0]['place']=dict(id='synthetic-object',provider='map',name='지도에서 고른 장소',address='')
        self.assertEqual(self.publish()[0],201)
        self.approve_fixture()
        raw=self.call(f"/v1/packs/{self.pack['id']}/versions/1")[2]
        self.assertEqual(json.loads(raw)['stops'][0]['place']['id'],'synthetic-object')

    def test_quarantine_and_operator_authority_are_separate(self):
        self.login();status,_,data=self.publish();self.assertEqual(status,201)
        checksum=json.loads(data)['checksum'];path=f"/v1/moderation/packs/{self.pack['id']}/versions/1"
        body=dict(checksum=checksum,decision='approved',reviewer='test-operator',reviewNote='Synthetic content inspected')
        self.assertEqual(self.call('/v1/moderation/packs')[0],401)
        self.assertEqual(self.call(path)[0],401)
        self.assertEqual(self.call(path,body)[0],401,'Creator cookie must not grant moderation')
        self.assertEqual(self.operator(path,dict(body,checksum='0'*64))[0],409)
        self.assertEqual(self.operator(path,dict(body,reviewNote=''))[0],400)
        private=json.loads(self.call('/v1/studio/packs')[2])['packs']
        self.assertEqual(next(p for p in private if p['id']==self.pack['id'])['state'],'approved')
        self.assertTrue(any(p['id']==self.pack['id'] for p in json.loads(self.call('/v1/packs')[2])['packs']))
        self.assertEqual(self.operator(path,dict(body,decision='rejected'))[0],200)
        self.assertEqual(self.call(f"/v1/packs/{self.pack['id']}/versions/1")[0],404)
        self.approve_fixture()
        self.pack['version']=2;self.assertEqual(self.publish()[0],201)
        self.assertEqual(self.call(f"/v1/packs/{self.pack['id']}/versions/2")[0],200,'A new valid version is published directly')

    def test_report_quarantines_exact_bytes_and_preserves_original(self):
        self.login();self.publish();checksum=self.approve_fixture()
        public=f"/v1/packs/{self.pack['id']}/versions/1"
        original=self.call(public)[2]
        self.assertEqual(self.call(public+'/reports',{'reason':'privacy'},origin='https://other.invalid')[0],403)
        self.assertEqual(self.call(public+'/reports',{'reason':'unknown'})[0],400)
        status,_,data=self.call(public+'/reports',{'reason':'privacy'});self.assertEqual(status,202)
        report=json.loads(data)
        self.assertEqual(report['state'],'quarantined')
        self.assertEqual(json.loads(self.call(public+'/reports',{'reason':'privacy'})[2])['reportId'],report['reportId'])
        self.assertEqual(self.call(public)[0],404)
        self.assertEqual(self.call('/v1/packs')[1]['Cache-Control'],'no-store')
        self.assertEqual(self.operator(f"/v1/moderation/packs/{self.pack['id']}/versions/1")[2],original)
        _,headers,raw=self.operator('/v1/moderation/reports')
        self.assertIn('no-store',headers['Cache-Control'])
        reports=json.loads(raw)['reports']
        self.assertTrue(any(r['id']==report['reportId'] and r['checksum']==checksum and r['reason']=='privacy' for r in reports))
        self.cookies.clear();self.assertEqual(self.call(public+'/reports',{'reason':'other'})[0],401)

    def test_corrupt_original_cannot_be_approved(self):
        self.login();_,_,data=self.publish();checksum=json.loads(data)['checksum']
        import psycopg
        with psycopg.connect(os.environ['WEGOH_DATABASE_DSN']) as conn:
            self.assertTrue(conn.info.dbname.startswith('wegohcheck_'))
        from pathlib import Path
        file=Path(os.environ['WEGOH_CONTENT_DIR'])/checksum;original=file.read_bytes()
        try:
            file.write_bytes(original+b' changed')
            path=f"/v1/moderation/packs/{self.pack['id']}/versions/1"
            self.assertEqual(self.operator(path,dict(checksum=checksum,decision='approved',reviewer='isolated-test',reviewNote='Synthetic content'))[0],503)
            self.assertEqual(self.call(f"/v1/packs/{self.pack['id']}/versions/1")[0],503)
            self.assertEqual(self.call(f"/v1/local/packs/{self.pack['id']}/versions/1/reports",dict(reason='other',checksum=checksum),extra_headers={'X-WegoH-Local-Report':'1'})[0],503)
        finally:file.write_bytes(original)

    def test_local_vehicle_report_requires_explicit_scope_and_exact_bytes(self):
        self.login();self.publish();checksum=self.approve_fixture();self.cookies.clear()
        path=f"/v1/local/packs/{self.pack['id']}/versions/1/reports"
        body=dict(reason='harmful',checksum=checksum);headers={'X-WegoH-Local-Report':'1'}
        self.assertEqual(self.call(path,body)[0],403)
        self.assertEqual(self.call(path,body,extra_headers={'X-WegoH-Local-Report':'true'})[0],403)
        self.assertEqual(self.call(path,body,origin='https://other.invalid',extra_headers=headers)[0],403)
        self.assertEqual(self.call(path,body,origin='',extra_headers=headers)[0],403)
        self.assertEqual(self.call(path,dict(body,checksum='0'*64),extra_headers=headers)[0],409)
        self.assertEqual(self.call(path,dict(body,checksum='invalid'),extra_headers=headers)[0],400)
        self.assertEqual(self.call(path,dict(body,reason='unknown'),extra_headers=headers)[0],400)
        self.assertEqual(self.call(path,dict(body,latitude=37.4979),extra_headers=headers)[0],400,'Location fields must not enter this channel')
        self.assertEqual(self.call(path,raw=b'x'*262145,extra_headers=headers)[0],413)
        self.assertEqual(self.call('/v1/local/packs/missing/versions/1/reports',body,extra_headers=headers)[0],404)
        self.assertEqual(self.call(f"/v1/local/packs/{self.pack['id']}/versions/2/reports",body,extra_headers=headers)[0],404)
        status,_,raw=self.call(path,body,extra_headers=headers);self.assertEqual(status,202)
        report=json.loads(raw)
        self.assertEqual(json.loads(self.call(path,body,extra_headers=headers)[2])['reportId'],report['reportId'])
        self.assertEqual(self.call(f"/v1/packs/{self.pack['id']}/versions/1")[0],404)
        import psycopg
        with psycopg.connect(os.environ['WEGOH_DATABASE_DSN']) as conn:
            self.assertTrue(conn.info.dbname.startswith('wegohcheck_'))
            row=conn.execute('SELECT creator_id,reason,checksum FROM content_reports WHERE report_id=%s',(report['reportId'],)).fetchone()
        self.assertEqual(row,('local-vehicle','harmful',checksum))
        self.assertEqual(self.operator(f"/v1/moderation/packs/{self.pack['id']}/versions/1")[0],200,'Original must be retained')

    def test_local_report_rejects_real_nonloopback_peer(self):
        # UDP connect only selects a local route; no datagram is transmitted.
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as probe:
                probe.connect(('192.0.2.1',9));address=probe.getsockname()[0]
        except OSError:self.skipTest('No nonloopback local interface available')
        if ipaddress.ip_address(address).is_loopback:self.skipTest('No nonloopback local interface available')
        url=urllib.parse.urlsplit(BASE)
        connection=http.client.HTTPConnection(url.hostname,url.port,source_address=(address,0),timeout=10)
        try:
            connection.request('POST','/v1/local/packs/missing/versions/1/reports',json.dumps(dict(reason='other',checksum='0'*64)),
                               headers={'Origin':BASE,'Content-Type':'application/json','X-WegoH-Local-Report':'1'})
            response=connection.getresponse();response.read()
            self.assertEqual(response.status,403,'Actual nonloopback peer cannot claim the local vehicle channel')
        finally:connection.close()

    def test_local_report_route_is_absent_when_workspace_is_disabled(self):
        import asyncio
        from pathlib import Path
        from unittest.mock import patch
        from fastapi import HTTPException
        from starlette.requests import Request
        from studio import create_router
        endpoint=next(route.endpoint for route in create_router('unused',Path('.')).routes if route.path=='/v1/local/packs/{pack_id}/versions/{version}/reports')
        request=Request(dict(type='http',method='POST',scheme='http',server=('127.0.0.1',80),client=('127.0.0.1',12345),path='/',query_string=b'',headers=[]))
        with patch.dict(os.environ,WEGOH_LOCAL_STUDIO='0'):
            with self.assertRaises(HTTPException) as caught:asyncio.run(endpoint('missing',1,request))
        self.assertEqual(caught.exception.status_code,404)

if __name__ == '__main__':
    unittest.main(verbosity=2)
