"""Current Native report authority; synthetic trusted edge/PG, not physical GPS/TLS."""
import unittest,json,hashlib,secrets
from datetime import datetime,timezone
import psycopg
import test_team_auth as fixture

class NativeReportAuthorityTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):
  self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp();self.certs={}
 def connect(self,session,who='alice'):
  _,_,c=self.h.pair(session,who);self.certs[c['grantId']]=self.h._native_fingerprint;return c
 def native(self,c,path,body=None,method='GET',certificate=None):return self.h.native(path,body,method,token=c['accessToken'],certificate=certificate or self.certs[c['grantId']])
 def approve(self,session,c,purposes,who='alice'):
  path='/v1/devices/'+c['deviceId']+'/functional-permissions';code,_,old=self.h.call(path,session=session,who=who);self.assertEqual(code,200,old)
  body={k:v for k,v in old.items()if k not in('deviceId','expiresAt')};body['approvedPurposes']=self.h.web_purposes(old,purposes)
  code,_,value=self.h.call(path,body,'PUT',session=session,who=who);self.assertEqual(code,200,value);return value['revision']
 def snapshot(self,session,c,room=None,who='alice'):
  path='/v1/devices/'+c['deviceId']+'/vehicle-domain'+('?roomId='+room if room else '')
  code,_,value=self.h.call(path,session=session,who=who);self.assertEqual(code,200,value);return value
 def room_grant(self,session,c,room,who='alice',**flags):
  current=self.snapshot(session,c,room,who);r=current['roomReporting'];body=dict(deviceId=c['deviceId'],revision=r['revision'],joinedAt=r['joinedAt'],devicePermissionRevision=current['functionalRevision'],shareLocation=False,shareVisits=False,receiveLocation=False,receiveVisits=False,expiresInHours=1);body.update(flags)
  code,_,value=self.h.call('/v1/social/rooms/'+room+'/device-reporting',body,'PUT',session=session,who=who);self.assertEqual(code,200,value);return value
 def base(self):
  with psycopg.connect(self.h.dsn)as conn:return {n:conn.execute('SELECT row_to_json(t)::text FROM '+n+' t ORDER BY row_to_json(t)::text').fetchall()for n in ['native_v2_grants','native_v2_credentials','native_v2_installations','native_v2_approvals','native_v2_certificates','native_v2_operations']}
 def test_current_native_sender_separate_room_receivers_scope_and_no_legacy_identity(self):
  a,b,e=self.h.login(),self.h.login('bob'),self.h.login('eve');ca=self.connect(a);cb=self.connect(b,'bob');base=self.base()
  self.assertEqual(self.h.call('/v1/social/friends/requests',dict(targetId=b['user']['id']),'POST',session=a)[0],201)
  self.assertEqual(self.h.call('/v1/social/friends/requests/'+a['user']['id']+'/respond',dict(accept=True),'POST',session=b,who='bob')[0],200)
  code,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic report room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a);self.assertEqual(code,201,room);rid=room['id'];path='/v1/social/rooms/'+rid
  detail=self.h.call(path,session=a)[2];flags={k:k in('status','location')for k in('status','location','visits','music','voice','control')}
  self.assertEqual(self.h.call('/v1/social/rooms/join',dict(code=detail['code'],consents=flags),'POST',session=b,who='bob')[0],200)
  self.assertEqual(self.h.call(path+'/consents',dict(consents=flags),'PATCH',session=a)[0],200)
  own=self.native(ca,'/v1/device/vehicle-domain');self.assertEqual(own[0],200,own[2]);self.assertEqual(own[2]['authority'],'native-functional');self.assertEqual(own[2]['reporting'],dict(location=False,visits=False));self.assertEqual(own[2]['functionalRevision'],self.snapshot(a,ca)['functionalRevision'])
  self.assertEqual(self.h.call('/v1/devices/'+ca['deviceId']+'/vehicle-domain',session=b,who='bob')[0],404)
  snapshot='/v1/device/vehicle-domain?roomId='+rid
  code,_,own_room=self.native(ca,snapshot);self.assertEqual(code,200,own_room);self.assertEqual(own_room['deviceId'],ca['deviceId']);self.assertEqual(own_room['roomReporting']['roomId'],rid);self.assertFalse(own_room['roomReporting']['shareLocation']);self.assertIsNone(own_room['latestLocation']);self.assertIsNone(own_room['latestVisit'])
  self.assertEqual(self.native(ca,snapshot,certificate=self.certs[cb['grantId']])[0],401)
  for suffix in ['roomId='+rid+'&roomId='+rid,'roomId=','roomId='+'f'*33,'room='+rid,'roomId='+rid+'&access_token=synthetic-forbidden','latitude=37.0&longitude=127.0']:
   self.assertEqual(self.native(ca,'/v1/device/vehicle-domain?'+suffix)[0],400)
  code,_,private_room=self.h.call('/v1/social/rooms',dict(name='Other owner synthetic room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=e,who='eve');self.assertEqual(code,201,private_room)
  self.assertEqual(self.native(ca,'/v1/device/vehicle-domain?roomId='+private_room['id'])[0],404)
  self.assertEqual(self.h.call('/v1/devices/'+ca['deviceId']+'/reporting-permissions',dict(revision=0,purposes=dict(location=True,visits=False),expiresInHours=1),'PUT',session=a)[0],409)
  revision=self.approve(a,ca,['vehicle-location:report'])
  code,_,current=self.native(ca,snapshot);self.assertEqual(code,200,current);r=current['roomReporting'];report=dict(eventId=secrets.token_hex(16),devicePermissionRevision=revision,roomRevision=r['revision'],capturedAt=datetime.now(timezone.utc).isoformat(),latitude=37.5,longitude=127.0,accuracyMeters=5.0,functionalRevision=revision)
  endpoint='/v1/native/rooms/'+rid+'/reports/location';self.assertEqual(self.native(ca,endpoint,report,'POST')[0],403)
  current=self.room_grant(a,ca,rid,shareLocation=True)
  code,_,native_current=self.native(ca,snapshot);self.assertEqual(code,200,native_current);self.assertEqual(native_current['roomReporting']['revision'],current['roomReporting']['revision']);report['roomRevision']=native_current['roomReporting']['revision']
  missing=dict(report);missing.pop('functionalRevision');self.assertEqual(self.native(ca,endpoint,missing,'POST')[0],400)
  self.assertEqual(self.native(ca,endpoint,report,'POST',certificate=self.certs[cb['grantId']])[0],401)
  code,_,saved=self.native(ca,endpoint,report,'POST');self.assertEqual(code,200,saved);self.assertEqual(saved['status'],'accepted')
  self.assertEqual(self.native(ca,endpoint,report,'POST')[2]['status'],'duplicate')
  self.assertEqual(self.native(ca,endpoint,dict(report,latitude=37.6),'POST')[0],409)
  received=path+'/device-reports';native_received='/v1/native/rooms/'+rid+'/device-reports'
  self.assertEqual(self.h.call(received,session=b,who='bob')[2]['reports'],[])
  self.assertEqual(self.native(cb,native_received)[0],403)
  self.approve(b,cb,['vehicle-reports:read'],'bob');self.assertEqual(self.native(cb,native_received)[2]['reports'],[])
  self.room_grant(b,cb,rid,'bob',receiveLocation=True)
  code,_,view=self.native(cb,native_received);self.assertEqual(code,200,view);self.assertEqual(len(view['reports']),1);self.assertEqual(view['reports'][0]['location']['latitude'],37.5);self.assertFalse(view['reports'][0]['location']['physicalArrivalVerified'])
  self.assertEqual(self.h.call(received,session=e,who='eve')[0],404)
  # An unrelated newly approved purpose must not erase or silently renew existing room consent/cache.
  new_revision=self.approve(a,ca,['vehicle-location:report','vehicle-reports:read'])
  self.assertGreater(new_revision,report['functionalRevision'])
  self.assertEqual(self.native(ca,endpoint,report,'POST')[0],409)
  self.assertEqual(len(self.native(cb,native_received)[2]['reports']),1)
  from unittest.mock import patch
  from native_functional_policy import FunctionalError
  from native_functional_withdrawal import withdraw_report_effects
  def report_state():
   with psycopg.connect(self.h.dsn)as conn:return {table:conn.execute('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text').fetchall()for table in ['native_functional_authorizations','team_vehicle_room_grants','team_vehicle_latest_reports','team_resource_versions']}
  original=report_state()
  def failed_cleanup(*args):
   withdraw_report_effects(*args)
   raise FunctionalError(503,'FUNCTIONAL_CLEANUP_UNAVAILABLE')
  with patch('native_functional_withdrawal.withdraw_report_effects',side_effect=failed_cleanup):
   code,_,failure=self.h.call('/v1/devices/'+ca['deviceId']+'/functional-permissions/vehicle-location:report',method='DELETE',session=a);self.assertEqual(code,503,failure)
  self.assertEqual(report_state(),original)
  self.approve(a,ca,['history:read']);self.assertEqual(self.native(ca,endpoint,report,'POST')[0],403)
  self.assertEqual(self.native(cb,native_received)[2]['reports'],[])
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT count(*) FROM team_devices').fetchone()[0],0)
   self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_purposes').fetchone()[0],0)
  self.assertEqual(self.base(),base)
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports WHERE device_id=%s',(ca['deviceId'],)).fetchone()[0],0)
  # Global reapproval alone cannot revive withdrawn per-room share/cache.
  revision=self.approve(a,ca,['history:read','vehicle-location:report'])
  current=self.snapshot(a,ca,rid);report.update(eventId=secrets.token_hex(16),functionalRevision=revision,devicePermissionRevision=revision,roomRevision=current['roomReporting']['revision'])
  self.assertEqual(self.native(ca,endpoint,report,'POST')[0],403)
  current=self.room_grant(a,ca,rid,shareLocation=True);report['roomRevision']=current['roomReporting']['revision']
  self.assertEqual(self.native(ca,endpoint,report,'POST')[0],200)
  self.assertEqual(len(self.native(cb,native_received)[2]['reports']),1)
  code,_,cut=self.h.call('/v1/devices/'+cb['deviceId']+'/functional-permissions/vehicle-reports:read',method='DELETE',session=b,who='bob');self.assertEqual(code,200,cut)
  self.assertEqual(self.native(cb,native_received)[0],403)
  self.approve(b,cb,['vehicle-reports:read'],'bob');self.assertEqual(self.native(cb,native_received)[2]['reports'],[])
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports WHERE device_id=%s',(ca['deviceId'],)).fetchone()[0],1)
  self.room_grant(b,cb,rid,'bob',receiveLocation=True)
  self.assertEqual(len(self.native(cb,native_received)[2]['reports']),1)
  self.assertEqual(self.base(),base)
  # An expired functional row also requires new per-room consent, even if the
  # owner explicitly approves the same global purpose under the still-live base.
  with psycopg.connect(self.h.dsn)as conn:conn.execute('UPDATE native_functional_authorizations SET expires_at=1 WHERE grant_id=%s',(ca['grantId'],))
  revision=self.approve(a,ca,['history:read','vehicle-location:report'])
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports WHERE device_id=%s',(ca['deviceId'],)).fetchone()[0],0)
  current=self.snapshot(a,ca,rid);report.update(eventId=secrets.token_hex(16),functionalRevision=revision,devicePermissionRevision=revision,roomRevision=current['roomReporting']['revision'])
  self.assertEqual(self.native(ca,endpoint,report,'POST')[0],403)
  current=self.room_grant(a,ca,rid,shareLocation=True);report['roomRevision']=current['roomReporting']['revision']
  self.assertEqual(self.native(ca,endpoint,report,'POST')[0],200)
  self.assertEqual(self.base(),base)
  # Mounted visit reports need a separately approved purpose and exact approved room course.
  pack=self.h.pack();self.assertEqual(self.h.publish(pack,a)[0],201);self.assertEqual(self.h.approve(pack,a)[0],200)
  code,_,visit_room=self.h.call('/v1/social/rooms',dict(name='Synthetic approved visit room',courseId=pack['id'],courseVersion=pack['version'],expiresInHours=1),'POST',session=a);self.assertEqual(code,201,visit_room)
  vrid=visit_room['id'];vroot='/v1/social/rooms/'+vrid
  self.assertEqual(self.h.call(vroot+'/consents',dict(consents={k:k in('status','location')for k in flags}),'PATCH',session=a)[0],200)
  vpath='/v1/device/vehicle-domain?roomId='+vrid;code,_,vcurrent=self.native(ca,vpath);self.assertEqual(code,200,vcurrent)
  visit=dict(eventId=secrets.token_hex(16),functionalRevision=revision,devicePermissionRevision=revision,roomRevision=vcurrent['roomReporting']['revision'],capturedAt=datetime.now(timezone.utc).isoformat(),courseId=pack['id'],courseVersion=pack['version'],checkpoint=1)
  visit_endpoint='/v1/native/rooms/'+vrid+'/reports/visits';self.assertEqual(self.native(ca,visit_endpoint,visit,'POST')[0],403)
  revision=self.approve(a,ca,['history:read','vehicle-location:report','vehicle-visits:report'])
  self.room_grant(a,ca,vrid,shareVisits=True)
  code,_,vcurrent=self.native(ca,vpath);self.assertEqual(code,200,vcurrent);self.assertTrue(vcurrent['roomReporting']['shareVisits'])
  visit.update(functionalRevision=revision,devicePermissionRevision=revision,roomRevision=vcurrent['roomReporting']['revision'])
  self.assertEqual(self.native(ca,visit_endpoint,dict(visit,courseId='synthetic-wrong-course'),'POST')[0],409)
  code,_,accepted=self.native(ca,visit_endpoint,visit,'POST');self.assertEqual(code,200,accepted);self.assertEqual(accepted['status'],'accepted')
  code,_,vread=self.native(ca,vpath);self.assertEqual(code,200,vread);v=vread['latestVisit']
  self.assertEqual((v['courseId'],v['courseVersion'],v['checkpoint'],v['eventId']),(pack['id'],pack['version'],1,visit['eventId']));self.assertEqual(v['source'],'user-confirmed');self.assertFalse(v['physicalArrivalVerified']);self.assertFalse(v['accuracyVerified'])
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT count(*) FROM team_history_visits').fetchone()[0],0);self.assertEqual(conn.execute('SELECT count(*) FROM visited_places').fetchone()[0],0)
  self.assertEqual(self.base(),base)
  # Base self-disconnect purges exact derivatives before personal auth is erased.
  with psycopg.connect(self.h.dsn)as conn:peer_before=conn.execute('SELECT row_to_json(g)::text FROM native_v2_grants g WHERE grant_id=%s',(cb['grantId'],)).fetchone()
  code,_,revoked=self.h.call('/v1/devices/'+ca['deviceId'],method='DELETE',session=a);self.assertEqual(code,200,revoked)
  self.assertEqual(self.native(ca,'/v1/account')[0],401)
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports WHERE device_id=%s',(ca['deviceId'],)).fetchone()[0],0)
   self.assertEqual(conn.execute('SELECT row_to_json(g)::text FROM native_v2_grants g WHERE grant_id=%s',(cb['grantId'],)).fetchone(),peer_before)
