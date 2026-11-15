"""Real TLS1.3/WSS, generated PCM and isolated temporary PG.
No microphone, live data, or raw audio file. Actual execution is separately recorded.
"""
import asyncio,faulthandler,hashlib,http.client,json,os,secrets,socket,ssl,struct,threading,time,unittest
from pathlib import Path
import psycopg
from fastapi import HTTPException
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed,InvalidStatus
import test_team_auth as auth_fixture
import test_team_friends as friend_fixture
from team_voice import TeamVoice,Peer
from test_native_mtls import OwnedTLSConnection

HERE=Path(__file__).resolve().parent
ROOT=auth_fixture.ROOT
class VoiceFixture(friend_fixture.FriendTests):
    websocket_max_size=2048
    @classmethod
    def setUpClass(cls):
        os.environ['WEGOH_VOICE_ENABLED']='1';super().setUpClass()
        import importlib
        wrapper=importlib.import_module('api_application');assert wrapper.app is cls.module.app
        cls.voice=cls.module.TEAM_VOICE
        cls.drain_condition=threading.Condition();cls.authorizing=0;cls.active_websockets=0
        authorize=cls.voice.authorize
        def tracked_authorize(*args,**kwargs):
            with cls.drain_condition:cls.authorizing+=1
            try:return authorize(*args,**kwargs)
            finally:
                with cls.drain_condition:cls.authorizing-=1;cls.drain_condition.notify_all()
        cls.voice.authorize=tracked_authorize
    @classmethod
    def tls_application(cls,application,accounts):
        async def drained(scope,receive,send):
            if scope['type']!='websocket':return await application(scope,receive,send)
            with cls.drain_condition:cls.active_websockets+=1
            try:await application(scope,receive,send)
            finally:
                with cls.drain_condition:cls.active_websockets-=1;cls.drain_condition.notify_all()
        return drained
    @classmethod
    def drain_voice(cls):
        # Only isolated test reset waits here. No application permission is cached.
        with cls.drain_condition:
            if not cls.drain_condition.wait_for(lambda:cls.active_websockets==0 and cls.authorizing==0,timeout=3):raise RuntimeError('Previous synthetic WSS authorization did not drain before DB reset')

class VoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Capture the real waiting stack if this normally short suite stalls.
        faulthandler.dump_traceback_later(45,repeat=False)
        cls.directory=ROOT/'.local'/('voice-fixture-'+secrets.token_hex(8));cls.directory.mkdir(mode=0o700,parents=True);cls.config=cls.directory/'config.json';cls.errors=[];cls.old_voice=os.environ.get('WEGOH_VOICE_ENABLED')
        def serve():
            try:friend_fixture.serve_fixture(cls.config,fixture_class=VoiceFixture)
            except BaseException as error:cls.errors.append(error)
        cls.thread=threading.Thread(target=serve,daemon=True);cls.thread.start();end=time.monotonic()+15
        while not cls.config.exists()and not cls.errors and time.monotonic()<end:time.sleep(.02)
        if cls.errors:raise cls.errors[0]
        if not cls.config.exists():raise RuntimeError('Owned TLS voice fixture did not start')
        cls.value=json.loads(cls.config.read_text());cls.ssl=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);cls.ssl.check_hostname=False;cls.ssl.verify_mode=ssl.CERT_NONE;cls.ssl.minimum_version=ssl.TLSVersion.TLSv1_3
    @classmethod
    def tearDownClass(cls):
        faulthandler.cancel_dump_traceback_later()
        cls.config.with_suffix('.stop').touch();cls.thread.join(10)
        if cls.old_voice is None:os.environ.pop('WEGOH_VOICE_ENABLED',None)
        else:os.environ['WEGOH_VOICE_ENABLED']=cls.old_voice
        if cls.thread.is_alive():raise RuntimeError('Owned fixture cleanup did not complete')
    def setUp(self):
        VoiceFixture.drain_voice()
        self.api=VoiceFixture(methodName='test_10_capabilities_browser_only_strict_inputs');self.api.connection_factory=lambda host,port,timeout:http.client.HTTPSConnection('127.0.0.1',self.value['tlsPort'],timeout=timeout,context=self.ssl);self.api.setUp();self.a=self.api.login();self.b=self.api.login('bob')
        code,_,room=self.api.call('/v1/social/rooms',dict(name='Synthetic voice room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=self.a);self.assertEqual(code,201,room);self.room=room['id'];self.base='/v1/social/rooms/'+self.room
        choices=self.choices(True);self.assertEqual(self.api.call(self.base+'/consents',dict(consents=choices),'PATCH',session=self.a)[0],200)
        self.assertEqual(self.api.call('/v1/social/rooms/join',dict(code=room['code'],consents=choices),'POST',session=self.b,who='bob')[0],200)
    @staticmethod
    def choices(voice):return{key:voice if key=='voice'else False for key in('status','location','visits','music','voice','control')}
    def ws(self,session,who='alice',**kw):
        raw=socket.create_connection(('127.0.0.1',self.value['tlsPort']),timeout=3)
        result=connect('wss://web.wegoh.invalid'+kw.get('path',self.base+'/voice')+kw.get('query',''),sock=raw,ssl=self.ssl,origin=kw.get('origin',auth_fixture.WEB),create_connection=OwnedTLSConnection,additional_headers={'Cf-Access-Jwt-Assertion':self.api.assertion(who),'Cookie':session['cookie']},open_timeout=3,close_timeout=1)
        self.assertEqual(result.socket.version(),'TLSv1.3');return result
    def json(self,socket,kind):
        value=json.loads(socket.recv(timeout=2));self.assertEqual(value['type'],kind,value);return value
    @staticmethod
    def frame(seq):return struct.pack('<I',seq)+b'\x01\x00'*320
    def start(self,a,b):
        self.json(a,'ready');self.json(b,'ready');a.send(json.dumps(dict(type='floor-request')));lease=self.json(a,'floor-granted');self.json(b,'floor-started');return lease
    def test_01_two_actual_tls_wss_directions_floor_exclusion_and_stop(self):
        with self.ws(self.a)as a,self.ws(self.b,'bob')as b:
            self.start(a,b)
            for seq in range(3):
                frame=self.frame(seq);a.send(frame);self.assertEqual(hashlib.sha256(b.recv(timeout=2)).digest(),hashlib.sha256(frame).digest())
            b.send(json.dumps(dict(type='floor-request')));self.json(b,'floor-busy');a.send(json.dumps(dict(type='floor-release')));self.json(a,'floor-ended');self.json(b,'floor-ended')
            b.send(json.dumps(dict(type='floor-request')));self.json(b,'floor-granted');self.json(a,'floor-started');b.send(self.frame(0));self.assertEqual(hashlib.sha256(a.recv(timeout=2)).hexdigest(),hashlib.sha256(self.frame(0)).hexdigest())
    def test_02_current_consent_origin_query_csrf_and_actor_boundary(self):
        self.api.call(self.base+'/consents',dict(consents=self.choices(False)),'PATCH',session=self.b,who='bob')
        with self.assertRaises(InvalidStatus):self.ws(self.b,'bob')
        with self.assertRaises(InvalidStatus):self.ws(self.a,origin='https://different.invalid')
        with self.assertRaises(InvalidStatus):self.ws(self.a,query='?token=not-a-credential')
        self.assertEqual(self.api.call(self.base+'/voice/filters/'+self.b['user']['id'],dict(muted=True),'PUT',session=self.a,csrf=False)[0],403)
        self.assertEqual(self.api.native(self.base+'/voice/filters')[0],404)
        self.assertTrue(self.api.call('/v1/auth/session',session=self.a)[2]['capabilities']['roomVoice'])
        schema=self.api.call('/openapi.json',session=self.a)[2];self.assertEqual(schema['x-wegoh-voice']['pcm']['frameBytes'],644)
        self.assertEqual(schema['paths']['/v1/social/rooms/{room}/voice/filters/{speaker}']['put']['requestBody']['content']['application/json']['schema']['properties']['muted']['type'],'boolean')
        with self.ws(self.a,path='/v1/events')as events:
            self.json(events,'snapshot');self.assertTrue(events.ping().wait(1));events.send('{}')
            with self.assertRaises(ConnectionClosed):events.recv(timeout=2)
        with self.ws(self.a)as a:
            self.json(a,'ready');VoiceFixture.write_members([r for r in VoiceFixture.members_rows if r['email']!='alice@example.invalid'])
            with self.assertRaises(ConnectionClosed):a.recv(timeout=2)
    def test_03_frame_size_and_sequence_fail_closed(self):
        # Normative budgets: natural jitter, instantaneous burst, rolling average.
        jitter=Peer(None,'synthetic','synthetic',{});jitter.rate_updated=0
        for i in range(7):TeamVoice.frame_rate(jitter,i*.016)
        burst=Peer(None,'synthetic','synthetic',{});burst.rate_updated=0
        for _ in range(25):TeamVoice.frame_rate(burst,0)
        with self.assertRaises(HTTPException)as exceeded:TeamVoice.frame_rate(burst,0)
        self.assertEqual(exceeded.exception.status_code,429)
        steady=Peer(None,'synthetic','synthetic',{});steady.rate_updated=0
        with self.assertRaises(HTTPException)as exceeded:
            for i in range(360):TeamVoice.frame_rate(steady,i/60)
        self.assertEqual(exceeded.exception.status_code,429)
        with self.ws(self.a)as a:
            self.json(a,'ready');a.send(self.frame(0))
            with self.assertRaises(ConnectionClosed):a.recv(timeout=2)
        for raw in(self.frame(1),self.frame(0)+b'x',b'x'*2049):
            with self.ws(self.a)as a:
                self.json(a,'ready');a.send(json.dumps(dict(type='floor-request')));self.json(a,'floor-granted');a.send(raw)
                with self.assertRaises(ConnectionClosed):a.recv(timeout=2)
    def test_04_persistent_receiver_filter_reconnect_and_unmute(self):
        with self.ws(self.a)as a,self.ws(self.b,'bob')as b:
            self.start(a,b);path=self.base+'/voice/filters/'+self.a['user']['id'];self.assertEqual(self.api.call(path,dict(muted=True),'PUT',session=self.b,who='bob')[0],200)
            a.send(self.frame(0))
            with self.assertRaises(TimeoutError):b.recv(timeout=.3)
            self.assertEqual(self.api.call(self.base+'/voice/filters',session=self.b,who='bob')[2]['mutedSpeakerIds'],[self.a['user']['id']])
            self.assertEqual(self.api.call(path,dict(muted=False),'PUT',session=self.b,who='bob')[0],200);a.send(self.frame(1));self.assertEqual(hashlib.sha256(b.recv(timeout=2)).hexdigest(),hashlib.sha256(self.frame(1)).hexdigest())
    def test_05_withdraw_receiver_and_sender_without_clearing_others_floor(self):
        with self.ws(self.a)as a,self.ws(self.b,'bob')as b:
            self.start(a,b);self.api.call(self.base+'/consents',dict(consents=self.choices(False)),'PATCH',session=self.b,who='bob')
            with self.assertRaises(ConnectionClosed):b.recv(timeout=2)
            a.send(self.frame(0));a.send(json.dumps(dict(type='ping')));self.json(a,'pong')
            self.api.call(self.base+'/consents',dict(consents=self.choices(False)),'PATCH',session=self.a)
            with self.assertRaises(ConnectionClosed):a.recv(timeout=2)
    def test_06_report_metadata_stops_sender_and_requires_operator_resolution(self):
        with self.ws(self.a)as a,self.ws(self.b,'bob')as b:
            lease=self.start(a,b);a.send(self.frame(0));self.assertIsInstance(b.recv(timeout=2),bytes)
            code,_,report=self.api.call(self.base+'/voice/reports',dict(speakerId=self.a['user']['id'],leaseId=lease['leaseId'],reason='privacy'),'POST',session=self.b,who='bob');self.assertEqual(code,202,report);self.assertFalse(report['audioRetained']);self.json(a,'floor-ended');self.json(b,'floor-ended')
            a.send(json.dumps(dict(type='floor-request')))
            with self.assertRaises(ConnectionClosed):a.recv(timeout=2)
            self.assertEqual(self.api.call('/v1/moderation/voice-reports',session=self.b,who='bob')[0],403)
            queue=self.api.call('/v1/moderation/voice-reports',session=self.a)[2]['items'];self.assertEqual(queue[0]['reason'],'privacy');self.assertFalse(queue[0]['audioRetained'])
            self.assertEqual(self.api.call('/v1/moderation/voice-reports/'+report['id']+'/resolve',dict(decision='restore'),'POST',session=self.a)[0],200)
        with psycopg.connect(self.api.dsn)as conn:
            raw=bytes(conn.execute('SELECT protected FROM team_voice_reports').fetchone()[0]);self.assertNotIn(b'privacy',raw)
            columns=[x[0]for x in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name='team_voice_reports'")];self.assertEqual(set(columns),{'report_id','room_id','account_id','speaker_id','protected','created_at','resolved_at'})
        with self.ws(self.a)as a:self.assertFalse(self.json(a,'ready')['automaticTransmit'])
        VoiceFixture.voice.enabled=False
        try:
            view=self.api.call(self.base,session=self.a)[2];self.assertTrue(view['consents']['voice']);self.assertNotIn('voice',view['availableConsentKeys'])
            choices=self.choices(True);choices['status']=True;self.assertEqual(self.api.call(self.base+'/consents',dict(consents=choices),'PATCH',session=self.a)[0],200)
            with self.assertRaises(InvalidStatus):self.ws(self.a)
        finally:VoiceFixture.voice.enabled=True
    def test_07_room_expiry_and_current_membership_close_without_audio_storage(self):
        with self.ws(self.a)as a,self.ws(self.b,'bob')as b:
            self.start(a,b)
            self.assertEqual(self.api.call('/v1/social/blocks',dict(targetId=self.b['user']['id']),'POST',session=self.a)[0],201)
            with self.assertRaises(ConnectionClosed):b.recv(timeout=2)
            # Owner still has an active floor; a departed receiver cannot clear it.
            a.send(json.dumps(dict(type='ping')));self.json(a,'pong')
            with psycopg.connect(self.api.dsn)as conn:conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 second' WHERE room_id=%s",(self.room,))
            with self.assertRaises(ConnectionClosed):a.recv(timeout=2)
        self.assertEqual(len(list(VoiceFixture.state.glob('*.pcm'))),0)
    def test_08_actual_floor_deadline_and_slow_receiver_bounded_close(self):
        with self.ws(self.a)as a,self.ws(self.b,'bob')as b:
            lease=self.start(a,b);self.assertEqual(lease['leaseSeconds'],15);time.sleep(15.2);self.json(a,'floor-ended');self.json(b,'floor-ended')
            # Only the previous owner may discard already-queued late PCM.
            a.send(self.frame(0));a.send(json.dumps(dict(type='ping')));self.json(a,'pong')
            with self.assertRaises(TimeoutError):b.recv(timeout=.1)
            b.send(json.dumps(dict(type='floor-request')));self.json(b,'floor-granted');self.json(a,'floor-started')
            peer=next(x for x in VoiceFixture.voice.peers if x.actor==self.a['user']['id'])
            # Hold the scheduled delivery before its final guard. Release the
            # old floor, then let it run: only floor-ended may arrive, never PCM.
            service=VoiceFixture.voice;entered=threading.Event();release=threading.Event();deliver=service.deliver
            async def held(*args):
                entered.set()
                while not release.is_set():await asyncio.sleep(.001)
                return await deliver(*args)
            service.deliver=held
            try:
                b.send(self.frame(0));self.assertTrue(entered.wait(1));b.send(json.dumps(dict(type='floor-release')));self.json(b,'floor-ended');release.set();self.json(a,'floor-ended')
            finally:release.set();service.deliver=deliver
            b.send(json.dumps(dict(type='floor-request')));self.json(b,'floor-granted');self.json(a,'floor-started')
            original=peer.socket.send_bytes
            async def delayed(raw):await asyncio.sleep(.6);await original(raw)
            peer.socket.send_bytes=delayed;b.send(self.frame(0))
            with self.assertRaises(ConnectionClosed)as closed:a.recv(timeout=2)
            self.assertEqual(closed.exception.rcvd.code,1013)
            self.assertEqual(peer.queue.maxsize,32)
            # Actual WSS still drives the failure; only ASGI close write-drain is
            # deliberately held. Cleanup must finish at its own .25s bound.
            source=next(x for x in VoiceFixture.voice.peers if x.actor==self.b['user']['id']);original_close=source.socket.close;close_finished=threading.Event()
            async def slow_close(*args,**kwargs):
                try:await asyncio.sleep(.6);await original_close(*args,**kwargs)
                finally:close_finished.set()
            source.socket.close=slow_close;started=time.monotonic()
            try:
                b.send(self.frame(2));self.assertTrue(close_finished.wait(1));self.assertLess(time.monotonic()-started,.55);self.assertTrue(source.closed);self.assertIsNone(source.floor)
            finally:source.socket.close=original_close


if __name__=='__main__':unittest.main(verbosity=2)
