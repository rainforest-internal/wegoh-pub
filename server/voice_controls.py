"""User-selected live speaker filters and encrypted, audio-free report metadata."""
import secrets,time
import psycopg
from fastapi import APIRouter,HTTPException,Request,Response
from starlette.concurrency import run_in_threadpool
from team_data import changed
from team_trip_context import resolve_trip_context
from team_friends import blocked
from native_access_codec import decode_json, CodecError
from native_principal import is_native_principal

def controls(service, *, trip_context=False):
    router=APIRouter();auth,rooms=service.auth,service.rooms
    base = '/v1/social/' + ('trips' if trip_context else 'rooms') + '/{room}/voice'
    def context(conn, identifier, actor):
        if trip_context:
            return resolve_trip_context(auth, conn, identifier, actor, states=('active',))['roomId']
        return identifier
    async def body(request,fields):
        if request.url.path.startswith('/v1/iphone/'):
            from iphone_sessions import body as iphone_body
            raw = await iphone_body(request, 'application/json', maximum_bytes=1024)
        else:
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>1024:raise HTTPException(413)
        try:value=decode_json(bytes(raw), maximum_bytes=1024)
        except(CodecError,ValueError,UnicodeError):raise HTTPException(400)
        if not isinstance(value,dict)or set(value)!=set(fields):raise HTTPException(400)
        return value
    def client_actor(request, response, *, mutate=False, connection=None):
        response.headers['Cache-Control'] = 'private, no-store'
        if request.url.path.startswith('/v1/iphone/'):
            if not trip_context or request.url.query:
                raise HTTPException(400, 'IPHONE_INVALID_REQUEST')
            return auth.iphone_sessions.authenticate(request, 'trips:manage' if mutate else 'trips:read',
                                                     connection=connection, lock=mutate and connection is not None)
        return auth.browser(request, mutate=mutate, connection=connection)
    def moderator(request,mutate=False):
        actor=auth.browser(request,mutate=mutate)
        if actor['role']!='admin':raise HTTPException(403)
        return actor
    @router.get(base+'/filters')
    def filters(room:str,request:Request,response:Response):
        response.headers['Cache-Control'] = 'private, no-store'
        muted=[]
        with psycopg.connect(auth.dsn)as conn:
            rooms.graph_lock(conn)
            if trip_context and is_native_principal(getattr(request.state, 'device_identity', None)):
                if request.url.query:raise HTTPException(400)
                identity, current, _ = service.clip_service._actor(request, conn, room)
                actor, room = identity['id'], current['roomId']
            else:
                actor=client_actor(request,response,connection=conn)['id']
                room=context(conn,room,actor)
            rooms.access(conn,room,actor,trip_context=trip_context)
            for speaker,raw in conn.execute('SELECT speaker_id,protected FROM team_voice_filters WHERE room_id=%s AND account_id=%s',(room,actor)):
                if rooms.restore('voice-filter:'+actor,room+':'+speaker,raw)['muted'] and not blocked(conn,actor,speaker):muted.append(speaker)
        return dict(mutedSpeakerIds=sorted(muted))
    @router.put(base+'/filters/{speaker}')
    async def filter_speaker(room:str,speaker:str,request:Request,response:Response):
        actor=client_actor(request,response,mutate=True)['id'];value=await body(request,('muted',))
        if type(value['muted'])is not bool or actor==speaker:raise HTTPException(400)
        with psycopg.connect(auth.dsn)as conn:
            rooms.graph_lock(conn);actor=client_actor(request,response,mutate=True,connection=conn)['id']
            room=context(conn,room,actor)
            rooms.access(conn,room,actor,trip_context=trip_context);rooms.access(conn,room,speaker,trip_context=trip_context)
            if blocked(conn,actor,speaker):raise HTTPException(404)
            raw=rooms.protect('voice-filter:'+actor,room+':'+speaker,value)
            conn.execute('INSERT INTO team_voice_filters(room_id,account_id,speaker_id,protected)VALUES(%s,%s,%s,%s)ON CONFLICT(room_id,account_id,speaker_id)DO UPDATE SET protected=excluded.protected',(room,actor,speaker,raw));changed(conn,actor,'rooms')
        for target in tuple(service.peers):
            if target.room==room and target.actor==actor:
                target.epoch+=1
                if value['muted']:target.muted.add(speaker)
                else:target.muted.discard(speaker)
                service.purge(target,speaker=speaker)
        return dict(speakerId=speaker,muted=value['muted'])
    @router.post(base+'/reports',status_code=202)
    async def report(room:str,request:Request,response:Response):
        actor=client_actor(request,response,mutate=True)['id'];value=await body(request,('speakerId','leaseId','reason'))
        await run_in_threadpool(auth.rate,'voice-report:'+actor,limit=20);identifier=secrets.token_hex(16)
        with psycopg.connect(auth.dsn)as conn:
            rooms.graph_lock(conn);actor=client_actor(request,response,mutate=True,connection=conn)['id']
            room=context(conn,room,actor)
            rooms.access(conn,room,actor,trip_context=trip_context)
            recent=service.recent_floors.get((room,value.get('leaseId')))if isinstance(value.get('leaseId'),str)else None
            if recent is None and isinstance(value.get('leaseId'), str) and getattr(service, 'clip_service', None):
                recent=service.clip_service.report_receipt(conn, room, value['leaseId'], actor)
            if not isinstance(value['speakerId'],str)or not isinstance(value['reason'],str)or value['reason']not in('harmful','privacy','rights','other')or not recent or value['leaseId']!=recent['leaseId']or value['speakerId']!=recent['speakerId']or actor==value['speakerId']or recent['sequence']<0 or actor not in recent['deliveredTo'] or(recent['endedAt']is not None and time.monotonic()-recent['endedAt']>60):raise HTTPException(404)
            if blocked(conn,actor,value['speakerId']):raise HTTPException(404)
            raw=rooms.protect('voice-report:'+actor,identifier,dict(value,status='unresolved'))
            conn.execute('INSERT INTO team_voice_reports(report_id,room_id,account_id,speaker_id,protected)VALUES(%s,%s,%s,%s,%s)',(identifier,room,actor,value['speakerId'],raw))
        source=service.active_floors.get(room)
        if source and source.actor==value['speakerId']:await service.stop(source)
        return dict(id=identifier,status='received',audioRetained=False)
    if trip_context:
        phone = '/v1/iphone/trips/{room}/voice'
        router.add_api_route(phone+'/filters', filters, methods=['GET'], include_in_schema=False)
        router.add_api_route(phone+'/filters/{speaker}', filter_speaker, methods=['PUT'], include_in_schema=False)
        router.add_api_route(phone+'/reports', report, methods=['POST'], status_code=202, include_in_schema=False)
        return router
    @router.get('/v1/moderation/voice-reports')
    def pending(request:Request):
        moderator(request);items=[]
        with psycopg.connect(auth.dsn)as conn:
            for identifier,room,reporter,speaker,raw,created in conn.execute('SELECT report_id,room_id,account_id,speaker_id,protected,created_at FROM team_voice_reports WHERE resolved_at IS NULL ORDER BY created_at,report_id LIMIT 100'):
                value=rooms.restore('voice-report:'+reporter,identifier,raw);items.append(dict(id=identifier,roomId=room,reporterId=reporter,speakerId=speaker,reason=value['reason'],createdAt=created,audioRetained=False))
        return dict(items=items)
    @router.post('/v1/moderation/voice-reports/{identifier}/resolve')
    async def resolve(identifier:str,request:Request):
        moderator(request,True);value=await body(request,('decision',))
        if not isinstance(value['decision'],str)or value['decision']not in('restore','retain'):raise HTTPException(400)
        with psycopg.connect(auth.dsn)as conn:
            row=conn.execute('SELECT account_id,protected FROM team_voice_reports WHERE report_id=%s FOR UPDATE',(identifier,)).fetchone()
            if not row:raise HTTPException(404)
            stored=rooms.restore('voice-report:'+row[0],identifier,row[1]);stored['status']=value['decision'];raw=rooms.protect('voice-report:'+row[0],identifier,stored)
            conn.execute('UPDATE team_voice_reports SET protected=%s,resolved_at=CASE WHEN %s THEN now() ELSE NULL END WHERE report_id=%s',(raw,value['decision']=='restore',identifier))
        return dict(status=value['decision'])
    return router
