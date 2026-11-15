"""Authenticated half-duplex PCM relay. No audio logging or persistence.

One process/worker only. PostgreSQL session lock also prevents duplicate floors
across accidental workers; cross-worker delivery is deliberately not claimed.
"""
import asyncio,json,logging,os,re,secrets,struct,time,threading
from enum import Enum
from collections import deque
from dataclasses import dataclass,field
from urllib.parse import urlsplit
import psycopg
from fastapi import APIRouter,HTTPException,WebSocket,WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from team_data import close_socket
from private_records import PrivateRecordError

FRAME_BYTES=644
LEASE_SECONDS=15
FRAME_RATE_PER_SECOND=55.0
FRAME_RATE_BURST=25.0
FRAME_RATE_WINDOW_LIMIT=80
RELAY_QUEUE_LIMIT=32
FRAME_INTERVAL_SECONDS=.02
FRAME_SCHEDULER_ALLOWANCE_SECONDS=.002
FORMAT=dict(encoding='pcm_s16le',sampleRate=16000,channels=1,samplesPerFrame=320,frameBytes=FRAME_BYTES,sequence='uint32-le-first0')

logger=logging.getLogger('wegoh.voice')

class VoicePhase(str,Enum):
    AUTH='auth'
    FRAME='frame'
    CONTROL='control'
    SENDER='sender'
    INVALIDATION='invalidation'

class VoiceReason(str,Enum):
    REQUEST_REJECTED='request_rejected'
    AUTHORIZATION_DENIED='authorization_denied'
    AUTHORITY_CHANGED='authority_changed'
    SOURCE_AUTHORITY_DENIED='source_authority_denied'
    CONNECTION_LIMIT='connection_limit'
    NATIVE_DUPLICATE='native_duplicate'
    RATE_WINDOW='rate_window'
    RATE_BURST='rate_burst'
    FRAME_SIZE='frame_size'
    FRAME_WITHOUT_FLOOR='frame_without_floor'
    SEQUENCE_MISMATCH='sequence_mismatch'
    CONTROL_FORMAT='control_format'
    CONTROL_TYPE='control_type'
    CONTROL_SIZE='control_size'
    CONTROL_RATE='control_rate'
    QUEUE_FULL='queue_full'
    SEND_TIMEOUT='send_timeout'
    TRANSPORT_FAILURE='transport_failure'
    DATABASE_FAILURE='database_failure'
    INTEGRITY_FAILURE='integrity_failure'
    CONTEXT_INVALIDATED='context_invalidated'

class VoiceRejection(HTTPException):
    def __init__(self,status,reason,received_seq=None):
        super().__init__(status)
        self.reason=reason
        self.received_seq=received_seq

def record_rejection(peer,phase,error,code,reason=None,status=None):
    sqlstate=None
    if isinstance(error,VoiceRejection):
        reason=reason or error.reason
    if isinstance(error,HTTPException):
        status=status or error.status_code
        reason=reason or (VoiceReason.AUTHORIZATION_DENIED if status in (401,403) else VoiceReason.REQUEST_REJECTED)
    elif isinstance(error,psycopg.Error):
        reason=reason or VoiceReason.DATABASE_FAILURE
        state=error.sqlstate
        sqlstate=state if isinstance(state,str) and re.fullmatch(r'[A-Za-z0-9]{5}',state,flags=re.ASCII) else None
    elif isinstance(error,PrivateRecordError):reason=reason or VoiceReason.INTEGRITY_FAILURE
    elif isinstance(error,asyncio.TimeoutError):reason=reason or VoiceReason.SEND_TIMEOUT
    reason=reason or VoiceReason.TRANSPORT_FAILURE
    logger.warning('voice.connection: stopped phase=%s reason=%s status=%d close_code=%d last_seq=%d received_seq=%s window=%d credit=%.3f sqlstate=%s',
        phase.value,reason.value,status or 503,code,peer.sequence if peer else -1,
        error.received_seq if isinstance(error,VoiceRejection) else None,
        len(peer.frames) if peer else 0,peer.rate_credit if peer else 0,sqlstate)

