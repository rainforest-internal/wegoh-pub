"""Actual native social vertical after the reviewed core link; synthetic PrivatePG."""
import hashlib,json,unittest
import psycopg
import test_team_auth as fixture
from native_functional_policy import WIRE
class FunctionalBusinessTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):
  self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp();self.certificates={}
 def connect(self,session,who='alice'):
  _,_,c=self.h.pair(session,who);self.certificates[c['grantId']]=self.h._native_fingerprint;return c
 def native(self,c,path,body=None,method='GET',certificate=None):
  return self.h.native(path,body,method,token=c['accessToken'],certificate=certificate or self.certificates[c['grantId']])
 def approve(self,session,c,purposes,who='alice'):
  path='/v1/devices/'+c['deviceId']+'/functional-permissions';code,_,old=self.h.call(path,session=session,who=who);self.assertEqual(code,200)
  body={k:v for k,v in old.items()if k not in ('deviceId','expiresAt')};body['approvedPurposes']=self.h.web_purposes(old,purposes)
  code,_,value=self.h.call(path,body,'PUT',session=session,who=who);self.assertEqual(code,200);return value['revision']
 def state(self):
  result={}
  with psycopg.connect(self.h.dsn)as conn:
   for table in ['native_v2_grants','native_v2_credentials','native_v2_approvals','native_v2_operations','native_v2_installations','native_v2_certificates']:
    values=conn.execute('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text').fetchall();result[table]=hashlib.sha256(json.dumps(values).encode()).hexdigest()
  return result
 def test_native_friend_request_respond_scope_withdrawal_and_original_authority(self):
  from private_records import VisitCipher
  alice,bob,eve=self.h.login(),self.h.login('bob'),self.h.login('eve')
  car=self.connect(alice)
  def on_car(path,body=None,method='GET',expected=200):
   code,_,value=self.native(car,path,body,method)
   self.assertEqual(code,expected,value)
   return value
  personal_path='/v1/device/functional-permissions'
  current=on_car(personal_path)
  self.assertIn('friends:manage',current['approvedPurposes'])
  on_car('/v1/social/overview')
  on_car('/v1/social/trips')
  base=self.state()

  # An older connection saved with every optional function turned off.
  with psycopg.connect(self.h.dsn) as conn:
   old=dict(approvedPurposes=[],functionalDisclosureVersion=WIRE['disclosureVersion'],
            functionalDisclosureSha256=WIRE['disclosureSha256'])
   protected=VisitCipher().protect('native-functional',car['grantId'],old)
   conn.execute('UPDATE native_functional_authorizations SET protected=%s, revision=revision+1 WHERE grant_id=%s',
                (protected,car['grantId']))
  current=on_car(personal_path)
  revision=current['revision']
  account={'friends:read','friends:manage','rooms:read','rooms:interact','history:read',
           'missions:read','cautions:read','recommendations:use'}
  sensitive={'missions:progress','room-voice:receive','room-voice:transmit','room-music:read','room-music:control',
             'vehicle-location:report','vehicle-reports:read','vehicle-visits:report','device-commands:request','device-commands:receive','history:write'}
  self.assertTrue(account.issubset(current['approvedPurposes']))
  self.assertTrue(sensitive.isdisjoint(current['approvedPurposes']))
  for path in ('/v1/social/history','/v1/recommendations/settings','/v1/social/cautions'):
   with self.subTest(path=path):on_car(path)
  friend_request='/v1/social/friends/requests'
  on_car(friend_request,dict(targetId=bob['user']['id']),'POST',400)
  on_car(friend_request,dict(targetId=bob['user']['id'],functionalRevision=revision),'POST',201)
  respond=friend_request+'/'+alice['user']['id']+'/respond'
  self.assertEqual(self.h.call(respond,dict(accept=True),'POST',session=eve,who='eve')[0],404)
  self.assertEqual(self.h.call(respond,dict(accept=True),'POST',session=bob,who='bob')[0],200)
  self.assertEqual(on_car('/v1/social/overview')['friends'][0]['id'],bob['user']['id'])
  code,_,trip=self.h.call('/v1/social/trips',dict(title='Private trip',description='',memberIds=[]),
                          'POST',session=bob,who='bob')
  self.assertEqual(code,201,trip)
  on_car('/v1/social/trips/'+trip['id'],expected=404)
  self.assertEqual(on_car('/v1/social/trips'),dict(trips=[],invitations=[]))
  for path in ('/v1/device/command-inbox','/v1/native/voice-rooms','/v1/social/rooms/'+trip['id']+'/music',
               '/v1/native/rooms/'+trip['id']+'/device-reports'):
   with self.subTest(path=path):on_car(path,expected=403)
  self.assertEqual(base,self.state())
  with psycopg.connect(self.h.dsn)as conn:
   saved,=conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s',(car['grantId'],)).fetchone()
   self.assertEqual(saved,protected)
 def test_native_room_owner_member_roles_wrong_key_and_expiry(self):
  a,b=self.h.login(),self.h.login('bob');alice=self.connect(a);revision=self.approve(a,alice,['rooms:read','rooms:interact'])
  body=dict(name='Synthetic shared road',courseId=None,courseVersion=None,expiresInHours=1,functionalRevision=revision)
  code,_,room=self.native(alice,'/v1/social/rooms',body,'POST');self.assertEqual(code,201)
  detail=self.h.call('/v1/social/rooms/'+room['id'],session=a)[2]
  self.assertEqual(self.native(alice,'/v1/social/invites/'+detail['code'])[0],200)
  bob=self.connect(b,'bob');br=self.approve(b,bob,['rooms:read','rooms:interact'],'bob')
  flags={k:k=='status'for k in ('status','location','visits','music','voice','control')}
  self.assertEqual(self.native(bob,'/v1/social/rooms/join',dict(code=detail['code'],consents=flags,functionalRevision=br),'POST')[0],200)
  path='/v1/social/rooms/'+room['id']
  self.assertEqual(self.native(bob,path+'/role',dict(accountId=a['user']['id'],role='dj',functionalRevision=br),'PATCH')[0],403)
  self.assertEqual(self.native(alice,path+'/role',dict(accountId=b['user']['id'],role='dj',functionalRevision=revision),'PATCH')[0],200)
  self.assertEqual(self.native(alice,path,certificate=self.certificates[bob['grantId']])[0],401)
  self.assertEqual(self.native(bob,path+'/leave',dict(functionalRevision=br),'POST')[0],200)
  self.assertEqual(self.native(bob,path)[0],404);self.assertEqual(self.native(alice,path)[0],200)
  with psycopg.connect(self.h.dsn)as conn:conn.execute('UPDATE native_v2_grants SET expires_at=1 WHERE grant_id=%s',(alice['grantId'],))
  self.assertEqual(self.native(alice,path)[0],410)
 def test_native_history_write_current_revision_owned_read_trace_consent_and_withdrawal(self):
  from datetime import datetime,timezone,timedelta
  a,b=self.h.login(),self.h.login('bob');ca=self.connect(a);cb=self.connect(b,'bob');base=self.state()
  self.assertEqual(self.native(ca,'/v1/social/history')[0],200)
  ra=self.approve(a,ca,['history:read','history:write']);self.approve(b,cb,['history:read'],'bob')
  now=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
  record=dict(title='Synthetic native record',startedAt=now,endedAt=None,courseId=None,courseVersion=None)
  self.assertEqual(self.native(ca,'/v1/social/history',record,'POST')[0],400)
  code,_,created=self.native(ca,'/v1/social/history',dict(record,functionalRevision=ra),'POST');self.assertEqual(code,201,created)
  item=created['id'];path='/v1/social/history/'+item
  self.assertEqual(self.native(cb,path)[0],404)
  self.assertEqual(self.native(ca,path,certificate=self.certificates[cb['grantId']])[0],401)
  listing=self.native(ca,'/v1/social/history');self.assertEqual(listing[0],200,listing[2]);self.assertEqual([x['id']for x in listing[2]['history']],[item]);self.assertEqual(listing[2]['friends'],[])
  update=dict(record,title='Synthetic amended',revision=1,functionalRevision=ra)
  self.assertEqual(self.native(ca,path,update,'PUT')[0],200)
  self.assertEqual(self.native(ca,path,update,'PUT')[0],409)
  visit=dict(revision=2,place=dict(name='Synthetic virtual stop',latitude=37.0,longitude=127.0),visitedAt=now,review='Owner-only synthetic review',rating=4,functionalRevision=ra)
  code,_,saved=self.native(ca,path+'/visits',visit,'POST');self.assertEqual(code,201,saved)
  amended=dict(visit,revision=3,review='Native amended visit')
  self.assertEqual(self.native(ca,path+'/visits/'+saved['id'],amended,'PUT')[0],200)
  browser=self.h.call('/v1/social/history',dict(record,title='Browser-origin record'),'POST',session=a);self.assertEqual(browser[0],201,browser[2]);browser_path='/v1/social/history/'+browser[2]['id']
  browser_visit={k:v for k,v in visit.items()if k!='functionalRevision'};browser_visit['revision']=1
  browser_saved=self.h.call(browser_path+'/visits',browser_visit,'POST',session=a);self.assertEqual(browser_saved[0],201,browser_saved[2])
  browser_visit.update(revision=2,review='Browser amended visit')
  self.assertEqual(self.h.call(browser_path+'/visits/'+browser_saved[2]['id'],browser_visit,'PUT',session=a)[0],200)
  browser_detail=self.h.call(browser_path,session=a)[2];self.assertEqual(browser_detail['source']['kind'],'web-confirmed');self.assertEqual(browser_detail['visits'][0]['source']['kind'],'web-confirmed')

  detail=self.native(ca,path);self.assertEqual(detail[0],200,detail[2]);self.assertEqual(len(detail[2]['visits']),1);self.assertFalse(detail[2]['nativeReadOnly']);self.assertTrue(detail[2]['capabilities']['historyReplay']);self.assertEqual(detail[2]['source']['kind'],'device-reported');self.assertEqual(detail[2]['visits'][0]['source']['kind'],'device-reported')
  batch=dict(revision=4,batchId='a'*32,streamId='b'*32,label='Synthetic virtual GPS',points=[dict(latitude=37.0,longitude=127.0,capturedAt=now,accuracyMeters=5.0)],functionalRevision=ra)
  self.assertEqual(self.native(ca,path+'/trace-batches',batch,'POST')[0],403)
  # Functional history consent cannot itself enable per-record trace collection.
  self.assertEqual(self.native(ca,path+'/permissions',dict(permissionRevision=1,collectTrace=True,functionalRevision=ra),'PATCH')[0],404)
  self.assertEqual(self.h.call(path+'/permissions',dict(permissionRevision=1,collectTrace=True),'PATCH',session=a)[0],200)
  code,_,trace=self.native(ca,path+'/trace-batches',batch,'POST');self.assertEqual(code,201,trace)
  code,_,duplicate=self.native(ca,path+'/trace-batches',batch,'POST');self.assertEqual(code,200,duplicate);self.assertTrue(duplicate['duplicate'])
  self.assertEqual(self.native(ca,path)[2]['traceBatches'][0]['source']['kind'],'device-reported')
  with psycopg.connect(self.h.dsn)as conn:
   original=conn.execute('SELECT protected FROM team_histories WHERE history_id=%s',(item,)).fetchone()[0]
   original_batches=conn.execute('SELECT protected FROM team_history_trace_batches WHERE history_id=%s',(item,)).fetchall()
  newer=self.approve(a,ca,['history:read'])
  self.assertGreater(newer,ra);self.assertEqual(self.native(ca,path)[0],200)
  detail=self.native(ca,path)[2]
  self.assertEqual(self.native(ca,path,dict(update,revision=detail['revision']),'PUT')[0],409)
  self.assertEqual(self.native(ca,path+'/trace-batches',dict(batch,batchId='d'*32,revision=detail['revision'],functionalRevision=newer),'POST')[0],403)
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT protected FROM team_histories WHERE history_id=%s',(item,)).fetchone()[0],original)
   self.assertEqual(conn.execute('SELECT protected FROM team_history_trace_batches WHERE history_id=%s',(item,)).fetchall(),original_batches)
   self.assertEqual(conn.execute('SELECT count(*) FROM team_devices').fetchone()[0],0)
  self.assertEqual(self.native(ca,path,dict(update,revision=detail['revision'],functionalRevision=newer),'PUT')[0],200)
  self.assertEqual(self.state(),base)


 def test_native_history_fifty_plus_one_closed_cursor_owner_and_purpose_boundary(self):
  import base64
  from datetime import datetime,timezone,timedelta
  a,b=self.h.login(),self.h.login('bob');ca=self.connect(a);cb=self.connect(b,'bob');base=self.state()
  self.approve(a,ca,['history:read']);self.approve(b,cb,['history:read'],'bob')
  now=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat();ids=[]
  record=dict(title='Synthetic keyset record',startedAt=now,endedAt=None,courseId=None,courseVersion=None)
  with psycopg.connect(self.h.dsn)as conn:
   for index in range(51):ids.append(self.h.module.TEAM_HISTORY.add(conn,a['user']['id'],dict(record,title='Synthetic record '+str(index)),dict(kind='web-confirmed',actorId=a['user']['id'],receivedAt=now)))
   other=self.h.module.TEAM_HISTORY.add(conn,b['user']['id'],record,dict(kind='web-confirmed',actorId=b['user']['id'],receivedAt=now))
  code,_,first=self.native(ca,'/v1/social/history');self.assertEqual(code,200,first);self.assertEqual(len(first['history']),50)
  cursor=first['nextCursor'];self.assertIsInstance(cursor,str)
  path='/v1/social/history?cursor='+cursor
  code,_,last=self.native(ca,path);self.assertEqual(code,200,last);self.assertEqual(len(last['history']),1);self.assertIsNone(last['nextCursor'])
  seen=[x['id']for x in first['history']+last['history']];self.assertEqual(len(set(seen)),51);self.assertEqual(set(seen),set(ids));self.assertNotIn(other,seen)
  code,_,peer=self.native(cb,path);self.assertEqual(code,200,peer);self.assertTrue({x['id']for x in peer['history']}<={other})
  self.assertEqual(self.native(ca,path,certificate=self.certificates[cb['grantId']])[0],401)
  bad=['cursor='+cursor+'&cursor='+cursor,'cursor='+cursor+'&limit=1','cursor=','cursor='+'a'*257,'cursor=A','access_token=synthetic-not-authority','bearer=synthetic-not-authority']
  duplicate=base64.urlsafe_b64encode(b'{"updatedAt":"2026-01-01T00:00:00Z","id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}').decode().rstrip('=')
  bad.append('cursor='+duplicate)
  for query in bad:
   with self.subTest(queryLength=len(query)):self.assertEqual(self.native(ca,'/v1/social/history?'+query)[0],400)
  self.assertEqual(self.native(ca,'/v1/account?cursor='+cursor)[0],400)
  self.assertEqual(self.native(ca,'/v1/device-sessions/refresh?cursor='+cursor,{},'POST')[0],403)
  self.assertEqual(self.native(ca,path,{},'POST')[0],400)
  self.approve(a,ca,[]);self.assertEqual(self.native(ca,path)[2]['history'],last['history'])
  self.assertEqual(self.state(),base)

if __name__=='__main__':unittest.main()
