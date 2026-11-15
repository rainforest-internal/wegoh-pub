"""Owned synthetic HTTP, permission and populated backup contracts for caution records."""
import copy
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import unittest
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import test_team_auth as fixture
from test_team_history import HistoryTests


class CautionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass(); __import__('api_application')
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=HistoryTests(methodName='test_01_owner_admin_and_personal_crud_capabilities');self.h.setUp()
        self.api=self.h.api;self.a,self.b,self.e=self.h.users()
    def call(self,path='',data=None,method='GET',session=None,who='alice',**options):
        return self.api.call('/v1/social/cautions'+path,data,method,session=session or self.a,who=who,**options)
    def body(self,**changes):
        value=dict(eventId=secrets.token_hex(16),kind='road-surface',observedAt='2026-01-02T02:00:00Z',
            placeSource=dict(kind='selected-place',place=dict(id='synthetic-public-place',provider='map',name='합성 공개 장소',
                address='합성 주소',latitude=37.5,longitude=127.0)),publicPlaceConfirmed=True,storageConsent=True,rightsConfirmed=True)
        value.update(changes);return value
    def create(self,**changes):
        body=self.body(**changes);status,_,value=self.call(data=body,method='POST')
        self.assertEqual(status,201,value);return value['id'],body
    def detail(self,item):
        status,_,value=self.call('/'+item);self.assertEqual(status,200,value);return value
    def approve(self,item):
        detail=self.detail(item)
        status,_,request=self.call('/'+item+'/review-request',dict(revision=detail['revision'],consent=True),'PATCH')
        self.assertEqual(status,200,request)
        status,_,value=self.api.call('/v1/moderation/content/caution/'+item,
            dict(checksum=request['review']['checksum'],decision='approved',reviewer='Synthetic admin',reviewNote='Synthetic place metadata only; not road truth'),
            'POST',session=self.a)
        self.assertEqual(status,200,value)
    def share(self,item):
        current=self.call('/'+item+'/shares')[2]
        return self.call('/'+item+'/shares/'+self.b['user']['id'],dict(revision=current['revision'],
            permissionRevision=current['permissionRevision'],consent=True,expiresInHours=1,rightsConfirmed=True),'PUT')
    def prepare_shared(self):
        self.h.make_friend(self.a,self.b);item,body=self.create();self.approve(item)
        self.assertEqual(self.share(item)[0],200)
        return item,body

    def test_01_exact_fields_explicit_storage_no_sdk_facts_and_native_requires_auth(self):
        for change in (dict(storageConsent=False),dict(publicPlaceConfirmed=False),dict(rightsConfirmed=False),
                       dict(observedAt=''),dict(kind='sdk-hard-braking'),dict(vehicleVerified=True)):
            self.assertEqual(self.call(data=self.body(**change),method='POST')[0],400)
        huge=self.body();huge['placeSource']['place']['latitude']=10**400
        self.assertEqual(self.call(data=huge,method='POST')[0],400)
        self.assertEqual(self.call(data=self.body(),method='POST',csrf=False)[0],403)
        item,_=self.create();detail=self.detail(item)
        self.assertFalse(detail['source']['physicalMeasurementVerified']);self.assertFalse(detail['currentRoadConditionVerified'])
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.assertEqual(self.api.native('/v1/social/cautions')[0],401)

    def test_02_uncertain_save_is_idempotent_body_change_and_deleted_nonce_conflict(self):
        item,body=self.create()
        status,_,again=self.call(data=body,method='POST');self.assertEqual(status,200,again);self.assertEqual(again['id'],item)
        self.assertEqual(self.call(data=dict(body,kind='other'),method='POST')[0],409)
        found=self.call('?eventId='+body['eventId'])[2]['items'];self.assertEqual([r['id']for r in found],[item])
        self.assertEqual(self.call('/'+item,method='DELETE')[0],200)
        self.assertEqual(self.call(data=body,method='POST')[0],409)
        with psycopg.connect(self.api.dsn)as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_cautions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_caution_receipts').fetchone()[0],1)

    def test_03_own_saved_visit_only_no_friend_history_or_media_copy(self):
        record=self.h.create(self.a);self.assertEqual(self.h.visit(record,self.a)[0],201)
        history=self.h.detail(record,self.a);visit=history['visits'][0]
        source=dict(kind='own-history-visit',historyId=record,visitId=visit['id'],revision=history['revision'])
        item,_=self.create(placeSource=source);stored=self.detail(item)
        self.assertEqual(stored['place']['name'],visit['place']['name'])
        self.assertNotIn('photos',stored);self.assertNotIn('review',stored['place']);self.assertNotIn('rating',stored)
        self.h.make_friend(self.a,self.b);self.h.share(record,self.a,self.b);self.h.approve_text(record,self.a)
        self.approve(item);self.assertEqual(self.share(item)[0],200)
        status,_,received=self.call('/'+item,session=self.b,who='bob');self.assertEqual(status,200,received)
        self.assertNotIn('placeSource',received);self.assertNotEqual(received['place']['id'],visit['id'])
        self.assertNotIn(record,json.dumps(received));self.assertNotIn(visit['id'],json.dumps(received))
        self.assertEqual(self.call(data=self.body(placeSource=source),method='POST',session=self.b,who='bob')[0],404)
        self.assertEqual(self.h.call('/history/'+record,method='DELETE',session=self.a)[0],200)
        self.assertEqual(self.detail(item)['place'],stored['place'])  # Explicit independent snapshot survives source deletion.

    def test_04_review_and_individual_sharing_are_distinct_and_recipient_is_redacted(self):
        self.h.make_friend(self.a,self.b);item,_=self.create()
        self.assertEqual(self.share(item)[0],409)
        self.approve(item);self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.assertEqual(self.share(item)[0],200)
        status,_,received=self.call('/'+item,session=self.b,who='bob');self.assertEqual(status,200,received)
        self.assertNotIn('placeSource',received);self.assertIsNone(received['permissionRevision'])
        self.assertNotIn('photos',received);self.assertFalse(received['currentRoadConditionVerified'])
        self.assertEqual(self.call('/'+item+'/shares',session=self.b,who='bob')[0],404)

    def test_05_expiry_stale_revoke_block_and_new_friendship_do_not_restore_access(self):
        item,_=self.prepare_shared()
        with self.api.websocket(self.b,who='bob')as socket:
            self.assertEqual(json.loads(socket.recv(timeout=3))['type'],'snapshot')
            self.assertEqual(self.call('/'+item+'/shares/'+self.b['user']['id'],method='DELETE')[0],200)
            event=json.loads(socket.recv(timeout=3));self.assertIn('cautions',event['resources'])
            self.assertNotIn(item,json.dumps(event));self.assertNotIn('latitude',json.dumps(event))
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.assertEqual(self.share(item)[0],200)
        self.assertEqual(self.h.call('/blocks',dict(targetId=self.b['user']['id']),'POST',session=self.a)[0],201)
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.h.call('/blocks/'+self.b['user']['id'],method='DELETE',session=self.a);self.h.make_friend(self.a,self.b)
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.assertEqual(self.share(item)[0],200)
        with psycopg.connect(self.api.dsn)as conn:conn.execute("UPDATE team_caution_shares SET expires_at=now()-interval '1 second' WHERE caution_id=%s",(item,))
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.assertEqual(self.call('/'+item)[0],200)  # Sharing expiry does not erase the owner's record.

    def test_06_edit_report_and_same_checksum_reapproval_require_new_sharing(self):
        item,body=self.prepare_shared()
        self.assertEqual(self.call('/'+item+'/reports',dict(reason='rights'),'POST',session=self.b,who='bob')[0],202)
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.approve(item)
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.assertEqual(self.share(item)[0],200)
        edit={key:value for key,value in body.items()if key!='eventId'};edit.update(revision=self.detail(item)['revision'],kind='other')
        self.assertEqual(self.call('/'+item,edit,'PUT')[0],200)
        self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)
        self.approve(item);self.assertEqual(self.call('/'+item,session=self.b,who='bob')[0],404)

    def test_07_encrypted_storage_current_owner_and_actual_typed_ten_operations(self):
        item,_=self.create()
        with psycopg.connect(self.api.dsn)as conn:
            raw=bytes(conn.execute('SELECT protected FROM team_cautions WHERE caution_id=%s',(item,)).fetchone()[0])
            self.assertNotIn('합성 공개 장소'.encode(),raw);self.assertNotIn(b'latitude',raw)
        broken=bytearray(raw);broken[-1]^=1
        with psycopg.connect(self.api.dsn)as conn:conn.execute('UPDATE team_cautions SET protected=%s WHERE caution_id=%s',(bytes(broken),item))
        try:self.assertEqual(self.call('/'+item)[0],503)
        finally:
            with psycopg.connect(self.api.dsn)as conn:conn.execute('UPDATE team_cautions SET protected=%s WHERE caution_id=%s',(raw,item))
        status,_,schema=self.api.call('/developer/openapi.json',session=self.a);self.assertEqual(status,200,schema)
        from api_doc_cautions import OPS,BODY
        self.assertEqual(len(OPS),10)
        for method,path in OPS:
            operation=schema['paths'][path][method]
            native_read=(method,path)in {('get','/v1/social/cautions'),('get','/v1/social/cautions/{item}')}
            self.assertEqual(operation['x-wegoh-surface'],'browser-and-native' if native_read else 'browser')
            self.assertEqual(operation['x-wegoh-native-access'],native_read)
            self.assertEqual(any('NativeMTLS'in security and'DeviceBearer'in security for security in operation['security']),native_read)
            if (method,path)in BODY:self.assertFalse(operation['requestBody']['content']['application/json']['schema']['additionalProperties'])
        listing=schema['paths']['/v1/social/cautions']['get']['parameters']
        self.assertEqual({p['name']for p in listing},{'cursor','eventId'})
        self.assertEqual(self.api.native('/v1/social/cautions/'+item)[0],401)
        self.assertEqual(self.call('/'+item,session=self.e,who='eve')[0],404)
        self.assertEqual(self.call('/'+item,method='DELETE',session=self.b,who='bob')[0],404)

    def test_09_manual_harsh_braking_requires_review_and_explicit_friend_grant(self):
        self.h.make_friend(self.a,self.b)
        item,body=self.create(kind="harsh-braking")
        own=self.detail(item)
        self.assertEqual(own["kind"],"harsh-braking")
        self.assertEqual(own["observedAt"],"2026-01-02T02:00:00+00:00")
        self.assertEqual(own["source"],dict(kind="user-observed",physicalMeasurementVerified=False))
        self.assertFalse(own["currentRoadConditionVerified"])
        self.assertEqual(self.call("/"+item+"/shares")[2]["grants"],[])
        self.assertEqual(self.call("/"+item,session=self.b,who="bob")[0],404)
        self.assertEqual(self.share(item)[0],409)
        self.approve(item)
        self.assertEqual(self.call("/"+item,session=self.b,who="bob")[0],404)
        self.assertEqual(self.share(item)[0],200)
        status,_,shared=self.call("/"+item,session=self.b,who="bob")
        self.assertEqual(status,200,shared)
        self.assertEqual(shared["kind"],"harsh-braking")
        self.assertEqual(shared["observedAt"],own["observedAt"])
        self.assertFalse(shared["source"]["physicalMeasurementVerified"])
        self.assertFalse(shared["currentRoadConditionVerified"])
        self.assertNotIn("placeSource",shared)
        self.assertEqual(self.call("/"+item+"/shares/"+self.b["user"]["id"],method="DELETE")[0],200)
        self.assertEqual(self.call("/"+item,session=self.b,who="bob")[0],404)
        self.assertEqual(self.detail(item)["kind"],"harsh-braking")
        from api_doc_cautions import KIND
        self.assertIn("harsh-braking",KIND["enum"])

    def test_08_populated_three_tables_exact_encrypted_snapshot_and_restore(self):
        item,_=self.prepare_shared();source=fixture.ROOT/'server/ops/live/backup.py'
        spec=importlib.util.spec_from_file_location('caution_backup_contract',source)
        backup=importlib.util.module_from_spec(spec);sys.modules[spec.name]=backup;spec.loader.exec_module(backup)
        tables=('team_cautions','team_caution_shares','team_caution_receipts')
        with psycopg.connect(self.api.dsn)as conn:
            before={table:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]for table in tables}
            self.assertTrue(all(before.values()));conn.execute((fixture.ROOT/'server/schema.sql').read_text())
            self.assertEqual(before,{table:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]for table in tables})
        work=self.api.state/('caution-backup-'+secrets.token_hex(8));work.mkdir(mode=0o700)
        base=work/'snapshots';base.mkdir(mode=0o700);tool=Path(self.api.tools['pg_ctl']).parent
        layout=backup.Layout(self.api.dsn,self.api.state/'content',base,str(tool/'pg_dump'),str(tool/'pg_restore'))
        name='caution_restore_'+secrets.token_hex(6)
        with psycopg.connect(self.api.dsn,autocommit=True)as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        try:
            snapshot=backup.snapshot(layout);target=make_conninfo(self.api.dsn,dbname=name)
            restored=work/'restore';restored.mkdir(mode=0o700)
            self.assertTrue(backup.verify_into(layout,snapshot,target,restored)['verified'])
            with psycopg.connect(target)as conn:
                self.assertEqual(before,{table:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]for table in tables})
        finally:
            with psycopg.connect(self.api.dsn,autocommit=True)as conn:
                conn.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s',(name,))
                conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
