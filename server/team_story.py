"""Explicit, revocable external-story purposes. No encoder or external URL fetch.

Manifests are personal, short lived authorization snapshots, not completed files.
Revocation prevents future retrieval; already exported user files cannot be recalled.
"""
import copy,hashlib,json,math,secrets
from datetime import datetime,timezone,timedelta
import psycopg
from fastapi import APIRouter,HTTPException,Request,Response
from team_history import identifier,revision,timestamp,unavailable
from team_friends import ACCOUNT,linked

RADIUS=200
MAX_HISTORIES=5
MAX_POINTS=20000

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def distance(a,b):
    lat1,lat2=map(math.radians,(a['latitude'],b['latitude']));dl=math.radians(b['longitude']-a['longitude']);dp=lat2-lat1
    return 6371000*2*math.asin(min(1,math.sqrt(math.sin(dp/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2)))

class TeamStory:
    def __init__(self,auth,history,photos):self.auth,self.history,self.photos,self.dsn,self.enabled=auth,history,photos,auth.dsn,auth.enabled
    @property
    def content(self):return self.auth.content_service
    def fingerprint(self,conn,item,owner,photos):
        entries=[]
        keys=[('history',item)]
        if photos:
            keys += [('photo',item+':'+v+':'+p)for v,p in conn.execute('SELECT visit_id,photo_id FROM team_history_photos WHERE history_id=%s ORDER BY visit_id,photo_id',(item,))]
        for kind,key in keys:
            # Same content locks as moderation: a decision/report cannot race an authorization snapshot.
            row=self.content.row(conn,kind,key,lock=True)
            entries.append([kind,key,None if not row else [row[1],row[2],row[4].isoformat(),row[5].isoformat()if row[5]else None]])
        return hashlib.sha256(canonical(entries)).hexdigest()
    def consent(self,conn,item,owner,target):
        row=conn.execute('SELECT revision,protected FROM team_story_permissions WHERE history_id=%s AND exporter_id=%s FOR SHARE',(item,target)).fetchone()
        return (row[0],self.history.restore('story-consent',owner,item+':'+target,row[1]))if row else(0,None)
    def permitted(self,conn,item,actor):
        row,value,own,grant=self.history.row(conn,item,actor,stable=True)
        if not self.history.person(row[1]):unavailable()
        number,permission=self.consent(conn,item,row[1],actor)
        if(not permission or permission.get('consent')is not True or permission['historyRevision']!=row[3]
            or permission['permissionRevision']!=row[4]or datetime.fromisoformat(permission['expiresAt'])<=datetime.now(timezone.utc)):unavailable()
        if not self.content.allowed(conn,'history',item,row[1],self.history.projection(conn,item,row[1])):unavailable()
        if permission['contentFingerprint']!=self.fingerprint(conn,item,row[1],permission['photos']):unavailable()
        choices={key:bool(permission[key]and grant.get(key,False))for key in('visits','trace','photos')}
        if any(permission[key]and not choices[key]for key in choices):unavailable()
        if conn.execute('SELECT coalesce(sum(point_count),0)FROM team_history_trace_batches WHERE history_id=%s',(item,)).fetchone()[0]>MAX_POINTS:unavailable(413,'Story point limit exceeded')
        detail=self.history.detail(conn,item,actor)
        return row,detail,permission,number
    def build(self,conn,items,actor):
        histories=[];suppressed_points=0;suppressed_visits=0;expires=datetime.now(timezone.utc)+timedelta(minutes=5);total=0
        self.history.rooms.graph_lock(conn)
        # A shared order prevents multi-record readers from deadlocking owners.
        for item in sorted(items):
            self.history.row(conn,item,actor,stable=True)
        for item in items:
            row,data,permission,number=self.permitted(conn,item,actor);expires=min(expires,datetime.fromisoformat(permission['expiresAt']))
            streams={};endpoints=[]
            for batch in data['traceBatches']:
                key=batch['streamId'];stream=streams.setdefault(key,dict(streamId=key,label=batch['label'],source=batch['source'],points=[]));stream['points'].extend(batch['points'])
            batches=[]
            for stream in streams.values():
                points=sorted(stream['points'],key=lambda p:p['capturedAt']);total+=len(points)
                if total>MAX_POINTS:unavailable(413,'Story point limit exceeded')
                if not points:continue
                endpoints.extend((points[0],points[-1]));retained=[];segment=-1;last=-2
                for index,point in enumerate(points):
                    if distance(point,points[0])<RADIUS or distance(point,points[-1])<RADIUS:
                        suppressed_points+=1;continue
                    if not permission['trace']:continue
                    if index!=last+1:segment+=1
                    retained.append(dict(point,originalIndex=index,segmentId=segment));last=index
                if retained:batches.append(dict(streamId=stream['streamId'],label=stream['label'],source=stream['source'],points=retained))
            visits=[]
            if permission['visits']:
                for visit in data['visits']:
                    if any(distance(visit['place'],endpoint)<RADIUS for endpoint in endpoints):suppressed_visits+=1;continue
                    location=visit['place']if endpoints and permission['trace']else dict(name=visit['place']['name'],latitude=None,longitude=None)
                    photos=[]
                    if permission['photos']:
                        for photo in visit['photos']:
                            key=self.photos.key(item,visit['id'],photo['id'])
                            if not self.content.allowed(conn,'photo',key,row[1],self.photos.projection(conn,key,row[1])):continue
                            photos.append({k:photo[k]for k in('id','width','height','checksum')})
                    visits.append(dict(id=visit['id'],place=location,visitedAt=visit['visitedAt'],review=visit['review'],rating=visit['rating'],source=visit['source'],photos=photos))
            histories.append(dict(id=item,ownerId=row[1],title=data['title'],historyRevision=row[3],permissionRevision=row[4],exportRevision=number,source={k:data['source'][k]for k in('kind','actorId','receivedAt')},traceBatches=batches,visits=visits))
        result=dict(histories=histories,privacy=dict(endpointRadiusMeters=RADIUS,suppressedPoints=suppressed_points,suppressedVisits=suppressed_visits))
        if len(canonical(result))>8*1024*1024:unavailable(413,'Story manifest limit exceeded')
        return result,expires
    def output(self,key,snapshot,expires):
        result=copy.deepcopy(snapshot);checksum=hashlib.sha256(canonical(snapshot)).hexdigest()
        for history in result['histories']:
            for visit in history['visits']:
                for photo in visit['photos']:photo['url']='/v1/social/story-manifests/'+key+'/photos/'+history['id']+'/'+visit['id']+'/'+photo['id']
        return dict(result,id=key,checksum=checksum,expiresAt=expires.isoformat(),serverNow=datetime.now(timezone.utc).isoformat())
    def current(self,conn,key,actor):
        self.history.rooms.graph_lock(conn) # Same order as creation/expiry cleanup.
        identifier(key);row=conn.execute('SELECT protected,expires_at FROM team_story_manifests WHERE manifest_id=%s AND account_id=%s FOR SHARE',(key,actor)).fetchone()
        if not row or row[1]<=datetime.now(timezone.utc):unavailable()
        value=self.history.restore('story-manifest',actor,key,row[0]);snapshot,_=self.build(conn,value['historyIds'],actor)
        if hashlib.sha256(canonical(snapshot)).hexdigest()!=value['checksum']:unavailable()
        return snapshot,row[1]
    def router(self):
        router=APIRouter()
        if not self.auth.enabled:return router
        async def body(request,fields):
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>4096:unavailable(413,'Story request too large')
            try:value=json.loads(raw)
            except(ValueError,UnicodeError):unavailable(400,'Invalid JSON')
            if not isinstance(value,dict)or set(value)!=set(fields):unavailable(400,'Invalid story fields')
            return value
        @router.get('/v1/social/history/{item}/export-permissions')
        def permissions(item:str,request:Request):
            actor=self.auth.browser(request)['id'];result=[]
            with psycopg.connect(self.dsn)as conn:
                row,_,own,_=self.history.row(conn,item,actor,stable=True)
                targets=[r[0]for r in conn.execute('SELECT exporter_id FROM team_story_permissions WHERE history_id=%s ORDER BY exporter_id',(item,))]if own else[actor]
                for target in targets:
                    number,value=self.consent(conn,item,row[1],target)
                    if value:
                        active=False
                        try:self.permitted(conn,item,target);active=True
                        except HTTPException as error:
                            if error.status_code!=404:raise
                        result.append(dict(exporterId=target,revision=number,consent=value['consent'],visits=value['visits'],trace=value['trace'],photos=value['photos'],expiresAt=value['expiresAt'],historyRevision=value['historyRevision'],active=active))
            return dict(historyId=item,historyRevision=row[3],permissions=result,serverNow=datetime.now(timezone.utc).isoformat())
        @router.put('/v1/social/history/{item}/export-permissions/{target}')
        async def allow(item:str,target:str,request:Request):
            owner=self.auth.browser(request,mutate=True)['id'];data=await body(request,('revision','historyRevision','consent','visits','trace','photos','expiresAt'))
            if not ACCOUNT.fullmatch(target)or type(data['revision'])is not int or not 0<=data['revision']<2147483647 or data['consent']is not True or any(type(data[k])is not bool for k in('visits','trace','photos'))or(data['photos']and not data['visits'])or not(data['visits']or data['trace']):unavailable(400,'Choose external story purposes')
            expected=revision(data['historyRevision']);expires=timestamp(data['expiresAt'],future=True);now=datetime.now(timezone.utc)
            if not now<datetime.fromisoformat(expires)<=now+timedelta(hours=24):unavailable(400,'Choose a story expiry within 24 hours')
            self.auth.rate('story-consent:'+owner,limit=30)
            with psycopg.connect(self.dsn)as conn:
                self.history.rooms.graph_lock(conn);row,_,_,_=self.history.row(conn,item,owner,True)
                if row[3]!=expected:unavailable(409,'Refresh the record')
                if target!=owner and(not self.history.person(target)or not linked(conn,owner,target)):unavailable()
                number,_=self.consent(conn,item,owner,target)
                if number!=data['revision']:unavailable(409,'Refresh external sharing permissions')
                if not self.content.allowed(conn,'history',item,owner,self.history.projection(conn,item,owner)):unavailable()
                value={k:data[k]for k in('consent','visits','trace','photos','expiresAt','historyRevision')};value['permissionRevision']=row[4];value['contentFingerprint']=self.fingerprint(conn,item,owner,data['photos'])
                raw=self.history.protect('story-consent',owner,item+':'+target,value)
                conn.execute('INSERT INTO team_story_permissions(history_id,exporter_id,revision,protected)VALUES(%s,%s,%s,%s)ON CONFLICT(history_id,exporter_id)DO UPDATE SET revision=excluded.revision,protected=excluded.protected',(item,target,number+1,raw));self.history.notify(conn,item,owner,(target,))
            return dict(revision=number+1,historyRevision=row[3])
        @router.delete('/v1/social/history/{item}/export-permissions/{target}')
        def revoke(item:str,target:str,request:Request):
            owner=self.auth.browser(request,mutate=True)['id']
            if not ACCOUNT.fullmatch(target):unavailable()
            with psycopg.connect(self.dsn)as conn:
                self.history.rooms.graph_lock(conn);row,_,_,_=self.history.row(conn,item,owner,True);number,value=self.consent(conn,item,owner,target)
                if value:
                    value['consent']=False;conn.execute('UPDATE team_story_permissions SET revision=revision+1,protected=%s WHERE history_id=%s AND exporter_id=%s',(self.history.protect('story-consent',owner,item+':'+target,value),item,target))
                    self.history.notify(conn,item,owner,(target,))
            return dict(status='revoked',revision=number+int(value is not None))
        @router.post('/v1/social/story-manifests',status_code=201)
        async def create(request:Request):
            actor=self.auth.browser(request,mutate=True)['id'];data=await body(request,('historyIds',));items=data['historyIds']
            if not isinstance(items,list)or not 1<=len(items)<=MAX_HISTORIES or any(not isinstance(x,str)for x in items)or len(set(items))!=len(items):unavailable(400,'Choose one to five records')
            for item in items:identifier(item)
            self.auth.rate('story-manifest:'+actor,limit=20);key=secrets.token_hex(16)
            with psycopg.connect(self.dsn)as conn:
                snapshot,expires=self.build(conn,items,actor);value=dict(historyIds=items,checksum=hashlib.sha256(canonical(snapshot)).hexdigest())
                conn.execute('DELETE FROM team_story_manifests WHERE account_id=%s AND expires_at<now()',(actor,))
                if conn.execute('SELECT count(*)FROM team_story_manifests WHERE account_id=%s',(actor,)).fetchone()[0]>=20:unavailable(429,'Story manifest limit reached')
                conn.execute('INSERT INTO team_story_manifests(manifest_id,account_id,protected,expires_at)VALUES(%s,%s,%s,%s)',(key,actor,self.history.protect('story-manifest',actor,key,value),expires))
            return self.output(key,snapshot,expires)
        @router.get('/v1/social/story-manifests/{key}')
        def read(key:str,request:Request):
            actor=self.auth.browser(request)['id']
            with psycopg.connect(self.dsn)as conn:snapshot,expires=self.current(conn,key,actor)
            return self.output(key,snapshot,expires)
        @router.delete('/v1/social/story-manifests/{key}')
        def discard(key:str,request:Request):
            actor=self.auth.browser(request,mutate=True)['id'];identifier(key)
            with psycopg.connect(self.dsn)as conn:conn.execute('DELETE FROM team_story_manifests WHERE manifest_id=%s AND account_id=%s',(key,actor))
            return dict(status='deleted')
        @router.get('/v1/social/story-manifests/{key}/photos/{item}/{visit}/{photo}')
        def image(key:str,item:str,visit:str,photo:str,request:Request):
            actor=self.auth.browser(request)['id'];identifier(item);identifier(visit);identifier(photo)
            with psycopg.connect(self.dsn)as conn:
                snapshot,_=self.current(conn,key,actor)
                selected=next((h for h in snapshot['histories']if h['id']==item),None)
                if not selected or not any(v['id']==visit and any(p['id']==photo for p in v['photos'])for v in selected['visits']):unavailable()
                raw=self.photos.read_image(conn,item,visit,photo,selected['ownerId'])
            return Response(raw,media_type='image/jpeg',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
        return router
