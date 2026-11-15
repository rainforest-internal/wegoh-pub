"""Personal trip records and purpose-limited sharing; REST is authoritative.

Browser reports/confirmed places are not vehicle/GPS attestations. No photo,
audio, external story publication or rendering is implemented by this module.
"""
from course_publication import COURSE_AVAILABLE
from datetime import datetime, timezone, timedelta
import base64, binascii, json, math, re, secrets
import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import VisitCipher, PrivateRecordError
from team_data import changed
from team_friends import ACCOUNT, linked

IDENTIFIER=re.compile(r'[a-f0-9]{32}')
CAPABILITIES=dict(history=True,historyVisits=True,historyTraceIngest=True,historyTraceCapture=False,
                  historyPhotos=False,historyReplay=True,historyExport=False)

def unavailable(status=404,detail='History unavailable'):raise HTTPException(status,detail)
def identifier(value):
    if not isinstance(value,str) or not IDENTIFIER.fullmatch(value):unavailable()
    return value
def text(value,limit,empty=False,multiline=False):
    if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()) or any(ord(c)<32 and not(multiline and c in '\n\r\t') for c in value):unavailable(400,'Invalid record text')
    return value.strip()
def timestamp(value,future=False):
    if not isinstance(value,str) or len(value)>40:unavailable(400,'Invalid record time')
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None:raise ValueError()
        result=result.astimezone(timezone.utc)
        if not future and result>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError()
    except (ValueError,OverflowError):unavailable(400,'Invalid record time')
    return result.isoformat()
def revision(value):
    if type(value)is not int or not 1<=value<=2147483647:unavailable(400,'Invalid revision')
    return value

def place(value):
    if not isinstance(value,dict) or set(value)!={'name','latitude','longitude'}:unavailable(400,'Choose a place')
    result=dict(value,name=text(value['name'],80))
    for key,low,high in [('latitude',-90,90),('longitude',-180,180)]:
        if type(value[key])not in(int,float) or not math.isfinite(value[key]) or not low<=value[key]<=high:unavailable(400,'Invalid place')
    return result

from native_access import native_resource
from native_functional_identity import request_actor,transaction_actor,business_json
from native_functional_query import history_cursor

