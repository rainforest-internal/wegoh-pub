"""Explicit typed UGC review, separate from data ownership and sharing consent.

Only adapters construct projections. Unknown kinds/fields fail closed. Unrequested
private originals never enter an operator queue. A checksum decision is a human
operation, not a keyword filter or a software proof of cognitive review.
"""
import base64,hashlib,hmac,json,secrets
from datetime import datetime,timezone
from urllib.parse import urlsplit
import psycopg
from fastapi import APIRouter,HTTPException,Request,Response
from private_records import VisitCipher
from team_data import changed

KINDS={'history','room','room-place','photo','room-music','caution'}
STATES={'private','quarantined','approved','rejected'}
REASONS={'harmful','privacy','rights','other'}
MAX_PROJECTION=4*1024*1024

def unavailable(code=404,detail='Content unavailable'):
    raise HTTPException(code,detail)

def key_valid(value,kind=None):
    import re
    return bool(isinstance(value,str)and re.fullmatch(r'[a-f0-9]{32}(?::[a-f0-9]{32}){0,2}',value)and(kind is None or len(value.split(':'))=={'history':1,'room':1,'room-place':2,'photo':3,'room-music':2,'caution':1}.get(kind)))

def bounded_text(value,maximum,empty=False):
    return isinstance(value,str)and (empty or bool(value.strip()))and len(value)<=maximum

def projection_bytes(kind,value):
    if kind not in KINDS or not isinstance(value,dict):unavailable(400,'Invalid content kind')
    if kind=='history':
        if set(value)!={'title','places','reviews','traceLabels'}or not bounded_text(value['title'],100):unavailable(400,'Invalid history projection')
        for name,maximum in [('places',80),('reviews',1000),('traceLabels',64)]:
            if not isinstance(value[name],list)or len(value[name])>(100000 if name=='traceLabels'else 500)or any(not bounded_text(item,maximum,empty=name=='reviews')for item in value[name]):unavailable(400,'Invalid text projection')
    elif kind=='room-music':
        if set(value)!={'name','tracks'}or not bounded_text(value['name'],80)or not isinstance(value['tracks'],list)or not 1<=len(value['tracks'])<=100:unavailable(400,'Invalid music projection')
        ids=set()
        for track in value['tracks']:
            if not isinstance(track,dict)or set(track)!={'id','title','url'}or not key_valid(track['id'],'room')or track['id']in ids or not bounded_text(track['title'],120)or not bounded_text(track['url'],2048):unavailable(400,'Invalid music track')
            try:
                url=urlsplit(track['url'])
                if url.scheme!='https'or not url.hostname or url.username or url.password or url.port not in(None,443)or any(c.isspace()for c in track['url']):raise ValueError()
            except ValueError:unavailable(400,'Use an HTTPS track link')
            ids.add(track['id'])
    elif kind=='caution':
        from team_cautions import KINDS as CAUTION_KINDS, place as caution_place
        from team_history import timestamp
        if set(value)!={'kind','observedAt','place'}or value['kind']not in CAUTION_KINDS:unavailable(400,'Invalid caution projection')
        timestamp(value['observedAt']);caution_place(value['place'])
    elif kind in('room','room-place'):
        if set(value)!={'name'}or not bounded_text(value['name'],80):unavailable(400,'Invalid room projection')
    elif(set(value)!={'checksum','width','height','contentType'}or value['contentType']!='image/jpeg'
         or not isinstance(value['checksum'],str)or len(value['checksum'])!=64
         or any(c not in'0123456789abcdef'for c in value['checksum'])
         or any(type(value[n])is not int or not 1<=value[n]<=2048 for n in('width','height'))):unavailable(400,'Invalid photo projection')
    try:raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except(UnicodeError,ValueError):unavailable(400,'Invalid content text')
    if len(raw)>MAX_PROJECTION:unavailable(413,'Content review projection too large')
    return raw

