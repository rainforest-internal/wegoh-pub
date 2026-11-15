"""Direct purpose-cleanup seam on synthetic PG; API integration is a separate case."""
import unittest,json,hashlib,secrets
from datetime import datetime,timezone,timedelta
import psycopg
import test_team_auth as fixture
from native_functional_withdrawal import withdraw_report_effects

class ReportWithdrawalEffectsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):
  self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
 def test_scoped_latest_purge_projection_invalidate_rollback_and_original_cipher_preservation(self):
  a,b,c=self.h.login(),self.h.login('bob'),self.h.login('eve');owner=a['user']['id'];peer=b['user']['id'];third=c['user']['id']
  _,_,one=self.h.pair(a);_,_,two=self.h.pair(c,'eve');_,_,other=self.h.pair(b,'bob')
  room=self.h.call('/v1/social/rooms',dict(name='Synthetic cleanup room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a)[2]
  detail=self.h.call('/v1/social/rooms/'+room['id'],session=a)[2]
  flags={k:k in('status','location')for k in('status','location','visits','music','voice','control')}
  code,_,joined=self.h.call('/v1/social/rooms/join',dict(code=detail['code'],consents=flags),'POST',session=b,who='bob');self.assertEqual(code,200,joined)
  code,_,joined=self.h.call('/v1/social/rooms/join',dict(code=detail['code'],consents=flags),'POST',session=c,who='eve');self.assertEqual(code,200,joined)
  v=self.h.module.TEAM_VEHICLE;rid=room['id'];expiry=datetime.now(timezone.utc)+timedelta(hours=1)
  def rows(conn,table):return conn.execute('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text').fetchall()
  with psycopg.connect(self.h.dsn)as conn:
   v.rooms.graph_lock(conn)
   for account,devices,receiver in [(owner,[one['deviceId']],one['deviceId']),(peer,[other['deviceId']],other['deviceId']),(third,[two['deviceId']],two['deviceId'])]:
    access,grant,revision,_=v.room_grants(conn,rid,account)
    grant['devices']={device:dict(shareLocation=True,shareVisits=True,receiveLocation=True,receiveVisits=True,permissionRevision=1,nonce='a'*32,expiresAt=expiry.isoformat())for device in devices}
    grant['receiverDeviceId']=receiver;v.store_room(conn,rid,account,grant,expiry)
   for account,device,kind in [(owner,one['deviceId'],'location'),(owner,one['deviceId'],'visits'),(third,two['deviceId'],'location'),(peer,other['deviceId'],'location')]:
    payload=dict(eventId=secrets.token_hex(16),capturedAt=datetime.now(timezone.utc).isoformat(),roomJoinedAt='synthetic',grantNonce='a'*32,devicePermissionRevision=1,report=dict(synthetic=True))
    conn.execute('INSERT INTO team_vehicle_latest_reports(room_id,device_id,kind,account_id,protected,received_at)VALUES(%s,%s,%s,%s,%s,now())',(rid,device,kind,account,v.protect('latest',account,rid+':'+device+':'+kind,payload)))
   history=self.h.module.TEAM_HISTORY.add(conn,owner,dict(title='Preserved original',startedAt=datetime.now(timezone.utc).isoformat(),endedAt=None,courseId=None,courseVersion=None),dict(kind='web-confirmed',actorId=owner,receivedAt=datetime.now(timezone.utc).isoformat()))
   original_history=rows(conn,'team_histories');original_latest=rows(conn,'team_vehicle_latest_reports')
   base={name:rows(conn,name)for name in ['native_v2_grants','native_v2_credentials','native_v2_installations','native_v2_approvals','native_v2_certificates','native_v2_operations']}
   original_peer=conn.execute('SELECT protected FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,peer)).fetchone()[0]
   original_third=conn.execute('SELECT protected FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,third)).fetchone()[0]
   kept=conn.execute("SELECT device_id,kind,protected FROM team_vehicle_latest_reports WHERE NOT(device_id=%s AND kind='location') ORDER BY device_id,kind",(one['deviceId'],)).fetchall()
  class Rollback(Exception):pass
  with self.assertRaises(Rollback):
   with psycopg.connect(self.h.dsn)as conn:
    result=withdraw_report_effects(conn,self.h.module.TEAM_AUTH,owner,one['deviceId'],frozenset({'vehicle-location:report'}));self.assertEqual(result['latestDeleted'],1);raise Rollback()
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(rows(conn,'team_vehicle_latest_reports'),original_latest)
  with psycopg.connect(self.h.dsn)as conn:
   before_peer=conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='vehicle'",(peer,)).fetchone()
   result=withdraw_report_effects(conn,self.h.module.TEAM_AUTH,owner,one['deviceId'],frozenset({'vehicle-location:report'}))
   self.assertEqual(result,dict(latestDeleted=1,roomsInvalidated=1))
   self.assertEqual(conn.execute('SELECT device_id,kind,protected FROM team_vehicle_latest_reports ORDER BY device_id,kind').fetchall(),kept)
   grant=v.restore('room-grant',owner,rid,conn.execute('SELECT protected FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,owner)).fetchone()[0])
   self.assertFalse(grant['devices'][one['deviceId']]['shareLocation']);self.assertTrue(grant['devices'][one['deviceId']]['shareVisits']);self.assertEqual(grant['devices'][one['deviceId']]['nonce'],'a'*32)
   third_grant=v.restore('room-grant',third,rid,conn.execute('SELECT protected FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,third)).fetchone()[0])
   self.assertTrue(third_grant['devices'][two['deviceId']]['shareLocation'])
   self.assertEqual(conn.execute('SELECT protected FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,third)).fetchone()[0],original_third)
   self.assertEqual(conn.execute('SELECT protected FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,peer)).fetchone()[0],original_peer)
   now_peer=conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='vehicle'",(peer,)).fetchone();self.assertTrue(now_peer and(not before_peer or now_peer[0]>before_peer[0]))
   self.assertEqual(rows(conn,'team_histories'),original_history)
   for table,original in base.items():self.assertEqual(rows(conn,table),original)
   self.assertEqual(withdraw_report_effects(conn,self.h.module.TEAM_AUTH,owner,one['deviceId'],frozenset({'vehicle-location:report'})),dict(latestDeleted=0,roomsInvalidated=0))
   from trip_room_migration import TripRoomMigration
   TripRoomMigration(self.h.module.TEAM_AUTH).migrate_room(conn,rid)
   count=conn.execute('SELECT count(*) FROM team_vehicle_latest_reports').fetchone()[0]
   withdraw_report_effects(conn,self.h.module.TEAM_AUTH,owner,one['deviceId'],frozenset({'vehicle-reports:read'}))
   self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports').fetchone()[0],count)
   grant=v.restore('room-grant',owner,rid,conn.execute('SELECT protected FROM team_vehicle_room_grants WHERE room_id=%s AND account_id=%s',(rid,owner)).fetchone()[0]);self.assertIsNone(grant['receiverDeviceId']);self.assertFalse(grant['devices'][one['deviceId']]['receiveVisits'])


class ReportWithdrawalTripContractTests(unittest.TestCase):
 def test_rooms_read_withdrawal_clears_every_room_report_purpose(self):
  from types import SimpleNamespace
  from unittest.mock import Mock,MagicMock,patch
  from native_functional_withdrawal import REPORT_PURPOSES
  conn=MagicMock();conn.autocommit=False
  auth=SimpleNamespace(room_music_service=Mock(),room_music_access=Mock())
  auth.room_music_service.withdraw_native_source.return_value=[]
  result=dict(latestDeleted=1,roomsInvalidated=1)
  with patch('native_functional_withdrawal._withdraw_report_effects',return_value=result)as cleanup:
   self.assertEqual(withdraw_report_effects(conn,auth,'owner','a'*32,frozenset({'rooms:read'})),result)
  self.assertEqual(cleanup.call_args.args[2:],('owner','a'*32,REPORT_PURPOSES))
