"""Owned synthetic TLS1.3/PG report contracts. No physical GPS/vehicle or Cloudflare claim."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import http.client
import importlib.util
import json
from pathlib import Path
import secrets
import ssl
import sys
import threading
import unittest
from unittest.mock import patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
import test_enrollment
import test_native_functional_business as current_fixture

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import test_native_mtls as mtls
import test_team_rooms as room_fixture
from test_team_rooms import choices
import test_team_auth as fixture


class VehicleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mtls.NativeMTLSTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        mtls.NativeMTLSTests.tearDownClass()

    def setUp(self):
        self.n=mtls.NativeMTLSTests('test_01_real_tls_certificate_and_protocol_floor')
        self.n.setUp()
        self.h=room_fixture.RoomTests('test_18_room_owner_member_roles_and_explicit_close')
        self.dsn=self.h.dsn
        self.factory=current_fixture.FunctionalBusinessTests();self.factory.h=self.h;self.factory.certificates={}
        self.contexts={};self.fingerprints={};self.revisions={}

    def call(self,path,data=None,method='GET',session=None,who='alice',**kw):
        code,_,value=self.h.call(path,data,method,session=session,who=who,**kw)
        return code,value

    def native(self,path,data=None,method='GET',token=None,**kwargs):
        if data is not None and method!='GET':data=dict(data,functionalRevision=self.revisions[token])
        return self.n.native(path,data,method,token=token,context=self.contexts.get(token),**kwargs)

    def websocket(self,token):
        self.n.clients['a']=(self.contexts[token],self.fingerprints[token])
        return self.n.websocket(token)

    def device(self,session,who='alice'):
        # Keep actual TLS: public-v1 approval issues the CSR leaf signed by the
        # existing owned edge CA, with a distinct client context per credential.
        key,csr=test_enrollment.make_csr();issuer=test_enrollment.SyntheticIssuer()
        issuer.key=serialization.load_pem_private_key((self.h.state/'synthetic-ca.key').read_bytes(),password=None)
        issuer.name=x509.load_pem_x509_certificate((self.h.state/'synthetic-ca.crt').read_bytes()).subject
        certificates=[];response=issuer.response
        def capture(csr):
            value=response(csr);certificates.append(value['certificate']);return value
        with patch.object(test_enrollment,'make_csr',return_value=(key,csr)),patch.object(test_enrollment,'SyntheticIssuer',return_value=issuer),patch.object(issuer,'response',side_effect=capture):
            token=self.factory.connect(session,who)
        self.assertEqual(len(certificates),1)
        directory=self.h.state/('report-client-'+secrets.token_hex(8));directory.mkdir(mode=0o700)
        cert_path=directory/'client.pem';cert_path.write_text(certificates[0]);cert_path.chmod(0o600)
        key_path=directory/'client.key';key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key_path.chmod(0o600)
        context=ssl.create_default_context(cafile=str(self.h.state/'synthetic-ca.crt'));context.minimum_version=ssl.TLSVersion.TLSv1_3;context.load_cert_chain(str(cert_path),str(key_path))
        fingerprint=x509.load_pem_x509_certificate(cert_path.read_bytes()).fingerprint(hashes.SHA256()).hex()
        self.assertEqual(fingerprint,self.factory.certificates[token['grantId']])
        self.contexts[token['accessToken']]=context;self.fingerprints[token['accessToken']]=fingerprint;self.revisions[token['accessToken']]=0
        return token

    def snapshot(self,session,token,room=None,who='alice'):
        path='/v1/devices/'+token['deviceId']+'/vehicle-domain'
        if room:path+='?roomId='+room['id']
        code,value=self.call(path,session=session,who=who)
        self.assertEqual(code,200,value)
        return value

    def prepare(self,allowed=True,receiver_device=True):
        a,b,e=self.h.sessions()
        self.assertEqual(self.h.friend('/friends/requests',{'targetId':b['user']['id']},'POST',session=a)[0],201)
        self.assertEqual(self.h.friend('/friends/requests/'+a['user']['id']+'/respond',{'accept':True},'POST',who='bob',session=b)[0],200)
        pack=self.h.pack();pack['stops'].append(dict(pack['stops'][0],id='second',name='Second synthetic stop',latitude=37.51,longitude=127.01))
        self.assertEqual(self.h.publish(pack,a)[0],201);self.assertEqual(self.h.approve(pack,a)[0],200)
        room=self.h.new_room(a,courseId=pack['id'],courseVersion=pack['version'])
        self.assertEqual(self.h.join(b,room['code'],status=True,location=True)[0],200)
        self.assertEqual(self.call('/v1/social/rooms/'+room['id']+'/consents',{'consents':choices(status=True,location=True)},'PATCH',session=a)[0],200)
        ta=self.device(a);tb=self.device(b,'bob') if receiver_device else None
        if allowed:
            self.permission(a,ta,location=True,visits=True)
            self.grant(a,ta,room,shareLocation=True,shareVisits=True)
            self.receive(b,room,who='bob',receiveLocation=True,receiveVisits=True)
        return a,b,e,room,pack,ta,tb

    def permission(self,session,token,who='alice',**purposes):
        path='/v1/devices/'+token['deviceId']+'/functional-permissions'
        code,current=self.call(path,session=session,who=who);self.assertEqual(code,200,current)
        approved=set(current['approvedPurposes'])
        for key,value in purposes.items():
            purpose={'location':'vehicle-location:report','visits':'vehicle-visits:report'}[key]
            if value:approved.add(purpose)
            else:approved.discard(purpose)
        self.revisions[token['accessToken']]=self.factory.approve(session,token,sorted(approved),who)
        return self.snapshot(session,token,who=who)

    def grant(self,session,token,room,who='alice',**flags):
        current=self.snapshot(session,token,room,who)
        value=current['roomReporting']
        body=dict(deviceId=token['deviceId'],revision=value['revision'],joinedAt=value['joinedAt'],
            devicePermissionRevision=current['revision'],shareLocation=False,shareVisits=False,
            receiveLocation=False,receiveVisits=False,expiresInHours=1)
        body.update(flags)
        code,result=self.call('/v1/social/rooms/'+room['id']+'/device-reporting',body,'PUT',session,who)
        self.assertEqual(code,200,result);return result,body

    def receive(self,session,room,who='bob',**flags):
        path='/v1/social/rooms/'+room['id']+'/report-receiving'
        code,current=self.call(path,session=session,who=who);self.assertEqual(code,200,current)
        body=dict(revision=current['revision'],joinedAt=current['joinedAt'],receiveLocation=False,receiveVisits=False,expiresInHours=1)
        body.update(flags);code,value=self.call(path,body,'PUT',session,who)
        self.assertEqual(code,200,value);return value,body

    def location(self,session,token,room,**extra):
        current=self.snapshot(session,token,room)
        body=dict(eventId=secrets.token_hex(16),devicePermissionRevision=current['revision'],
            roomRevision=current['roomReporting']['revision'],capturedAt=datetime.now(timezone.utc).isoformat(),
            latitude=37.5,longitude=127.0,accuracyMeters=None)
        body.update(extra)
        code,value=self.native('/v1/native/rooms/'+room['id']+'/reports/location',body,'POST',token=token['accessToken'])
        return code,value,body

    def visits(self,session,token,room,pack,**extra):
        current=self.snapshot(session,token,room)
        body=dict(eventId=secrets.token_hex(16),devicePermissionRevision=current['revision'],
            roomRevision=current['roomReporting']['revision'],capturedAt=datetime.now(timezone.utc).isoformat(),
            courseId=pack['id'],courseVersion=pack['version'],checkpoint=1)
        body.update(extra)
        code,value=self.native('/v1/native/rooms/'+room['id']+'/reports/visits',body,'POST',token=token['accessToken'])
        return code,value,body

    def received(self,session,room,who='bob'):
        code,value=self.call('/v1/social/rooms/'+room['id']+'/device-reports',session=session,who=who)
        self.assertEqual(code,200,value);return value['reports']

    def test_01_default_off_exact_owner_host_csrf_and_held_body_logout(self):
        a,b,e,room,pack,ta,tb=self.prepare(False)
        current=self.snapshot(a,ta,room)
        self.assertEqual(current['reporting'],dict(location=False,visits=False))
        self.assertEqual(current['supportedControlActions'],[]);self.assertIsNone(current['latestLocation'])
        code,own=self.native('/v1/device/vehicle-domain',token=ta['accessToken']);self.assertEqual(code,200,own);self.assertEqual(own['reporting'],dict(location=False,visits=False));self.assertEqual(own['supportedControlActions'],[])
        self.assertEqual(self.location(a,ta,room)[0],403)
        path='/v1/devices/'+ta['deviceId']+'/reporting-permissions'
        data=dict(revision=0,purposes=dict(location=True,visits=False),expiresInHours=1)
        self.assertEqual(self.call(path,data,'PUT',a,csrf=False)[0],403)
        self.assertEqual(self.call(path,data,'PUT',b,'bob')[0],404)
        self.assertEqual(self.native(path,data,'PUT',token=ta['accessToken'])[0],404)
        original=self.h.server.config.loaded_app;received=threading.Event();release=threading.Event()
        async def observed(scope,receive,send):
            async def tracked():
                message=await receive()
                if scope.get('path')==path and message.get('more_body') and message.get('body'):received.set()
                return message
            await original(scope,tracked,send)
        self.h.server.config.loaded_app=observed
        raw=json.dumps(data).encode();middle=len(raw)//2
        def send():
            def chunks():
                yield raw[:middle]
                if not release.wait(5):raise RuntimeError('Owned body release missing')
                yield raw[middle:]
            conn=http.client.HTTPConnection('127.0.0.1',self.h.port,timeout=6)
            headers={'Host':'web.wegoh.invalid','Content-Type':'application/json','Origin':fixture.WEB,
                'Cookie':a['cookie'],'X-WegoH-CSRF':a['csrfToken'],'Cf-Access-Jwt-Assertion':self.h.assertion(),'Transfer-Encoding':'chunked'}
            try:
                conn.request('PUT',path,body=chunks(),headers=headers,encode_chunked=True)
                response=conn.getresponse();response.read();return response.status
            finally:conn.close()
        try:
            with ThreadPoolExecutor(max_workers=1)as pool:
                future=pool.submit(send)
                try:
                    self.assertTrue(received.wait(4));self.assertEqual(self.call('/v1/auth/session',method='DELETE',session=a)[0],200)
                finally:release.set()
                self.assertEqual(future.result(timeout=8),401)
        finally:release.set();self.h.server.config.loaded_app=original
        with psycopg.connect(self.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_purposes').fetchone()[0],0)

    def test_02_actual_tls_sender_and_carless_web_bilateral_receiving(self):
        a,b,e,room,pack,ta,tb=self.prepare(receiver_device=False)
        self.assertIsNone(tb)
        self.assertEqual(self.call('/v1/devices',session=b,who='bob')[1]['devices'],[])
        code,result,body=self.location(a,ta,room)
        self.assertEqual(code,200,result);self.assertEqual(result['status'],'accepted')
        rows=self.received(b,room);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['accountId'],a['user']['id']);self.assertEqual(rows[0]['location']['latitude'],37.5)
        self.assertIsNone(rows[0]['location']['accuracyMeters']);self.assertFalse(rows[0]['location']['accuracyVerified'])
        self.assertEqual(self.call('/v1/social/rooms/'+room['id']+'/report-receiving',method='DELETE',session=b,who='bob')[0],200)
        self.assertEqual(self.received(b,room),[])
        self.receive(b,room,receiveLocation=True)
        self.assertEqual(len(self.received(b,room)),1)
        self.assertEqual(self.call('/v1/devices',session=b,who='bob')[1]['devices'],[])
        with psycopg.connect(self.dsn)as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_devices WHERE account_id=%s',(b['user']['id'],)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_purposes WHERE account_id=%s',(b['user']['id'],)).fetchone()[0],0)

    def test_03_idempotency_and_coordinate_time_latest_boundaries(self):
        a,b,e,room,pack,ta,tb=self.prepare()
        code,first,body=self.location(a,ta,room);self.assertEqual(code,200,first)
        path='/v1/native/rooms/'+room['id']+'/reports/location'
        code,same=self.native(path,body,'POST',token=ta['accessToken']);self.assertEqual(code,200);self.assertEqual(same['status'],'duplicate');self.assertEqual(same['receivedAt'],first['receivedAt'])
        self.assertEqual(self.native(path,dict(body,latitude=38),'POST',token=ta['accessToken'])[0],409)
        for patch in [dict(latitude=True),dict(latitude=91),dict(latitude=10**400),dict(longitude=-(10**400)),dict(accuracyMeters=10**400),dict(accuracyMeters=-1),dict(capturedAt='2026-10-28T00:00:00'),dict(capturedAt=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()),dict(capturedAt=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat())]:
            self.assertEqual(self.location(a,ta,room,**patch)[0],400,patch)
        self.assertEqual(self.location(a,ta,room,capturedAt=body['capturedAt'])[0],409)
        with psycopg.connect(self.dsn)as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_report_receipts').fetchone()[0],1)

    def test_04_revoke_reallow_old_nonce_never_revives_report(self):
        a,b,e,room,pack,ta,tb=self.prepare();code,result,body=self.location(a,ta,room);self.assertEqual(code,200)
        path='/v1/devices/'+ta['deviceId']+'/functional-permissions/vehicle-location:report'
        code,revoked=self.call(path,method='DELETE',session=a);self.assertEqual(code,200,revoked)
        self.revisions[ta['accessToken']]=revoked['revision']
        self.assertEqual(self.received(b,room),[])
        self.permission(a,ta,location=True,visits=True)
        self.assertEqual(self.location(a,ta,room)[0],403)
        self.grant(a,ta,room,shareLocation=True,shareVisits=True)
        self.assertEqual(self.received(b,room),[])
        self.assertEqual(self.native('/v1/native/rooms/'+room['id']+'/reports/location',body,'POST',token=ta['accessToken'])[0],409)
        self.assertEqual(self.location(a,ta,room)[0],200)
        self.assertEqual(self.call('/v1/devices/'+ta['deviceId'],method='DELETE',session=a)[0],200)
        self.assertEqual(self.received(b,room),[])
        self.assertEqual(self.native('/v1/device/vehicle-domain',token=ta['accessToken'])[0],401)

    def test_05_leave_rejoin_block_expiry_and_current_receiving_epoch(self):
        a,b,e,room,pack,ta,tb=self.prepare();self.assertEqual(self.location(a,ta,room)[0],200)
        _,old=self.receive(b,room,who='bob',receiveLocation=True,receiveVisits=True)
        self.assertEqual(self.call('/v1/social/rooms/'+room['id']+'/leave',method='POST',session=b,who='bob')[0],200)
        self.assertEqual(self.h.join(b,room['code'],status=True,location=True)[0],200)
        self.assertEqual(self.received(b,room),[])
        self.assertEqual(self.call('/v1/social/rooms/'+room['id']+'/report-receiving',old,'PUT',b,'bob')[0],409)
        self.receive(b,room,who='bob',receiveLocation=True)
        self.assertEqual(len(self.received(b,room)),1)
        self.assertEqual(self.h.friend('/blocks',{'targetId':a['user']['id']},'POST',who='bob',session=b)[0],201)
        self.assertEqual(self.call('/v1/social/rooms/'+room['id']+'/device-reports',session=b,who='bob')[0],404)
        self.assertEqual(self.h.friend('/blocks/'+a['user']['id'],method='DELETE',who='bob',session=b)[0],200)
        with psycopg.connect(self.dsn)as conn:conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 second' WHERE room_id=%s",(room['id'],))
        self.assertEqual(self.location_snapshot_status(a,ta,room),404)

    def location_snapshot_status(self,a,ta,room):
        return self.call('/v1/devices/'+ta['deviceId']+'/vehicle-domain?roomId='+room['id'],session=a)[0]

    def test_06_visits_exact_approved_course_source_and_no_history_copy(self):
        a,b,e,room,pack,ta,tb=self.prepare()
        for patch in [dict(courseVersion=True),dict(courseVersion=2),dict(checkpoint=0),dict(checkpoint=3),dict(courseId='missing')]:
            self.assertIn(self.visits(a,ta,room,pack,**patch)[0],(400,409),patch)
        code,result,_=self.visits(a,ta,room,pack);self.assertEqual(code,200,result)
        visit=self.received(b,room)[0]['visit'];self.assertEqual(visit['checkpoint'],1);self.assertEqual(visit['source'],'user-confirmed');self.assertFalse(visit['physicalArrivalVerified'])
        with psycopg.connect(self.dsn)as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_history_visits').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM visited_places').fetchone()[0],0)
            from test_course_moderation_fixture import restrict_course
            for (checksum,) in conn.execute('SELECT checksum FROM pack_versions').fetchall():
                restrict_course(conn, checksum, state='quarantined')
        self.assertEqual(self.visits(a,ta,room,pack)[0],409)
        self.assertEqual(self.received(b,room),[])

    def test_07_selected_native_receiver_and_live_resource_invalidation(self):
        a,b,e,room,pack,ta,tb=self.prepare();self.assertEqual(self.location(a,ta,room)[0],200)
        self.assertEqual(self.native('/v1/native/rooms/'+room['id']+'/device-reports',token=tb['accessToken'])[0],403)
        self.assertEqual(self.call('/v1/devices/'+tb['deviceId'],method='DELETE',session=b,who='bob')[0],200)
        self.assertEqual(self.native('/v1/native/rooms/'+room['id']+'/device-reports',token=tb['accessToken'])[0],401)
        other=self.device(b,'bob')
        self.grant(b,other,room,who='bob',receiveLocation=True)
        current=self.snapshot(b,other,room,'bob');self.assertEqual(current['roomReporting']['receiverDeviceId'],other['deviceId'])
        self.revisions[other['accessToken']]=self.factory.approve(b,other,['rooms:read','vehicle-reports:read'],'bob')
        path='/v1/native/rooms/'+room['id']+'/device-reports'
        self.assertEqual(self.native(path,token=tb['accessToken'])[0],401)
        self.assertEqual(len(self.native(path,token=other['accessToken'])[1]['reports']),1)
        self.assertEqual(self.call('/v1/social/rooms/'+room['id']+'/report-receiving',method='DELETE',session=b,who='bob')[0],200)
        self.assertEqual(self.received(b,room),[])
        self.assertEqual(len(self.native(path,token=other['accessToken'])[1]['reports']),1)
        self.revisions[other['accessToken']]=self.factory.approve(b,other,[],'bob')
        self.assertEqual(self.native(path,token=other['accessToken'])[0],403)
        self.revisions[other['accessToken']]=self.factory.approve(b,other,['rooms:read','vehicle-reports:read'],'bob')
        with psycopg.connect(self.dsn)as conn:
            before=dict(conn.execute('SELECT resource,revision FROM team_resource_versions WHERE account_id=%s',(b['user']['id'],)))
        with self.websocket(other['accessToken'])as native_ws:
            initial=json.loads(native_ws.recv(timeout=3));self.assertEqual(initial['type'],'snapshot')
            # Current public-v1 events expose only the approved base resources.
            self.assertEqual(set(initial['resources']),{'courses','devices','playlists'})
            with self.h.websocket(b,who='bob')as ws:
                web_initial=json.loads(ws.recv(timeout=3));self.assertEqual(web_initial['type'],'snapshot');self.assertIn('vehicle',web_initial['resources'])
                self.assertEqual(self.call('/v1/devices/'+ta['deviceId'],method='DELETE',session=a)[0],200)
                event=json.loads(ws.recv(timeout=3));self.assertEqual(event['type'],'invalidate');self.assertIn('rooms',event['resources'])
            self.assertEqual(json.loads(native_ws.recv(timeout=3)),dict(type='invalidate',epoch=initial['epoch'],seq=1,resources=['devices']))
        with psycopg.connect(self.dsn)as conn:after=dict(conn.execute('SELECT resource,revision FROM team_resource_versions WHERE account_id=%s',(b['user']['id'],)))
        self.assertGreater(after['rooms'],before['rooms']);self.assertEqual(self.native(path,token=other['accessToken'])[1]['reports'],[])

    def test_08_populated_four_tables_actual_encrypted_backup_restore(self):
        a,b,e,room,pack,ta,tb=self.prepare();self.assertEqual(self.location(a,ta,room)[0],200);self.assertEqual(self.visits(a,ta,room,pack)[0],200)
        source=Path(__file__).parent/'ops/live/backup.py';spec=importlib.util.spec_from_file_location('vehicle_backup_contract',source)
        backup=importlib.util.module_from_spec(spec);sys.modules[spec.name]=backup;spec.loader.exec_module(backup)
        work=self.h.state/('vehicle-backup-'+secrets.token_hex(8));work.mkdir(mode=0o700);base=work/'snapshots';base.mkdir(mode=0o700)
        tool=Path(self.h.tools['pg_ctl']).parent;layout=backup.Layout(self.dsn,self.h.state/'content',base,str(tool/'pg_dump'),str(tool/'pg_restore'))
        name='vehicle_restore_'+secrets.token_hex(6)
        with psycopg.connect(self.dsn,autocommit=True)as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        try:
            with psycopg.connect(self.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*) FROM native_functional_authorizations').fetchone()[0],1)
            snapshot=backup.snapshot(layout);target=make_conninfo(self.dsn,dbname=name);restored=work/'restore';restored.mkdir(mode=0o700)
            self.assertTrue(backup.verify_into(layout,snapshot,target,restored)['verified'])
            with psycopg.connect(target)as conn:
                counts={t:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(t))).fetchone()[0]for t in ('team_vehicle_purposes','team_vehicle_room_grants','team_vehicle_latest_reports','team_vehicle_report_receipts')}
                self.assertEqual(counts,dict(team_vehicle_purposes=0,team_vehicle_room_grants=2,team_vehicle_latest_reports=2,team_vehicle_report_receipts=2))
                # Current report authority is separate and excluded from backups.
                self.assertEqual(conn.execute('SELECT count(*) FROM native_functional_authorizations').fetchone()[0],0)
                raw=conn.execute('SELECT protected FROM team_vehicle_latest_reports WHERE kind=%s',('location',)).fetchone()[0]
                self.assertNotIn(b'latitude',bytes(raw));value=self.h.module.TEAM_VEHICLE.restore('latest',a['user']['id'],room['id']+':'+ta['deviceId']+':location',raw)
                self.assertEqual(value['report']['latitude'],37.5)
            self.assertEqual(len(self.received(b,room)),1)
        finally:
            with psycopg.connect(self.dsn,autocommit=True)as conn:conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


    def test_09_linked_trip_preserves_finite_grants_and_rejects_closed_reports(self):
        from fastapi import HTTPException
        from trip_room_migration import TripRoomMigration
        a,b,e,room,pack,ta,tb=self.prepare()
        self.assertEqual(self.location(a,ta,room)[0],200)
        service=self.h.module.TEAM_VEHICLE;trips=self.h.module.TEAM_TRIPS
        owner=a['user']['id'];rid=room['id']
        with psycopg.connect(self.dsn)as conn:
            original=conn.execute('SELECT protected,expires_at FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,owner)).fetchone()
            receipts=conn.execute('SELECT protected FROM team_vehicle_report_receipts ORDER BY event_id').fetchall()
            histories=conn.execute('SELECT protected FROM team_histories ORDER BY history_id').fetchall()
            TripRoomMigration(self.h.module.TEAM_AUTH).migrate_room(conn,rid)
            trip=conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s',(rid,)).fetchone()[0]
            self.assertEqual(conn.execute('SELECT protected,expires_at FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,owner)).fetchone(),original)
            self.assertIsNone(service.member(conn,rid,owner,trip_context=True)[0]['expiresAt'])
            self.assertIsNone(service.latest(conn,rid,owner,ta['deviceId'],'location',trip_context=True))
            with self.assertRaises(HTTPException)as denied:service.member(conn,rid,owner)
            self.assertEqual(denied.exception.status_code,409)
            revision=conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0]
            trips.transition(conn,trip,owner,'finish',revision)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports WHERE room_id=%s',(rid,)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT protected FROM team_vehicle_report_receipts ORDER BY event_id').fetchall(),receipts)
            self.assertEqual(conn.execute('SELECT protected FROM team_histories ORDER BY history_id').fetchall(),histories)
            for read in (lambda:service.sender(conn,rid,owner,ta['deviceId'],'location',trip_context=True),
                         lambda:service.reports(conn,rid,b['user']['id'],trip_context=True)):
                with self.assertRaises(HTTPException)as denied:read()
                self.assertEqual(denied.exception.status_code,409)
            service.withdraw_trip_context(conn,trip,rid)
        self.assertEqual(self.call('/v1/social/rooms/'+rid+'/device-reports',session=a)[0],409)
        self.assertEqual(self.call('/v1/social/rooms/'+rid+'/device-reports',session=e,who='eve')[0],404)

    def test_10_trip_planning_expiry_and_member_generation(self):
        from fastapi import HTTPException
        from trip_room_migration import TripRoomMigration
        a,b,e,room,pack,ta,tb=self.prepare()
        service=self.h.module.TEAM_VEHICLE;trips=self.h.module.TEAM_TRIPS
        owner=a['user']['id'];peer=b['user']['id'];rid=room['id']
        with psycopg.connect(self.dsn)as conn:
            TripRoomMigration(self.h.module.TEAM_AUTH).migrate_room(conn,rid)
            trip=conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s',(rid,)).fetchone()[0]
            conn.execute("UPDATE team_trips SET state='planned',started_at=NULL WHERE trip_id=%s",(trip,))
        code,result=self.call('/v1/social/trips/'+trip+'/location-sharing',dict(locationConsent=True),'PATCH',session=a)
        self.assertEqual(code,200,result)
        with psycopg.connect(self.dsn)as conn:
            _,value,revision,_=service.room_grants(conn,rid,owner,trip_context=True)
            data=dict(deviceId=ta['deviceId'],revision=revision,joinedAt=value['joinedAt'],
                devicePermissionRevision=self.revisions[ta['accessToken']],shareLocation=True,shareVisits=True,
                receiveLocation=False,receiveVisits=False,expiresInHours=24)
            before=service.now(conn);service.update_room(conn,rid,owner,data,trip_context=True)
            _,value,_,_=service.room_grants(conn,rid,owner,trip_context=True)
            expiry=datetime.fromisoformat(value['devices'][ta['deviceId']]['expiresAt'])
            self.assertLessEqual(expiry,service.purposes(conn,owner,ta['deviceId'])[3])
            self.assertLessEqual(expiry,service.now(conn)+timedelta(hours=24));self.assertGreater(expiry,before)
            with self.assertRaises(HTTPException)as denied:service.sender(conn,rid,owner,ta['deviceId'],'location',trip_context=True)
            self.assertEqual(denied.exception.status_code,409)
            revision=conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0]
            trips.transition(conn,trip,owner,'start',revision)
            _,value,_,saved_expiry=service.room_grants(conn,rid,owner,trip_context=True)
            value['devices'][ta['deviceId']]['expiresAt']=(service.now(conn)-timedelta(seconds=1)).isoformat()
            service.store_room(conn,rid,owner,value,saved_expiry)
            with self.assertRaises(HTTPException)as denied:service.sender(conn,rid,owner,ta['deviceId'],'location',trip_context=True)
            self.assertEqual(denied.exception.status_code,403)
            trips.remove_member(conn,trip,peer)
            with self.assertRaises(HTTPException)as denied:service.reports(conn,rid,peer,trip_context=True)
            self.assertEqual(denied.exception.status_code,404)
            trips.save_member(conn,trip,peer,'accepted','link')
            _,reset,_,_=service.room_grants(conn,rid,peer,trip_context=True)
            self.assertEqual(reset['devices'],{});self.assertFalse(reset['receiveLocation'])


    def test_11_migrated_trip_shares_fresh_locations_and_preserves_visit_policy(self):
        from trip_room_migration import TripRoomMigration
        owner, friend, stranger, room, pack, car, _ = self.prepare(receiver_device=False)
        self.assertEqual(self.location(owner, car, room)[0], 200)
        self.assertEqual(self.visits(owner, car, room, pack)[0], 200)
        with psycopg.connect(self.dsn) as conn:
            TripRoomMigration(self.h.module.TEAM_AUTH).migrate_room(conn, room['id'])
            trip = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s', (room['id'],)).fetchone()[0]
        path = '/v1/social/trips/' + trip

        def web(session, endpoint, data=None, method='GET', status=200):
            code, value = self.call(endpoint, data, method, session=session, who=session['user']['displayName'])
            self.assertEqual(code, status, value)
            return value

        def reports(session):
            return web(session, path + '/device-reports')['reports']

        def consent(enabled):
            return web(owner, path + '/location-sharing', dict(locationConsent=enabled), 'PATCH')

        def send_location(revision, seconds_ago=0):
            captured_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
            data = dict(eventId=secrets.token_hex(16), capturedAt=captured_at.isoformat(),
                latitude=37.6, longitude=127.1, accuracyMeters=7.0, reportingRevision=revision,
                devicePermissionRevision=self.revisions[car['accessToken']])
            return self.native('/v1/native/trips/' + trip + '/reports/location', data, 'POST', token=car['accessToken'])[0]

        snapshot = '/v1/devices/' + car['deviceId'] + '/trips/' + trip + '/vehicle-domain'
        before = web(owner, snapshot)['tripReporting']['revision']
        legacy = reports(friend)
        self.assertEqual(len(legacy), 1)
        self.assertIsNone(legacy[0]['location'])
        self.assertEqual(legacy[0]['visit']['courseId'], pack['id'])
        token = web(owner, path + '/link', {}, 'POST', 201)['token']
        web(stranger, '/v1/social/trip-links/join', dict(token=token, locationConsent=False), 'POST')
        self.assertEqual(reports(stranger), [])
        consent(True)
        self.assertEqual(reports(stranger), [])
        self.assertIn(send_location(before), (403, 409))
        current = web(owner, snapshot)['tripReporting']['revision']
        self.assertEqual(send_location(current, seconds_ago=90), 200)
        self.assertEqual(reports(stranger), [])
        self.assertEqual(send_location(current), 200)
        self.assertEqual(reports(stranger)[0]['location']['latitude'], 37.6)
        self.assertIsNone(reports(stranger)[0]['visit'])
        self.assertEqual(reports(friend)[0]['visit']['courseId'], pack['id'])
        web(friend, '/v1/social/friends/' + owner['user']['id'], method='DELETE')
        self.assertIsNone(reports(friend)[0]['visit'])
        consent(False)
        self.assertEqual(reports(stranger), [])
        self.assertIn(send_location(current), (403, 409))
        consent(True)
        self.assertEqual(reports(stranger), [])
        self.assertIn(send_location(current), (403, 409))


class TripVehicleContractTests(unittest.TestCase):
    def test_trip_snapshot_hides_internal_room_fields(self):
        from team_vehicle import TeamVehicle
        value=dict(deviceId='device',roomId='internal-room',roomReporting=dict(roomId='internal-room',revision=4,expiresAt='finite'))
        result=TeamVehicle.trip_result(value,'trip')
        self.assertNotIn('roomId',result);self.assertNotIn('roomReporting',result)
        self.assertEqual(result['tripId'],'trip')
        self.assertEqual(result['tripReporting'],dict(revision=4,expiresAt='finite'))
        self.assertEqual(value['roomId'],'internal-room')

    def test_trip_routers_expose_reports_commands_and_friend_remotes_once(self):
        from types import SimpleNamespace
        from team_vehicle import TeamVehicle
        from team_device_commands import TeamDeviceCommands
        from friend_vehicle_controls import FriendVehicleControls
        from fastapi.routing import iter_route_contexts
        from fastapi.openapi.utils import _get_api_route_for_openapi
        auth=SimpleNamespace(enabled=True,dsn='unused');rooms=SimpleNamespace(enabled=True)
        vehicle=TeamVehicle(auth,rooms);commands=TeamDeviceCommands(auth,rooms)
        commands.friend_controls=FriendVehicleControls(commands)
        routes=vehicle.trip_router().routes+commands.trip_router().routes
        effective=[_get_api_route_for_openapi(context)for context in iter_route_contexts(routes)]
        keys=[(method,route.path)for route in effective if route is not None for method in route.methods]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertIn(('POST','/v1/native/trips/{trip}/reports/location'),keys)
        self.assertIn(('GET','/v1/social/trips/{trip}/vehicle-remotes'),keys)
        self.assertIn(('DELETE','/v1/social/trips/{room}/device-command-access'),keys)
        self.assertTrue(all('/trips/'in path for _,path in keys))


if __name__=='__main__':unittest.main()