class TeamContent:
    def __init__(self,auth):
        self.auth,self.dsn,self.enabled=auth,auth.dsn,auth.enabled
        self.adapters={}

    def register(self,kind,projector,notify,media=None):
        if kind not in KINDS or kind in self.adapters or not callable(projector)or not callable(notify)or(media is not None and(kind!='photo'or not callable(media))):raise ValueError('Invalid content adapter')
        self.adapters[kind]=(projector,notify,media)

    def identity(self,kind,key):
        if kind not in KINDS or not key_valid(key,kind):unavailable()
        if kind not in self.adapters:raise RuntimeError('Content adapter missing')

    @staticmethod
    def digest(kind,projection):return hashlib.sha256(projection_bytes(kind,projection)).hexdigest()

    @staticmethod
    def protect(owner,kind,key,value):return VisitCipher().protect('team-content:'+owner+':'+kind,key,value)

    @staticmethod
    def restore(owner,kind,key,raw):return VisitCipher().restore('team-content:'+owner+':'+kind,key,raw)

    def row(self,conn,kind,key,*,lock=False):
        self.identity(kind,key)
        if lock:
            if kind in ('room','room-place','room-music'):
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('social-membership',0))")
                link=conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL',(key.split(':')[0],)).fetchone()
                if link:
                    from team_trip_context import trip_state
                    trip_state(conn,link[0])
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('content:'+kind+':'+key,))
        return conn.execute('SELECT owner_id,checksum,state,protected,updated_at,expires_at,'
            '(expires_at IS NULL OR expires_at>now())FROM team_content_reviews WHERE kind=%s AND content_key=%s'+(' FOR UPDATE'if lock else''),(kind,key)).fetchone()

    def linked_context(self,conn,kind,key,owner):
        if kind not in ('room','room-place','room-music'):return None
        room=key.split(':')[0]
        row=conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL',(room,)).fetchone()
        if not row:return None
        from team_trip_context import resolve_trip_context
        from team_rooms import TeamRooms
        context=resolve_trip_context(self.auth,conn,row[0],owner)
        if kind=='room':
            if context['ownerId']!=owner:unavailable()
        else:
            member=conn.execute('SELECT protected,joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s AND left_at IS NULL',(room,owner)).fetchone()
            if not member:unavailable()
            rooms=getattr(self.auth,'room_service',None)or TeamRooms(self.auth)
            consents=rooms.member_payload(owner,room,member[0])['consents']
            required=('status','location')if kind=='room-place'else('music',)
            if not all(consents[name]for name in required):
                music=getattr(self.auth,'room_music_service',None)
                if kind!='room-music' or music is None or not music.current_saved_entry(conn,room,key.split(':')[1],owner):
                    unavailable()
            if kind=='room-place':
                signal=conn.execute('SELECT created_at FROM team_room_signals WHERE room_id=%s AND signal_id=%s AND account_id=%s',(room,key.split(':')[1],owner)).fetchone()
                if not signal or signal[0]<member[1]:unavailable()
        return context

    def context_available(self,conn,kind,key,owner):
        try:self.linked_context(conn,kind,key,owner)
        except HTTPException as error:
            if error.status_code in(403,404,409):return False
            raise
        return True

    def review(self,conn,kind,key,owner,projection):
        checksum=self.digest(kind,projection);row=self.row(conn,kind,key)
        state,requested='private',False
        if row:
            if row[0]!=owner:unavailable()
            value=self.restore(owner,kind,key,row[3])
            if row[6]and row[1]==checksum and value.get('requested')is True and self.context_available(conn,kind,key,owner):
                state,requested=row[2],True
        return dict(kind=kind,key=key,state=state,checksum=checksum,requested=requested)

    def allowed(self,conn,kind,key,owner,projection):
        return self.review(conn,kind,key,owner,projection)['state']=='approved'

    def shared(self,conn,kind,key,owner,projection):
        checksum=self.digest(kind,projection);row=self.row(conn,kind,key)
        if not row or row[0]!=owner or not row[6]or row[2]!='approved'or row[1]!=checksum:return None
        value=self.restore(owner,kind,key,row[3])
        if value.get('requested')is not True or not self.context_available(conn,kind,key,owner):return None
        if self.digest(kind,value['projection'])!=checksum:raise RuntimeError('Content projection integrity failed')
        # Return only the reviewed projection, never an automatic raw-model merge.
        return json.loads(projection_bytes(kind,value['projection']))

    def event(self,conn,kind,key,owner,action,details,event_id=None):
        self.identity(kind,key)
        identifier=event_id or secrets.token_hex(16)
        value=dict(action=action,at=datetime.now(timezone.utc).isoformat(),**details)
        raw=VisitCipher().protect('team-content-event:'+owner,identifier,value)
        conn.execute('INSERT INTO team_content_review_events(event_id,kind,content_key,owner_id,protected)VALUES(%s,%s,%s,%s,%s)ON CONFLICT(event_id)DO NOTHING',(identifier,kind,key,owner,raw))
        return identifier

    def notify(self,conn,kind,key,owner):
        self.adapters[kind][1](conn,key,owner)
        # Queue activity reaches current administrators only, never global '*'.
        for(account,)in conn.execute('SELECT account_id FROM team_accounts').fetchall():
            try:current=self.auth.current_account(account)
            except HTTPException:continue
            if current['role']=='admin':changed(conn,account,'content')

    def request(self,conn,kind,key,owner,projection,consent,expires_at=None):
        if type(consent)is not bool:unavailable(400,'Explicit review consent required')
        context=self.linked_context(conn,kind,key,owner)if consent else None
        checksum=self.digest(kind,projection);row=self.row(conn,kind,key,lock=True)
        if row and row[0]!=owner:unavailable()
        if not consent:
            if row:self.invalidate(conn,kind,key,owner)
            return dict(kind=kind,key=key,state='private',checksum=checksum,requested=False)
        if expires_at is not None and(not isinstance(expires_at,datetime)or expires_at.tzinfo is None):raise ValueError('Invalid content expiry')
        if kind in('room','room-place','room-music')and expires_at is None and context is None:raise ValueError('Room review expiry is required')
        if row and row[1]==checksum and row[6]and row[2]in('quarantined','approved'):
            saved=self.restore(owner,kind,key,row[3])
            if saved.get('requested')is True:return self.review(conn,kind,key,owner,projection)
        raw=self.protect(owner,kind,key,dict(requested=True,projection=projection))
        conn.execute("INSERT INTO team_content_reviews(kind,content_key,owner_id,checksum,state,protected,expires_at)VALUES(%s,%s,%s,%s,'quarantined',%s,%s)ON CONFLICT(kind,content_key)DO UPDATE SET checksum=excluded.checksum,state='quarantined',protected=excluded.protected,expires_at=excluded.expires_at,updated_at=now()",(kind,key,owner,checksum,raw,expires_at))
        self.event(conn,kind,key,owner,'requested',dict(checksum=checksum));self.notify(conn,kind,key,owner)
        return self.review(conn,kind,key,owner,projection)

    def sync(self,conn,kind,key,owner,projection,expires_at=None):
        row=self.row(conn,kind,key,lock=True)
        if not row:return self.review(conn,kind,key,owner,projection)
        if row[0]!=owner:unavailable()
        saved=self.restore(owner,kind,key,row[3])
        if saved.get('requested')is not True:return self.review(conn,kind,key,owner,projection)
        if row[1]==self.digest(kind,projection):return self.review(conn,kind,key,owner,projection)
        return self.request(conn,kind,key,owner,projection,True,expires_at=expires_at or row[5])

    def invalidate(self,conn,kind,key,owner):
        row=self.row(conn,kind,key,lock=True)
        if not row:return
        if row[0]!=owner:unavailable()
        # Clear only the consent-specific derived projection, not the original.
        raw=self.protect(owner,kind,key,dict(requested=False,projection=None))
        conn.execute("UPDATE team_content_reviews SET state='private',protected=%s,updated_at=now()WHERE kind=%s AND content_key=%s",(raw,kind,key))
        self.event(conn,kind,key,owner,'withdrawn',dict(checksum=row[1]));self.notify(conn,kind,key,owner)

    def withdraw_trip_context(self,conn,trip,room,account=None):
        query="SELECT kind,content_key,owner_id FROM team_content_reviews WHERE kind IN ('room','room-place','room-music') AND split_part(content_key,':',1)=%s AND state<>'private'"
        args=[room]
        if account is not None:
            query+=' AND owner_id=%s';args.append(account)
        for kind,key,owner in conn.execute(query+' ORDER BY kind,content_key',args).fetchall():
            self.invalidate(conn,kind,key,owner)

    def erase(self,conn,kind,key,owner):
        row=self.row(conn,kind,key,lock=True)
        if row and row[0]!=owner:unavailable()
        conn.execute('DELETE FROM team_content_reviews WHERE kind=%s AND content_key=%s AND owner_id=%s',(kind,key,owner))
        conn.execute('DELETE FROM team_content_review_events WHERE kind=%s AND content_key=%s AND owner_id=%s',(kind,key,owner))
        if row:self.notify(conn,kind,key,owner)

    def inspect(self,conn,kind,key):
        row=self.row(conn,kind,key)
        if not row or not row[6]or row[2]=='private':unavailable()
        saved=self.restore(row[0],kind,key,row[3])
        if saved.get('requested')is not True or not self.context_available(conn,kind,key,row[0]):unavailable()
        try:owner=self.auth.current_account(row[0])
        except HTTPException:unavailable()
        current=self.adapters[kind][0](conn,key,row[0])
        if self.digest(kind,current)!=row[1]:unavailable(409,'Content changed; request review again')
        projection=json.loads(projection_bytes(kind,saved['projection']))
        if self.digest(kind,projection)!=row[1]:raise RuntimeError('Content projection integrity failed')
        item=dict(kind=kind,key=key,ownerId=row[0],ownerName=owner['displayName'],review=dict(kind=kind,key=key,state=row[2],checksum=row[1],requested=True),projection=projection,expiresAt=row[5],updatedAt=row[4])
        if kind=='photo'and self.adapters[kind][2]:item['mediaUrl']='/v1/moderation/content/photo/'+key+'/media'
        return item

    def report(self,conn,kind,key,owner,projection,reporter,reason):
        if not isinstance(reason,str)or reason not in REASONS:unavailable(400,'Choose a report reason')
        row=self.row(conn,kind,key,lock=True);review=self.review(conn,kind,key,owner,projection)
        if not row or review['state']not in('approved','quarantined'):unavailable()
        event_id=hmac.new(self.auth.secret,('report:'+kind+':'+key+':'+review['checksum']+':'+reporter+':'+reason).encode(),hashlib.sha256).hexdigest()[:32]
        identifier=self.event(conn,kind,key,owner,'reported',dict(checksum=review['checksum'],reporter=reporter,reason=reason),event_id)
        conn.execute("UPDATE team_content_reviews SET state='quarantined',updated_at=now()WHERE kind=%s AND content_key=%s",(kind,key))
        self.notify(conn,kind,key,owner)
        return dict(reportId=identifier,state='quarantined')

    def moderator(self,request):
        if request.url.hostname==urlsplit(self.auth.public_origin).hostname:
            return self.auth.browser(request,mutate=request.method not in('GET','HEAD'),roles=('admin',))
        supplied=request.headers.get('authorization','')
        if request.url.hostname not in('localhost','127.0.0.1')or not request.client or request.client.host not in('127.0.0.1','::1')or not hmac.compare_digest(supplied.encode(),b'Bearer '+self.auth.secret):unavailable(401,'Operator authorization required')
        if request.headers.get('origin'):self.auth.check_origin(request)
        return dict(id='local-operator',displayName=None,role='admin')

    def router(self):
        router=APIRouter()
        if not self.enabled:return router
        @router.get('/v1/moderation/content')
        def queue(request:Request,response:Response):
            self.moderator(request);after=request.query_params.get('cursor');args=[];clause=''
            if set(request.query_params)-{'cursor'}:unavailable(400,'Invalid queue query')
            if after:
                try:
                    if len(after)>256:raise ValueError()
                    cursor=json.loads(base64.urlsafe_b64decode(after+'='*((-len(after))%4)))
                    if not isinstance(cursor,list)or len(cursor)!=2 or cursor[0]not in KINDS or not key_valid(cursor[1],cursor[0]):raise ValueError()
                except(ValueError,UnicodeError,TypeError):unavailable(400,'Invalid queue cursor')
                clause='AND(kind,content_key)>(%s,%s)';args=cursor
            with psycopg.connect(self.dsn)as conn:
                rows=conn.execute("SELECT kind,content_key FROM team_content_reviews WHERE state='quarantined'AND(expires_at IS NULL OR expires_at>now())"+clause+'ORDER BY kind,content_key LIMIT 101',args).fetchall();items=[]
                for kind,key in rows[:100]:
                    try:item=self.inspect(conn,kind,key)
                    except HTTPException as error:
                        if error.status_code in(403,404,409):continue
                        raise
                    item.pop('projection');item['detailUrl']='/v1/moderation/content/'+kind+'/'+key;items.append(item)
            cursor=base64.urlsafe_b64encode(json.dumps(list(rows[99])).encode()).decode().rstrip('=')if len(rows)>100 else None
            response.headers['Cache-Control']='private, no-store';return dict(items=items,nextCursor=cursor)
        @router.get('/v1/moderation/content/{kind}/{key}')
        def detail(kind:str,key:str,request:Request,response:Response):
            self.moderator(request)
            with psycopg.connect(self.dsn)as conn:item=self.inspect(conn,kind,key)
            response.headers['Cache-Control']='private, no-store';return item
        @router.get('/v1/moderation/content/{kind}/{key}/media')
        def media(kind:str,key:str,request:Request):
            self.moderator(request)
            if kind!='photo':unavailable()
            with psycopg.connect(self.dsn)as conn:
                item=self.inspect(conn,kind,key);reader=self.adapters[kind][2]
                if reader is None:unavailable()
                raw=reader(conn,key,item['ownerId'])
                if not isinstance(raw,bytes)or not 1<=len(raw)<=3145728 or hashlib.sha256(raw).hexdigest()!=item['projection']['checksum']:raise RuntimeError('Review image integrity failed')
            return Response(raw,media_type='image/jpeg',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Disposition':'inline; filename="review.jpg"'})
        @router.post('/v1/moderation/content/{kind}/{key}')
        async def decision(kind:str,key:str,request:Request):
            identity=self.moderator(request);raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>4096:unavailable(413,'Review request too large')
            try:body=json.loads(raw)
            except(ValueError,UnicodeError):unavailable(400,'Invalid JSON')
            if not isinstance(body,dict)or set(body)!={'checksum','decision','reviewer','reviewNote'}or body['decision']not in('approved','rejected')or not bounded_text(body['reviewer'],80)or not bounded_text(body['reviewNote'],1000):unavailable(400,'Explicit full-content review required')
            with psycopg.connect(self.dsn)as conn:
                self.row(conn,kind,key,lock=True);item=self.inspect(conn,kind,key)
                if item['review']['state']!='quarantined'or body['checksum']!=item['review']['checksum']:unavailable(409,'Review checksum or state changed')
                conn.execute('UPDATE team_content_reviews SET state=%s,updated_at=now()WHERE kind=%s AND content_key=%s',(body['decision'],kind,key))
                self.event(conn,kind,key,item['ownerId'],body['decision'],dict(checksum=body['checksum'],reviewer=identity['displayName']or body['reviewer'],reviewerId=identity['id'],reviewNote=body['reviewNote']))
                self.notify(conn,kind,key,item['ownerId'])
            return dict(kind=kind,key=key,state=body['decision'],checksum=body['checksum'],requested=True)
        return router