class TeamHistory:
    def __init__(self,auth,rooms):self.auth,self.rooms,self.dsn,self.enabled=auth,rooms,auth.dsn,auth.enabled
    def capabilities(self):
        photos=getattr(self,'photos_service',None)
        return dict(CAPABILITIES,cautions=bool(getattr(self.auth,'cautions_service',None)and self.auth.cautions_service.enabled),historyPhotos=bool(photos and photos.enabled),historyPhotoUpload=bool(photos and photos.can_upload),historyRemix=bool(getattr(self.auth,'history_remix_service',None)and self.auth.history_remix_service.enabled),historyExportManifest=bool(getattr(self.auth,'story_service',None)))
    @property
    def content(self):return getattr(self.auth,'content_service',None)
    def projection(self,conn,item,owner):
        identifier(item)
        row=conn.execute('SELECT protected FROM team_histories WHERE history_id=%s AND owner_id=%s',(item,owner)).fetchone()
        if not row:unavailable()
        value=self.restore('record',owner,item,row[0]);places=[];reviews=[];labels=[]
        for visit,raw in conn.execute('SELECT visit_id,protected FROM team_history_visits WHERE history_id=%s ORDER BY visit_id',(item,)):
            data=self.restore('visit',owner,item+':'+visit,raw);places.append(data['place']['name']);reviews.append(data['review'])
        for batch,raw in conn.execute('SELECT batch_id,protected FROM team_history_trace_batches WHERE history_id=%s ORDER BY batch_id',(item,)):
            labels.append(self.restore('trace',owner,item+':'+batch,raw)['label'])
        return dict(title=value['title'],places=places,reviews=reviews,traceLabels=sorted(set(labels)))
    def review(self,conn,item,owner):
        if not self.content:return dict(kind='history',key=item,state='private',checksum=None,requested=False)
        return self.content.review(conn,'history',item,owner,self.projection(conn,item,owner))
    @staticmethod
    def protect(kind,owner,item,payload):return VisitCipher().protect('team-history-'+kind+':'+owner,item,payload)
    @staticmethod
    def restore(kind,owner,item,raw):return VisitCipher().restore('team-history-'+kind+':'+owner,item,raw)
    def person(self,account):
        try:
            p=self.auth.current_account(account);return dict(id=p['id'],name=p['displayName'])
        except HTTPException:return None
    def row(self,conn,item,actor,write=False,stable=False):
        identifier(item)
        row=conn.execute('SELECT history_id,owner_id,protected,revision,permission_revision,created_at,updated_at FROM team_histories WHERE history_id=%s'+(' FOR UPDATE'if write else ' FOR SHARE'if stable else ''),(item,)).fetchone()
        if not row or(write and row[1]!=actor):unavailable()
        value=self.restore('record',row[1],item,row[2])
        own=actor==row[1];grant=dict(visits=True,trace=True,photos=True)
        if not own:
            if not self.person(row[1]) or not linked(conn,row[1],actor):unavailable()
            shared=conn.execute('SELECT protected FROM team_history_shares WHERE history_id=%s AND account_id=%s',(item,actor)).fetchone()
            if not shared:unavailable()
            grant=self.restore('share',row[1],item+':'+actor,shared[0]);grant=dict(grant,photos=bool(grant.get('photos',False)))
            if not self.content or not self.content.allowed(conn,'history',item,row[1],self.projection(conn,item,row[1])):unavailable()
        return row,value,own,grant
    def save(self,conn,row,value,data=False,permission=False):
        conn.execute('UPDATE team_histories SET protected=%s,revision=revision+%s,permission_revision=permission_revision+%s,updated_at=now() WHERE history_id=%s',
          (self.protect('record',row[1],row[0],value),int(data),int(permission),row[0]))
        if self.content:self.content.sync(conn,'history',row[0],row[1],self.projection(conn,row[0],row[1]))
    def erase_photo_reviews(self,conn,item,owner,visit=None):
        if not self.content:return
        query='SELECT visit_id,photo_id FROM team_history_photos WHERE history_id=%s';args=[item]
        if visit is not None:query+=' AND visit_id=%s';args.append(visit)
        for vid,photo in conn.execute(query+' ORDER BY visit_id,photo_id',args):self.content.erase(conn,'photo',item+':'+vid+':'+photo,owner)
    def recipients(self,conn,item):return {x[0]for x in conn.execute('SELECT account_id FROM team_history_shares WHERE history_id=%s',(item,))}
    def notify(self,conn,item,owner,extra=()):
        for account in sorted(self.recipients(conn,item)|set(extra)|{owner}):changed(conn,account,'history')
    def revoke_pair(self,conn,a,b):
        # Ended/blocked friendships never revive old purpose grants on re-friending.
        rows=conn.execute('SELECT h.history_id,h.owner_id FROM team_histories h JOIN team_history_shares s USING(history_id) WHERE(h.owner_id=%s AND s.account_id=%s)OR(h.owner_id=%s AND s.account_id=%s)ORDER BY h.history_id FOR UPDATE OF h',(a,b,b,a)).fetchall()
        for item,owner in rows:
            target=b if owner==a else a;row,value,_,_=self.row(conn,item,owner,True)
            conn.execute('DELETE FROM team_history_shares WHERE history_id=%s AND account_id=%s',(item,target))
            remix=getattr(self.auth,'history_remix_service',None)
            if remix:remix.revoke_context(conn,item,target)
            self.save(conn,row,value,permission=True);self.notify(conn,item,owner,(target,))
    def course(self,conn,value):
        if value['courseId']is None:return None
        r=conn.execute(f"SELECT p.pack_id,p.version,p.title FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}",(value['courseId'],value['courseVersion'])).fetchone()
        return dict(id=r[0],version=r[1],title=r[2])if r else None
    def validate_record(self,data):
        value={k:data[k]for k in ('title','startedAt','endedAt','courseId','courseVersion')};value['title']=text(value['title'],100);value['startedAt']=timestamp(value['startedAt'])
        value['endedAt']=timestamp(value['endedAt'])if value['endedAt']is not None else None
        if value['endedAt']is not None and value['endedAt']<value['startedAt']:unavailable(400,'Record time order is invalid')
        if value['courseId']is not None:
            if not isinstance(value['courseId'],str)or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}',value['courseId'])or type(value['courseVersion'])is not int or not 1<=value['courseVersion']<=2147483647:unavailable(400,'Choose an available course')
        elif value['courseVersion']is not None:unavailable(400,'Course version requires a course')
        return value
    def add(self,conn,owner,value,source):
        if value['courseId']is not None and self.course(conn,value)is None:unavailable(409,'Course unavailable')
        if conn.execute('SELECT count(*) FROM team_histories WHERE owner_id=%s',(owner,)).fetchone()[0]>=500:unavailable(409,'Record limit reached')
        item=secrets.token_hex(16);value=dict(value,permissions=dict(collectTrace=False),source=source)
        conn.execute('INSERT INTO team_histories(history_id,owner_id,protected)VALUES(%s,%s,%s)',(item,owner,self.protect('record',owner,item,value)))
        self.notify(conn,item,owner);return item
    def saved_room_history(self,conn,room,owner):
        row=conn.execute('SELECT h.history_id,h.revision,h.permission_revision '
            'FROM team_room_history_saves s JOIN team_histories h USING(history_id) '
            'WHERE s.room_id=%s AND s.account_id=%s AND h.owner_id=%s FOR SHARE OF h',
            (room,owner,owner)).fetchone()
        return dict(id=row[0],revision=row[1],permissionRevision=row[2])if row else None
    @staticmethod
    def trip_period(context,joined,left):
        ended=min(left,context['endedAt'])if left and context['endedAt'] else left or context['endedAt']
        started=context['startedAt']
        start=max(joined,started)if started and(left is None or started<=left)else joined
        return start,max(start,ended)if ended else None
    def save_trip_history(self,conn,context,owner,title,joined,left):
        self.rooms.graph_lock(conn)
        saved=self.saved_room_history(conn,context['roomId'],owner)
        if saved:return saved,False
        started,ended=self.trip_period(context,joined,left)
        if ended is None:unavailable(409,'Trip has not ended')
        value=dict(title=text(title,100),startedAt=started.isoformat(),
            endedAt=ended.isoformat(),courseId=None,courseVersion=None)
        if left is None:
            raw=conn.execute('SELECT protected FROM team_rooms WHERE room_id=%s',
                (context['roomId'],)).fetchone()[0]
            room=self.rooms.restore('owner:'+context['ownerId'],context['roomId'],raw)
            course=dict(courseId=room['courseId'],courseVersion=room['courseVersion'])
            if course['courseId']is not None and self.course(conn,course):value.update(course)
        source=dict(kind='room-confirmed',actorId=owner,receivedAt=datetime.now(timezone.utc).isoformat(),tripId=context['tripId'])
        item=self.add(conn,owner,value,source)
        conn.execute('INSERT INTO team_room_history_saves(room_id,account_id,history_id) VALUES(%s,%s,%s)',
            (context['roomId'],owner,item))
        return dict(id=item,revision=1,permissionRevision=1),True
    def summary(self,conn,row,value,own,grant):
        shared=self.content.shared(conn,'history',row[0],row[1],self.projection(conn,row[0],row[1]))if not own else None
        if not own and shared is None:unavailable()
        sender=self.person(row[1]);visits=conn.execute('SELECT count(*)FROM team_history_visits WHERE history_id=%s',(row[0],)).fetchone()[0]if grant['visits']else 0
        count=conn.execute('SELECT coalesce(sum(point_count),0)FROM team_history_trace_batches WHERE history_id=%s',(row[0],)).fetchone()[0]if grant['trace']else 0
        return dict(id=row[0],title=value['title']if own else shared['title'],ownerId=row[1],ownerName=sender['name']if sender else None,own=own,createdAt=row[5],updatedAt=row[6],startedAt=value['startedAt'],endedAt=value['endedAt'],courseId=value['courseId'],courseVersion=value['courseVersion'],revision=row[3],permissionRevision=row[4]if own else None,review=self.review(conn,row[0],row[1]),visitCount=visits,tracePointCount=count,sharedWith=sorted(self.recipients(conn,row[0]))if own else [])
    def detail(self,conn,item,actor):
        row,value,own,grant=self.row(conn,item,actor,stable=True);result=self.summary(conn,row,value,own,grant)
        visits=[];batches=[];grants=[];reviewed_visits={};shared=None
        if not own:
            shared=self.content.shared(conn,'history',item,row[1],self.projection(conn,item,row[1]))
            if shared is None:unavailable()
            reviewed_visits={vid:(shared['places'][i],shared['reviews'][i])for i,(vid,)in enumerate(conn.execute('SELECT visit_id FROM team_history_visits WHERE history_id=%s ORDER BY visit_id',(item,)))}
        if grant['visits']:
            for vid,raw in conn.execute('SELECT visit_id,protected FROM team_history_visits WHERE history_id=%s ORDER BY created_at,visit_id',(item,)):
                photos=getattr(self,'photos_service',None)
                metadata=photos.meta(conn,item,vid,row[1],include_private=own)if photos and photos.enabled and grant.get('photos',False)else[]
                v=self.restore('visit',row[1],item+':'+vid,raw)
                location={k:v['place'][k]for k in('name','latitude','longitude')};review_text=v['review']
                if not own:location['name'],review_text=reviewed_visits[vid]
                visits.append(dict(id=vid,place=location,visitedAt=v['visitedAt'],review=review_text,rating=v['rating'],source={k:v['source'][k]for k in('kind','actorId','receivedAt')},photos=metadata))
            visits.sort(key=lambda x:(x['visitedAt'],x['id']))
        if grant['trace']:
            for bid,raw in conn.execute('SELECT batch_id,protected FROM team_history_trace_batches WHERE history_id=%s ORDER BY created_at,batch_id',(item,)):
                v=self.restore('trace',row[1],item+':'+bid,raw)
                batches.append(dict(id=bid,streamId=v['streamId'],label=v['label']if own else next(label for label in shared['traceLabels']if label==v['label']),points=[{k:p[k]for k in('latitude','longitude','capturedAt','accuracyMeters')}for p in v['points']],source={k:v['source'][k]for k in('kind','actorId','receivedAt')}))
        if own:
            for target,raw in conn.execute('SELECT account_id,protected FROM team_history_shares WHERE history_id=%s ORDER BY account_id',(item,)):
                who=self.person(target);g=self.restore('share',row[1],item+':'+target,raw);g=dict(g,photos=bool(g.get('photos',False)));grants.append(dict(accountId=target,name=who['name']if who else None,available=bool(who and linked(conn,row[1],target)),**g))
        source={k:value['source'][k]for k in('kind','actorId','receivedAt')}
        if own and 'roomId'in value['source']:source['roomId']=value['source']['roomId']
        if own and 'tripId'in value['source']:source['tripId']=value['source']['tripId']
        return dict(result,permissions=value['permissions']if own else None,access=grant,visits=visits,traceBatches=batches,grants=grants,source=source,course=self.course(conn,value),capabilities=self.capabilities())
    def router(self):
        router=APIRouter()
        if not self.enabled:return router
        def actor(request,write=False):return request_actor(self.auth,request,mutate=write)['id']
        async def body(request,required,optional=()):
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>262144:unavailable(413,'Record request too large')
            value=business_json(request,raw,maximum=262144)
            if not isinstance(value,dict)or not set(required)<=set(value)or set(value)-set(required)-set(optional):unavailable(400,'Invalid record fields')
            return value
        def native_capabilities(request):
            purposes=request.state.functional_snapshot['approvedPurposes']
            return dict(history=True,historyRemix=False,historyTraceIngest='history:write' in purposes,historyPhotos=False,historyPhotoUpload=False,historyReplay=True,historyExport=False,cautions=False)
        def expected(row,data):
            if revision(data['revision'])!=row[3]:unavailable(409,'Refresh the record')
        def origin(owner,kind='web-confirmed',request=None,**extra):return dict(kind='device-reported' if request is not None and native_resource(request) else kind,actorId=owner,receivedAt=datetime.now(timezone.utc).isoformat(),**extra)
        @router.get('/v1/social/history')
        def listing(request:Request):
            owner=actor(request);records=[];friends=[];after=request.query_params.get('cursor');args=[owner,owner];clause=''
            if set(request.query_params)-{'cursor'}or len(request.query_params.getlist('cursor'))>1:unavailable(400,'Invalid pagination fields')
            if after:
                try:moment,cursor_id=history_cursor(after)
                except ValueError:unavailable(400,'Invalid record cursor')
                clause=' AND(updated_at,history_id)<(%s,%s)';args.extend((moment,cursor_id))
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=False)['id']
                rows=conn.execute('SELECT history_id,updated_at FROM team_histories WHERE(owner_id=%s OR history_id IN(SELECT history_id FROM team_history_shares WHERE account_id=%s))'+clause+' ORDER BY updated_at DESC,history_id DESC LIMIT 51',args).fetchall()
                ids=rows[:50];next_cursor=None
                if len(rows)>50:
                    item,updated=ids[-1];next_cursor=base64.urlsafe_b64encode(json.dumps(dict(updatedAt=updated.isoformat(),id=item)).encode()).decode().rstrip('=')
                for(item,_)in ids:
                    try:r,v,own,g=self.row(conn,item,owner)
                    except HTTPException as e:
                        if e.status_code==404:continue
                        raise
                    records.append(self.summary(conn,r,v,own,g))
                for(a,b)in ([] if native_resource(request) else conn.execute('SELECT account_a,account_b FROM team_friend_pairs WHERE account_a=%s OR account_b=%s',(owner,owner))):
                    target=b if a==owner else a;who=self.person(target)
                    if who and linked(conn,owner,target):friends.append(who)
            if native_resource(request):
                for item in records:item.update(sharedWith=[],permissionRevision=None)
                return dict(history=records,friends=[],nextCursor=next_cursor,nativeReadOnly='history:write' not in request.state.functional_snapshot['approvedPurposes'],capabilities=native_capabilities(request))
            return dict(history=records,friends=friends,nextCursor=next_cursor,capabilities=self.capabilities())
        @router.post('/v1/social/history',status_code=201)
        async def create(request:Request):
            owner=actor(request,True);data=await body(request,('title','startedAt','endedAt','courseId','courseVersion'));value=self.validate_record(data);self.auth.rate('history-write:'+owner,limit=30)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                self.rooms.graph_lock(conn);item=self.add(conn,owner,value,origin(owner,request=request))
            return dict(id=item,revision=1,permissionRevision=1)
        @router.post('/v1/social/rooms/{room}/history',status_code=201)
        async def from_room(room:str,request:Request):
            owner=actor(request,True);data=await body(request,('title',));self.auth.rate('history-write:'+owner,limit=30)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                self.rooms.graph_lock(conn);room_value=self.rooms.access(conn,room,owner);now=datetime.now(timezone.utc).isoformat()
                value=dict(title=text(data['title'],100),startedAt=now,endedAt=None,courseId=room_value['courseId'],courseVersion=room_value['courseVersion'])
                item=self.add(conn,owner,value,origin(owner,'room-confirmed',roomId=room))
            return dict(id=item,revision=1,permissionRevision=1)
        @router.post('/v1/social/history/from-archive',status_code=201)
        async def from_archive(request:Request,response:Response):
            # Archive reads and this personal save are browser-only. This does
            # not reopen a room or extend any native history writing purpose.
            if native_resource(request):unavailable()
            owner=actor(request,True);data=await body(request,('roomId','title'))
            room=identifier(data['roomId']);title=text(data['title'],100)
            self.auth.rate('history-write:'+owner,limit=30)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                self.rooms.graph_lock(conn)
                archived=self.rooms.archive_access(conn,room,owner)
                saved=conn.execute('SELECT h.history_id,h.revision,h.permission_revision '
                    'FROM team_room_history_saves s JOIN team_histories h USING(history_id) '
                    'WHERE s.room_id=%s AND s.account_id=%s AND h.owner_id=%s',
                    (room,owner,owner)).fetchone()
                if saved:
                    response.status_code=200
                    result=dict(id=saved[0],revision=saved[1],permissionRevision=saved[2])
                else:
                    joined,left=conn.execute('SELECT joined_at,left_at FROM team_room_members '
                        'WHERE room_id=%s AND account_id=%s',(room,owner)).fetchone()
                    ended=min(left,archived['archivedAt'])if left else archived['archivedAt']
                    value=dict(title=title,startedAt=joined.isoformat(),
                        endedAt=max(joined,ended).isoformat(),courseId=archived['courseId'],
                        courseVersion=archived['courseVersion'])
                    item=self.add(conn,owner,value,origin(owner,'room-confirmed',roomId=room))
                    conn.execute('INSERT INTO team_room_history_saves(room_id,account_id,history_id) '
                        'VALUES(%s,%s,%s)',(room,owner,item))
                    result=dict(id=item,revision=1,permissionRevision=1)
            response.headers['Cache-Control']='private, no-store'
            return result
        @router.get('/v1/social/history/{item}')
        def read(item:str,request:Request):
            owner=actor(request)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn)['id']
                result=self.detail(conn,item,owner)
            if native_resource(request):
                result.update(sharedWith=[],permissionRevision=None,grants=[],permissions=None,nativeReadOnly='history:write' not in request.state.functional_snapshot['approvedPurposes'],capabilities=native_capabilities(request))
                result['source']={k:result['source'][k]for k in('kind','actorId','receivedAt')}
                for visit in result['visits']:visit['photos']=[]
            return result
        @router.put('/v1/social/history/{item}')
        async def update(item:str,request:Request):
            owner=actor(request,True);data=await body(request,('revision','title','startedAt','endedAt','courseId','courseVersion'));value=self.validate_record(data);self.auth.rate('history-write:'+owner,limit=30)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,old,_,_=self.row(conn,item,owner,True);expected(row,data)
                if value['courseId']is not None and self.course(conn,value)is None:unavailable(409,'Course unavailable')
                old.update(value);self.save(conn,row,old,data=True);self.notify(conn,item,owner)
            return dict(id=item,revision=row[3]+1)
        @router.delete('/v1/social/history/{item}')
        async def delete(item:str,request:Request):
            owner=actor(request,True)
            if native_resource(request):await body(request,())
            self.auth.rate('history-write:'+owner,limit=30)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,_,_,_=self.row(conn,item,owner,True);receivers=self.recipients(conn,item)
                self.erase_photo_reviews(conn,item,owner)
                remix=getattr(self.auth,'history_remix_service',None)
                if remix:remix.revoke_context(conn,item)
                if self.content:self.content.erase(conn,'history',item,owner)
                conn.execute('DELETE FROM team_histories WHERE history_id=%s',(item,));self.notify(conn,item,owner,receivers)
            return dict(status='deleted')
        @router.patch('/v1/social/history/{item}/review-request')
        async def request_review(item:str,request:Request):
            owner=actor(request,True);data=await body(request,('revision','consent'))
            if type(data['consent'])is not bool:unavailable(400,'Choose the review purpose')
            revision(data['revision'])
            if not self.content:unavailable(503,'Content review unavailable')
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,value,_,_=self.row(conn,item,owner,True)
                if data['consent']:expected(row,data)
                result=self.content.request(conn,'history',item,owner,self.projection(conn,item,owner),data['consent'])
                remix=getattr(self.auth,'history_remix_service',None)
                if remix and not data['consent']:remix.revoke_context(conn,item)
                self.save(conn,row,value,permission=True);self.notify(conn,item,owner)
            return dict(review=result,permissionRevision=row[4]+1)
        @router.post('/v1/social/history/{item}/reports',status_code=202)
        async def report_history(item:str,request:Request):
            reporter=actor(request,True);data=await body(request,('reason',));self.auth.rate('content-report:'+reporter,limit=30)
            if data['reason']not in('harmful','privacy','rights','other'):unavailable(400,'Choose a report reason')
            if not self.content:unavailable(503,'Content review unavailable')
            with psycopg.connect(self.dsn)as conn:
                reporter=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,_,_,_=self.row(conn,item,reporter)
                result=self.content.report(conn,'history',item,row[1],self.projection(conn,item,row[1]),reporter,data['reason']);self.notify(conn,item,row[1])
            return result
        @router.patch('/v1/social/history/{item}/permissions')
        async def permissions(item:str,request:Request):
            owner=actor(request,True);data=await body(request,('permissionRevision','collectTrace'))
            if type(data['collectTrace'])is not bool:unavailable(400,'Choose a collection permission')
            requested=revision(data['permissionRevision'])
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,value,_,_=self.row(conn,item,owner,True)
                if data['collectTrace']and requested!=row[4]:unavailable(409,'Refresh sharing permissions')
                value['permissions']['collectTrace']=data['collectTrace'];self.save(conn,row,value,permission=True);self.notify(conn,item,owner)
            return dict(permissions=value['permissions'],permissionRevision=row[4]+1)
        @router.put('/v1/social/history/{item}/shares/{target}')
        async def share(item:str,target:str,request:Request):
            owner=actor(request,True);data=await body(request,('permissionRevision','visits','trace'),('photos',));data['photos']=data.get('photos',False)
            if not ACCOUNT.fullmatch(target)or target==owner or type(data['visits'])is not bool or type(data['trace'])is not bool or type(data['photos'])is not bool or(data['photos']and not data['visits'])or not(data['visits']or data['trace']):unavailable(400,'Choose a friend and sharing purpose')
            requested=revision(data['permissionRevision'])
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                self.rooms.graph_lock(conn);row,value,_,_=self.row(conn,item,owner,True)
                if requested!=row[4]:unavailable(409,'Refresh sharing permissions')
                if not self.person(target)or not linked(conn,owner,target):unavailable()
                remix=getattr(self.auth,'history_remix_service',None)
                if remix and not data['visits']:remix.revoke_context(conn,item,target,kind='visits')
                choices=dict(visits=data['visits'],trace=data['trace'],photos=data['photos']);raw=self.protect('share',owner,item+':'+target,choices)
                conn.execute('INSERT INTO team_history_shares(history_id,account_id,protected)VALUES(%s,%s,%s)ON CONFLICT(history_id,account_id)DO UPDATE SET protected=excluded.protected',(item,target,raw));self.save(conn,row,value,permission=True);self.notify(conn,item,owner)
            return dict(status='shared',permissionRevision=row[4]+1)
        @router.delete('/v1/social/history/{item}/shares/{target}')
        def revoke(item:str,target:str,request:Request):
            owner=actor(request,True)
            if not ACCOUNT.fullmatch(target)or target==owner:unavailable(400,'Invalid friend')
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,value,_,_=self.row(conn,item,owner,True);conn.execute('DELETE FROM team_history_shares WHERE history_id=%s AND account_id=%s',(item,target))
                remix=getattr(self.auth,'history_remix_service',None)
                if remix:remix.revoke_context(conn,item,target)
                self.save(conn,row,value,permission=True);self.notify(conn,item,owner,(target,))
            return dict(status='revoked',permissionRevision=row[4]+1)
        @router.delete('/v1/social/history/{item}/share')
        def revoke_all(item:str,request:Request):
            owner=actor(request,True)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,value,_,_=self.row(conn,item,owner,True);receivers=self.recipients(conn,item);conn.execute('DELETE FROM team_history_shares WHERE history_id=%s',(item,))
                remix=getattr(self.auth,'history_remix_service',None)
                if remix:remix.revoke_context(conn,item)
                self.save(conn,row,value,permission=True);self.notify(conn,item,owner,receivers)
            return dict(status='revoked',permissionRevision=row[4]+1)
        def visit_value(data,owner,request):
            rating=data['rating']
            if rating is not None and(type(rating)is not int or not 1<=rating<=5):unavailable(400,'Invalid place rating')
            return dict(place=place(data['place']),visitedAt=timestamp(data['visitedAt']),review=text(data['review'],1000,True,True),rating=rating,source=origin(owner,request=request))
        @router.post('/v1/social/history/{item}/visits',status_code=201)
        async def add_visit(item:str,request:Request):
            owner=actor(request,True);data=await body(request,('revision','place','visitedAt','review','rating'));value=visit_value(data,owner,request);self.auth.rate('history-write:'+owner,limit=30);vid=secrets.token_hex(16)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,record,_,_=self.row(conn,item,owner,True);expected(row,data)
                if conn.execute('SELECT count(*)FROM team_history_visits WHERE history_id=%s',(item,)).fetchone()[0]>=500:unavailable(409,'Visit limit reached')
                conn.execute('INSERT INTO team_history_visits(history_id,visit_id,protected)VALUES(%s,%s,%s)',(item,vid,self.protect('visit',owner,item+':'+vid,value)));self.save(conn,row,record,data=True);self.notify(conn,item,owner)
            return dict(id=vid,revision=row[3]+1)
        @router.put('/v1/social/history/{item}/visits/{vid}')
        async def update_visit(item:str,vid:str,request:Request):
            owner=actor(request,True);identifier(vid);data=await body(request,('revision','place','visitedAt','review','rating'));value=visit_value(data,owner,request)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,record,_,_=self.row(conn,item,owner,True);expected(row,data)
                if not conn.execute('UPDATE team_history_visits SET protected=%s WHERE history_id=%s AND visit_id=%s RETURNING visit_id',(self.protect('visit',owner,item+':'+vid,value),item,vid)).fetchone():unavailable()
                self.save(conn,row,record,data=True);self.notify(conn,item,owner)
            return dict(id=vid,revision=row[3]+1)
        @router.delete('/v1/social/history/{item}/visits/{vid}')
        async def delete_visit(item:str,vid:str,request:Request):
            owner=actor(request,True);identifier(vid);data=await body(request,('revision',))
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,record,_,_=self.row(conn,item,owner,True);expected(row,data)
                self.erase_photo_reviews(conn,item,owner,vid)
                if not conn.execute('DELETE FROM team_history_visits WHERE history_id=%s AND visit_id=%s RETURNING visit_id',(item,vid)).fetchone():unavailable()
                self.save(conn,row,record,data=True);self.notify(conn,item,owner)
            return dict(status='deleted',revision=row[3]+1)
        @router.post('/v1/social/history/{item}/trace-batches',status_code=201)
        async def trace(item:str,request:Request,response:Response):
            owner=actor(request,True);data=await body(request,('revision','batchId','streamId','label','points'));bid=identifier(data['batchId']);stream=identifier(data['streamId']);label=text(data['label'],64)
            if not isinstance(data['points'],list)or not 1<=len(data['points'])<=200:unavailable(400,'Invalid trace batch')
            points=[]
            for p in data['points']:
                if not isinstance(p,dict)or set(p)!={'latitude','longitude','capturedAt','accuracyMeters'}:unavailable(400,'Invalid trace point')
                geo=place(dict(name='reported',latitude=p['latitude'],longitude=p['longitude']));accuracy=p['accuracyMeters']
                if accuracy is not None and(type(accuracy)not in(int,float)or not math.isfinite(accuracy)or not 0<=accuracy<=10000):unavailable(400,'Invalid accuracy')
                points.append(dict(latitude=geo['latitude'],longitude=geo['longitude'],capturedAt=timestamp(p['capturedAt']),accuracyMeters=accuracy))
            if any(points[i]['capturedAt']>=points[i+1]['capturedAt']for i in range(len(points)-1)):unavailable(400,'Trace times must increase')
            self.auth.rate('history-trace:'+owner,limit=30)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id']
                row,record,_,_=self.row(conn,item,owner,True)
                if not record['permissions']['collectTrace']:unavailable(403,'Trace collection permission required')
                old=conn.execute('SELECT protected FROM team_history_trace_batches WHERE history_id=%s AND batch_id=%s',(item,bid)).fetchone()
                requested=dict(streamId=stream,label=label,points=points)
                if old:
                    stored=self.restore('trace',owner,item+':'+bid,old[0])
                    if any(stored[k]!=v for k,v in requested.items()):unavailable(409,'Trace batch is immutable')
                    response.status_code=200
                    return dict(id=bid,revision=row[3],duplicate=True)
                expected(row,data)
                if conn.execute('SELECT coalesce(sum(point_count),0)FROM team_history_trace_batches WHERE history_id=%s',(item,)).fetchone()[0]+len(points)>100000:unavailable(409,'Trace point limit reached')
                payload=dict(requested,source=origin(owner,'browser-reported',request=request));conn.execute('INSERT INTO team_history_trace_batches(history_id,batch_id,protected,point_count)VALUES(%s,%s,%s,%s)',(item,bid,self.protect('trace',owner,item+':'+bid,payload),len(points)));self.save(conn,row,record,data=True);self.notify(conn,item,owner)
            return dict(id=bid,revision=row[3]+1,duplicate=False)
        return router
