"""Explicit user-observed caution records with private defaults and revocable individual sharing."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import secrets

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool
from private_records import VisitCipher
from team_data import changed
from team_friends import ACCOUNT, linked
from team_history import timestamp
from native_functional_identity import transaction_actor

IDENT = re.compile('[0-9a-f]{32}')
KINDS = ('road-surface','construction','visibility','harsh-braking','other')
CREATE = {'eventId','kind','observedAt','placeSource','publicPlaceConfirmed','storageConsent','rightsConfirmed'}
EDIT = (CREATE - {'eventId'}) | {'revision'}


def fail(code=404, detail='Caution unavailable'):
    raise HTTPException(code, detail)


def identifier(value):
    if not isinstance(value,str) or not IDENT.fullmatch(value): fail()
    return value


def exact(value, fields):
    if not isinstance(value,dict) or set(value)!=set(fields): fail(400,'Invalid caution fields')


def canonical(value):
    try:return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    except(ValueError,UnicodeError):fail(400,'Invalid caution text')


def number(value):
    if type(value) is not int or not 1<=value<=2147483647: fail(400,'Invalid caution revision')
    return value


def place(value):
    exact(value,('id','provider','name','address','latitude','longitude'))
    for key, limit in (('id',240),('provider',40),('name',80),('address',200)):
        text=value[key]
        if (not isinstance(text,str) or len(text)>limit or (key!='address' and not text.strip())
                or any(ord(ch)<32 for ch in text)): fail(400,'Choose a public place')
    for key, low, high in (('latitude',-90,90),('longitude',-180,180)):
        value_=value[key]
        if type(value_) not in (int,float) or not low<=value_<=high or not math.isfinite(value_):
            fail(400,'Invalid selected public place')
    return dict(value)


def saved_public_place(value):
    # Public identity uses only the explicitly confirmed public snapshot.
    # Never include a private history/visit identifier, including its hash.
    public={key:value[key]for key in ('name','latitude','longitude')}
    return place(dict(id='saved-place-'+hashlib.sha256(canonical(public)).hexdigest(),
                      provider='own-saved-visit',address='',**public))


class TeamCautions:
    def __init__(self, auth, history):
        self.auth,self.history,self.dsn,self.enabled=auth,history,auth.dsn,auth.enabled

    @property
    def content(self): return self.auth.content_service

    @staticmethod
    def protect(kind, owner, key, value):
        return VisitCipher().protect('team-cautions-'+kind+':'+owner,key,value)

    @staticmethod
    def restore(kind, owner, key, raw):
        value=VisitCipher().restore('team-cautions-'+kind+':'+owner,key,raw)
        try:
            if kind=='record':
                exact(value,('kind','observedAt','place','placeSource','source'))
                if value['kind'] not in KINDS:raise ValueError()
                timestamp(value['observedAt']);place(value['place'])
                exact(value['source'],('kind','physicalMeasurementVerified'))
                if value['source']['kind']!='user-observed' or value['source']['physicalMeasurementVerified'] is not False:raise ValueError()
                source=value['placeSource']
                if source['kind']=='selected-place':
                    exact(source,('kind','place'));place(source['place'])
                    if source['place']!=value['place']:raise ValueError()
                elif source['kind']=='own-history-visit':
                    exact(source,('kind','historyId','visitId','revision'))
                    identifier(source['historyId']);identifier(source['visitId']);number(source['revision'])
                    if value['place']!=saved_public_place(value['place']):raise ValueError()
                else:raise ValueError()
            elif kind=='share':
                exact(value,('consent','rightsConfirmed','recordRevision','reviewFingerprint','expiresAt'))
                if value['consent'] is not True or value['rightsConfirmed'] is not True:raise ValueError()
                number(value['recordRevision'])
                if not isinstance(value['reviewFingerprint'],str) or not re.fullmatch('[0-9a-f]{64}',value['reviewFingerprint']):raise ValueError()
                timestamp(value['expiresAt'],future=True)
            elif kind=='receipt':
                exact(value,('requestSha256',))
                if not isinstance(value['requestSha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['requestSha256']):raise ValueError()
            else:raise ValueError()
        except (HTTPException,KeyError,TypeError,ValueError,OverflowError):
            fail(503,'Stored caution integrity unavailable')
        return value

    def normalize(self, data, *, create):
        exact(data,CREATE if create else EDIT)
        if data['kind'] not in KINDS or any(data[key] is not True for key in
                ('publicPlaceConfirmed','storageConsent','rightsConfirmed')):
            fail(400,'Confirm the observed public place, storage and rights')
        if create: identifier(data['eventId'])
        else: number(data['revision'])
        source=data['placeSource']
        if not isinstance(source,dict): fail(400,'Choose the observed place')
        if source.get('kind')=='selected-place':
            exact(source,('kind','place')); source=dict(kind='selected-place',place=place(source['place']))
        elif source.get('kind')=='own-history-visit':
            exact(source,('kind','historyId','visitId','revision'))
            identifier(source['historyId']); identifier(source['visitId']); number(source['revision'])
            source=dict(source)
        else: fail(400,'Choose a selected place or your own saved visit')
        return dict(kind=data['kind'],observedAt=timestamp(data['observedAt']),placeSource=source,
                    publicPlaceConfirmed=True,storageConsent=True,rightsConfirmed=True)

    def resolve(self, conn, owner, normalized):
        source=normalized['placeSource']
        if source['kind']=='selected-place':
            chosen=source['place']
        else:
            row,_,own,_=self.history.row(conn,source['historyId'],owner,stable=True)
            if not own: fail()  # Friend history reading never grants derivative rights.
            if row[3]!=source['revision']: fail(409,'Saved visit changed; choose the current source')
            row=conn.execute('SELECT protected FROM team_history_visits WHERE history_id=%s AND visit_id=%s',
                             (source['historyId'],source['visitId'])).fetchone()
            if not row: fail()
            saved=self.history.restore('visit',owner,source['historyId']+':'+source['visitId'],row[0])
            original=saved['place']
            chosen=saved_public_place(original)
        return dict(kind=normalized['kind'],observedAt=normalized['observedAt'],place=chosen,
                    placeSource=dict(source),source=dict(kind='user-observed',physicalMeasurementVerified=False))

    def projection(self, conn, item, owner):
        row=conn.execute('SELECT protected FROM team_cautions WHERE caution_id=%s AND owner_id=%s',(item,owner)).fetchone()
        if not row: fail()
        value=self.restore('record',owner,item,row[0])
        return {key:value[key] for key in ('kind','observedAt','place')}

    def notify(self, conn, item, owner, extra=()):
        recipients={a for a, in conn.execute('SELECT account_id FROM team_caution_shares WHERE caution_id=%s',(item,))}
        for account in sorted(recipients|{owner}|set(extra)): changed(conn,account,'cautions')

    def review_state(self, conn, item, owner, value):
        projection={key:value[key] for key in ('kind','observedAt','place')}
        shared=self.content.shared(conn,'caution',item,owner,projection)
        row=self.content.row(conn,'caution',item)
        if shared is None or not row: return None,None
        stamp=hashlib.sha256(canonical(dict(checksum=row[1],state=row[2],
            protectedSha256=hashlib.sha256(bytes(row[3])).hexdigest(),updatedAt=row[4].isoformat()))).hexdigest()
        return shared,stamp

    def row(self, conn, item, actor, *, write=False):
        identifier(item)
        row=conn.execute('SELECT caution_id,owner_id,protected,revision,permission_revision,created_at,updated_at '
            'FROM team_cautions WHERE caution_id=%s'+(' FOR UPDATE' if write else ' FOR SHARE'),(item,)).fetchone()
        if not row or (write and row[1]!=actor): fail()
        value=self.restore('record',row[1],item,row[2]); expiry=None
        if actor!=row[1]:
            if not self.history.person(row[1]) or not linked(conn,row[1],actor): fail()
            grant=conn.execute('SELECT protected,expires_at FROM team_caution_shares WHERE caution_id=%s '
                               'AND account_id=%s AND expires_at>now()',(item,actor)).fetchone()
            if not grant: fail()
            saved=self.restore('share',row[1],item+':'+actor,grant[0])
            if datetime.fromisoformat(saved['expiresAt'].replace('Z','+00:00'))!=grant[1]:fail(503,'Stored caution sharing expiry unavailable')
            shared,stamp=self.review_state(conn,item,row[1],value)
            if (shared is None or saved['consent'] is not True or saved['rightsConfirmed'] is not True
                    or saved['recordRevision']!=row[3] or saved['reviewFingerprint']!=stamp): fail()
            # Return exactly the reviewed projection, never private source references.
            value=dict(shared,source=dict(kind='user-observed',physicalMeasurementVerified=False))
            expiry=grant[1]
        return row,value,expiry

    def public(self, conn, item, actor):
        row,value,expiry=self.row(conn,item,actor)
        own=row[1]==actor; author=self.history.person(row[1])
        output=dict(id=item,own=own,revision=row[3],permissionRevision=row[4] if own else None,
            kind=value['kind'],place=value['place'],observedAt=value['observedAt'],source=value['source'],
            ownerId=row[1],ownerName=author['name'] if author else None,shareExpiresAt=expiry,
            review=self.content.review(conn,'caution',item,row[1],{k:value[k] for k in ('kind','observedAt','place')}),
            serverNow=datetime.now(timezone.utc),currentRoadConditionVerified=False)
        if own: output['placeSource']=value['placeSource']
        return output

    def create(self, conn, owner, data):
        normalized=self.normalize(data,create=True); event=data['eventId']
        self.history.rooms.graph_lock(conn)
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('cautions:'+owner,))
        digest=hashlib.sha256(canonical(normalized)).hexdigest()
        previous=conn.execute('SELECT caution_id,protected FROM team_caution_receipts WHERE account_id=%s AND event_id=%s '
                              'FOR UPDATE',(owner,event)).fetchone()
        if previous:
            receipt=self.restore('receipt',owner,event,previous[1])
            if receipt['requestSha256']!=digest: fail(409,'This submission identifier has a different body')
            if previous[0] is None: fail(409,'This submission was deleted; do not recreate it automatically')
            value=self.public(conn,previous[0],owner)
            return 200,dict(id=previous[0],revision=value['revision'],permissionRevision=value['permissionRevision'],duplicate=True)
        if conn.execute('SELECT count(*) FROM team_caution_receipts WHERE account_id=%s',(owner,)).fetchone()[0]>=2000:
            fail(409,'Caution submission limit reached')
        if conn.execute('SELECT count(*) FROM team_cautions WHERE owner_id=%s',(owner,)).fetchone()[0]>=500:
            fail(409,'Caution record limit reached')
        item=secrets.token_hex(16); value=self.resolve(conn,owner,normalized)
        conn.execute('INSERT INTO team_cautions(caution_id,owner_id,protected) VALUES(%s,%s,%s)',
                     (item,owner,self.protect('record',owner,item,value)))
        conn.execute('INSERT INTO team_caution_receipts(account_id,event_id,caution_id,protected) VALUES(%s,%s,%s,%s)',
                     (owner,event,item,self.protect('receipt',owner,event,dict(requestSha256=digest))))
        self.notify(conn,item,owner)
        return 201,dict(id=item,revision=1,permissionRevision=1,visibility='private')

    def edit(self, conn, owner, item, data):
        normalized=self.normalize(data,create=False)
        self.history.rooms.graph_lock(conn); row,old,_=self.row(conn,item,owner,write=True)
        if data['revision']!=row[3]: fail(409,'Caution changed; reload before editing')
        value=self.resolve(conn,owner,normalized)
        recipients={a for a, in conn.execute('SELECT account_id FROM team_caution_shares WHERE caution_id=%s',(item,))}
        conn.execute('DELETE FROM team_caution_shares WHERE caution_id=%s',(item,))
        conn.execute('UPDATE team_cautions SET protected=%s,revision=revision+1,permission_revision=permission_revision+1,'
            'updated_at=now() WHERE caution_id=%s',(self.protect('record',owner,item,value),item))
        self.content.sync(conn,'caution',item,owner,self.projection(conn,item,owner))
        self.notify(conn,item,owner,recipients)
        return dict(id=item,revision=row[3]+1,permissionRevision=row[4]+1,visibility='private')

    def share(self, conn, owner, item, target, data):
        exact(data,('revision','permissionRevision','consent','expiresInHours','rightsConfirmed'))
        if not isinstance(target,str) or not ACCOUNT.fullmatch(target) or target==owner: fail(400,'Choose a friend')
        if type(data['consent']) is not bool or type(data['rightsConfirmed']) is not bool: fail(400,'Explicit caution sharing purpose required')
        number(data['revision']); number(data['permissionRevision'])
        if type(data['expiresInHours']) is not int or not 1<=data['expiresInHours']<=24:fail(400,'Choose a sharing period of one to24 hours')
        if data['consent'] is False: return self.revoke(conn,owner,item,target)
        if data['rightsConfirmed'] is not True:
            fail(400,'Confirm rights and a sharing period of one to24 hours')
        self.history.rooms.graph_lock(conn); row,value,_=self.row(conn,item,owner,write=True)
        if row[3]!=data['revision'] or row[4]!=data['permissionRevision']: fail(409,'Caution sharing changed')
        if not self.history.person(target) or not linked(conn,owner,target): fail()
        shared,stamp=self.review_state(conn,item,owner,value)
        if shared is None: fail(409,'Request and complete current content review before sharing')
        expiry=datetime.now(timezone.utc)+timedelta(hours=data['expiresInHours'])
        saved=dict(consent=True,rightsConfirmed=True,recordRevision=row[3],reviewFingerprint=stamp,expiresAt=expiry.isoformat())
        conn.execute('INSERT INTO team_caution_shares(caution_id,account_id,protected,expires_at) VALUES(%s,%s,%s,%s) '
            'ON CONFLICT(caution_id,account_id) DO UPDATE SET protected=excluded.protected,expires_at=excluded.expires_at',
            (item,target,self.protect('share',owner,item+':'+target,saved),expiry))
        conn.execute('UPDATE team_cautions SET permission_revision=permission_revision+1,updated_at=now() WHERE caution_id=%s',(item,))
        self.notify(conn,item,owner)
        return dict(accountId=target,consent=True,permissionRevision=row[4]+1,expiresAt=expiry,serverNow=datetime.now(timezone.utc))

    def revoke(self, conn, owner, item, target):
        # Stale-safe privacy action; no target membership/revision is required.
        self.history.rooms.graph_lock(conn)
        row=conn.execute('SELECT owner_id,permission_revision FROM team_cautions WHERE caution_id=%s FOR UPDATE',(identifier(item),)).fetchone()
        if not row or row[0]!=owner: fail()
        removed=conn.execute('DELETE FROM team_caution_shares WHERE caution_id=%s AND account_id=%s RETURNING account_id',(item,target)).fetchone()
        conn.execute('UPDATE team_cautions SET permission_revision=permission_revision+1,updated_at=now() WHERE caution_id=%s',(item,))
        self.notify(conn,item,owner,(target,)if removed else())
        return dict(accountId=target,consent=False,permissionRevision=row[1]+1)

    def revoke_pair(self, conn, a, b):
        rows=conn.execute('SELECT c.caution_id,c.owner_id,s.account_id FROM team_cautions c JOIN team_caution_shares s USING(caution_id) '
            'WHERE(c.owner_id=%s AND s.account_id=%s)OR(c.owner_id=%s AND s.account_id=%s) ORDER BY c.caution_id FOR UPDATE OF c',(a,b,b,a)).fetchall()
        for item,owner,target in rows:
            conn.execute('DELETE FROM team_caution_shares WHERE caution_id=%s AND account_id=%s',(item,target))
            conn.execute('UPDATE team_cautions SET permission_revision=permission_revision+1,updated_at=now() WHERE caution_id=%s',(item,))
            self.notify(conn,item,owner,(target,))

    def router(self):
        router=APIRouter()
        if not self.enabled:return router
        async def body(request,fields):
            raw=bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw)>8192:fail(413,'Caution request too large')
            except TimeoutError:fail(408,'Caution request timed out')
            try:data=json.loads(raw,parse_constant=lambda _:(_ for _ in()).throw(ValueError()))
            except(ValueError,UnicodeError,RecursionError):fail(400,'Invalid caution JSON')
            exact(data,fields);return data
        def actor(conn,request,mutate=False):return transaction_actor(self.auth,request,conn,mutate=mutate)['id']
        async def mutate(request,fields,operation):
            data=await body(request,fields)
            def write():
                with psycopg.connect(self.dsn) as conn:
                    owner=actor(conn,request,True);self.auth.rate('caution-write:'+owner,limit=30)
                    return operation(conn,owner,data)
            return await run_in_threadpool(write)
        @router.post('/v1/social/cautions',status_code=201)
        async def create(request:Request,response:Response):
            status,value=await mutate(request,CREATE,self.create);response.status_code=status;return value
        @router.get('/v1/social/cautions')
        def listing(request:Request):
            params=request.query_params
            if set(params)-{'cursor','eventId'} or ('cursor'in params and'eventId'in params):fail(400,'Invalid caution pagination')
            with psycopg.connect(self.dsn) as conn:
                owner=actor(conn,request);self.history.rooms.graph_lock(conn)
                if 'eventId'in params:
                    row=conn.execute('SELECT caution_id FROM team_caution_receipts WHERE account_id=%s AND event_id=%s',(owner,identifier(params['eventId']))).fetchone()
                    return dict(items=[self.public(conn,row[0],owner)] if row and row[0] else [],nextCursor=None,serverNow=datetime.now(timezone.utc))
                arguments=[owner,owner];extra=''
                if 'cursor'in params:
                    try:
                        raw=params['cursor']
                        if len(raw)>256 or not re.fullmatch('[A-Za-z0-9_-]+',raw):raise ValueError()
                        decoded=json.loads(base64.urlsafe_b64decode(raw+'='*((-len(raw))%4)))
                        exact(decoded,('updatedAt','id'));identifier(decoded['id']);moment=timestamp(decoded['updatedAt'])
                    except(ValueError,UnicodeError,KeyError,HTTPException):fail(400,'Invalid caution cursor')
                    extra=' AND(c.updated_at,c.caution_id)<(%s,%s)';arguments += [moment,decoded['id']]
                rows=conn.execute('SELECT c.caution_id,c.updated_at FROM team_cautions c WHERE(c.owner_id=%s OR c.caution_id IN '
                    '(SELECT caution_id FROM team_caution_shares WHERE account_id=%s AND expires_at>now()))'+extra+
                    ' ORDER BY c.updated_at DESC,c.caution_id DESC LIMIT 51',arguments).fetchall()
                items=[]
                for item,_ in rows[:50]:
                    try:items.append(self.public(conn,item,owner))
                    except HTTPException as error:
                        if error.status_code!=404:raise
                cursor=None
                if len(rows)>50:
                    item,updated=rows[49];cursor=base64.urlsafe_b64encode(canonical(dict(updatedAt=updated.isoformat(),id=item))).decode().rstrip('=')
                return dict(items=items,nextCursor=cursor,serverNow=datetime.now(timezone.utc))
        @router.get('/v1/social/cautions/{item}')
        def detail(item:str,request:Request):
            with psycopg.connect(self.dsn) as conn:
                owner=actor(conn,request);self.history.rooms.graph_lock(conn);return self.public(conn,item,owner)
        @router.put('/v1/social/cautions/{item}')
        async def edit(item:str,request:Request):return await mutate(request,EDIT,lambda c,a,d:self.edit(c,a,item,d))
        @router.delete('/v1/social/cautions/{item}')
        def delete(item:str,request:Request):
            with psycopg.connect(self.dsn) as conn:
                owner=actor(conn,request,True);self.history.rooms.graph_lock(conn)
                row=conn.execute('SELECT owner_id FROM team_cautions WHERE caution_id=%s FOR UPDATE',(identifier(item),)).fetchone()
                if not row or row[0]!=owner:fail()
                recipients={a for a, in conn.execute('SELECT account_id FROM team_caution_shares WHERE caution_id=%s',(item,))}
                self.content.erase(conn,'caution',item,owner)
                conn.execute('DELETE FROM team_cautions WHERE caution_id=%s',(item,));self.notify(conn,item,owner,recipients)
                return dict(status='deleted')
        @router.get('/v1/social/cautions/{item}/shares')
        def shares(item:str,request:Request):
            with psycopg.connect(self.dsn) as conn:
                owner=actor(conn,request);self.history.rooms.graph_lock(conn);row,value,_=self.row(conn,item,owner,write=True)
                shared,stamp=self.review_state(conn,item,owner,value);grants=[];friends=[]
                for a,b in conn.execute('SELECT account_a,account_b FROM team_friend_pairs WHERE account_a=%s OR account_b=%s',(owner,owner)):
                    target=b if a==owner else a;who=self.history.person(target)
                    if who and linked(conn,owner,target):friends.append(who)
                for target,raw,expiry in conn.execute('SELECT account_id,protected,expires_at FROM team_caution_shares WHERE caution_id=%s ORDER BY account_id',(item,)):
                    saved=self.restore('share',owner,item+':'+target,raw)
                    if datetime.fromisoformat(saved['expiresAt'].replace('Z','+00:00'))!=expiry:fail(503,'Stored caution sharing expiry unavailable')
                    active=bool(shared and saved['consent'] and saved['rightsConfirmed'] and saved['recordRevision']==row[3]
                        and saved['reviewFingerprint']==stamp and expiry>datetime.now(timezone.utc)
                        and self.history.person(target) and linked(conn,owner,target))
                    grants.append(dict(accountId=target,consent=saved['consent'],active=active,expiresAt=expiry))
                return dict(revision=row[3],permissionRevision=row[4],friends=friends,grants=grants,serverNow=datetime.now(timezone.utc))
        @router.put('/v1/social/cautions/{item}/shares/{target}')
        async def share(item:str,target:str,request:Request):
            return await mutate(request,('revision','permissionRevision','consent','expiresInHours','rightsConfirmed'),lambda c,a,d:self.share(c,a,item,target,d))
        @router.delete('/v1/social/cautions/{item}/shares/{target}')
        def revoke(item:str,target:str,request:Request):
            if not ACCOUNT.fullmatch(target):fail(400,'Invalid recipient')
            with psycopg.connect(self.dsn) as conn:return self.revoke(conn,actor(conn,request,True),item,target)
        @router.patch('/v1/social/cautions/{item}/review-request')
        async def review(item:str,request:Request):
            def apply(conn,owner,data):
                self.history.rooms.graph_lock(conn);row,value,_=self.row(conn,item,owner,write=True)
                if type(data['consent'])is not bool:fail(400,'Explicit content review purpose required')
                number(data['revision'])
                if data['consent'] and data['revision']!=row[3]:fail(409,'Caution changed')
                result=self.content.request(conn,'caution',item,owner,self.projection(conn,item,owner),data['consent'])
                recipients={a for a, in conn.execute('SELECT account_id FROM team_caution_shares WHERE caution_id=%s',(item,))}
                conn.execute('DELETE FROM team_caution_shares WHERE caution_id=%s',(item,))
                conn.execute('UPDATE team_cautions SET permission_revision=permission_revision+1 WHERE caution_id=%s',(item,))
                self.notify(conn,item,owner,recipients);return dict(review=result,permissionRevision=row[4]+1)
            return await mutate(request,('revision','consent'),apply)
        @router.post('/v1/social/cautions/{item}/reports',status_code=202)
        async def report(item:str,request:Request):
            def apply(conn,actor_,data):
                self.history.rooms.graph_lock(conn);row,value,_=self.row(conn,item,actor_)
                return self.content.report(conn,'caution',item,row[1],{k:value[k] for k in ('kind','observedAt','place')},actor_,data['reason'])
            return await mutate(request,('reason',),apply)
        return router