@dataclass(eq=False)
class Peer:
    socket:object
    actor:str
    room:str
    identity:dict
    queue:asyncio.Queue=field(default_factory=lambda:asyncio.Queue(maxsize=RELAY_QUEUE_LIMIT))
    muted:set=field(default_factory=set)
    floor:object=None
    lease:str|None=None
    until:float=0
    sequence:int=-1
    ended_lease:str|None=None
    rate_credit:float=FRAME_RATE_BURST
    rate_updated:float=field(default_factory=time.monotonic)
    next_delivery:float=0
    frames:deque=field(default_factory=deque)
    closed:bool=False
    epoch:int=0
    invalidated:bool=False
    loop:object=None

class TeamVoice:
    def __init__(self,auth,rooms):
        self.auth,self.rooms,self.dsn=auth,rooms,auth.dsn
        self.enabled=auth.enabled and os.environ.get('WEGOH_VOICE_ENABLED')=='1' and os.environ.get('WEB_CONCURRENCY','1')=='1'
        self.peers=set();self.opening=set();self.native_opening=set();self.active_floors={};self.recent_floors={}
    def authorize(self,socket,room):
        from voice_authorization import authorize_voice
        return authorize_voice(self,socket,room)
    @staticmethod
    def current_peer(peer,fresh):
        if peer.invalidated or fresh['id']!=peer.actor:return False
        if peer.identity.get('voiceTransport') in ('native','iphone'):return fresh.get('voiceTransport')==peer.identity.get('voiceTransport') and fresh.get('voiceStamp')==peer.identity.get('voiceStamp')
        return fresh.get('voiceTransport')=='browser'and fresh.get('role')==peer.identity.get('role') and fresh.get('voiceStamp')==peer.identity.get('voiceStamp')
    def withdraw_trip_context(self, conn, trip, room, account=None):
        self.invalidate_context(room, accounts=None if account is None else {account})
        if getattr(self, "clip_service", None):
            self.clip_service.memory.withdraw(trip, account)

    def on_trip_block(self, conn, trip, room, blocker, target):
        self.invalidate_context(room, accounts={blocker, target})

    def invalidate_context(self, room=None, *, accounts=None, device=None, legacy_only=False):
        groups={}
        for peer in tuple(self.peers):
            if legacy_only and peer.identity.get('voiceTripId') is not None:
                continue
            if (room is None or peer.room==room) and (accounts is None or peer.actor in accounts) and (device is None or peer.identity.get('voiceTransport')=='native' and peer.identity.get('deviceId')==device) and peer.loop is not None:
                groups.setdefault(peer.loop,[]).append(peer)
        for loop,targets in groups.items():
            complete=threading.Event()
            def invalidate(targets=tuple(targets),complete=complete,loop=loop):
                try:
                    for peer in targets:
                        if peer.closed:continue
                        peer.invalidated=True;peer.epoch+=1
                        while not peer.queue.empty():peer.queue.get_nowait()
                        loop.create_task(self.terminate(peer))
                finally:complete.set()
            try:current=asyncio.get_running_loop()
            except RuntimeError:current=None
            if current is loop:invalidate()
            elif loop.is_running():loop.call_soon_threadsafe(invalidate)
            else:
                from native_functional_policy import FunctionalError
                raise FunctionalError(503,'VOICE_INVALIDATION_UNAVAILABLE')
            if not complete.wait(.25):
                from native_functional_policy import FunctionalError
                raise FunctionalError(503,'VOICE_INVALIDATION_UNAVAILABLE')

    def invalidate_native(self, account, device, room=None):
        self.invalidate_context(room, accounts={account}, device=device, legacy_only=room is not None)

    def trip_router(self):
        return self.router(trip_context=True)

    def acquire_floor(self,peer):
        conn=psycopg.connect(self.dsn,autocommit=True)
        try:
            conn.execute("SELECT set_config('idle_session_timeout',%s,false)",(str(LEASE_SECONDS+1)+'s',))
            if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0))',('voice-floor:'+peer.room,)).fetchone()[0]:conn.close();return None
            return conn
        except BaseException:conn.close();raise
    async def put(self,peer,value):
        if peer.closed:return
        try:peer.queue.put_nowait(value)
        except asyncio.QueueFull:await self.terminate(peer,1013,phase=VoicePhase.SENDER,reason=VoiceReason.QUEUE_FULL,status=429)
    @staticmethod
    def purge(peer,lease=None,speaker=None):
        retained=[]
        while not peer.queue.empty():
            value=peer.queue.get_nowait()
            if isinstance(value,tuple)and(lease is None or value[0]==lease)and(speaker is None or value[1]==speaker):continue
            retained.append(value)
        for value in retained:peer.queue.put_nowait(value)
    async def stop(self,peer):
        if peer.floor is None and peer.lease is None:return
        conn=peer.floor;lease=peer.lease;peer.ended_lease=lease;peer.epoch+=1;peer.floor=None;peer.lease=None;peer.until=0;peer.sequence=-1
        if self.active_floors.get(peer.room)is peer:self.active_floors.pop(peer.room,None)
        recent=self.recent_floors.get((peer.room,lease))
        if recent:recent['endedAt']=time.monotonic()
        # Clear only this floor's samples, preserving ready/other control ACKs.
        # Keep the DB floor lock until these end notifications have been queued.
        try:
            for target in tuple(self.peers):
                if target.room==peer.room:
                    self.purge(target,lease=lease);await self.put(target,dict(type='floor-ended',leaseId=lease))
        finally:
            if conn is not None:await run_in_threadpool(conn.close)
    async def terminate(self,peer,code=1008,*,phase=VoicePhase.AUTH,error=None,reason=None,status=None):
        if peer.closed:return
        peer.closed=True;peer.epoch+=1
        if peer.invalidated:
            phase=VoicePhase.INVALIDATION;reason=VoiceReason.CONTEXT_INVALIDATED;status=403
        if code!=1000:record_rejection(peer,phase,error,code,reason,status)
        if peer.floor is not None:await self.stop(peer)
        while not peer.queue.empty():peer.queue.get_nowait()
        try:await asyncio.wait_for(peer.socket.close(code=code),timeout=.25)
        except(WebSocketDisconnect,RuntimeError,OSError,asyncio.TimeoutError):pass
    async def sender(self,peer):
        while not peer.closed:
            value=await peer.queue.get()
            if isinstance(value,tuple):
                lease,speaker,raw=value
                current=self.active_floors.get(peer.room)
                if not current or current.lease!=lease or current.actor!=speaker:continue
                if time.monotonic()>=current.until:await self.stop(current);continue
                # Current identity/membership/consent is checked at delivery, not
                # only on connect or enqueue. No stale frame survives withdrawal.
                native=peer.identity.get('voiceTransport')=='native' and current.identity.get('voiceTransport')=='native'
                parallel=not native and all(x.identity.get('voiceTransport') in ('iphone','native') for x in (peer,current))
                if parallel:
                    from voice_authorization import authorize_delivery_source
                    fresh,source=await asyncio.gather(
                        run_in_threadpool(self.authorize,peer.socket,peer.room),
                        run_in_threadpool(authorize_delivery_source,self,peer,current),
                        return_exceptions=True)
                    if isinstance(fresh,BaseException):raise fresh
                    if isinstance(source,(HTTPException,PrivateRecordError)):
                        await self.terminate(current,phase=VoicePhase.SENDER,error=source,reason=VoiceReason.SOURCE_AUTHORITY_DENIED);continue
                    if isinstance(source,BaseException):raise source
                elif native:
                    from voice_authorization import authorize_native_delivery,VoiceDeliverySourceDenied
                    try:fresh,source=await run_in_threadpool(authorize_native_delivery,self,peer,current)
                    except VoiceDeliverySourceDenied as error:await self.terminate(current,phase=VoicePhase.SENDER,error=error.__cause__,reason=VoiceReason.SOURCE_AUTHORITY_DENIED);continue
                else:
                    fresh=await run_in_threadpool(self.authorize,peer.socket,peer.room)
                if not self.current_peer(peer,fresh):raise VoiceRejection(403,VoiceReason.AUTHORITY_CHANGED)
                if not fresh['voiceCanReceive']:continue
                if speaker in fresh['voiceMuted']:continue
                if not native and not parallel:
                    try:source=await run_in_threadpool(self.authorize,current.socket,current.room)
                    except(HTTPException,PrivateRecordError) as error:await self.terminate(current,phase=VoicePhase.SENDER,error=error,reason=VoiceReason.SOURCE_AUTHORITY_DENIED);continue
                if source is None:continue
                if not self.current_peer(current,source) or not source['voiceCanTransmit'] or source['voiceSuspended']:await self.terminate(current,phase=VoicePhase.SENDER,reason=VoiceReason.SOURCE_AUTHORITY_DENIED,status=403);continue
                # wait_for schedules another coroutine. The final epoch/floor
                # check is INSIDE it immediately before handing bytes to ASGI.
                try:await asyncio.wait_for(self.deliver(peer,current,lease,speaker,raw,current.epoch,peer.epoch),timeout=.25)
                except(asyncio.TimeoutError,OSError) as error:await self.terminate(peer,1013,phase=VoicePhase.SENDER,error=error);return
            else:await asyncio.wait_for(peer.socket.send_json(value),timeout=.25)
    async def deliver(self,peer,source,lease,speaker,raw,source_epoch,target_epoch):
        delay=peer.next_delivery-time.monotonic()
        if delay>0:await asyncio.sleep(delay)
        if(peer.closed or source.closed or peer.invalidated or source.invalidated or peer.epoch!=target_epoch or source.epoch!=source_epoch or self.active_floors.get(peer.room)is not source or source.lease!=lease or source.actor!=speaker or time.monotonic()>=source.until or speaker in peer.muted):return
        # Audio already handed to the transport cannot be recalled. Owned queued
        # audio is discarded on stop/mute; clients discard their own old epoch.
        await peer.socket.send_bytes(raw)
        peer.next_delivery=max(peer.next_delivery+FRAME_INTERVAL_SECONDS,
            time.monotonic()+FRAME_INTERVAL_SECONDS-FRAME_SCHEDULER_ALLOWANCE_SECONDS)
        recent=self.recent_floors.get((peer.room,lease))
        if recent is not None:recent['deliveredTo'].add(peer.actor)
    @staticmethod
    def frame_rate(peer,now):
        while peer.frames and peer.frames[0]<now-1:peer.frames.popleft()
        peer.rate_credit=min(FRAME_RATE_BURST,peer.rate_credit+max(0.0,now-peer.rate_updated)*FRAME_RATE_PER_SECOND)
        peer.rate_updated=max(peer.rate_updated,now)
        if len(peer.frames)>=FRAME_RATE_WINDOW_LIMIT:raise VoiceRejection(429,VoiceReason.RATE_WINDOW)
        if peer.rate_credit<1.0:raise VoiceRejection(429,VoiceReason.RATE_BURST)
        peer.rate_credit-=1.0;peer.frames.append(now)
    async def relay(self,peer,raw):
        now=time.monotonic()
        if len(raw)!=FRAME_BYTES:raise VoiceRejection(400,VoiceReason.FRAME_SIZE)
        self.frame_rate(peer,now)
        # Ordered frames queued before floor-ended must not disconnect the joined
        # member or be reinterpreted as a new lease. Authorization still precedes
        # every relay call; size/rate limits also apply while no floor is owned.
        if not peer.lease or peer.floor is None:
            if peer.ended_lease is not None:return
            raise VoiceRejection(403,VoiceReason.FRAME_WITHOUT_FLOOR)
        if now>=peer.until:await self.stop(peer);return
        seq=struct.unpack_from('<I',raw)[0]
        if seq!=peer.sequence+1:raise VoiceRejection(400,VoiceReason.SEQUENCE_MISMATCH,seq)
        peer.sequence=seq
        self.recent_floors[(peer.room,peer.lease)]['sequence']=seq
        for target in tuple(self.peers):
            if target is not peer and target.room==peer.room and peer.actor not in target.muted:await self.put(target,(peer.lease,peer.actor,raw))
    async def control(self,peer,message):
        if not isinstance(message,dict)or set(message)!={'type'}:raise VoiceRejection(400,VoiceReason.CONTROL_FORMAT)
        # One manual start allows hands-free speech until release/stop or the
        # fixed lease ends; a held pointer/key is never a server requirement.
        if message['type']=='floor-request':
            fresh=await run_in_threadpool(self.authorize,peer.socket,peer.room)
            if not self.current_peer(peer,fresh) or not fresh['voiceCanTransmit'] or peer.lease or fresh['voiceSuspended']:raise VoiceRejection(403,VoiceReason.AUTHORITY_CHANGED)
            current=self.active_floors.get(peer.room)
            if current and time.monotonic()>=current.until:await self.stop(current);current=None
            if current:await self.put(peer,dict(type='floor-busy'));return
            conn=await run_in_threadpool(self.acquire_floor,peer)
            if conn is None:await self.put(peer,dict(type='floor-busy'));return
            if peer.closed:await run_in_threadpool(conn.close);return
            peer.floor=conn;peer.lease=secrets.token_hex(16);peer.until=time.monotonic()+LEASE_SECONDS;peer.sequence=-1;peer.ended_lease=None;self.active_floors[peer.room]=peer
            for key,value in tuple(self.recent_floors.items()):
                if value['endedAt']is not None and time.monotonic()-value['endedAt']>60:self.recent_floors.pop(key,None)
            room_keys=[key for key in self.recent_floors if key[0]==peer.room]
            for key in room_keys[:-19]:self.recent_floors.pop(key,None)
            self.recent_floors[(peer.room,peer.lease)]=dict(leaseId=peer.lease,speakerId=peer.actor,sequence=-1,endedAt=None,deliveredTo=set())
            for target in tuple(self.peers):
                if target.room==peer.room:await self.put(target,dict(type='floor-granted'if target is peer else'floor-started',leaseId=peer.lease,speakerId=peer.actor,leaseSeconds=LEASE_SECONDS))
        elif message['type']=='floor-release':await self.stop(peer)
        elif message['type']=='stop':await self.terminate(peer,1000)
        elif message['type']=='ping':await self.put(peer,dict(type='pong'))
        else:raise VoiceRejection(400,VoiceReason.CONTROL_TYPE)
    def router(self, *, trip_context=False):
        router=APIRouter()
        if not self.auth.enabled:return router
        from voice_controls import controls
        router.include_router(controls(self, trip_context=trip_context))
        if not self.enabled:return router
        async def voice(socket:WebSocket,room:str):
            peer=None;writer=None;ticket=None;native_ticket=None;phase=VoicePhase.AUTH
            try:
                identity=await run_in_threadpool(self.authorize,socket,room)
                room=identity.get('voiceRoomId',room)
                await run_in_threadpool(self.auth.rate,'voice-open:'+identity['id'],limit=20)
                if sum(x.actor==identity['id']for x in self.peers)+sum(x[0]==identity['id']for x in self.opening)>=2 or sum(x.room==room for x in self.peers)+sum(x[1]==room for x in self.opening)>=(40 if trip_context else 10):raise VoiceRejection(429,VoiceReason.CONNECTION_LIMIT)
                if identity.get('voiceTransport')=='native':
                    key=(identity['grantId'],room)
                    if key in self.native_opening or any(x.room==room and x.identity.get('grantId')==identity['grantId']for x in self.peers):raise VoiceRejection(429,VoiceReason.NATIVE_DUPLICATE)
                    # Reserve before accept can yield. Publication to live peers and
                    # release below have no intervening await or unreserved gap.
                    self.native_opening.add(key);native_ticket=key
                ticket=(identity['id'],room,secrets.token_hex(8));self.opening.add(ticket)
                await socket.accept();peer=Peer(socket,identity['id'],room,identity);peer.loop=asyncio.get_running_loop();self.peers.add(peer)
                self.opening.discard(ticket);ticket=None
                if native_ticket:self.native_opening.discard(native_ticket);native_ticket=None
                writer=asyncio.create_task(self.sender(peer))
                current=self.active_floors.get(room)
                floor=dict(leaseId=current.lease,speakerId=current.actor)if current else None
                await self.put(peer,dict(type='ready',format=FORMAT,leaseSeconds=LEASE_SECONDS,automaticTransmit=False,floor=floor))
                controls=deque()
                while not peer.closed:
                    phase=VoicePhase.SENDER
                    try:message=await asyncio.wait_for(socket.receive(),timeout=.25)
                    except asyncio.TimeoutError:message=None
                    if writer.done():await writer;break
                    phase=VoicePhase.AUTH
                    fresh=await run_in_threadpool(self.authorize,socket,room)
                    if not self.current_peer(peer,fresh):raise VoiceRejection(403,VoiceReason.AUTHORITY_CHANGED)
                    if peer.lease and(time.monotonic()>=peer.until or fresh['voiceSuspended']):await self.stop(peer)
                    peer.muted=fresh['voiceMuted']
                    if not message:continue
                    if message['type']=='websocket.disconnect':break
                    if message.get('bytes')is not None:
                        phase=VoicePhase.FRAME
                        if not fresh['voiceCanTransmit']:raise VoiceRejection(403,VoiceReason.AUTHORIZATION_DENIED)
                        await self.relay(peer,message['bytes'])
                    elif message.get('text')is not None:
                        phase=VoicePhase.CONTROL
                        text=message['text']
                        if len(text.encode())>1024:raise VoiceRejection(413,VoiceReason.CONTROL_SIZE)
                        now=time.monotonic()
                        while controls and controls[0]<now-1:controls.popleft()
                        if len(controls)>=10:raise VoiceRejection(429,VoiceReason.CONTROL_RATE)
                        controls.append(now)
                        try:value=json.loads(text)
                        except ValueError:raise VoiceRejection(400,VoiceReason.CONTROL_FORMAT)
                        await self.control(peer,value)
                    else:raise VoiceRejection(400,VoiceReason.CONTROL_FORMAT)
            except(WebSocketDisconnect,HTTPException,PrivateRecordError,RuntimeError,OSError,psycopg.Error,asyncio.TimeoutError) as error:
                if peer:await self.terminate(peer,phase=phase,error=error)
                else:
                    record_rejection(None,phase,error,1008)
                    await close_socket(socket)
            finally:
                if ticket:self.opening.discard(ticket)
                if native_ticket:self.native_opening.discard(native_ticket)
                if peer:
                    await self.stop(peer);self.peers.discard(peer);peer.closed=True
                    if not any(x.room==room for x in self.peers):
                        for key in tuple(self.recent_floors):
                            if key[0]==room:self.recent_floors.pop(key,None)
                if writer:
                    writer.cancel();await asyncio.gather(writer,return_exceptions=True)
                from voice_authorization import close_voice_database
                await run_in_threadpool(close_voice_database, socket)
        if trip_context:
            @router.websocket('/v1/iphone/trips/{trip}/voice')
            @router.websocket('/v1/social/trips/{trip}/voice')
            async def trip_voice(socket: WebSocket, trip: str):
                socket.state.voice_trip = trip
                await voice(socket, trip)
        else:
            router.add_api_websocket_route('/v1/social/rooms/{room}/voice', voice)
        return router
