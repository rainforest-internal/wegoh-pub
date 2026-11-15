"""External-file consent contracts against isolated populated PG/real HTTP.
No live identities, device/GPS claims, external fetch or media encoder is used.
"""
from datetime import datetime,timezone,timedelta
import hashlib,json,secrets,unittest
from concurrent.futures import ThreadPoolExecutor
import threading,time
import psycopg,uvicorn
import test_team_auth as fixture
from test_team_history import HistoryTests
from test_team_photos import PhotoTests

class StoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        from team_api_docs import install_api_docs
        install_api_docs(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH,fixture.TeamTests.module.WEB)
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=HistoryTests(methodName='test_01_owner_admin_and_personal_crud_capabilities');self.h.setUp();self.api=self.h.api
    def path(self,item,target=None):return '/v1/social/history/'+item+'/export-permissions'+('/'+target if target else '')
    def permit(self,item,session,target=None,who='alice',**changes):
        target=target or session['user']['id'];info=self.api.call(self.path(item),session=session,who=who)[2];old=next((x['revision']for x in info['permissions']if x['exporterId']==target),0)
        data=dict(revision=old,historyRevision=info['historyRevision'],consent=True,visits=True,trace=False,photos=False,expiresAt=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat());data.update(changes)
        return self.api.call(self.path(item,target),data,'PUT',session=session,who=who)
    def manifest(self,items,session,who='alice'):return self.api.call('/v1/social/story-manifests',dict(historyIds=items),'POST',session=session,who=who)
    def setup_record(self,trace=False):
        a,b,e=self.h.users();item=self.h.create(a);self.h.visit(item,a)
        if trace:
            self.h.call('/history/'+item+'/permissions',dict(permissionRevision=1,collectTrace=True),'PATCH',session=a)
            points=[dict(latitude=37.0,longitude=127+x,capturedAt='2026-01-02T02:00:'+str(i).zfill(2)+'Z',accuracyMeters=10)for i,x in enumerate([0,.001,.004,.006,.004,.001,0,.01,.014,.018,.02])]
            self.assertEqual(self.h.call('/history/'+item+'/trace-batches',self.h.batch(item,a,points=points),'POST',session=a)[0],201)
        self.h.approve_text(item,a);return a,b,e,item
    def test_01_default_off_self_explicit_csrf_owner_native(self):
        a,b,e,item=self.setup_record();self.assertEqual(self.manifest([item],a)[0],404)
        data=dict(revision=0,historyRevision=self.h.detail(item,a)['revision'],consent=True,visits=True,trace=False,photos=False,expiresAt=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        self.assertEqual(self.api.call(self.path(item,a['user']['id']),data,'PUT',session=a,csrf=False)[0],403)
        self.assertEqual(self.api.call(self.path(item,b['user']['id']),data,'PUT',session=b,who='bob')[0],404)
        self.assertEqual(self.api.native('/v1/social/story-manifests')[0],404)
        self.assertEqual(self.permit(item,a)[0],200);code,headers,value=self.manifest([item],a);self.assertEqual(code,201,value)
        self.assertEqual({k.lower():v for k,v in headers.items()}['cache-control'],'private, no-store');self.assertNotIn('file',value);self.assertEqual(value['histories'][0]['visits'][0]['place']['latitude'],None)
    def test_02_current_friend_internal_grants_and_separate_participant_purposes(self):
        a,b,e,item=self.setup_record();self.h.make_friend(a,b);self.assertEqual(self.h.share(item,a,b)[0],200)
        self.assertEqual(self.manifest([item],b,'bob')[0],404);self.assertEqual(self.permit(item,a,target=b['user']['id'])[0],200)
        code,_,value=self.manifest([item],b,'bob');self.assertEqual(code,201,value);key=value['id']
        self.assertEqual(self.api.call('/v1/social/story-manifests/'+key,session=a)[0],404)
        self.assertEqual(self.api.call(self.path(item),session=b,who='bob')[2]['permissions'][0]['exporterId'],b['user']['id'])
        self.assertEqual(self.api.call(self.path(item,b['user']['id']),method='DELETE',session=a)[0],200)
        self.assertEqual(self.api.call('/v1/social/story-manifests/'+key,session=b,who='bob')[0],404)
        self.assertEqual(self.h.detail(item,b,'bob')['visits'][0]['review'],'Private place review') # Internal use survives external revocation.
    def test_03_endpoint_privacy_segments_provenance_and_no_identity_name(self):
        a,b,e,item=self.setup_record(True);self.assertEqual(self.permit(item,a,trace=True)[0],200)
        code,_,value=self.manifest([item],a);self.assertEqual(code,201,value);history=value['histories'][0];points=history['traceBatches'][0]['points']
        self.assertEqual(history['traceBatches'][0]['source']['kind'],'browser-reported');self.assertEqual([p['originalIndex']for p in points],[2,3,4,7,8]);self.assertEqual([p['segmentId']for p in points],[0,0,0,1,1])
        self.assertEqual(value['privacy']['suppressedPoints'],6);self.assertEqual(value['privacy']['endpointRadiusMeters'],200)
        raw=json.dumps(value);self.assertNotIn('@',raw);self.assertNotIn('ownerName',raw);self.assertNotIn('roomId',raw)
        self.assertEqual(self.api.call('/v1/social/story-manifests/'+value['id'],session=a)[2]['checksum'],value['checksum'])
    def test_04_revision_encryption_no_implicit_resurrection(self):
        a,b,e,item=self.setup_record();self.assertEqual(self.permit(item,a)[0],200);value=self.manifest([item],a)[2]
        with psycopg.connect(self.api.dsn)as conn:
            raw=bytes(conn.execute('SELECT protected FROM team_story_permissions').fetchone()[0]);self.assertNotIn(b'expiresAt',raw)
            manifest=bytes(conn.execute('SELECT protected FROM team_story_manifests').fetchone()[0]);self.assertNotIn(item.encode(),manifest)
        record=self.h.detail(item,a);data={k:record[k]for k in('revision','title','startedAt','endedAt','courseId','courseVersion')};data['title']='Changed approved content'
        self.assertEqual(self.h.call('/history/'+item,data,'PUT',session=a)[0],200);self.assertEqual(self.api.call('/v1/social/story-manifests/'+value['id'],session=a)[0],404)
        self.h.approve_text(item,a);self.assertEqual(self.manifest([item],a)[0],404);self.assertEqual(self.permit(item,a)[0],200);self.assertEqual(self.manifest([item],a)[0],201)
    def test_05_approved_photo_export_url_and_report_requarantine(self):
        a,b,e,item=self.setup_record();visit=self.h.detail(item,a)['visits'][0]['id'];photo=PhotoTests(methodName='test_01_actual_sandbox_orientation_and_metadata_stripping');photo.h=self.h;photo.api=self.api
        code,_,upload=photo.upload(item,visit,a);self.assertEqual(code,201,upload);entry=upload['photo'];self.assertEqual(self.permit(item,a,photos=True)[0],200)
        value=self.manifest([item],a)[2];self.assertEqual(value['histories'][0]['visits'][0]['photos'],[])
        photo.review(item,a,entry);self.assertEqual(self.manifest([item],a)[0],404);self.assertEqual(self.permit(item,a,photos=True)[0],200)
        value=self.manifest([item],a)[2];url=value['histories'][0]['visits'][0]['photos'][0]['url'];self.assertEqual(self.api.call(url,session=a)[0],200)
        self.assertEqual(self.api.call(url,session=b,who='bob')[0],404)
        self.assertEqual(self.api.call(entry['url']+'/reports',dict(reason='privacy'),'POST',session=a)[0],202);self.assertEqual(self.api.call(url,session=a)[0],404)
        photo.review(item,a,entry);self.assertEqual(self.manifest([item],a)[0],404) # Reapproval never revives old external consent.
    def test_06_expiry_account_removal_schema_preservation_and_bounds(self):
        a,b,e,item=self.setup_record();self.assertEqual(self.permit(item,a,expiresAt=(datetime.now(timezone.utc)+timedelta(hours=25)).isoformat())[0],400)
        self.assertEqual(self.permit(item,a,photos=True,visits=False)[0],400);self.assertEqual(self.permit(item,a)[0],200);value=self.manifest([item],a)[2]
        self.assertEqual(self.manifest([item,item],a)[0],400);self.assertEqual(self.manifest([item]*6,a)[0],400)
        with psycopg.connect(self.api.dsn)as conn:
            conn.execute((fixture.ROOT/'server/schema.sql').read_text());self.assertEqual(conn.execute('SELECT count(*)FROM team_story_permissions').fetchone()[0],1)
            conn.execute("UPDATE team_story_manifests SET expires_at=now()-interval '1 second'")
        self.assertEqual(self.api.call('/v1/social/story-manifests/'+value['id'],session=a)[0],404)
        fixture.TeamTests.write_members([r for r in fixture.TeamTests.members_rows if r['email']!='alice@example.invalid'])
        self.assertEqual(self.manifest([item],a)[0],403)
    def test_07_friend_revocation_and_explicit_manifest_discard(self):
        a,b,e,item=self.setup_record();self.h.make_friend(a,b);self.h.share(item,a,b);self.permit(item,a,target=b['user']['id']);value=self.manifest([item],b,'bob')[2]
        self.assertEqual(self.api.call('/v1/social/story-manifests/'+value['id'],method='DELETE',session=b,who='bob')[0],200);self.assertEqual(self.api.call('/v1/social/story-manifests/'+value['id'],session=b,who='bob')[0],404)
        # Actual second HTTP worker: external revocation waits for the current
        # graph/history snapshot, then makes every future retrieval unavailable.
        port=fixture.free_port();server=uvicorn.Server(uvicorn.Config(self.api.module.app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False,log_level='warning',ws='websockets-sansio'));thread=threading.Thread(target=server.run,daemon=True);thread.start()
        other=fixture.TeamTests(methodName='test_01_jwt_verification_and_exact_hosts');other.port=port
        service=self.api.module.TEAM_STORY;original=service.permitted;observed=threading.Event();release=threading.Event()
        def held(conn,record,actor):
            answer=original(conn,record,actor);observed.set()
            if not release.wait(3):raise RuntimeError('Snapshot was not released')
            return answer
        try:
            end=time.monotonic()+3
            while not server.started and time.monotonic()<end:time.sleep(.01)
            self.assertTrue(server.started);service.permitted=held
            with ThreadPoolExecutor(max_workers=2)as pool:
                pending=pool.submit(other.call,'/v1/social/story-manifests',dict(historyIds=[item]),'POST',who='bob',session=b);self.assertTrue(observed.wait(3))
                revoke=pool.submit(self.api.call,self.path(item,b['user']['id']),method='DELETE',session=a)
                time.sleep(.1);self.assertFalse(revoke.done());release.set();created=pending.result(3);self.assertEqual(created[0],201,created);self.assertEqual(revoke.result(3)[0],200)
            service.permitted=original;self.assertEqual(self.api.call('/v1/social/story-manifests/'+created[2]['id'],session=b,who='bob')[0],404)
        finally:release.set();service.permitted=original;server.should_exit=True;thread.join(5)
        self.permit(item,a,target=b['user']['id']);value=self.manifest([item],b,'bob')[2];self.assertEqual(self.h.call('/friends/'+b['user']['id'],method='DELETE',session=a)[0],200);self.assertEqual(self.api.call('/v1/social/story-manifests/'+value['id'],session=b,who='bob')[0],404)
        self.h.make_friend(a,b);self.h.share(item,a,b);self.assertEqual(self.manifest([item],b,'bob')[0],404)
    def test_08_openapi_exact_body_binary_closed_and_stale_permission(self):
        a,b,e,item=self.setup_record();self.assertEqual(self.permit(item,a)[0],200);self.assertEqual(self.permit(item,a,revision=0)[0],409)
        code,_,schema=self.api.call('/openapi.json',session=a);self.assertEqual(code,200)
        paths=schema['paths'];permission=paths['/v1/social/history/{item}/export-permissions/{target}']['put'];body=permission['requestBody']['content']['application/json']['schema'];self.assertEqual(set(body['required']),{'revision','historyRevision','consent','visits','trace','photos','expiresAt'})
        media=paths['/v1/social/story-manifests/{key}/photos/{item}/{visit}/{photo}']['get'];self.assertFalse(media['x-wegoh-executable']);self.assertFalse(media['x-wegoh-native-access']);self.assertIn('image/jpeg',media['responses']['200']['content'])
        value=self.manifest([item],a)[2];self.assertEqual(len(value['checksum']),64);self.assertLessEqual(datetime.fromisoformat(value['expiresAt'])-datetime.fromisoformat(value['serverNow']),timedelta(minutes=5))

if __name__=='__main__':unittest.main()
