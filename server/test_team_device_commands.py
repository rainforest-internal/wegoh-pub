"""Owned synthetic PG/TLS1.3 command contracts; no Vehicle/HVAC/production data."""
from pathlib import Path
import datetime as dt
import importlib.util
import json
import secrets
import ssl
import sys
import unittest
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import test_native_mtls as mtls_fixture
import test_team_rooms as room_fixture
from device_command_registry import ProductionCommandRegistry

class EmptyCommandRegistry:
    def describe(self):return []
    def lookup(self,identifier,revision):return None

import test_team_missions as mission_fixture
import test_enrollment
import test_native_functional_business as current_fixture
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

ACTION=dict(id='fixture.no-physical-effect',revision=1)
TABLES=('team_device_command_access','team_device_command_members','team_device_command_grants','team_device_commands')


class FixtureAction:
    # Trusted owned-fixture display contract, never physical SDK support.
    display_label='기기 요청'
    argument_kind='empty-object'
    def validate_arguments(self,value):
        return value=={}

    def validate_ack(self,stage,evidence,context):
        if stage in ('received','unknown','rejected'):
            return evidence=={}
        if set(evidence)!={'kind','adapterEventId','observedAt'}:
            return False
        if evidence['kind']!='fixture-no-physical-effect' or evidence['adapterEventId']!=context['requestId']:
            return False
        try:
            observed=dt.datetime.fromisoformat(evidence['observedAt'].replace('Z','+00:00'))
            created=dt.datetime.fromisoformat(context['createdAt'])
            return created<=observed<=dt.datetime.now(dt.timezone.utc)
        except (ValueError,TypeError,AttributeError):
            return False


class FixtureRegistry:
    def describe(self):return [dict(ACTION)]
    def lookup(self,identifier,revision):
        return FixtureAction() if identifier==ACTION['id'] and revision==ACTION['revision'] else None


_share_module_fixture = False
_module_fixture_started = False


def setUpModule():
    global _share_module_fixture
    _share_module_fixture = True


def tearDownModule():
    global _share_module_fixture, _module_fixture_started
    try:
        if _module_fixture_started:mtls_fixture.NativeMTLSTests.tearDownClass()
    finally:
        _share_module_fixture = False
        _module_fixture_started = False


class CommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _module_fixture_started
        if not _share_module_fixture or not _module_fixture_started:
            mtls_fixture.NativeMTLSTests.setUpClass()
            if _share_module_fixture:_module_fixture_started = True
        cls.tls=mtls_fixture.NativeMTLSTests('test_01_real_tls_certificate_and_protocol_floor')

    @classmethod
    def tearDownClass(cls):
        if not _share_module_fixture:mtls_fixture.NativeMTLSTests.tearDownClass()

    def setUp(self):
        self.h=room_fixture.RoomTests('test_18_room_owner_member_roles_and_explicit_close');self.h.setUp();self.dsn=self.h.dsn
        self.service=self.h.module.TEAM_DEVICE_COMMANDS
        self.service.registry=FixtureRegistry()
        self.factory=current_fixture.FunctionalBusinessTests()
        self.factory.h=self.h;self.factory.certificates={}

    def tearDown(self):
        self.service.registry=ProductionCommandRegistry()

    def web(self,path,data=None,method='GET',who='alice',session=None,**kwargs):
        return self.h.call(path,data,method,who=who,session=session,**kwargs)

    def native(self,path,data=None,method='GET',token=None,**kwargs):
        if data is not None and method!='GET':data=dict(data,functionalRevision=self.functional_revision)
        return self.tls.native(path,data,method,token=token or self.token['accessToken'],**kwargs)

    def prepare(self,allowed=True,actions=None,*,guest_owner=False):
        self.a,self.b,self.e=self.h.sessions();aid=self.a['user']['id']
        self.assertEqual(self.h.request_friend(self.a,self.b)[0],201)
        self.assertEqual(self.h.friend('/friends/requests/'+aid+'/respond',dict(accept=True),'POST',who='bob',session=self.b)[0],200)
        if guest_owner:
            code,_,self.room=self.h.room('/rooms',dict(name='Shared road',courseId=None,courseVersion=None,expiresInHours=6),
                'POST',who='bob',session=self.b)
            self.assertEqual(code,201)
            self.assertEqual(self.h.join(self.a,self.room['code'],who='alice')[0],200)
        else:
            self.room=self.h.new_room(self.a)
            self.assertEqual(self.h.join(self.b,self.room['code'])[0],200)
        self.rid=self.room['id']
        # Current proof-checked public-v1 approval issues the leaf used by real
        # TLS requests. The owned edge CA signs it; spoofed headers cannot bind it.
        key,csr=test_enrollment.make_csr();issuer=test_enrollment.SyntheticIssuer()
        issuer.key=serialization.load_pem_private_key((self.h.state/'synthetic-ca.key').read_bytes(),password=None)
        issuer.name=x509.load_pem_x509_certificate((self.h.state/'synthetic-ca.crt').read_bytes()).subject
        certificates=[];response=issuer.response
        def capture(csr):
            value=response(csr);certificates.append(value['certificate']);return value
        with patch.object(test_enrollment,'make_csr',return_value=(key,csr)),patch.object(test_enrollment,'SyntheticIssuer',return_value=issuer),patch.object(issuer,'response',side_effect=capture):
            self.token=self.factory.connect(self.a)
        self.assertEqual(len(certificates),1);self.did=self.token['deviceId']
        directory=self.h.state/('command-client-'+secrets.token_hex(8));directory.mkdir(mode=0o700)
        cert_path=directory/'client.pem';cert_path.write_text(certificates[0]);cert_path.chmod(0o600)
        key_path=directory/'client.key';key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key_path.chmod(0o600)
        context=ssl.create_default_context(cafile=str(self.h.state/'synthetic-ca.crt'));context.minimum_version=ssl.TLSVersion.TLSv1_3;context.load_cert_chain(str(cert_path),str(key_path))
        fingerprint=x509.load_pem_x509_certificate(cert_path.read_bytes()).fingerprint(hashes.SHA256()).hex()
        self.assertEqual(fingerprint,self.factory.certificates[self.token['grantId']])
        self.tls.clients['a']=(context,fingerprint)
        self.functional_revision=self.factory.approve(self.a,self.token,['device-commands:receive'])
        self.d='/v1/devices/'+self.did+'/command-access';self.m='/v1/social/rooms/'+self.rid+'/device-command-access'
        self.g='/v1/social/rooms/'+self.rid+'/device-command-grants/'+self.did+'/'+aid;self.q='/v1/social/rooms/'+self.rid+'/device-requests'
        if allowed:self.allow([dict(ACTION)] if actions is None else actions)

    def allow(self,actions):
        status,_,access=self.web(self.d,session=self.a);self.assertEqual(status,200)
        status,_,access=self.web(self.d,dict(revision=access['revision'],consent=True,expiresInHours=1,actions=actions),'PUT',session=self.a);self.assertEqual(status,200)
        status,_,member=self.web(self.m,session=self.a);self.assertEqual(status,200)
        status,_,member=self.web(self.m,dict(revision=member['revision'],joinedAt=member['currentJoinedAt'],consent=True,expiresInHours=1,actions=actions),'PUT',session=self.a);self.assertEqual(status,200)
        status,_,snapshot=self.web(self.m,session=self.a);self.assertEqual(status,200)
        own=snapshot['currentJoinedAt']
        previous=next((x for x in snapshot['grants'] if x['deviceId']==self.did and x['requesterId']==self.a['user']['id']),{'revision':0})
        status,_,self.saved_grant=self.web(self.g,dict(revision=previous['revision'],consent=True,expiresInHours=1,actions=actions,
            deviceRevision=access['revision'],participationRevision=member['revision'],ownerJoinedAt=own,requesterJoinedAt=own),'PUT',session=self.a)
        self.assertEqual(status,200)

    def create(self,event_id=None,**changes):
        data=dict(eventId=event_id or secrets.token_hex(16),targetDeviceId=self.did,grantRevision=self.saved_grant['revision'],
            capabilityId=ACTION['id'],capabilityRevision=1,arguments={},expiresInSeconds=60);data.update(changes)
        status,_,value=self.web(self.q,data,'POST',session=self.a)
        return status,value,data

    def claim(self,identifier,claim_id=None):
        return self.native('/v1/device/requests/'+identifier+'/claim',dict(claimId=claim_id or secrets.token_hex(16)),'POST')

    def ack(self,identifier,lease,stage,ack_id=None,evidence=None):
        return self.native('/v1/device/requests/'+identifier+'/ack',dict(ackId=ack_id or secrets.token_hex(16),leaseId=lease,stage=stage,evidence={}if evidence is None else evidence),'POST')

    def test_01_default_off_old_read_scope_and_exact_target_auth(self):
        self.prepare(False)
        self.assertFalse(self.web(self.d,session=self.a)[2]['consent'])
        certificate=self.factory.certificates[self.token['grantId']]
        self.h.set_command_receiver(self.token,False,certificate)
        self.assertEqual(self.native('/v1/device/command-inbox')[0],403)
        self.functional_revision=self.h.set_command_receiver(self.token,True,certificate)['revision']
        self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'],[])
        # A supported Native-origin-off boot retains the authored browser/API
        # contract while the existing exact-host authentication stays closed.
        from team_device_commands import TeamDeviceCommands
        auth=self.h.module.TEAM_AUTH;origin=auth.native_origin
        try:
            auth.native_origin=''
            off=TeamDeviceCommands(auth,self.h.module.TEAM_ROOMS)
            self.assertTrue(off.enabled);self.assertEqual(len(off.router().routes),14)
            self.assertEqual(len(off.registry.describe()),11)
            self.assertEqual(self.native('/v1/device/command-inbox')[0],404)
            self.assertEqual(self.native('/v1/account')[0],404)
        finally:
            auth.native_origin=origin
        self.assertEqual(self.web(self.d,session=self.e,who='eve')[0],404)
        self.assertEqual(self.native('/v1/device/command-inbox',client='b')[0],403)
        self.assertEqual(self.tls.native('/v1/device/command-inbox')[0],401)
        self.assertEqual(self.web(self.d,dict(revision=0,consent=True,actions=[ACTION],expiresInHours=1),'PUT',session=self.a,csrf=False)[0],403)

    def test_02_explicit_empty_registry_never_queues_or_expands_old_actions(self):
        self.service.registry=EmptyCommandRegistry();self.prepare(True,[])
        self.assertEqual(self.web(self.d,session=self.a)[2]['supportedControlActions'],[])
        self.assertEqual(self.create()[0],503)
        with psycopg.connect(self.dsn) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_device_commands').fetchone()[0],0)
        self.service.registry=FixtureRegistry()
        self.assertEqual(self.create()[0],403)
        self.allow([dict(ACTION)]);self.assertEqual(self.create()[0],201)
        self.assertFalse(self.web(self.d,session=self.a)[2]['physicalExecutionSupported'])

    def test_03_idempotent_delivery_ordered_ack_and_bounded_integer_inputs(self):
        self.prepare();code,item,data=self.create();self.assertEqual(code,201);identifier=item['id']
        self.assertEqual(self.web(self.q,data,'POST',session=self.a)[2]['id'],identifier)
        self.assertEqual(self.create(data['eventId'],expiresInSeconds=61)[0],409)
        self.assertEqual(self.create(capabilityRevision=10**400)[0],400)
        self.assertEqual(self.create(expiresInSeconds=10**400)[0],400)
        self.assertEqual(self.web(self.d,dict(revision=10**400,consent=True,actions=[ACTION],expiresInHours=1),'PUT',session=self.a)[0],400)
        self.assertEqual(self.web('/v1/devices',who='bob',session=self.b)[2]['devices'],[])
        claim_id=secrets.token_hex(16);code,lease=self.claim(identifier,claim_id);self.assertEqual(code,200)
        self.assertEqual(lease['stage'],'delivered');self.assertTrue(lease['mayHaveExecuted']);self.assertFalse(lease['physicalExecutionVerified'])
        server_now=dt.datetime.fromisoformat(lease['serverNow'].replace('Z','+00:00'))
        lease_end=dt.datetime.fromisoformat(lease['leaseExpiresAt'].replace('Z','+00:00'))
        self.assertIsNotNone(server_now.utcoffset());self.assertIsNotNone(lease_end.utcoffset())
        self.assertLessEqual(server_now,lease_end)
        self.assertLessEqual((lease_end-server_now).total_seconds(),30)
        self.assertGreater((lease_end-server_now).total_seconds(),10)
        self.assertLessEqual(lease_end,dt.datetime.fromisoformat(item['expiresAt'].replace('Z','+00:00')))
        self.assertEqual(self.claim(identifier,claim_id)[1]['leaseId'],lease['leaseId'])
        self.assertEqual(self.claim(identifier)[0],409)
        self.assertEqual(self.ack(identifier,lease['leaseId'],'state-confirmed')[0],409)
        aid=secrets.token_hex(16);code,received=self.ack(identifier,lease['leaseId'],'received',aid);self.assertEqual(code,200)
        self.assertEqual(self.ack(identifier,lease['leaseId'],'received',aid)[1]['stage'],'received')
        self.assertEqual(self.ack(identifier,lease['leaseId'],'unknown',aid)[0],409)
        evidence=dict(kind='fixture-no-physical-effect',adapterEventId=identifier,observedAt=dt.datetime.now(dt.timezone.utc).isoformat())
        self.assertEqual(self.ack(identifier,lease['leaseId'],'sdk-accepted',evidence=evidence)[0],200)
        self.assertEqual(self.ack(identifier,lease['leaseId'],'state-confirmed',evidence=dict(evidence,adapterEventId='0'*32))[0],400)
        code,last=self.ack(identifier,lease['leaseId'],'state-confirmed',evidence=evidence);self.assertEqual(code,200);self.assertFalse(last['physicalExecutionVerified'])

    def test_04_revocation_cancellation_and_no_delivered_rollback_claim(self):
        self.prepare();_,item,_=self.create();identifier=item['id'];code,lease=self.claim(identifier);self.assertEqual(code,200)
        with self.h.websocket(self.a) as receiver:
            self.assertEqual(json.loads(receiver.recv(timeout=2))['type'],'snapshot')
            self.assertEqual(self.web(self.g,method='DELETE',session=self.a)[0],200)
            notification=json.loads(receiver.recv(timeout=2));self.assertEqual(notification['type'],'invalidate')
            self.assertIn('devices',notification['resources']);self.assertIn('rooms',notification['resources'])
            self.assertNotIn(lease['leaseId'],json.dumps(notification))
        self.assertEqual(self.ack(identifier,lease['leaseId'],'received')[0],403)
        code,_,value=self.web(self.q+'/'+identifier,method='DELETE',session=self.a);self.assertEqual(code,200)
        self.assertEqual(value['stage'],'unknown');self.assertTrue(value['mayHaveExecuted'])
        self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'],[])
        self.allow([ACTION]);_,queued,_=self.create()
        cancelled=self.web(self.q+'/'+queued['id'],method='DELETE',session=self.a)[2]
        self.assertEqual(cancelled['stage'],'cancelled');self.assertFalse(cancelled['mayHaveExecuted'])
        self.assertEqual(self.claim(queued['id'])[0],409)

    def test_05_leave_rejoin_block_device_revoke_and_wss_invalidation(self):
        self.prepare(guest_owner=True);_,item,_=self.create()
        self.assertEqual(self.h.room('/rooms/'+self.rid+'/leave',method='POST',session=self.a)[0],200)
        self.assertEqual(self.h.join(self.a,self.room['code'],who='alice')[0],200)
        self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'],[])
        self.assertIn(self.create()[0],(403,409));self.allow([ACTION]);_,item,_=self.create()
        self.assertEqual(self.h.friend('/blocks',dict(targetId=self.b['user']['id']),'POST',session=self.a)[0],201)
        self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'],[])
        self.assertEqual(self.web('/v1/devices/'+self.did,method='DELETE',session=self.a)[0],200)
        self.assertEqual(self.native('/v1/device/command-inbox')[0],401)
        with psycopg.connect(self.dsn) as conn:
            # Notifications carry only resource invalidation; no args/lease/token.
            rows=conn.execute("SELECT resource,revision FROM team_resource_versions WHERE account_id=%s AND resource IN ('devices','rooms')",(self.a['user']['id'],)).fetchall()
        self.assertTrue(rows)

    def test_06_expiry_records_unknown_and_cannot_revive_delivery(self):
        self.prepare();_,item,_=self.create();identifier=item['id'];_,lease=self.claim(identifier)
        with psycopg.connect(self.dsn) as conn:
            value=self.service.load_request(conn,identifier);value['leaseExpiresAt']=(self.service.now(conn)-dt.timedelta(seconds=1)).isoformat();self.service.save_request(conn,identifier,value)
        result=self.web(self.q,session=self.a)[2]['requests'][0]
        self.assertEqual(result['stage'],'unknown');self.assertTrue(result['mayHaveExecuted']);self.assertEqual(self.claim(identifier)[0],410)
        _,queued,_=self.create()
        with psycopg.connect(self.dsn) as conn:
            value=self.service.load_request(conn,queued['id']);value['expiresAt']=(self.service.now(conn)-dt.timedelta(seconds=1)).isoformat();self.service.save_request(conn,queued['id'],value)
        items=self.web(self.q,session=self.a)[2]['requests'];expired=next(x for x in items if x['id']==queued['id'])
        self.assertEqual(expired['stage'],'expired');self.assertFalse(expired['mayHaveExecuted'])

    def test_07_no_cross_room_idempotency_or_unregistered_state_claim(self):
        self.prepare();_,item,data=self.create();room2=self.h.new_room(self.a);self.assertEqual(self.h.join(self.b,room2['code'])[0],200)
        self.assertEqual(self.web('/v1/social/rooms/'+room2['id']+'/device-requests',data,'POST',session=self.a)[0],403)
        self.assertEqual(self.web(self.q,who='eve',session=self.e)[0],404)
        self.assertEqual(self.native('/v1/device/requests/'+item['id']+'/claim',dict(claimId='a'*16),'POST',client='b')[0],403)
        code,lease=self.claim(item['id']);self.assertEqual(code,200)
        self.service.registry=ProductionCommandRegistry()
        self.assertEqual(self.ack(item['id'],lease['leaseId'],'received')[0],403)
        self.service.registry=FixtureRegistry()
        # Existing helper sends a real held body and revokes the same actor session before its tail.
        # Use owner Alice here because this preserved helper deliberately binds its signed assertion to Alice.
        with psycopg.connect(self.dsn)as conn:before=conn.execute('SELECT count(*) FROM team_device_commands').fetchone()[0]
        mission_fixture.MissionsTests.held_body_logout(self,self.q,data,self.a)
        with psycopg.connect(self.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_device_commands').fetchone()[0],before)

    def test_08_populated_encrypted_backup_restore_and_transaction_rollback(self):
        self.prepare();_,item,_=self.create();identifier=item['id']
        with psycopg.connect(self.dsn) as conn:
            before=self.service.load_request(conn,identifier)
            with self.assertRaises(RuntimeError):
                with conn.transaction():
                    changed=dict(before,stage='cancelled');self.service.save_request(conn,identifier,changed);raise RuntimeError('owned rollback')
            self.assertEqual(self.service.load_request(conn,identifier)['stage'],'queued')
            counts={n:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(n))).fetchone()[0]for n in TABLES}
            self.assertTrue(all(counts.values()))
            raw=conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(identifier,)).fetchone()[0]
            self.assertNotIn(ACTION['id'].encode(),bytes(raw))
        source=Path(__file__).parent/'ops/live/backup.py';spec=importlib.util.spec_from_file_location('owned_command_backup',source)
        backup=importlib.util.module_from_spec(spec);sys.modules[spec.name]=backup;spec.loader.exec_module(backup)
        work=self.h.state/('command-backup-'+secrets.token_hex(8));work.mkdir(mode=0o700);base=work/'snapshots';base.mkdir(mode=0o700)
        tools=Path(self.h.tools['pg_ctl']).parent;layout=backup.Layout(self.dsn,self.h.state/'content',base,str(tools/'pg_dump'),str(tools/'pg_restore'))
        name='command_restore_'+secrets.token_hex(6)
        with psycopg.connect(self.dsn,autocommit=True)as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        try:
            snapshot=backup.snapshot(layout);target=make_conninfo(self.dsn,dbname=name);restored=work/'restore';restored.mkdir(mode=0o700)
            self.assertTrue(backup.verify_into(layout,snapshot,target,restored)['verified'])
            with psycopg.connect(target)as conn:
                restored_counts={n:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(n))).fetchone()[0]for n in TABLES}
                self.assertEqual(restored_counts,counts)
                raw=conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(identifier,)).fetchone()[0]
                self.assertEqual(self.service.restore('request',identifier,raw)['stage'],'queued')
        finally:
            with psycopg.connect(self.dsn,autocommit=True)as conn:conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


    def test_09_linked_owner_commands_keep_expiry_and_stop_on_finish(self):
        from fastapi import HTTPException
        from trip_room_migration import TripRoomMigration
        self.prepare()
        owner=self.a['user']['id']
        _,delivered,_=self.create();self.assertEqual(self.claim(delivered['id'])[0],200)
        _,queued,_=self.create()
        with psycopg.connect(self.dsn)as conn:
            access_before=conn.execute('SELECT protected FROM team_device_command_access WHERE device_id=%s',(self.did,)).fetchone()[0]
            TripRoomMigration(self.h.module.TEAM_AUTH).migrate_room(conn,self.rid)
            trip=conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s',(self.rid,)).fetchone()[0]
            _,expiry=self.service.context(conn,self.rid,self.did,owner,owner,trip_context=True)
            self.assertIsNone(self.service.membership(conn,self.rid,owner,trip_context=True)[1])
            self.assertLessEqual(expiry,dt.datetime.fromisoformat(self.saved_grant['expiresAt']))
            with self.assertRaises(HTTPException)as denied:self.service.context(conn,self.rid,self.did,owner,owner)
            self.assertEqual(denied.exception.status_code,409)
            revision=conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0]
            self.h.module.TEAM_TRIPS.transition(conn,trip,owner,'finish',revision)
            self.assertEqual(self.service.load_request(conn,queued['id'])['stage'],'cancelled')
            self.assertEqual(self.service.load_request(conn,delivered['id'])['stage'],'unknown')
            self.assertEqual(conn.execute('SELECT protected FROM team_device_command_access WHERE device_id=%s',(self.did,)).fetchone()[0],access_before)
            self.service.withdraw_trip_context(conn,trip,self.rid)
        self.assertEqual(self.claim(queued['id'])[0],409)
        self.assertEqual(self.web(self.m,session=self.a)[0],409)

    def test_10_trip_departure_rejoin_does_not_restore_command_permissions(self):
        from fastapi import HTTPException
        from trip_room_migration import TripRoomMigration
        self.prepare(guest_owner=True);peer=self.a['user']['id']
        _,queued,_=self.create()
        with psycopg.connect(self.dsn)as conn:
            TripRoomMigration(self.h.module.TEAM_AUTH).migrate_room(conn,self.rid)
            trip=conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s',(self.rid,)).fetchone()[0]
            before=self.service.participation(conn,self.rid,peer,trip_context=True)[1]
            self.h.module.TEAM_TRIPS.remove_member(conn,trip,peer)
            self.assertEqual(self.service.load_request(conn,queued['id'])['stage'],'cancelled')
            with self.assertRaises(HTTPException)as denied:self.service.context(conn,self.rid,self.did,peer,peer,trip_context=True)
            self.assertEqual(denied.exception.status_code,404)
            self.h.module.TEAM_TRIPS.save_member(conn,trip,peer,'accepted','link')
            member,joined,_=self.service.participation(conn,self.rid,peer,trip_context=True)
            self.assertNotEqual(before,joined);self.assertFalse(member['consent'])
            with self.assertRaises(HTTPException)as denied:self.service.context(conn,self.rid,self.did,peer,peer,trip_context=True)
            self.assertEqual(denied.exception.status_code,403)


