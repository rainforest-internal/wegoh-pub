"""Owner-uploaded visit photographs with a separate, default-off sharing purpose."""
import asyncio,base64,hashlib,json,os,selectors,subprocess,sys,threading,time
from datetime import datetime,timezone
from pathlib import Path
import psycopg
from fastapi import APIRouter,HTTPException,Request,Response
from starlette.concurrency import run_in_threadpool
from photo_codec import MAX_INPUT,MAX_OUTPUT
from team_history import identifier,revision,unavailable

WORKER=Path(__file__).with_name('photo_codec.py')
ENV={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'}

def bounded_worker(data,content_type):
    """No shell/env credentials; bounded stdin/stdout/CPU/memory and wall time."""
    try:process=subprocess.Popen([sys.executable,'-I',str(WORKER),content_type],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=ENV,close_fds=True)
    except OSError:unavailable(503,'Photo processing unavailable')
    output=bytearray();offset=0;deadline=time.monotonic()+8
    try:
        with selectors.DefaultSelector()as selector:
            os.set_blocking(process.stdin.fileno(),False);os.set_blocking(process.stdout.fileno(),False)
            selector.register(process.stdin,selectors.EVENT_WRITE);selector.register(process.stdout,selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic()>deadline:raise TimeoutError()
                for key,event in selector.select(.05):
                    if key.fileobj is process.stdin:
                        try:written=os.write(process.stdin.fileno(),data[offset:offset+65536])
                        except BrokenPipeError:written=0;offset=len(data)
                        offset+=written
                        if offset>=len(data):selector.unregister(process.stdin);process.stdin.close()
                    else:
                        chunk=os.read(process.stdout.fileno(),65536)
                        if not chunk:selector.unregister(process.stdout);process.stdout.close()
                        else:
                            output.extend(chunk)
                            if len(output)>MAX_OUTPUT+512:raise ValueError('Output bound')
            code=process.wait(timeout=max(.01,deadline-time.monotonic()))
        if code==69:unavailable(503,'Photo processing unavailable')
        if code!=0:unavailable(400,'Invalid image')
        header,image=bytes(output).split(b'\n',1)
        if len(header)>256:raise ValueError('Invalid worker header')
        meta=json.loads(header)
        if len(header)>256 or set(meta)!={'width','height','sandbox'}or any(type(meta[k])is not int or not 1<=meta[k]<=2048 for k in ('width','height'))or meta['sandbox']not in('linux-seccomp-memory-only','macos-seatbelt')or len(image)>MAX_OUTPUT or not image.startswith(b'\xff\xd8\xff')or not image.endswith(b'\xff\xd9'):raise ValueError('Invalid worker response')
        return meta,image
    except HTTPException:raise
    except (OSError,ValueError,TimeoutError,subprocess.TimeoutExpired):unavailable(503,'Photo processing unavailable')
    finally:
        if process.poll()is None:process.kill()
        process.wait()
        for stream in(process.stdin,process.stdout):
            if not stream.closed:stream.close()

class TeamPhotos:
    def __init__(self,auth,history):
        self.auth,self.history,self.dsn=auth,history,auth.dsn;self.gate=threading.BoundedSemaphore(1);self.enabled=auth.enabled;self.can_upload=False;self.sandbox=None
        if auth.enabled:
            try:
                result=subprocess.run([sys.executable,'-I',str(WORKER),'--probe'],capture_output=True,timeout=3,env=ENV,close_fds=True)
                probe=json.loads(result.stdout)
                self.can_upload=result.returncode==0 and set(probe.get('blocked',()))=={'file','network'}
                if self.can_upload:self.sandbox=probe['sandbox']
            except(OSError,ValueError,subprocess.TimeoutExpired):pass # Capabilities stay false, never unsafe fallback.
    @property
    def content(self):return getattr(self.auth,'content_service',None)
    @staticmethod
    def key(item,visit,photo):return item+':'+visit+':'+photo
    def projection(self,conn,key,owner):
        parts=key.split(':')
        if len(parts)!=3:unavailable()
        item,visit,photo=map(identifier,parts)
        row=conn.execute('SELECT protected FROM team_history_photos WHERE history_id=%s AND visit_id=%s AND photo_id=%s AND owner_id=%s',(item,visit,photo,owner)).fetchone()
        if not row:unavailable()
        value=self.history.restore('photo',owner,key,row[0])
        return dict(checksum=value['checksum'],width=value['width'],height=value['height'],contentType='image/jpeg')
    def notify_content(self,conn,key,owner):self.history.notify(conn,key.split(':')[0],owner)
    def media(self,conn,key,owner):
        parts=key.split(':')
        if len(parts)!=3:unavailable()
        return self.read_image(conn,*parts,owner)
    def read_image(self,conn,item,visit,photo,owner):
        record=conn.execute('SELECT protected,image_protected FROM team_history_photos WHERE history_id=%s AND visit_id=%s AND photo_id=%s AND owner_id=%s',(item,visit,photo,owner)).fetchone()
        if not record:unavailable()
        value=self.history.restore('photo',owner,self.key(item,visit,photo),record[0]);blob=self.history.restore('photo-image',owner,self.key(item,visit,photo),record[1]);image=base64.b64decode(blob['image'],validate=True)
        if len(image)>MAX_OUTPUT or hashlib.sha256(image).hexdigest()!=value['checksum']:unavailable(503,'Photo integrity check failed')
        return image
    def store(self,owner,item,visit,expected,meta,image,review_requested=False):
        import secrets
        photo=secrets.token_hex(16);now=datetime.now(timezone.utc).isoformat()
        payload=dict(width=meta['width'],height=meta['height'],contentType='image/jpeg',checksum=hashlib.sha256(image).hexdigest(),source=dict(kind='user-upload',actorId=owner,receivedAt=now),rights=dict(confirmed=True,confirmedAt=now,purpose='private-record-and-separate-photo-grants'))
        with psycopg.connect(self.dsn)as conn:
            self.history.rooms.graph_lock(conn);row,value=self.owned(conn,item,visit,owner,expected)
            if conn.execute('SELECT count(*)FROM team_history_photos WHERE history_id=%s AND visit_id=%s',(item,visit)).fetchone()[0]>=6:raise HTTPException(409,'Visit photo limit reached',headers={'X-WegoH-Error-Code':'PHOTO_VISIT_LIMIT'})
            if conn.execute('SELECT coalesce(sum(byte_size),0)FROM team_history_photos WHERE owner_id=%s',(owner,)).fetchone()[0]+len(image)>100*1024*1024:raise HTTPException(409,'Photo storage limit reached',headers={'X-WegoH-Error-Code':'PHOTO_STORAGE_LIMIT'})
            conn.execute('INSERT INTO team_history_photos(history_id,visit_id,photo_id,owner_id,protected,image_protected,byte_size)VALUES(%s,%s,%s,%s,%s,%s,%s)',(item,visit,photo,owner,self.history.protect('photo',owner,item+':'+visit+':'+photo,payload),self.history.protect('photo-image',owner,item+':'+visit+':'+photo,dict(image=base64.b64encode(image).decode())),len(image)))
            self.history.save(conn,row,value,data=True)
            if review_requested:
                if not self.content:unavailable(503,'Content review unavailable')
                key=self.key(item,visit,photo);self.content.request(conn,'photo',key,owner,self.projection(conn,key,owner),True)
            self.history.notify(conn,item,owner);entry=next(x for x in self.meta(conn,item,visit,owner)if x['id']==photo)
        return dict(id=photo,revision=row[3]+1,photo=entry)
    def meta(self,conn,item,visit,owner,include_private=True):
        result=[]
        for photo,raw,created in conn.execute('SELECT photo_id,protected,created_at FROM team_history_photos WHERE history_id=%s AND visit_id=%s ORDER BY created_at,photo_id',(item,visit)):
            key=self.key(item,visit,photo);value=self.history.restore('photo',owner,key,raw);projection=dict(checksum=value['checksum'],width=value['width'],height=value['height'],contentType='image/jpeg')
            review=self.content.review(conn,'photo',key,owner,projection)if self.content else dict(kind='photo',key=key,state='private',checksum=None,requested=False)
            if not include_private and(not self.content or not self.content.allowed(conn,'photo',key,owner,projection)):continue
            result.append(dict(id=photo,width=value['width'],height=value['height'],contentType='image/jpeg',createdAt=created,source={k:value['source'][k]for k in('kind','actorId','receivedAt')},checksum=value['checksum'],review=review,url='/v1/social/history/'+item+'/visits/'+visit+'/photos/'+photo))
        return result
    def owned(self,conn,item,visit,owner,expected):
        identifier(visit);row,value,_,_=self.history.row(conn,item,owner,True)
        if revision(expected)!=row[3]:unavailable(409,'Refresh the record')
        if not conn.execute('SELECT 1 FROM team_history_visits WHERE history_id=%s AND visit_id=%s',(item,visit)).fetchone():unavailable()
        return row,value
    def router(self):
        router=APIRouter()
        if not self.auth.enabled:return router
        def ready():
            if not self.can_upload:unavailable(503,'Photo processing unavailable')
        @router.post('/v1/social/history/{item}/visits/{visit}/photos',status_code=201)
        async def upload(item:str,visit:str,request:Request):
            owner=self.auth.browser(request,mutate=True)['id'];ready()
            if request.headers.get('x-wegoh-rights-confirmed')!='true':unavailable(400,'Confirm photograph rights')
            raw_revision=request.headers.get('x-wegoh-history-revision','')
            if not 1<=len(raw_revision)<=10 or not raw_revision.isascii()or not raw_revision.isdecimal():unavailable(400,'Invalid revision')
            expected=revision(int(raw_revision));content_type=request.headers.get('content-type');review_requested=request.headers.get('x-wegoh-review-requested','false')
            if review_requested not in('true','false'):unavailable(400,'Choose the review purpose')
            if content_type not in('image/jpeg','image/png'):unavailable(400,'Use JPEG or PNG')
            with psycopg.connect(self.dsn)as conn:self.owned(conn,item,visit,owner,expected)
            self.auth.rate('photo-upload:'+owner,limit=10)
            if not self.gate.acquire(blocking=False):unavailable(429,'Photo processing busy')
            try:
                data=bytearray()
                try:
                    async with asyncio.timeout(12):
                        async for chunk in request.stream():
                            data.extend(chunk)
                            if len(data)>MAX_INPUT:unavailable(413,'Image byte limit exceeded')
                except TimeoutError:unavailable(408,'Image upload timed out')
                if not data:unavailable(400,'Choose an image')
                meta,image=await run_in_threadpool(bounded_worker,bytes(data),content_type)
                self.auth.current_account(owner) # Confirm current membership again after untrusted decode.
                return await run_in_threadpool(self.store,owner,item,visit,expected,meta,image,review_requested=='true')
            finally:self.gate.release()
        @router.get('/v1/social/history/{item}/visits/{visit}/photos/{photo}')
        def content(item:str,visit:str,photo:str,request:Request):
            owner=self.auth.browser(request)['id'];identifier(visit);identifier(photo)
            with psycopg.connect(self.dsn)as conn:
                row,_,own,grant=self.history.row(conn,item,owner)
                if not(grant['visits']and grant.get('photos',False)):unavailable()
                key=self.key(item,visit,photo)
                if not own and(not self.content or not self.content.allowed(conn,'photo',key,row[1],self.projection(conn,key,row[1]))):unavailable()
                image=self.read_image(conn,item,visit,photo,row[1])
            return Response(image,media_type='image/jpeg',headers={'Cache-Control':'private, no-store','Content-Disposition':'inline; filename="'+photo+'.jpg"','X-Content-Type-Options':'nosniff'})
        async def json_body(request,fields):
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>4096:unavailable(413,'Request too large')
            try:data=json.loads(raw)
            except(ValueError,UnicodeError):unavailable(400,'Invalid JSON')
            if not isinstance(data,dict)or set(data)!=set(fields):unavailable(400,'Invalid photo fields')
            return data
        @router.patch('/v1/social/history/{item}/visits/{visit}/photos/{photo}/review-request')
        async def request_review(item:str,visit:str,photo:str,request:Request):
            owner=self.auth.browser(request,mutate=True)['id'];data=await json_body(request,('revision','consent'));identifier(photo)
            if type(data['consent'])is not bool:unavailable(400,'Choose the review purpose')
            revision(data['revision'])
            if not self.content:unavailable(503,'Content review unavailable')
            with psycopg.connect(self.dsn)as conn:
                row,value,_,_=self.history.row(conn,item,owner,True)
                if data['consent']and row[3]!=data['revision']:unavailable(409,'Refresh the record')
                key=self.key(item,visit,photo);projection=self.projection(conn,key,owner)
                result=self.content.request(conn,'photo',key,owner,projection,data['consent']);self.history.save(conn,row,value,data=True);self.history.notify(conn,item,owner)
            return dict(review=result,revision=row[3]+1)
        @router.post('/v1/social/history/{item}/visits/{visit}/photos/{photo}/reports',status_code=202)
        async def report_photo(item:str,visit:str,photo:str,request:Request):
            reporter=self.auth.browser(request,mutate=True)['id'];data=await json_body(request,('reason',));identifier(visit);identifier(photo);self.auth.rate('content-report:'+reporter,limit=30)
            if data['reason']not in('harmful','privacy','rights','other'):unavailable(400,'Choose a report reason')
            if not self.content:unavailable(503,'Content review unavailable')
            with psycopg.connect(self.dsn)as conn:
                row,_,own,grant=self.history.row(conn,item,reporter);key=self.key(item,visit,photo);projection=self.projection(conn,key,row[1])
                if not(grant['visits']and grant.get('photos',False))or not self.content.allowed(conn,'photo',key,row[1],projection):unavailable()
                result=self.content.report(conn,'photo',key,row[1],projection,reporter,data['reason']);self.history.notify(conn,item,row[1])
            return result
        @router.delete('/v1/social/history/{item}/visits/{visit}/photos/{photo}')
        async def delete(item:str,visit:str,photo:str,request:Request):
            owner=self.auth.browser(request,mutate=True)['id'];identifier(photo);raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>4096:unavailable(413,'Request too large')
            try:data=json.loads(raw)
            except(ValueError,UnicodeError):unavailable(400,'Invalid JSON')
            if not isinstance(data,dict)or set(data)!={'revision'}:unavailable(400,'Invalid deletion fields')
            with psycopg.connect(self.dsn)as conn:
                row,value=self.owned(conn,item,visit,owner,data['revision'])
                if not conn.execute('DELETE FROM team_history_photos WHERE history_id=%s AND visit_id=%s AND photo_id=%s RETURNING photo_id',(item,visit,photo)).fetchone():unavailable()
                if self.content:self.content.erase(conn,'photo',self.key(item,visit,photo),owner)
                self.history.save(conn,row,value,data=True);self.history.notify(conn,item,owner)
            return dict(status='deleted',revision=row[3]+1)
        return router
