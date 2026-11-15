"""Focused real HTTP/WS and private temporary PostgreSQL history contracts.
No production account, file, trace provider, SDK or clock is accessed/changed.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import json,secrets,threading,time,unittest
import os,stat,sys,tempfile
from pathlib import Path
import psycopg,uvicorn
import test_team_auth as fixture
import test_team_friends as friends

class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.TeamTests.setUpClass()
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.api=fixture.TeamTests(methodName='test_01_jwt_verification_and_exact_hosts');self.api.setUp()
    def call(self,path,data=None,method='GET',who='alice',session=None,**kwargs):return self.api.call('/v1/social'+path,data,method,who=who,session=session,**kwargs)
    def users(self):return self.api.login(),self.api.login('bob'),self.api.login('eve')
    def make_friend(self,a,b):
        self.assertEqual(self.call('/friends/requests',{'targetId':b['user']['id']},'POST',session=a)[0],201)
        self.assertEqual(self.call('/friends/requests/'+a['user']['id']+'/respond',{'accept':True},'POST','bob',b)[0],200)
    def create(self,session,who='alice',**kw):
        data=dict(title='Synthetic private trip',startedAt='2026-01-02T01:00:00Z',endedAt=None,courseId=None,courseVersion=None);data.update(kw)
        status,_,record=self.call('/history',data,'POST',who,session);self.assertEqual(status,201,record);return record['id']
    def detail(self,item,session,who='alice'):
        status,_,record=self.call('/history/'+item,who=who,session=session);self.assertEqual(status,200,record);return record
    def visit(self,item,session,**kw):
        data=dict(revision=self.detail(item,session)['revision'],place=dict(name='Synthetic confirmed place',latitude=37.654321,longitude=127.123456),visitedAt='2026-01-02T02:00:00Z',review='Private place review',rating=4);data.update(kw)
        return self.call('/history/'+item+'/visits',data,'POST',session=session)
    def share(self,item,a,b,visits=True,trace=False,expected=None):
        rev=self.detail(item,a)['permissionRevision']if expected is None else expected
        return self.call('/history/'+item+'/shares/'+b['user']['id'],dict(permissionRevision=rev,visits=visits,trace=trace),'PUT',session=a)
    def approve_text(self,item,session):
        code,_,result=self.call('/history/'+item+'/review-request',dict(revision=self.detail(item,session)['revision'],consent=True),'PATCH',session=session);self.assertEqual(code,200,result)
        review=result['review']
        code,_,value=self.api.call('/v1/moderation/content/history/'+item,dict(checksum=review['checksum'],decision='approved',reviewer='Synthetic reviewer',reviewNote='Synthetic full text review'),'POST',session=session);self.assertEqual(code,200,value)
    def batch(self,item,session,**changes):
        body=dict(revision=self.detail(item,session)['revision'],batchId=secrets.token_hex(16),streamId=secrets.token_hex(16),label='Browser report',points=[dict(latitude=37.5,longitude=127.0,capturedAt='2026-01-02T02:00:00Z',accuracyMeters=12),dict(latitude=37.51,longitude=127.01,capturedAt='2026-01-02T02:00:01Z',accuracyMeters=15)]);body.update(changes);return body

    def test_01_owner_admin_and_personal_crud_capabilities(self):
        a,b,e=self.users();item=self.create(b,'bob')
        self.assertEqual(self.call('/history/'+item,session=a)[0],404) # actual admin is not another owner
        self.assertEqual(self.call('/history/'+item,method='DELETE',session=a)[0],404)
        detail=self.detail(item,b,'bob');self.assertEqual(detail['source']['kind'],'web-confirmed');self.assertFalse(detail['permissions']['collectTrace'])
        self.assertTrue(detail['capabilities']['historyVisits']);self.assertFalse(detail['capabilities']['historyExport'])
        self.assertEqual(self.api.native('/v1/social/history')[0],401) # no native bearer is authenticated
        self.assertEqual(self.call('/history',who=None)[0],401)
        update={k:detail[k]for k in ('title','startedAt','endedAt','courseId','courseVersion','revision')};update['title']='Edited trip'
        self.assertEqual(self.call('/history/'+item,update,'PUT','bob',b)[0],200)
        self.assertEqual(self.call('/history/'+item,update,'PUT','bob',b)[0],409)
        self.assertEqual(self.detail(item,b,'bob')['title'],'Edited trip')
        self.assertEqual(self.call('/history/'+item,method='DELETE',who='bob',session=b)[0],200)
        self.assertEqual(self.call('/history/'+item,who='bob',session=b)[0],404)
        # Run the one existing capability/host case, not the other16 friendship tests.
        old=friends.FriendTests(methodName='test_10_capabilities_browser_only_strict_inputs');old.test_10_capabilities_browser_only_strict_inputs()

    def test_02_confirmed_visit_revision_rating_encryption_and_tamper(self):
        a,b,_=self.users();item=self.create(a);self.assertEqual(self.visit(item,a,rating=True)[0],400)
        self.assertEqual(self.visit(item,a,source={'kind':'device-reported'})[0],400)
        status,_,added=self.visit(item,a);self.assertEqual(status,201);detail=self.detail(item,a);visit=detail['visits'][0]
        self.assertEqual(visit['photos'],[]);self.assertEqual(visit['source']['actorId'],a['user']['id']);self.assertEqual(visit['rating'],4)
        self.assertEqual(self.call('/history/'+item+'/visits',dict(revision=1,place=visit['place'],visitedAt=visit['visitedAt'],review='',rating=None),'POST',session=a)[0],409)
        data=dict(revision=detail['revision'],place=visit['place'],visitedAt=visit['visitedAt'],review='Changed review',rating=5)
        self.assertEqual(self.call('/history/'+item+'/visits/'+added['id'],data,'PUT',session=a)[0],200)
        with psycopg.connect(self.api.dsn)as conn:
            raw=bytes(conn.execute('SELECT protected FROM team_history_visits WHERE history_id=%s',(item,)).fetchone()[0]);self.assertNotIn(b'127.123456',raw);self.assertNotIn(b'Changed review',raw)
            damaged=bytearray(raw);damaged[-1]^=1;conn.execute('UPDATE team_history_visits SET protected=%s WHERE history_id=%s',(bytes(damaged),item))
        self.assertEqual(self.call('/history/'+item,session=a)[0],503)

    def test_03_individual_grant_purpose_scope_and_delete(self):
        a,b,e=self.users();item=self.create(a);self.visit(item,a)
        self.assertEqual(self.share(item,a,b)[0],404);self.make_friend(a,b);self.assertEqual(self.share(item,a,b)[0],200);self.assertEqual(self.call('/history/'+item,session=b,who='bob')[0],404);self.approve_text(item,a)
        value=self.detail(item,b,'bob');self.assertFalse(value['own']);self.assertEqual(len(value['visits']),1);self.assertEqual(value['traceBatches'],[]);self.assertEqual(value['grants'],[]);self.assertIsNone(value['permissions'])
        self.assertEqual(self.call('/history/'+item+'/permissions',dict(permissionRevision=1,collectTrace=True),'PATCH','bob',b)[0],404)
        self.assertEqual(self.call('/history/'+item,session=e,who='eve')[0],404)
        self.assertEqual(self.call('/history/'+item+'/shares/'+b['user']['id'],dict(permissionRevision=1,visits=True,trace=True),'PUT',session=a)[0],409)
        self.assertEqual(self.call('/history/'+item+'/share',method='DELETE',session=a)[0],200)
        self.assertEqual(self.call('/history/'+item,session=b,who='bob')[0],404)
        own=self.detail(item,a);self.assertEqual(len(own['visits']),1)
        v=own['visits'][0];self.assertEqual(self.call('/history/'+item+'/visits/'+v['id'],dict(revision=own['revision']),'DELETE',session=a)[0],200)
        self.assertEqual(self.detail(item,a)['visits'],[])

    def test_04_trace_collection_revocation_idempotence_and_report_provenance(self):
        a,b,_=self.users();item=self.create(a);body=self.batch(item,a);path='/history/'+item
        self.assertEqual(self.call(path+'/trace-batches',body,'POST',session=a)[0],403)
        self.assertEqual(self.call(path+'/permissions',dict(permissionRevision=1,collectTrace=True),'PATCH',session=a)[0],200)
        self.assertEqual(self.call(path+'/trace-batches',body,'POST',session=a)[0],201)
        duplicate=self.call(path+'/trace-batches',body,'POST',session=a);self.assertEqual(duplicate[0],200);self.assertTrue(duplicate[2]['duplicate'])
        altered=dict(body,label='Changed batch');self.assertEqual(self.call(path+'/trace-batches',altered,'POST',session=a)[0],409)
        self.assertEqual(self.detail(item,a)['traceBatches'][0]['source']['kind'],'browser-reported')
        self.make_friend(a,b);self.assertEqual(self.share(item,a,b,visits=False,trace=True)[0],200);self.approve_text(item,a)
        shared=self.detail(item,b,'bob');self.assertEqual(shared['visits'],[]);self.assertEqual(shared['tracePointCount'],2)
        self.assertEqual(self.call(path+'/permissions',dict(permissionRevision=1,collectTrace=False),'PATCH',session=a)[0],200) # stale rev still stops collection
        self.assertEqual(self.call(path+'/trace-batches',self.batch(item,a),'POST',session=a)[0],403)
        self.assertEqual(len(self.detail(item,a)['traceBatches']),1)
        self.assertEqual(self.call(path+'/trace-batches',dict(body,source='vehicle'),'POST',session=a)[0],400)

    def test_05_real_websocket_grant_revoke_and_block_denial(self):
        a,b,_=self.users();self.make_friend(a,b);item=self.create(a);self.visit(item,a);self.share(item,a,b);self.approve_text(item,a)
        with self.api.websocket(b,who='bob')as socket:
            self.assertEqual(json.loads(socket.recv(timeout=2))['type'],'snapshot')
            self.assertEqual(self.call('/history/'+item+'/shares/'+b['user']['id'],method='DELETE',session=a)[0],200)
            event=json.loads(socket.recv(timeout=3));self.assertIn('history',event['resources']);self.assertNotIn('latitude',json.dumps(event))
        self.assertEqual(self.call('/history/'+item,session=b,who='bob')[0],404);self.share(item,a,b)
        self.assertEqual(self.call('/blocks',dict(targetId=b['user']['id']),'POST',session=a)[0],201)
        self.assertEqual(self.call('/history/'+item,session=b,who='bob')[0],404)
        self.assertEqual(self.call('/history',session=b,who='bob')[2]['history'],[])
        self.assertEqual(len(self.detail(item,a)['visits']),1)
        with psycopg.connect(self.api.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*)FROM team_history_shares WHERE history_id=%s',(item,)).fetchone()[0],0)
        self.call('/blocks/'+b['user']['id'],method='DELETE',session=a);self.make_friend(a,b)
        self.assertEqual(self.call('/history/'+item,session=b,who='bob')[0],404) # new friendship is not renewed history consent

    def test_06_concurrent_grants_and_collection_use_independent_workers(self):
        a,b,_=self.users();self.make_friend(a,b);item=self.create(a);port=fixture.free_port()
        server=uvicorn.Server(uvicorn.Config(self.api.module.app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False,log_level='warning',ws='websockets-sansio'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
        other=fixture.TeamTests(methodName='test_01_jwt_verification_and_exact_hosts');other.port=port
        try:
            end=time.monotonic()+5
            while not server.started and time.monotonic()<end:time.sleep(.01)
            self.assertTrue(server.started)
            with ThreadPoolExecutor(max_workers=2)as pool:
                work=[pool.submit(self.share,item,a,b,True,False,1),pool.submit(other.call,'/v1/social/history/'+item+'/permissions',dict(permissionRevision=1,collectTrace=True),'PATCH',session=a)]
                codes=[future.result(timeout=5)[0]for future in work]
            self.assertEqual(sorted(codes),[200,409]);self.assertEqual(self.detail(item,a)['permissionRevision'],2)
            # Pause only after the actual DB friendship read while graph/history
            # locks remain held. Another actual worker must wait before unfriend.
            import team_history
            original=team_history.linked;observed=threading.Event();release=threading.Event()
            def held_linked(conn,owner,target):
                actual=original(conn,owner,target)
                if owner==a['user']['id']and target==b['user']['id']:
                    observed.set()
                    if not release.wait(3):raise RuntimeError('Held share was not released')
                return actual
            self.call('/history/'+item+'/share',method='DELETE',session=a)
            rev=self.detail(item,a)['permissionRevision']
            try:
                team_history.linked=held_linked
                with ThreadPoolExecutor(max_workers=2)as pool:
                    grant=pool.submit(self.share,item,a,b,True,False,rev)
                    self.assertTrue(observed.wait(3))
                    unlink=pool.submit(other.call,'/v1/social/friends/'+b['user']['id'],method='DELETE',session=a)
                    time.sleep(.1);self.assertFalse(unlink.done())
                    release.set();self.assertEqual(grant.result(timeout=3)[0],200);self.assertEqual(unlink.result(timeout=3)[0],200)
            finally:release.set();team_history.linked=original
            with psycopg.connect(self.api.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*)FROM team_history_shares WHERE history_id=%s',(item,)).fetchone()[0],0)
            self.make_friend(a,b)
            self.assertEqual(self.call('/history/'+item,session=b,who='bob')[0],404)
        finally:server.should_exit=True;thread.join(5)

    def test_07_room_course_record_never_copies_other_member_content(self):
        a,b,_=self.users();pack=self.api.pack();self.api.publish(pack,a);self.api.approve(pack,a)
        status,_,room=self.call('/rooms',dict(name='Synthetic room',courseId=pack['id'],courseVersion=1,expiresInHours=6),'POST',session=a);self.assertEqual(status,201)
        options={key:key in('status','location')for key in('status','location','visits','music','voice','control')}
        self.call('/rooms/join',dict(code=room['code'],consents=options),'POST','bob',b)
        self.call('/rooms/'+room['id']+'/signals',dict(kind='rest',destination=dict(name='Other participant private place',latitude=35.1,longitude=128.1)),'POST','bob',b)
        status,_,record=self.call('/rooms/'+room['id']+'/history',dict(title='My selected room course'),'POST',session=a);self.assertEqual(status,201)
        value=self.detail(record['id'],a);self.assertEqual(value['courseId'],pack['id']);self.assertEqual(value['visits'],[]);self.assertEqual(value['traceBatches'],[]);self.assertEqual(value['sharedWith'],[])
        self.assertEqual(self.call('/history/'+record['id'],session=b,who='bob')[0],404)
        self.call('/rooms/'+room['id']+'/leave',method='POST',session=a);self.assertEqual(self.detail(record['id'],a)['title'],'My selected room course')

    def test_08_keyset_cursor_never_silently_truncates_or_fakes_times(self):
        a=self.api.login();service=self.api.module.TEAM_HISTORY
        value=dict(title='Synthetic page',startedAt='2026-01-02T01:00:00+00:00',endedAt=None,courseId=None,courseVersion=None)
        # Exact synthetic encrypted seed bypasses only HTTP write rate, never production state.
        with psycopg.connect(self.api.dsn)as conn:
            for _ in range(54):service.add(conn,a['user']['id'],value,dict(kind='web-confirmed',actorId=a['user']['id'],receivedAt='2026-01-02T01:00:00+00:00'))
        first=self.call('/history',session=a)[2];self.assertEqual(len(first['history']),50);self.assertTrue(first['nextCursor'])
        second=self.call('/history?cursor='+first['nextCursor'],session=a)[2];self.assertEqual(len(second['history']),4);self.assertIsNone(second['nextCursor']);self.assertEqual(len({v['id']for v in first['history']+second['history']}),54)
        self.assertEqual(self.call('/history?cursor=invalid',session=a)[0],400)
        self.assertEqual(self.call('/history?ownerId=someone',session=a)[0],400)
        item=first['history'][0]['id'];bad=dict(revision=1,place=dict(name='Bad future',latitude=37.5,longitude=127.0),visitedAt=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),review='',rating=None)
        self.assertEqual(self.call('/history/'+item+'/visits',bad,'POST',session=a)[0],400)

def serve_fixture(path):
    class HistoryBrowserFixture(friends.FriendTests):
        @classmethod
        def write_members(cls,rows):
            names={'alice':'가'*64,'bob':'나'*64}
            super().write_members([dict(row,name=names.get(row['email'].split('@')[0],row['name']))for row in rows])
        @classmethod
        def fixture_tick(cls,helper,config):
            control=config.with_suffix('.control.json')
            if not control.exists():return
            info=control.lstat()
            if not stat.S_ISREG(info.st_mode)or info.st_uid!=os.getuid()or info.st_mode&0o077:raise RuntimeError('Unsafe isolated control')
            value=json.loads(control.read_bytes())
            action=value.get('action')if isinstance(value,dict)else None
            if action=='seed-history-page':
                if set(value)!={'action','accountId','count'}or type(value['count'])is not int or not 1<=value['count']<=60:raise RuntimeError('Invalid synthetic seed')
            elif action=='set-fixture-membership':
                if set(value)!={'action','accountId','allowed'}or type(value['allowed'])is not bool:raise RuntimeError('Invalid synthetic membership')
            else:raise RuntimeError('Invalid synthetic control')
            if cls.state.resolve().parent!=Path(tempfile.gettempdir()).resolve()or not cls.state.name.startswith('wegoh-team-contract-'):raise RuntimeError('Not an owned temporary cluster')
            owner=value['accountId'];result=dict(action=action)
            with psycopg.connect(cls.dsn)as conn:
                row=conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s',(owner,)).fetchone()
                if not row:raise RuntimeError('Not a generated fixture actor')
                if action=='seed-history-page':
                    for index in range(value['count']):
                        record=dict(title='합성 페이지 기록 '+str(index+1),startedAt='2026-01-02T01:00:00+00:00',endedAt=None,courseId=None,courseVersion=None)
                        cls.module.TEAM_HISTORY.add(conn,owner,record,dict(kind='synthetic-test',actorId=owner,receivedAt=datetime.now(timezone.utc).isoformat()))
                    result['created']=value['count']
                else:
                    from private_records import VisitCipher
                    email=VisitCipher().restore('team-account:'+owner,'identity',row[0])['email']
                    base=next((member for member in cls.members_rows if member['email']==email),None)
                    if not base:raise RuntimeError('Not a declared synthetic actor')
                    members=[member for member in json.loads(cls.members_file.read_bytes())if member['email']!=email]
                    if value['allowed']:members.append(base)
                    cls.write_members(members);result['allowed']=value['allowed']
            result['performedAt']=datetime.now(timezone.utc).isoformat()
            target=config.with_suffix('.control-result.json');target.write_text(json.dumps(result));target.chmod(0o600);control.unlink()
    friends.serve_fixture(path,fixture_class=HistoryBrowserFixture)

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--serve-fixture':serve_fixture(sys.argv[2])
    else:unittest.main(verbosity=2)