class ReceivedGrantTests(unittest.TestCase):
    """Four new Web-projection boundaries, not inheritance/rerun of prior API8."""
    @classmethod
    def setUpClass(cls):CommandTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):CommandTests.tearDownClass.__func__(cls)
    setUp=CommandTests.setUp
    tearDown=CommandTests.tearDown
    web=CommandTests.web
    native=CommandTests.native
    prepare=CommandTests.prepare
    allow=CommandTests.allow
    create=CommandTests.create

    def received(self):
        status,_,value=self.web(self.m,session=self.a)
        self.assertEqual(status,200)
        return value['receivedGrants']

    def test_01_received_grants_for_carless_requester(self):
        self.prepare(True)
        self.assertEqual(self.web('/v1/devices',who='bob',session=self.b)[2]['devices'],[])
        with psycopg.connect(self.dsn)as conn:before=conn.execute('SELECT count(*) FROM team_device_commands').fetchone()[0]
        self.assertEqual(self.web(self.m,who='bob',session=self.b)[2]['receivedGrants'],[])
        items=self.received();self.assertEqual(len(items),1);item=items[0]
        self.assertEqual(set(item),{'targetDeviceId','ownerId','ownerName','deviceName','grantRevision','expiresAt','actions'})
        self.assertEqual(item['targetDeviceId'],self.did);self.assertEqual(item['ownerId'],self.a['user']['id'])
        self.assertEqual(item['ownerName'],self.a['user']['displayName'])
        own=self.web('/v1/devices',session=self.a)[2]['devices'];self.assertEqual(item['deviceName'],next(x['name']for x in own if x['id']==self.did))
        self.assertEqual(item['grantRevision'],self.saved_grant['revision'])
        self.assertEqual(item['actions'],[dict(ACTION,label='기기 요청',argumentKind='empty-object')])
        self.assertNotIn(self.token['accessToken'],json.dumps(item))
        self.assertNotIn('leaseId',item);self.assertNotIn('arguments',item)
        with psycopg.connect(self.dsn)as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_device_commands').fetchone()[0],before)
            self.assertGreater(dt.datetime.fromisoformat(item['expiresAt']),self.service.now(conn))
        # Display-only response fields cannot become permissive purpose inputs.
        current=self.web(self.d,session=self.a)[2]
        self.assertEqual(self.web(self.d,dict(revision=current['revision'],consent=True,expiresInHours=1,actions=item['actions']),'PUT',session=self.a)[0],400)
        self.assertEqual(self.web(self.d,session=self.a)[2]['revision'],current['revision'])

    def test_02_default_off_empty_registry_and_missing_display_contract_hide_targets(self):
        self.prepare(False)
        self.assertEqual(self.received(),[])
        self.allow([ACTION]);self.assertEqual(len(self.received()),1)
        self.service.registry=EmptyCommandRegistry();self.assertEqual(self.received(),[])
        self.assertEqual(self.web(self.d,session=self.a)[2]['supportedControlActions'],[])
        self.service.registry=FixtureRegistry()
        with patch.object(FixtureAction,'display_label',''):
            self.assertEqual(self.received(),[])
            self.assertEqual(self.web(self.d,session=self.a)[2]['supportedControlActions'],[])
        with patch.object(FixtureAction,'argument_kind','unknown'):
            self.assertEqual(self.received(),[])
        # A server registry revision change does not expand a saved permission.
        class NextRevision:
            def describe(self):return [dict(id=ACTION['id'],revision=2)]
            def lookup(self,identifier,revision):return FixtureAction()if identifier==ACTION['id']and revision==2 else None
        self.service.registry=NextRevision();self.assertEqual(self.received(),[])

    def test_03_each_consent_withdrawal_and_expiry_remove_sensitive_projection(self):
        self.prepare(True);self.assertEqual(len(self.received()),1)
        self.assertEqual(self.web(self.g,method='DELETE',session=self.a)[0],200);self.assertEqual(self.received(),[])
        self.allow([ACTION]);self.assertEqual(len(self.received()),1)
        self.assertEqual(self.web(self.d,method='DELETE',session=self.a)[0],200);self.assertEqual(self.received(),[])
        self.allow([ACTION]);member=self.web(self.m,session=self.a)[2]
        self.assertEqual(self.web(self.m,dict(revision=member['revision'],joinedAt=member['currentJoinedAt'],consent=False,expiresInHours=1,actions=[]),'PUT',session=self.a)[0],200)
        self.assertEqual(self.received(),[])
        self.allow([ACTION])
        with psycopg.connect(self.dsn)as conn:
            owner,grant=self.service.grant(conn,self.rid,self.did,self.a['user']['id'])
            grant['expiresAt']=(self.service.now(conn)-dt.timedelta(seconds=1)).isoformat()
            key=self.rid+':'+self.did+':'+self.a['user']['id']
            conn.execute('UPDATE team_device_command_grants SET protected=%s WHERE room_id=%s AND device_id=%s AND requester_id=%s',
                (self.service.protect('grant',key,grant),self.rid,self.did,self.a['user']['id']))
        self.assertEqual(self.received(),[])
        self.allow([ACTION]);self.assertEqual(len(self.received()),1)
        self.assertEqual(self.web('/v1/devices/'+self.did,method='DELETE',session=self.a)[0],200)
        self.assertEqual(self.received(),[])

    def test_04_current_room_peer_rejoin_block_and_cipher_failure_are_not_hidden(self):
        self.prepare(True,guest_owner=True)
        self.assertEqual(self.web(self.m,who='eve',session=self.e)[0],404)
        second=self.h.new_room(self.a);self.assertEqual(self.h.join(self.b,second['code'])[0],200)
        path='/v1/social/rooms/'+second['id']+'/device-command-access'
        self.assertEqual(self.web(path,who='bob',session=self.b)[2]['receivedGrants'],[])
        self.assertEqual(self.h.room('/rooms/'+self.rid+'/leave',method='POST',session=self.a)[0],200)
        self.assertEqual(self.h.join(self.a,self.room['code'],who='alice')[0],200);self.assertEqual(self.received(),[])
        self.allow([ACTION]);self.assertEqual(len(self.received()),1)
        self.assertEqual(self.h.friend('/blocks',dict(targetId=self.b['user']['id']),'POST',session=self.a)[0],201)
        status,_,blocked=self.web(self.m,session=self.a)
        self.assertEqual(status,404);self.assertNotIn('receivedGrants',blocked)
        # An unrelated blocked record is restored by a fresh isolated prepare,
        # not by changing production consent or bypassing its current checks.
        self.h.setUp();self.prepare(True)
        with psycopg.connect(self.dsn)as conn:
            conn.execute('UPDATE team_device_command_access SET protected=%s WHERE device_id=%s',(b'owned-invalid-ciphertext',self.did))
        status,_,value=self.web(self.m,session=self.a)
        self.assertEqual(status,503)
        self.assertNotIn('receivedGrants',value)


class RoomCommandContractTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, MagicMock
        from team_device_commands import TeamDeviceCommands
        self.owner='team-'+'a'*40;self.peer='team-'+'b'*40;self.device='c'*32;self.room='d'*32
        self.service=TeamDeviceCommands.__new__(TeamDeviceCommands)
        self.service.enabled=True;self.service.dsn='unused';self.service.registry=ProductionCommandRegistry()
        self.service.rooms=SimpleNamespace(graph_lock=Mock());self.conn=MagicMock()
        self.service.browser=Mock(return_value=dict(id=self.owner))
        self.now=dt.datetime.now(dt.timezone.utc);self.expiry=self.now+dt.timedelta(hours=1);self.joined=self.now.isoformat()
        actions=self.service.registry.describe()
        access=dict(revision=1,consent=True,expiresAt=self.expiry.isoformat(),actions=actions)
        self.grant=dict(access,deviceRevision=1,participationRevision=1,ownerJoinedAt=self.joined,requesterJoinedAt=self.joined)
        self.service.now=Mock(return_value=self.now);self.service.access=Mock(return_value=access)
        self.service.device=Mock(return_value=self.expiry)
        self.service.participation=Mock(return_value=(dict(access,joinedAt=self.joined),self.joined,self.expiry))
        self.service.membership=Mock(return_value=(self.joined,self.expiry));self.service.grant=Mock(side_effect=lambda *_:(self.owner,dict(self.grant)))
        self.service.protect=Mock(return_value=b'protected');self.service.revoke_rows=Mock();self.service.notify=Mock()
        self.routes={(method,r.path):r.endpoint for r in self.service.router().routes for method in r.methods}

    def invoke(self,method,path,data,**params):
        import asyncio
        import inspect
        from contextlib import nullcontext
        from fastapi import Request
        async def receive():return dict(type='http.request',body=json.dumps(data).encode(),more_body=False)
        request=Request(dict(type='http',method=method,headers=[]),receive)
        with patch('team_device_commands.psycopg.connect',return_value=nullcontext(self.conn)):
            result=self.routes[(method,path)](request=request,**params)
            return asyncio.run(result) if inspect.isawaitable(result) else result

    def test_room_context_allows_only_owner_actions(self):
        from fastapi import HTTPException
        actions=self.service.registry.describe()
        self.assertEqual(len(actions),11)
        for action in actions:
            with self.subTest(action=action['id']):
                snapshot,expiry=self.service.context(self.conn,self.room,self.device,self.owner,self.owner,action=action)
                self.assertEqual(snapshot['grantRevision'],1)
                self.assertEqual(expiry,self.expiry)
                with self.assertRaises(HTTPException) as denied:
                    self.service.context(self.conn,self.room,self.device,self.peer,self.owner,action=action)
                self.assertEqual(denied.exception.status_code,403)

    def test_trip_context_uses_finite_permissions_without_a_room_expiry(self):
        member,joined,_=self.service.participation.return_value
        self.service.participation.return_value=(member,joined,None)
        self.service.membership.return_value=(joined,None)
        _,expiry=self.service.context(self.conn,self.room,self.device,self.owner,self.owner,trip_context=True)
        self.assertEqual(expiry,self.expiry)
        self.service.participation.assert_called_with(self.conn,self.room,self.owner,trip_context=True,active=True)

    def test_room_grants_allow_only_self(self):
        from fastapi import HTTPException
        path='/v1/social/rooms/{room}/device-command-grants/{device}/{peer}'
        data=dict(revision=1,deviceRevision=1,participationRevision=1,ownerJoinedAt=self.joined,requesterJoinedAt=self.joined,consent=True,expiresInHours=1,actions=self.service.registry.describe())
        value=self.invoke('PUT',path,data,room=self.room,device=self.device,peer=self.owner)
        self.assertEqual(len(value['actions']),11)
        self.assertEqual(value['requesterId'],self.owner)
        with self.assertRaises(HTTPException) as denied:
            self.invoke('PUT',path,data,room=self.room,device=self.device,peer=self.peer)
        self.assertEqual(denied.exception.status_code,403)

    def legacy_commands(self,scope):
        import copy
        from types import SimpleNamespace
        from unittest.mock import Mock
        from friend_vehicle_controls import FriendVehicleControls
        from test_device_command_registry import CONTRACTS
        removed=(('steering.heat','STEERING_WHEEL_HEAT',dict(value=1)),
            ('hvac.defroster','DEFROSTER',dict(window='FRONT_WINDSHIELD',value=True)))
        contracts=[(i,p,a) for i,_,_,p,a in CONTRACTS]+list(removed)
        actions=[dict(id=i,revision=1) for i,_,_ in contracts]
        for permission in (self.service.access.return_value,self.service.participation.return_value[0],self.grant):
            permission['actions']=copy.deepcopy(actions)
        self.service.auth=SimpleNamespace(secret=b'fixture-command-secret')
        controls=self.service.friend_controls=FriendVehicleControls(self.service)
        controls.friendship=Mock()
        self.friend_grant=dict(revision=7,consent=True,expiresAt=None,actions=copy.deepcopy(actions),
            nativeBinding=dict(grantId='fixture-grant',functionalRevision=3))
        controls.grant=Mock(return_value=(self.owner,self.friend_grant))
        controls.device=Mock(return_value=SimpleNamespace(grant_id='fixture-grant',functional_revision=3,expires_at=self.expiry))
        room=None if scope=='friend-remote' else self.room
        requester=self.owner if scope=='room-owner' else self.peer
        if scope == 'friend-remote':
            context=dict(friendRemote=True,grantRevision=7,grantId='fixture-grant',functionalRevision=3)
        else:
            context=dict(grantRevision=1,deviceRevision=1,participationRevision=1,
                         requesterJoinedAt=self.joined,ownerJoinedAt=self.joined)
        values={}
        for index,(identifier,prop,arguments) in enumerate(contracts):
            key=f'{index:032x}'
            values[key]=dict(roomId=room,targetDeviceId=self.device,requesterId=requester,ownerId=self.owner,
                capabilityId=identifier,capabilityRevision=1,arguments=copy.deepcopy(arguments),context=copy.deepcopy(context),
                createdAt=self.joined,expiresAt=self.expiry.isoformat(),stage='queued',lastAcknowledgedStage=None,
                mayHaveExecuted=False,reason=None,leaseHash=None,leaseExpiresAt=None,claimIdHash=None,leaseId=None,acks={})
        def execute(query,args):
            if query.startswith('SELECT request_id FROM '):return [(key,) for key in values]
            if query.startswith('SELECT protected FROM '):return SimpleNamespace(fetchone=lambda:(values[args[0]],))
            raise AssertionError(query)
        self.conn.execute.side_effect=execute
        self.service.restore=Mock(side_effect=lambda kind,key,value:copy.deepcopy(value))
        self.service.save_request=Mock();self.service.notify_progress=Mock()
        self.service.native=Mock(return_value=dict(id=self.owner,deviceId=self.device))
        self.saved_permissions=copy.deepcopy((self.service.access.return_value,self.service.participation.return_value,self.grant,self.friend_grant))
        return values,{i:p for i,p,_ in contracts}

    def assert_permissions_unchanged(self):
        self.assertEqual((self.service.access.return_value,self.service.participation.return_value,self.grant,self.friend_grant),self.saved_permissions)
        self.service.protect.assert_not_called()

    def test_only_registered_owner_actions_visible_in_legacy_queues(self):
        from fastapi import Response

        for scope in ('room-owner','room-friend','friend-remote'):
            with self.subTest(scope=scope):
                self.setUp();values,_=self.legacy_commands(scope)
                expected={a['id'] for a in self.service.registry.describe()} if scope=='room-owner' else set()
                inbox=self.invoke('GET','/v1/device/command-inbox',None,response=Response(),view='active')
                self.assertEqual({v['capabilityId'] for v in inbox['requests']},expected)
                self.assertEqual(len(inbox['requests']),len(expected))
                if scope!='friend-remote':
                    for viewer in {self.owner,next(iter(values.values()))['requesterId']}:
                        self.service.browser.return_value=dict(id=viewer)
                        listing=self.invoke('GET','/v1/social/rooms/{room}/device-requests',None,room=self.room)
                        self.assertEqual({v['capabilityId'] for v in listing['requests']},expected)
                        self.assertEqual(len(listing['requests']),len(expected))
                self.service.save_request.assert_not_called()
                self.assert_permissions_unchanged()

    def test_retired_grants_and_removed_actions_deny_claim_and_every_ack_stage(self):
        from fastapi import HTTPException
        for scope in ('room-owner','room-friend','friend-remote'):
            self.setUp();values,properties=self.legacy_commands(scope)
            for key,value in values.items():
                if scope=='room-owner' and value['capabilityId'] not in ('steering.heat','hvac.defroster'):continue
                with self.subTest(scope=scope,action=value['capabilityId'],operation='claim'):
                    with self.assertRaises(HTTPException) as caught:
                        self.invoke('POST','/v1/device/requests/{identifier}/claim',dict(claimId='legacy-claim-0001'),identifier=key)
                    self.assertEqual(caught.exception.status_code,403)
                for stage,current in (('received','delivered'),('sdk-accepted','received'),('state-confirmed','sdk-accepted'),('rejected','delivered'),('unknown','delivered')):
                    with self.subTest(scope=scope,action=value['capabilityId'],stage=stage):
                        value.update(stage=current,mayHaveExecuted=True,leaseHash=self.service.digest('lease','fixture-lease'),leaseExpiresAt=self.expiry.isoformat())
                        evidence={}
                        if stage in ('sdk-accepted','state-confirmed'):
                            evidence=dict(kind='pleos-vehicle-setter-v1',requestId=key,property=properties[value['capabilityId']],**value['arguments'])
                            if stage=='state-confirmed':evidence.update(kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
                        with self.assertRaises(HTTPException) as caught:
                            self.invoke('POST','/v1/device/requests/{identifier}/ack',dict(ackId='legacy-ack-00001',leaseId='fixture-lease',stage=stage,evidence=evidence),identifier=key)
                        self.assertEqual(caught.exception.status_code,403)
                self.service.save_request.assert_not_called()
            self.assert_permissions_unchanged()

    def test_owner_actions_keep_claim_and_ordered_ack(self):
        values,properties=self.legacy_commands('room-owner')
        for key,value in values.items():
            if value['capabilityId'] in ('steering.heat','hvac.defroster'):continue
            with self.subTest(action=value['capabilityId']):
                claimed=self.invoke('POST','/v1/device/requests/{identifier}/claim',dict(claimId='current-claim-01'),identifier=key)
                self.assertEqual(claimed['stage'],'delivered')
                value.update(self.service.save_request.call_args.args[2])
                for stage in ('received','sdk-accepted','state-confirmed'):
                    evidence={}
                    if stage!='received':
                        evidence=dict(kind='pleos-vehicle-setter-v1',requestId=key,property=properties[value['capabilityId']],**value['arguments'])
                        if stage=='state-confirmed':evidence.update(kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
                    result=self.invoke('POST','/v1/device/requests/{identifier}/ack',dict(ackId='current-ack-0001-'+stage,leaseId=claimed['leaseId'],stage=stage,evidence=evidence),identifier=key)
                    self.assertEqual(result['stage'],stage)
                    value.update(self.service.save_request.call_args.args[2])
        self.assert_permissions_unchanged()

    def test_driving_rejection_reason_is_kept_on_the_request(self):
        from fastapi import HTTPException
        values,_=self.legacy_commands('room-owner')
        key,value=next((k,v) for k,v in values.items() if v['capabilityId'] not in ('steering.heat','hvac.defroster'))
        claimed=self.invoke('POST','/v1/device/requests/{identifier}/claim',dict(claimId='driving-claim-01'),identifier=key)
        value.update(self.service.save_request.call_args.args[2])
        received=self.invoke('POST','/v1/device/requests/{identifier}/ack',dict(ackId='driving-ack-received',leaseId=claimed['leaseId'],stage='received',evidence={}),identifier=key)
        self.assertIsNone(received['reason'])
        value.update(self.service.save_request.call_args.args[2])
        with self.assertRaises(HTTPException) as caught:
            self.invoke('POST','/v1/device/requests/{identifier}/ack',dict(ackId='driving-ack-invalid',leaseId=claimed['leaseId'],stage='rejected',evidence={'reason':'parked'}),identifier=key)
        self.assertEqual(caught.exception.status_code,400)
        rejected=self.invoke('POST','/v1/device/requests/{identifier}/ack',dict(ackId='driving-ack-rejected',leaseId=claimed['leaseId'],stage='rejected',evidence={'reason':'driving-restricted'}),identifier=key)
        self.assertEqual((rejected['stage'],rejected['reason']),('rejected','driving-restricted'))
        self.assertEqual(self.service.save_request.call_args.args[2]['reason'],'driving-restricted')
        self.assert_permissions_unchanged()


if __name__=='__main__':unittest.main(verbosity=2)
