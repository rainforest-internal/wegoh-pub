"""Only synthetic photo/private temporary PG contracts; no production state/keys."""
import io,json,sys,http.client,subprocess,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import psycopg
from fastapi import HTTPException
from PIL import Image,PngImagePlugin
import test_team_auth as fixture
import test_team_friends as friends
import test_team_history as history
from team_photos import bounded_worker,WORKER,ENV

class PhotoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        from team_api_docs import install_api_docs
        install_api_docs(fixture.TeamTests.module.app,fixture.TeamTests.module.TEAM_AUTH,fixture.TeamTests.module.WEB)
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=history.HistoryTests(methodName='test_01_owner_admin_and_personal_crud_capabilities');self.h.setUp();self.api=self.h.api
    def image(self,fmt='PNG',size=(80,40)):
        out=io.BytesIO();image=Image.new('RGB',size,'navy')
        if fmt=='JPEG':
            exif=Image.Exif();exif[274]=6;exif[305]='Synthetic photo metadata';image.save(out,format=fmt,exif=exif)
        else:
            info=PngImagePlugin.PngInfo();info.add_text('GPS','Synthetic private marker');image.save(out,format=fmt,pnginfo=info)
        return out.getvalue()
    def setup_visit(self):
        a,b,e=self.h.users();item=self.h.create(a);code,_,visit=self.h.visit(item,a);self.assertEqual(code,201);return a,b,e,item,visit['id']
    def path(self,item,visit,photo=None):return '/v1/social/history/'+item+'/visits/'+visit+'/photos'+('/'+photo if photo else '')
    def upload(self,item,visit,session,*,who='alice',raw=None,ctype='image/png',rights=True,expected=None,csrf=True,origin=fixture.WEB):
        if expected is None:expected=self.h.detail(item,session,who)['revision']
        headers={'Host':'web.wegoh.invalid','Cf-Access-Jwt-Assertion':self.api.assertion(who),'Cookie':session['cookie'],'Content-Type':ctype,'Origin':origin,'X-WegoH-History-Revision':str(expected)}
        if csrf:headers['X-WegoH-CSRF']=session['csrfToken']
        if rights:headers['X-WegoH-Rights-Confirmed']='true'
        conn=http.client.HTTPConnection('127.0.0.1',self.api.port,timeout=12);conn.request('POST',self.path(item,visit),body=raw if raw is not None else self.image(),headers=headers);response=conn.getresponse();body=response.read();result=(response.status,dict(response.getheaders()),json.loads(body));conn.close();return result
    def grant(self,item,a,b,photos,visits=True):
        return self.h.call('/history/'+item+'/shares/'+b['user']['id'],dict(permissionRevision=self.h.detail(item,a)['permissionRevision'],visits=visits,trace=False,photos=photos),'PUT',session=a)
    def review(self,item,a,photo=None):
        path='/v1/social/history/'+item
        if photo:path=photo['url']
        result=self.api.call(path+'/review-request',dict(revision=self.h.detail(item,a)['revision'],consent=True),'PATCH',session=a)
        self.assertEqual(result[0],200,result)
        review=result[2]['review'];endpoint='/v1/moderation/content/'+review['kind']+'/'+review['key']
        code,_,value=self.api.call(endpoint,session=a);self.assertEqual(code,200,value)
        self.assertEqual(value['review']['checksum'],review['checksum'])
        self.assertEqual(self.api.call(endpoint,dict(checksum='0'*64,decision='approved',reviewer='Synthetic reviewer',reviewNote='Synthetic complete review'),'POST',session=a)[0],409)
        code,_,value=self.api.call(endpoint,dict(checksum=review['checksum'],decision='approved',reviewer='Synthetic reviewer',reviewNote='Synthetic complete review'),'POST',session=a);self.assertEqual(code,200,value)
        return endpoint
    def test_01_actual_sandbox_orientation_and_metadata_stripping(self):
        check=subprocess.run([sys.executable,'-I',str(WORKER),'--probe'],capture_output=True,timeout=4,env=ENV);self.assertEqual(check.returncode,0);self.assertEqual(set(json.loads(check.stdout)['blocked']),{'file','network'})
        for fmt,ctype,expected in [('JPEG','image/jpeg',(40,80)),('PNG','image/png',(80,40))]:
            meta,raw=bounded_worker(self.image(fmt),ctype)
            with Image.open(io.BytesIO(raw))as result:self.assertEqual(result.format,'JPEG');self.assertEqual(result.size,expected);self.assertFalse(result.getexif());self.assertNotIn('GPS',result.info)
            self.assertNotIn(b'Synthetic',raw);self.assertIn(meta['sandbox'],('linux-seccomp-memory-only','macos-seatbelt'))
    def test_02_rights_owner_csrf_origin_native_and_capabilities(self):
        a,b,e,item,visit=self.setup_visit();self.assertTrue(a['capabilities']['historyPhotos']);self.assertTrue(a['capabilities']['historyPhotoUpload'])
        self.assertEqual(self.upload(item,visit,a,rights=False)[0],400)
        self.assertEqual(self.upload(item,visit,a,csrf=False)[0],403)
        self.assertEqual(self.upload(item,visit,a,origin='https://else.invalid')[0],403)
        self.assertEqual(self.upload(item,visit,b,who='bob',expected=2)[0],404)
        self.assertEqual(self.api.native(self.path(item,visit,'0'*32))[0],401)
        _,_,credential=self.api.pair(a)
        self.assertEqual(self.api.native(self.path(item,visit,'0'*32),token=credential['accessToken'])[0],401)
        code,_,schema=self.api.call('/openapi.json',session=a);self.assertEqual(code,200)
        path='/v1/social/history/{item}/visits/{visit}/photos';post=schema['paths'][path]['post'];get=schema['paths'][path+'/{photo}']['get'];delete=schema['paths'][path+'/{photo}']['delete']
        self.assertEqual(set(post['requestBody']['content']),{'image/jpeg','image/png'});self.assertFalse(post['x-wegoh-executable']);self.assertFalse(get['x-wegoh-executable']);self.assertTrue(delete['x-wegoh-executable'])
        self.assertTrue({'X-WegoH-History-Revision','X-WegoH-Rights-Confirmed'}<={x['name']for x in post['parameters']})
        self.assertEqual(post['security'],[{'CloudflareAccess':[],'TeamSession':[],'CurrentSessionCSRF':[]}])
        csrf=schema['components']['securitySchemes']['CurrentSessionCSRF']
        self.assertEqual((csrf['type'],csrf['in'],csrf['name']),('apiKey','header','X-WegoH-CSRF'))
        self.assertFalse(any(x['name']=='X-WegoH-CSRF'for x in post['parameters']))
        self.assertEqual(get['responses']['200']['content']['image/jpeg']['schema']['format'],'binary')

        with psycopg.connect(self.api.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*)FROM team_history_photos').fetchone()[0],0)
    def test_03_actual_upload_canonical_jpeg_and_encrypted_metadata_blob(self):
        a,b,e,item,visit=self.setup_visit();status,_,value=self.upload(item,visit,a,raw=self.image('JPEG'),ctype='image/jpeg');self.assertEqual(status,201,value);self.assertEqual(value['revision'],3)
        photo=value['photo'];self.assertEqual((photo['width'],photo['height']),(40,80));self.assertEqual(photo['source']['actorId'],a['user']['id']);self.assertEqual(photo['contentType'],'image/jpeg')
        code,headers,image=self.api.call(photo['url'],session=a);self.assertEqual(code,200);self.assertEqual({k.lower():v for k,v in headers.items()}['content-type'],'image/jpeg');self.assertEqual({k.lower():v for k,v in headers.items()}['cache-control'],'private, no-store')
        with Image.open(io.BytesIO(image))as result:self.assertFalse(result.getexif())
        with psycopg.connect(self.api.dsn)as conn:
            meta,blob=conn.execute('SELECT protected,image_protected FROM team_history_photos').fetchone();self.assertNotIn(b'user-upload',bytes(meta));self.assertNotIn(image,bytes(blob));self.assertNotIn(b'Synthetic',bytes(blob))
        self.assertEqual(len(self.h.detail(item,a)['visits'][0]['photos']),1)
        self.assertEqual(photo['review']['state'],'private');self.assertFalse(photo['review']['requested'])
        self.assertEqual(self.api.call('/v1/moderation/content',session=a)[2]['items'],[])
        self.assertEqual(self.api.call('/v1/moderation/content/photo/'+item+':'+visit+':'+photo['id'],session=a)[0],404)
    def test_04_legacy_visit_grant_never_opens_photos_and_explicit_revoke(self):
        a,b,e,item,visit=self.setup_visit();self.h.make_friend(a,b);self.h.share(item,a,b);self.review(item,a)
        # Exact prior two-purpose encrypted record, not a new expanded consent.
        with psycopg.connect(self.api.dsn)as conn:conn.execute('UPDATE team_history_shares SET protected=%s WHERE history_id=%s',(self.api.module.TEAM_HISTORY.protect('share',a['user']['id'],item+':'+b['user']['id'],dict(visits=True,trace=False)),item))
        status,_,upload=self.upload(item,visit,a);self.assertEqual(status,201);url=upload['photo']['url'];self.assertEqual(self.h.detail(item,b,'bob')['visits'][0]['photos'],[]);self.assertEqual(self.api.call(url,who='bob',session=b)[0],404)
        self.assertEqual(self.grant(item,a,b,True,False)[0],400);self.assertEqual(self.grant(item,a,b,True)[0],200)
        # Legacy visit permission and even the new purpose do not bypass UGC review.
        self.assertEqual(self.api.call(url,who='bob',session=b)[0],404)
        endpoint=self.review(item,a,upload['photo'])
        self.assertEqual(self.api.call(url,who='bob',session=b)[0],200);self.assertEqual(len(self.h.detail(item,b,'bob')['visits'][0]['photos']),1)
        self.assertEqual(self.api.call(url+'/reports',dict(reason='privacy'),'POST',who='bob',session=b)[0],202)
        self.assertEqual(self.api.call(url,who='bob',session=b)[0],404)
        self.assertEqual(self.api.call(url,session=a)[0],200)
        self.review(item,a,upload['photo'])
        self.assertEqual(self.api.call(url+'/review-request',dict(revision=1,consent=False),'PATCH',session=a)[0],200)
        self.assertEqual(self.api.call(endpoint,session=a)[0],404)
        self.assertEqual(self.api.call(url,who='bob',session=b)[0],404)
        self.review(item,a,upload['photo'])
        self.assertEqual(self.grant(item,a,b,False)[0],200);self.assertEqual(self.api.call(url,who='bob',session=b)[0],404);self.assertEqual(self.h.detail(item,b,'bob')['visits'][0]['photos'],[]);self.assertEqual(self.api.call(url,session=a)[0],200)
    def test_05_same_actual_store_transaction_serializes_independent_connections(self):
        a,b,e,item,visit=self.setup_visit();service=self.api.module.TEAM_PHOTOS;meta,image=bounded_worker(self.image(),'image/png')
        def save():
            try:return service.store(a['user']['id'],item,visit,2,meta,image)
            except HTTPException as error:return error.status_code
        with ThreadPoolExecutor(max_workers=2)as pool:values=list(pool.map(lambda _:save(),range(2)))
        self.assertEqual(sum(isinstance(x,dict)for x in values),1);self.assertIn(409,values)
        with psycopg.connect(self.api.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*)FROM team_history_photos WHERE history_id=%s',(item,)).fetchone()[0],1)
    def test_06_six_photo_limit_revision_delete_and_visit_cascade(self):
        a,b,e,item,visit=self.setup_visit();photos=[]
        for _ in range(6):
            code,_,photo=self.upload(item,visit,a);self.assertEqual(code,201);photos.append(photo)
        code,headers,_=self.upload(item,visit,a);self.assertEqual(code,409);self.assertEqual({k.lower():v for k,v in headers.items()}['x-wegoh-error-code'],'PHOTO_VISIT_LIMIT')
        url=photos[0]['photo']['url'];self.assertEqual(self.api.call(url,dict(revision=2),'DELETE',session=a)[0],409)
        current=self.h.detail(item,a)['revision'];self.assertEqual(self.api.call(url,dict(revision=current),'DELETE',session=a)[0],200);self.assertEqual(self.api.call(url,session=a)[0],404)
        current=self.h.detail(item,a)['revision'];self.assertEqual(self.h.call('/history/'+item+'/visits/'+visit,dict(revision=current),'DELETE',session=a)[0],200)
        for photo in photos:self.assertEqual(self.api.call(photo['photo']['url'],session=a)[0],404)
        with psycopg.connect(self.api.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*)FROM team_history_photos').fetchone()[0],0)
    def test_07_mime_bytes_pixels_and_ciphertext_integrity_fail_closed(self):
        a,b,e,item,visit=self.setup_visit()
        self.assertEqual(self.upload(item,visit,a,raw=b'%!PS untrusted',ctype='image/png')[0],400)
        self.assertEqual(self.upload(item,visit,a,raw=self.image(),ctype='image/jpeg')[0],400)
        self.assertEqual(self.upload(item,visit,a,raw=self.image(size=(4001,4001)))[0],400)
        self.assertEqual(self.upload(item,visit,a,raw=b'x'*(3*1024*1024+1))[0],413)
        code,_,photo=self.upload(item,visit,a);self.assertEqual(code,201)
        with psycopg.connect(self.api.dsn)as conn:
            row=conn.execute('SELECT image_protected FROM team_history_photos').fetchone();bad=bytearray(row[0]);bad[-1]^=1;conn.execute('UPDATE team_history_photos SET image_protected=%s',(bytes(bad),))
        self.assertEqual(self.api.call(photo['photo']['url'],session=a)[0],503)
        self.assertEqual(len(self.h.detail(item,a)['visits'][0]['photos']),1) # Metadata does not decrypt image bodies.
    def test_08_real_websocket_block_revokes_photo_grant_without_deleting(self):
        a,b,e,item,visit=self.setup_visit();self.h.make_friend(a,b);code,_,photo=self.upload(item,visit,a);self.assertEqual(code,201);self.review(item,a);self.review(item,a,photo['photo']);self.grant(item,a,b,True)
        with self.api.websocket(b,who='bob')as socket:
            self.assertEqual(json.loads(socket.recv(timeout=2))['type'],'snapshot');self.assertEqual(self.grant(item,a,b,False)[0],200);event=json.loads(socket.recv(timeout=3));self.assertIn('history',event['resources']);self.assertNotIn('image',json.dumps(event))
        self.grant(item,a,b,True);self.assertEqual(self.h.call('/blocks',dict(targetId=b['user']['id']),'POST',session=a)[0],201);self.assertEqual(self.api.call(photo['photo']['url'],who='bob',session=b)[0],404);self.assertEqual(self.api.call(photo['photo']['url'],session=a)[0],200)

def serve_fixture(path):
    class PhotoBrowserFixture(friends.FriendTests):
        @classmethod
        def write_members(cls,rows):
            names={'alice':'가'*64,'bob':'나'*64}
            super().write_members([dict(row,name=names.get(row['email'].split('@')[0],row['name']))for row in rows])
    friends.serve_fixture(path,fixture_class=PhotoBrowserFixture)
if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--serve-fixture':serve_fixture(sys.argv[2])
    else:unittest.main(verbosity=2)
