"""Native Voice first vertical: real local WS + synthetic trusted-edge/private PG, not TLS/OEM."""
import json,os,socket,struct,time,unittest
import hashlib,psycopg
from websockets.sync.client import connect
from websockets.exceptions import InvalidStatus,ConnectionClosed
import test_team_auth as auth_fixture
from native_functional_defaults import account_purposes
import test_native_functional_business as current_fixture

class NativeVoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous=os.environ.get('WEGOH_VOICE_ENABLED');os.environ['WEGOH_VOICE_ENABLED']='1'
        auth_fixture.TeamTests.setUpClass();__import__('api_application')
    @classmethod
    def tearDownClass(cls):
        auth_fixture.TeamTests.tearDownClass()
        if cls.previous is None:os.environ.pop('WEGOH_VOICE_ENABLED',None)
        else:os.environ['WEGOH_VOICE_ENABLED']=cls.previous
    def setUp(self):
        self.factory=current_fixture.FunctionalBusinessTests('test_native_friend_request_respond_scope_withdrawal_and_original_authority')
        self.factory.setUp();self.h=self.factory.h
    def expect(self,result,code,label):
        print('QA_VOICE_HTTP',label,result[0],flush=True)
        self.assertEqual(result[0],code,label)
        return result[2]
    def permissions(self,owner,credential,room,receive=False,transmit=False,who='alice'):
        path='/v1/devices/'+credential['deviceId']+'/rooms/'+room+'/voice-permissions'
        value=self.expect(self.h.call(path,session=owner,who=who),200,'own room voice default/read')
        body={k:v for k,v in value.items()if k not in('deviceId','roomId','expiresAt')}
        body['permissions']=dict(receiveVoice=receive,transmitVoice=transmit)
        return self.expect(self.h.call(path,body,'PUT',session=owner,who=who),200,'explicit per-direction phone approval')
    def join(self,room,owner,who):
        flags={key:False for key in ('status','location','visits','music','voice','control')}
        return self.expect(self.h.call('/v1/social/rooms/join',dict(code=room['code'],consents=flags),'POST',session=owner,who=who),200,'explicit independent account membership')
    def stream(self,credential,room,snapshot):
        raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=3)
        cert=self.factory.certificates[credential['grantId']]
        headers={'Authorization':'Bearer '+credential['accessToken'],'cf-cert-sha256':cert,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false','X-WegoH-Functional-Revision':str(snapshot['functionalRevision']),'X-WegoH-Room-Voice-Revision':str(snapshot['revision'])}
        try:return connect('ws://api.wegoh.invalid/v1/social/rooms/'+room+'/voice',sock=raw,additional_headers=headers,origin=None,open_timeout=3,close_timeout=1)
        except BaseException:raw.close();raise
    def control(self,stream,kind):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            value=stream.recv(timeout=max(.01,deadline-time.monotonic()))
            if isinstance(value,str):
                data=json.loads(value)
                if data['type']==kind:return data
        self.fail('Expected control '+kind)
    def test_actual_ws_default_denial_transmit_only_receive_only_without_rooms_scope(self):
        owner=self.h.login();other=self.h.login('bob');third=self.h.login('eve')
        sender=self.factory.connect(owner);receiver=self.factory.connect(other,'bob');sender2=self.factory.connect(third,'eve')
        base=self.factory.state()
        created=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic directional voice',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'synthetic room');room=created['id']
        # Existing public room code + explicit choices; no invented member rows.
        flags={key:False for key in ('status','location','visits','music','voice','control')}
        self.expect(self.h.call('/v1/social/rooms/join',dict(code=created['code'],consents=flags),'POST',session=other,who='bob'),200,'explicit invited membership')
        self.join(created,third,'eve')
        self.factory.approve(owner,sender,['room-voice:transmit'])
        self.factory.approve(other,receiver,['room-voice:receive'],who='bob')
        self.factory.approve(third,sender2,['room-voice:transmit'],who='eve')
        native_path='/v1/native/rooms/'+room+'/voice-permissions'
        false=self.expect(self.factory.native(sender,native_path),200,'transmit-only current purpose own snapshot')
        self.assertEqual(false['permissions'],dict(receiveVoice=False,transmitVoice=False))
        # Use a valid nonzero CAS stamp while no saved direction is approved.
        false=self.permissions(owner,sender,room)
        with self.assertRaises(InvalidStatus)as denied:self.stream(sender,room,false)
        print('QA_VOICE_WS defaultfalse',denied.exception.response.status_code,flush=True)
        self.assertEqual(denied.exception.response.status_code,403)
        tx=self.permissions(owner,sender,room,transmit=True)
        rx=self.permissions(other,receiver,room,receive=True,who='bob')
        tx2=self.permissions(third,sender2,room,transmit=True,who='eve')
        self.assertEqual(tx['permissions'],dict(receiveVoice=False,transmitVoice=True))
        self.assertEqual(rx['permissions'],dict(receiveVoice=True,transmitVoice=False))
        self.assertEqual(self.expect(self.factory.native(sender,'/v1/device/functional-permissions'),200,'minimum transmit scope')['approvedPurposes'],
                         sorted(account_purposes(['device-commands:receive','room-voice:transmit'])))
        peers=[]
        try:
            a=self.stream(sender,room,tx);peers.append(a);self.control(a,'ready')
            b=self.stream(receiver,room,rx);peers.append(b);self.control(b,'ready')
            c=self.stream(sender2,room,tx2);peers.append(c);self.control(c,'ready')
            a.send(json.dumps(dict(type='floor-request')));self.control(a,'floor-granted');self.control(b,'floor-started');self.control(c,'floor-started')
            frame=struct.pack('<I',0)+b'\x00'*640;a.send(frame)
            self.assertEqual(b.recv(timeout=2),frame,'receive-only actual PCM')
            with self.assertRaises(TimeoutError):c.recv(timeout=.35)
            # A receiver cannot acquire a floor or send; failure must not stop A's floor.
            b.send(json.dumps(dict(type='floor-request')))
            with self.assertRaises(ConnectionClosed):b.recv(timeout=2)
            a.send(json.dumps(dict(type='ping')));self.control(a,'pong')
            a.send(json.dumps(dict(type='floor-release')));self.control(a,'floor-ended');self.control(c,'floor-ended')
            c.send(json.dumps(dict(type='floor-request')));self.control(c,'floor-granted');self.control(a,'floor-started')
            c.send(frame)
            with self.assertRaises(TimeoutError):a.recv(timeout=.35)
            print('QA_VOICE_WS tx-only101/rx-only101/own-directions-positive/opposite-PCM0',flush=True)
        finally:
            for peer in peers:peer.close()
            deadline=time.monotonic()+2
            while self.h.module.TEAM_VOICE.peers and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(self.factory.state(),base,'base credential/grant/certificate authority unchanged')

    def test_native_opening_reservation_blocks_same_grant_and_cleans_failure_cancel(self):
        import asyncio
        from starlette.websockets import WebSocket
        owner=self.h.login();other_owner=self.h.login('bob');first=self.factory.connect(owner);other=self.factory.connect(other_owner,'bob')
        created=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic pending Voice admission',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'reservation room');room=created['id']
        self.join(created,other_owner,'bob')
        self.factory.approve(owner,first,['room-voice:receive']);self.factory.approve(other_owner,other,['room-voice:receive'],'bob')
        a=self.permissions(owner,first,room,receive=True);b=self.permissions(other_owner,other,room,receive=True,who='bob')
        base=self.factory.state();voice=self.h.module.TEAM_VOICE
        endpoint=next(route.endpoint for route in voice.router().routes if getattr(route,'path',None)=='/v1/social/rooms/{room}/voice')
        async def exercise():
            def pending(credential,snapshot,*,hold=False,fail_accept=False):
                incoming=asyncio.Queue();incoming.put_nowait(dict(type='websocket.connect'))
                sent=[];at_accept=asyncio.Event();release=asyncio.Event();ready=asyncio.Event()
                async def receive():return await incoming.get()
                async def send(message):
                    if message['type']=='websocket.accept':
                        at_accept.set()
                        if hold:await release.wait()
                        if fail_accept:raise OSError('Synthetic accept failure')
                    sent.append(message)
                    if message['type']=='websocket.send'and json.loads(message['text']).get('type')=='ready':ready.set()
                headers={'host':'api.wegoh.invalid','authorization':'Bearer '+credential['accessToken'],'cf-cert-sha256':self.factory.certificates[credential['grantId']],'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false','x-wegoh-functional-revision':str(snapshot['functionalRevision']),'x-wegoh-room-voice-revision':str(snapshot['revision'])}
                scope=dict(type='websocket',asgi=dict(version='3.0'),scheme='ws',path='/v1/social/rooms/'+room+'/voice',raw_path=b'',query_string=b'',headers=[(k.encode(),v.encode())for k,v in headers.items()],client=('127.0.0.1',1234),server=('api.wegoh.invalid',80),subprotocols=[])
                return dict(socket=WebSocket(scope,receive,send),incoming=incoming,sent=sent,at=at_accept,release=release,ready=ready)
            async def start(value):return await endpoint(value['socket'],room)
            tasks=[]
            async def stopped(value,task):
                value['incoming'].put_nowait(dict(type='websocket.disconnect',code=1000))
                await asyncio.wait_for(task,3)
            try:
                original=pending(first,a,hold=True);task=asyncio.create_task(start(original));tasks.append(task)
                await asyncio.wait_for(original['at'].wait(),3)
                self.assertEqual(voice.native_opening,{(first['grantId'],room)})
                duplicate=pending(first,a);await asyncio.wait_for(start(duplicate),3)
                self.assertFalse(any(x['type']=='websocket.accept'for x in duplicate['sent']))
                self.assertTrue(any(x['type']=='websocket.close'for x in duplicate['sent']))
                distinct=pending(other,b);second=asyncio.create_task(start(distinct));tasks.append(second)
                await asyncio.wait_for(distinct['ready'].wait(),3)
                original['release'].set();await asyncio.wait_for(original['ready'].wait(),3)
                self.assertFalse(voice.native_opening)
                self.assertEqual(sum(x.room==room and x.identity.get('grantId')==first['grantId']for x in voice.peers),1)
                await stopped(distinct,second);await stopped(original,task)
                self.assertFalse(voice.peers);self.assertFalse(voice.opening)
                failed=pending(first,a,fail_accept=True);await asyncio.wait_for(start(failed),3)
                self.assertFalse(voice.native_opening);self.assertFalse(voice.opening);self.assertFalse(voice.peers)
                cancelled=pending(first,a,hold=True);task=asyncio.create_task(start(cancelled));tasks.append(task)
                await asyncio.wait_for(cancelled['at'].wait(),3);task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                self.assertFalse(voice.native_opening);self.assertFalse(voice.opening);self.assertFalse(voice.peers)
                reopened=pending(first,a);task=asyncio.create_task(start(reopened));tasks.append(task)
                await asyncio.wait_for(reopened['ready'].wait(),3);await stopped(reopened,task)
                self.assertFalse(voice.native_opening);self.assertFalse(voice.opening);self.assertFalse(voice.peers)
            finally:
                for task in tasks:
                    if not task.done():task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
        asyncio.run(exercise());self.assertEqual(self.factory.state(),base)
        print('QA_VOICE_OPENING pre101samegrant-deny/distinctgrant-ready/acceptfailure-cancel-clean/reopen-ready',flush=True)

    def test_directional_global_withdrawal_reapproval_preserves_other_direction_and_device(self):
        owner=self.h.login();other_owner=self.h.login('bob');a=self.factory.connect(owner);b=self.factory.connect(other_owner,'bob')
        base=self.factory.state()
        created=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic voice revoke',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'revoke room');room=created['id']
        self.join(created,other_owner,'bob')
        both=['room-voice:receive','room-voice:transmit']
        self.factory.approve(owner,a,both);self.factory.approve(other_owner,b,both,'bob')
        first=self.permissions(owner,a,room,receive=True,transmit=True)
        untouched=self.permissions(other_owner,b,room,receive=True,transmit=True,who='bob')
        import psycopg
        with psycopg.connect(self.h.dsn)as conn:
            other_cipher=bytes(conn.execute('SELECT protected FROM native_room_voice_authorizations WHERE grant_id=%s AND room_id=%s',(b['grantId'],room)).fetchone()[0])
        path='/v1/native/rooms/'+room+'/voice-permissions'
        peer=self.stream(a,room,first);self.control(peer,'ready')
        flags={key:False for key in ('status','location','visits','music','voice','control')}
        self.expect(self.h.call('/v1/social/rooms/'+room+'/consents',dict(consents=flags),'PATCH',session=owner),200,'Browser false is independent')
        peer.send(json.dumps(dict(type='ping')));self.control(peer,'pong')
        self.factory.approve(owner,a,['room-voice:transmit'])
        with self.assertRaises(ConnectionClosed):peer.recv(timeout=2)
        now=self.expect(self.factory.native(a,path),200,'receive withdrawn; transmit preserved')
        self.assertEqual(now['permissions'],dict(receiveVoice=False,transmitVoice=True))
        self.factory.approve(owner,a,both)
        now=self.expect(self.factory.native(a,path),200,'global reapproval does not revive receive')
        self.assertFalse(now['permissions']['receiveVoice']);self.assertTrue(now['permissions']['transmitVoice'])
        with self.stream(a,room,now)as reopened:
            self.control(reopened,'ready');reopened.send(json.dumps(dict(type='floor-request')));self.control(reopened,'floor-granted')
        self.permissions(owner,a,room,receive=True,transmit=True)
        self.factory.approve(owner,a,['room-voice:receive'])
        now=self.expect(self.factory.native(a,path),200,'transmit withdrawn; receive preserved')
        self.assertEqual(now['permissions'],dict(receiveVoice=True,transmitVoice=False))
        self.factory.approve(owner,a,both)
        now=self.expect(self.factory.native(a,path),200,'transmit remains false after reapproval')
        self.assertFalse(now['permissions']['transmitVoice'])
        with psycopg.connect(self.h.dsn)as conn:
            self.assertEqual(bytes(conn.execute('SELECT protected FROM native_room_voice_authorizations WHERE grant_id=%s AND room_id=%s',(b['grantId'],room)).fetchone()[0]),other_cipher)
        self.assertEqual(self.expect(self.factory.native(b,path),200,'other account grant unchanged')['permissions'],untouched['permissions'])
        self.assertEqual(self.factory.state(),base)

    def test_actual_tls13_peer_der_binding_header_overwrite_and_directional_audio(self):
        import datetime,hashlib,http.client,ssl,threading,secrets
        import uvicorn,test_enrollment
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
        from test_native_mtls import EdgeHTTP,EdgeWSS,OwnedTLSConnection
        from websockets.exceptions import InvalidMessage
        original_issuer=test_enrollment.SyntheticIssuer;original_csr=test_enrollment.make_csr
        captured=[];keys=[]
        class CapturedIssuer(original_issuer):
            def __init__(self):
                super().__init__();self.name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic Voice CA '+secrets.token_hex(8))]);captured.append(self)
            def response(self,csr):
                value=super().response(csr);self.certificate=value['certificate'];return value
        def captured_csr():
            key,csr=original_csr();keys.append(key);return key,csr
        owner=self.h.login();other_owner=self.h.login('bob')
        test_enrollment.SyntheticIssuer=CapturedIssuer;test_enrollment.make_csr=captured_csr
        try:
            a=self.factory.connect(owner);b=self.factory.connect(other_owner,'bob')
        finally:
            test_enrollment.SyntheticIssuer=original_issuer;test_enrollment.make_csr=original_csr
        self.assertEqual(len(captured),2);self.assertEqual(len(keys),2)
        base=self.factory.state()
        now=datetime.datetime.now(datetime.timezone.utc);directory=auth_fixture.TeamTests.state/('native-voice-tls-'+secrets.token_hex(8));directory.mkdir(mode=0o700)
        def write(name,raw):
            path=directory/name
            with path.open('xb')as stream:stream.write(raw)
            path.chmod(0o600);return path
        roots=[];client_files=[]
        for index,(issuer,key)in enumerate(zip(captured,keys)):
            ca=(x509.CertificateBuilder().subject_name(issuer.name).issuer_name(issuer.name).public_key(issuer.key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=False,data_encipherment=False,key_agreement=False,key_cert_sign=True,crl_sign=True,encipher_only=False,decipher_only=False),critical=True).sign(issuer.key,hashes.SHA256()))
            roots.append(ca.public_bytes(serialization.Encoding.PEM))
            cert=write('client'+str(index)+'.pem',issuer.certificate.encode());private=write('client'+str(index)+'.key',key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));client_files.append((cert,private))
            actual=x509.load_pem_x509_certificate(issuer.certificate.encode()).fingerprint(hashes.SHA256()).hex()
            self.assertEqual(actual,self.factory.certificates[[a,b][index]['grantId']],'public1 issued CSR certificate is the actual mTLS peer')
        ca_file=write('ca.pem',b''.join(roots))
        server_key=rsa.generate_private_key(public_exponent=65537,key_size=2048);subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'api.wegoh.invalid')])
        server_cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(captured[0].name).public_key(server_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).add_extension(x509.SubjectAlternativeName([x509.DNSName('api.wegoh.invalid'),x509.IPAddress(__import__('ipaddress').ip_address('127.0.0.1'))]),critical=False).sign(captured[0].key,hashes.SHA256()))
        server_pem=write('server.pem',server_cert.public_bytes(serialization.Encoding.PEM));server_private=write('server.key',server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        contexts=[]
        for cert,key in client_files:
            ctx=ssl.create_default_context(cafile=str(ca_file));ctx.minimum_version=ssl.TLSVersion.TLSv1_3;ctx.load_cert_chain(str(cert),str(key));contexts.append(ctx)
        port=auth_fixture.free_port();config=uvicorn.Config(self.h.module.app,host='127.0.0.1',port=port,http=EdgeHTTP,ws=EdgeWSS,proxy_headers=False,access_log=False,log_level='critical',ssl_certfile=str(server_pem),ssl_keyfile=str(server_private),ssl_ca_certs=str(ca_file),ssl_cert_reqs=ssl.CERT_REQUIRED)
        config.load();config.ssl.minimum_version=ssl.TLSVersion.TLSv1_3;config.synthetic_revoked=set();server=uvicorn.Server(config);thread=threading.Thread(target=server.run,daemon=True);thread.start()
        deadline=time.monotonic()+5
        while not server.started and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(server.started)
        created=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic actual mTLS Voice',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'actualTLS room');room=created['id']
        self.join(created,other_owner,'bob')
        self.factory.approve(owner,a,['room-voice:transmit']);self.factory.approve(other_owner,b,['room-voice:receive'],'bob')
        tx=self.permissions(owner,a,room,transmit=True);rx=self.permissions(other_owner,b,room,receive=True,who='bob')
        def stream(credential,value,context,extra=None):
            raw=socket.create_connection(('127.0.0.1',port),timeout=3)
            headers={'Authorization':'Bearer '+credential['accessToken'],'X-WegoH-Functional-Revision':str(value['functionalRevision']),'X-WegoH-Room-Voice-Revision':str(value['revision'])};headers.update(extra or {})
            try:return connect('wss://api.wegoh.invalid/v1/social/rooms/'+room+'/voice',sock=raw,ssl=context,server_hostname='api.wegoh.invalid',additional_headers=headers,origin=None,open_timeout=3,close_timeout=1,create_connection=OwnedTLSConnection,proxy=None)
            except BaseException:raw.close();raise
        try:
            missing=ssl.create_default_context(cafile=str(ca_file));missing.minimum_version=ssl.TLSVersion.TLSv1_3
            with self.assertRaises((ssl.SSLError,ConnectionError,InvalidMessage,ConnectionClosed)):stream(a,tx,missing)
            spoof={'cf-cert-sha256':self.factory.certificates[a['grantId']],'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'}
            with self.assertRaises(InvalidStatus)as wrong:stream(a,tx,contexts[1],spoof)
            print('QA_VOICE_ACTUAL_MTLS wrong peer DER',wrong.exception.response.status_code,flush=True);self.assertEqual(wrong.exception.response.status_code,403)
            old=ssl.create_default_context(cafile=str(ca_file));old.load_cert_chain(str(client_files[0][0]),str(client_files[0][1]));old.minimum_version=ssl.TLSVersion.TLSv1_2;old.maximum_version=ssl.TLSVersion.TLSv1_2
            with self.assertRaises((ssl.SSLError,ConnectionError,InvalidMessage,ConnectionClosed)):stream(a,tx,old)
            opposite={'cf-cert-sha256':self.factory.certificates[b['grantId']],'cf-cert-presented':'false','cf-cert-verified':'false','cf-cert-revoked':'true'}
            with stream(a,tx,contexts[0],opposite)as sender,stream(b,rx,contexts[1])as receiver:
                self.assertEqual(sender.socket.version(),'TLSv1.3');self.assertEqual(receiver.socket.version(),'TLSv1.3')
                self.control(sender,'ready');self.control(receiver,'ready');sender.send(json.dumps(dict(type='floor-request')));self.control(sender,'floor-granted');self.control(receiver,'floor-started')
                frame=struct.pack('<I',0)+b'\x00'*640;sender.send(frame);self.assertEqual(receiver.recv(timeout=2),frame)
                print('QA_VOICE_ACTUAL_MTLS TLSv1.3 DER-bound forged-edge-overwritten PCM644',flush=True)
            self.assertEqual(self.factory.state(),base)
        finally:
            server.should_exit=True;thread.join(5)
            self.assertFalse(thread.is_alive(),'Owned synthetic TLS edge cleanup')

    def test_voice_consent_auth_free_backup_restores_zero_and_preserves_original_cipher(self):
     from pathlib import Path
     from psycopg import sql
     from ops.live import backup
     from native_access_backup import BackupProjectionError,validate_restored_projection
     a=self.h.login();c=self.factory.connect(a);self.factory.approve(a,c,['room-voice:receive','room-voice:transmit'])
     code,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic music backup room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a);self.assertEqual(code,201,room)
     consent=self.permissions(a,c,room['id'],receive=True,transmit=True)
     code,_,playlist=self.h.call('/v1/playlists',dict(name='Original synthetic playlist',tracks=[dict(title='Synthetic retained title',url='https://www.melon.com/song/detail.htm?songId=10000004')]),'POST',session=a);self.assertEqual(code,201,playlist)
     with psycopg.connect(self.h.dsn)as conn:
      private_row=conn.execute('SELECT * FROM native_room_voice_authorizations').fetchone();self.assertIsNotNone(private_row[5]);original_playlist=conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0]
     base_state=self.factory.state();key=self.h.state/'visits.key';key_sha=hashlib.sha256(key.read_bytes()).hexdigest();work=self.h.state/'room-voice-backup';work.mkdir(mode=0o700);content=self.h.state/'content';blob=b'Synthetic original music journey object';digest=hashlib.sha256(blob).hexdigest();(content/digest).write_bytes(blob)
     tools=Path(self.h.tools['pg_ctl']).parent;layout=backup.Layout(self.h.dsn,content,work,str(tools/'pg_dump'),str(tools/'pg_restore'));archive=backup.snapshot(layout);manifest=backup.authenticated_manifest(archive)
     self.assertEqual(manifest['tables']['native_room_voice_authorizations']['rows'],0);self.assertEqual(manifest['tables']['native_functional_authorizations']['rows'],0)
     target='room_voice_restore';destination=psycopg.conninfo.make_conninfo(self.h.dsn,dbname=target)
     with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
     try:
      scratch=work/'scratch';scratch.mkdir(mode=0o700);result=backup.verify_into(layout,archive,destination,scratch);self.assertTrue(result['verified']);self.assertEqual(result['nativeV2Auth']['personalSessionsRestored'],0)
      with psycopg.connect(destination)as conn:
       self.assertEqual(conn.execute('SELECT count(*) FROM native_room_voice_authorizations').fetchone()[0],0);self.assertEqual(conn.execute('SELECT count(*) FROM native_functional_authorizations').fetchone()[0],0);self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_credentials').fetchone()[0],0)
       self.assertEqual(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0],original_playlist)
       self.assertEqual(conn.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='native_room_voice_authorizations'::regclass AND contype='f' AND convalidated").fetchone()[0],3)
       conn.execute('INSERT INTO native_room_voice_authorizations VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',private_row)
       with self.assertRaises(BackupProjectionError):validate_restored_projection(conn,manifest['nativeV2Auth'],restored_at=1)
       conn.rollback()
      self.assertEqual((scratch/'objects'/digest).read_bytes(),blob)
     finally:
      with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
     self.assertEqual(self.factory.state(),base_state);self.assertEqual(hashlib.sha256(key.read_bytes()).hexdigest(),key_sha)
     with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT * FROM native_room_voice_authorizations').fetchone(),private_row);self.assertEqual(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0],original_playlist)

    def test_same_key_new_grant_has_no_room_voice_consent_until_fresh_phone_approval(self):
        import secrets
        from enrollment_crypto import challenge
        from native_access_codec import derive_revoke_capability,revoke_commitment,decode_request
        from native_authorization import restore
        owner=self.h.login();old=self.factory.connect(owner)
        self.factory.approve(owner,old,['room-voice:receive'])
        room=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic Voice same-key room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'same-key room')['id']
        first=self.permissions(owner,old,room,receive=True)
        with self.stream(old,room,first)as peer:self.control(peer,'ready')
        with psycopg.connect(self.h.dsn)as conn:
            row=conn.execute('SELECT protected_receipt FROM native_v2_certificates WHERE installation_key_id=%s AND generation=1',(old['installationKeyId'],)).fetchone()
            certificate=restore('generation',old['installationKeyId']+':1',row[0])['receipt']['certificatePem']
            original_certificates=conn.execute('SELECT row_to_json(t)::text FROM native_v2_certificates t ORDER BY row_to_json(t)::text').fetchall()
        verifier=secrets.token_urlsafe(32);operation=secrets.token_hex(16);scopes=old['scopes'];fingerprint=self.factory.certificates[old['grantId']]
        request=dict(authorizationVersion=1,operationId=operation,name='Synthetic same-key Voice reconnect',certificatePem=certificate,codeChallenge=challenge(verifier),requestedScopes=scopes,revokeCommitment=revoke_commitment(derive_revoke_capability(verifier,old['installationKeyId'],operation)))
        decode_request('ACCOUNT_AUTHORIZE',request)
        pending=self.expect(self.h.call('/v1/device-authorizations',request,'POST',who=None,host='api.wegoh.invalid',origin=None,certificate=fingerprint),201,'same-key public authorize')
        notice=self.expect(self.h.call('/v1/connections/'+pending['userCode'],session=owner),200,'new explicit phone notice')
        self.expect(self.h.call('/v1/connections/'+pending['userCode'],dict(authorizationVersion=1,consentVersion=notice['consentVersion'],approvedScopes=scopes,keepSignedIn=True,disclosureVersion=notice['disclosureSnapshot']['disclosureVersion'],disclosureSha256=notice['disclosureSnapshot']['disclosureSha256']),'POST',session=owner),200,'new explicit phone consent')
        authorized=self.expect(self.h.call('/v1/device-authorizations',request,'POST',who=None,host='api.wegoh.invalid',origin=None,certificate=fingerprint),200,'same authorize after phone')
        new=self.expect(self.h.call('/v1/device-sessions/exchange',dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=authorized['grantId'],codeVerifier=verifier),'POST',who=None,host='api.wegoh.invalid',origin=None,certificate=fingerprint),200,'public exchange')['credentialReceipt']
        self.factory.certificates[new['grantId']]=fingerprint
        self.assertEqual(new['installationKeyId'],old['installationKeyId']);self.assertNotEqual(new['grantId'],old['grantId'])
        self.assertEqual(self.factory.native(old,'/v1/account')[0],401)
        self.factory.approve(owner,new,['room-voice:receive'])
        view=self.expect(self.factory.native(new,'/v1/native/rooms/'+room+'/voice-permissions'),200,'new grant voice default false')
        self.assertEqual(view['permissions'],dict(receiveVoice=False,transmitVoice=False))
        false=self.permissions(owner,new,room)
        with self.assertRaises(InvalidStatus)as denied:self.stream(new,room,false)
        self.assertEqual(denied.exception.response.status_code,403)
        approved=self.permissions(owner,new,room,receive=True)
        with self.stream(new,room,approved)as peer:self.control(peer,'ready')
        with psycopg.connect(self.h.dsn)as conn:
            self.assertEqual(conn.execute('SELECT row_to_json(t)::text FROM native_v2_certificates t ORDER BY row_to_json(t)::text').fetchall(),original_certificates)

    def test_final_asgi_withdrawal_barrier_membership_rejoin_and_expiry_are_targeted(self):
        import asyncio,threading
        owner=self.h.login();other=self.h.login('bob');spare_owner=self.h.login('eve')
        sender=self.factory.connect(owner);target=self.factory.connect(other,'bob');spare=self.factory.connect(spare_owner,'eve');base=self.factory.state()
        created=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic bounded Voice race',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'boundary room');room=created['id']
        flags={key:False for key in ('status','location','visits','music','voice','control')}
        self.expect(self.h.call('/v1/social/rooms/join',dict(code=created['code'],consents=flags),'POST',session=other,who='bob'),200,'boundary member')
        self.join(created,spare_owner,'eve')
        self.factory.approve(owner,sender,['room-voice:transmit']);self.factory.approve(other,target,['room-voice:receive'],who='bob');self.factory.approve(spare_owner,spare,['room-voice:receive'],who='eve')
        tx=self.permissions(owner,sender,room,transmit=True);rx=self.permissions(other,target,room,receive=True,who='bob');other_rx=self.permissions(spare_owner,spare,room,receive=True,who='eve')
        voice=self.h.module.TEAM_VOICE;original=voice.deliver;paused=threading.Event();release=threading.Event();once=[]
        async def delayed(peer,*args):
            if peer.identity.get('deviceId')==target['deviceId']and not once:
                once.append(True);paused.set();await asyncio.to_thread(release.wait,3)
            return await original(peer,*args)
        peers=[]
        try:
            a=self.stream(sender,room,tx);b=self.stream(target,room,rx);c=self.stream(spare,room,other_rx);peers=[a,b,c]
            for peer in peers:self.control(peer,'ready')
            a.send(json.dumps(dict(type='floor-request')));self.control(a,'floor-granted');self.control(b,'floor-started');self.control(c,'floor-started')
            voice.deliver=delayed;frame=struct.pack('<I',0)+b'\x00'*640;a.send(frame);self.assertTrue(paused.wait(2),'Target delivery paused before actual ASGI send')
            self.assertEqual(c.recv(timeout=2),frame,'Other account device still receives')
            path='/v1/devices/'+target['deviceId']+'/rooms/'+room+'/voice-permissions'
            self.expect(self.h.call(path,method='DELETE',session=other,who='bob'),200,'targeted receiver revoke before response')
            release.set()
            with self.assertRaises(ConnectionClosed):b.recv(timeout=2)
            voice.deliver=original
            next_frame=struct.pack('<I',1)+b'\x00'*640;a.send(next_frame);self.assertEqual(c.recv(timeout=2),next_frame,'Other device and sender floor preserved')
            view=self.expect(self.factory.native(target,'/v1/native/rooms/'+room+'/voice-permissions'),200,'target flags remain false')
            self.assertEqual(view['permissions'],dict(receiveVoice=False,transmitVoice=False))
            fresh=self.permissions(other,target,room,receive=True,who='bob');b2=self.stream(target,room,fresh);peers.append(b2);self.control(b2,'ready')
            self.expect(self.h.call('/v1/social/rooms/'+room+'/leave',{},'POST',session=other,who='bob'),200,'actual membership leave')
            with self.assertRaises(ConnectionClosed):b2.recv(timeout=2)
            c.send(json.dumps(dict(type='ping')));self.control(c,'pong')
            a.send(json.dumps(dict(type='ping')));self.control(a,'pong')
            self.expect(self.h.call('/v1/social/rooms/join',dict(code=created['code'],consents=flags),'POST',session=other,who='bob'),200,'explicit new join epoch')
            empty=self.expect(self.factory.native(target,'/v1/native/rooms/'+room+'/voice-permissions'),200,'new join does not inherit')
            self.assertEqual(empty['permissions'],dict(receiveVoice=False,transmitVoice=False))
            fresh=self.permissions(other,target,room,receive=True,who='bob');b3=self.stream(target,room,fresh);peers.append(b3);self.control(b3,'ready')
            with psycopg.connect(self.h.dsn)as conn:
                conn.execute('UPDATE native_room_voice_authorizations SET expires_at=%s WHERE grant_id=%s AND room_id=%s',(int(time.time())-1,target['grantId'],room))
            with self.assertRaises(ConnectionClosed):b3.recv(timeout=2)
            a.send(json.dumps(dict(type='ping')));self.control(a,'pong')
            print('QA_VOICE_BOUNDARY old final-send PCM0/other-device-preserved/rejoinfalse/expiryclose',flush=True)
        finally:
            release.set();voice.deliver=original
            for peer in peers:peer.close()
            deadline=time.monotonic()+2
            while voice.peers and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(self.factory.state(),base)

    def test_current_voice_error_names_and_exact_negative_statuses(self):
        import copy
        owner=self.h.login();credential=self.factory.connect(owner)
        self.factory.approve(owner,credential,['room-voice:receive']);base=self.factory.state()
        room=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic named Voice errors',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'error fixture room')['id']
        path='/v1/devices/'+credential['deviceId']+'/rooms/'+room+'/voice-permissions'
        value=self.expect(self.h.call(path,session=owner),200,'actual closed snapshot')
        body={k:v for k,v in value.items()if k not in('deviceId','roomId','expiresAt')};body['permissions']=dict(receiveVoice=True,transmitVoice=False)
        cases=[(dict(body,unexpected=True),400,'INVALID_ROOM_VOICE_REQUEST'),(dict(body,roomVoiceDisclosureSha256='0'*64),409,'ROOM_VOICE_DISCLOSURE_CHANGED'),(dict(body,functionalRevision=body['functionalRevision']+1),409,'ROOM_VOICE_CONTEXT_CHANGED'),(dict(body,revision=body['revision']+1),409,'ROOM_VOICE_REVISION_CHANGED'),(dict(body,permissions=dict(receiveVoice=False,transmitVoice=True)),403,'FUNCTIONAL_PURPOSE_REQUIRED')]
        for wrong,status,error in cases:
            result=self.h.call(path,wrong,'PUT',session=owner)
            print('QA_CURRENT_VOICE_ERROR',result[0],result[2].get('error'),flush=True)
            self.assertEqual(result[0],status);self.assertEqual(result[2],dict(authorizationVersion=1,error=error));self.assertNotIn('MUSIC',error)
        self.expect(self.h.call(path,body,'PUT',session=owner),200,'one explicit save')
        result=self.h.call(path,body,'PUT',session=owner)
        self.assertEqual(result[0],409);self.assertEqual(result[2],dict(authorizationVersion=1,error='ROOM_VOICE_REVISION_CHANGED'))
        self.assertEqual(self.factory.state(),base)

    def test_own_devices_feed_only_target_room_revision_and_expiry_boolean(self):
        owner=self.h.login();other_owner=self.h.login('bob');a=self.factory.connect(owner);b=self.factory.connect(other_owner,'bob')
        self.factory.approve(owner,a,['room-voice:receive']);self.factory.approve(other_owner,b,['room-voice:receive'],'bob')
        created=self.expect(self.h.call('/v1/social/rooms',dict(name='Synthetic own Voice events',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=owner),201,'own events room');room=created['id']
        self.join(created,other_owner,'bob')
        self.permissions(owner,a,room,receive=True);self.permissions(other_owner,b,room,receive=True,who='bob');base=self.factory.state()
        with psycopg.connect(self.h.dsn)as conn:other_cipher=bytes(conn.execute('SELECT protected FROM native_room_voice_authorizations WHERE grant_id=%s AND room_id=%s',(a['grantId'],room)).fetchone()[0])
        def channel(c):
            raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=3)
            return connect('ws://api.wegoh.invalid/v1/events',sock=raw,origin=None,open_timeout=3,close_timeout=1,additional_headers={'Authorization':'Bearer '+c['accessToken'],'cf-cert-sha256':self.factory.certificates[c['grantId']],'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'})
        with channel(a)as unrelated,channel(b)as target:
            first=json.loads(target.recv(timeout=3));other_first=json.loads(unrelated.recv(timeout=3));self.assertEqual(first['resources'],['courses','devices','playlists']);self.assertEqual(other_first['resources'],first['resources']);seq=0
            with self.assertRaises(TimeoutError):target.recv(timeout=1.1)
            def target_changed():
                nonlocal seq
                event=json.loads(target.recv(timeout=3));seq+=1
                self.assertEqual(event,dict(type='invalidate',epoch=first['epoch'],seq=seq,resources=['devices']))
                with self.assertRaises(TimeoutError):unrelated.recv(timeout=1.1)
            self.expect(self.h.call('/v1/devices/'+b['deviceId']+'/rooms/'+room+'/voice-permissions',method='DELETE',session=other_owner,who='bob'),200,'only target room revoke');target_changed()
            self.permissions(other_owner,b,room,receive=True,who='bob');target_changed()
            with psycopg.connect(self.h.dsn)as conn:conn.execute('UPDATE native_room_voice_authorizations SET expires_at=1 WHERE grant_id=%s AND room_id=%s',(b['grantId'],room))
            target_changed()
        with psycopg.connect(self.h.dsn)as conn:self.assertEqual(bytes(conn.execute('SELECT protected FROM native_room_voice_authorizations WHERE grant_id=%s AND room_id=%s',(a['grantId'],room)).fetchone()[0]),other_cipher)
        self.assertEqual(self.factory.state(),base)

    def test_voice_only_room_selector_current_notice_directions_names_and_closed_pages(self):
        from native_room_voice_authority import CONTRACT
        from private_records import VisitCipher
        from starlette.requests import Request
        from starlette.websockets import WebSocket
        from native_functional_query import native_query_allowed
        owner=self.h.login();bob=self.h.login('bob');third=self.h.login('eve')
        tx=self.factory.connect(owner);rx=self.factory.connect(bob,'bob');other=self.factory.connect(third,'eve')
        baseline=self.factory.state()
        self.factory.approve(owner,tx,['room-voice:transmit'])
        self.factory.approve(bob,rx,['room-voice:receive'],who='bob')
        self.factory.approve(third,other,['rooms:read'],'eve')
        endpoint='/v1/native/voice-rooms'
        def listing(credential,path=endpoint):
            return self.expect(self.factory.native(credential,path),200,'voice-only room page')
        self.assertEqual(listing(tx)['items'],[])
        self.assertEqual(self.factory.native(other,endpoint)[0],403)
        room=self.expect(self.h.call('/v1/social/rooms',dict(name='Private other-owner Voice room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=bob,who='bob'),201,'other-owner room')
        flags={k:False for k in ('status','location','visits','music','voice','control')}
        self.expect(self.h.call('/v1/social/rooms/join',dict(code=room['code'],consents=flags),'POST',session=owner),200,'explicit current membership')
        a=self.permissions(owner,tx,room['id'],transmit=True);self.permissions(bob,rx,room['id'],receive=True,who='bob')
        page=listing(tx);self.assertEqual(set(page),{'authorizationVersion','deviceId','grantId','functionalRevision','items','nextCursor'})
        self.assertEqual(page['deviceId'],tx['deviceId']);self.assertEqual(page['grantId'],tx['grantId'])
        item=page['items'][0];self.assertEqual(set(item),{'roomId','name','availableDirections','revision','memberJoinedAt','expiresAt'})
        self.assertEqual(item['name'],'여행방');self.assertEqual(item['availableDirections'],['transmit']);self.assertIsNone(page['nextCursor'])
        self.assertEqual(listing(rx)['items'][0]['name'],'Private other-owner Voice room')
        self.assertEqual(listing(rx)['items'][0]['availableDirections'],['receive'])
        # The projection selects a reference; existing own GET and WS still grant admission.
        txown=self.expect(self.factory.native(tx,'/v1/native/rooms/'+item['roomId']+'/voice-permissions'),200,'selected reference own GET')
        rxown=self.expect(self.factory.native(rx,'/v1/native/rooms/'+item['roomId']+'/voice-permissions'),200,'receive reference own GET')
        with self.stream(tx,item['roomId'],txown)as sender,self.stream(rx,item['roomId'],rxown)as receiver:
            self.control(sender,'ready');self.control(receiver,'ready');sender.send(json.dumps(dict(type='floor-request')))
            self.control(sender,'floor-granted');self.control(receiver,'floor-started')
            frame=struct.pack('<I',0)+b'\x00'*640;sender.send(frame);self.assertEqual(receiver.recv(timeout=2),frame)
        # Simulate an actually stored prior-notice row, not a false new public authorization.
        old={'disclosureVersion': 1, 'disclosureSha256': 'f90f208be7c0ba273635aaf93693f092f5697b25b4e74ba34963c3b8a391a24d', 'disclosure': {'title': '여행방 음성 대화', 'purpose': '이 기기에서 선택한 여행방의 음성을 듣거나 내 목소리를 보냅니다.', 'permissions': [{'id': 'receiveVoice', 'label': '방 음성 듣기', 'purpose': '선택한 여행방에서 허용된 참여자의 목소리를 듣습니다.', 'dataCategories': ['참여자의 목소리', '말하는 참여자 표시'], 'retention': '기능 동의, 방, 연결의 기한 중 가장 이른 때까지 허용하며 음성은 저장하지 않습니다.', 'withdrawal': '이 기기의 해당 방 음성 수신을 중단하고 대기 중인 음성을 지웁니다.', 'refusal': '이 기기에서 해당 방의 목소리를 들을 수 없습니다. 음성 보내기는 별도로 선택합니다.'}, {'id': 'transmitVoice', 'label': '방에 음성 보내기', 'purpose': '사용자가 말하기를 선택할 때 마이크로 받은 목소리를 허용된 방 참여자에게 보냅니다.', 'dataCategories': ['내 목소리', '말하는 참여자 표시'], 'retention': '기능 동의, 방, 연결의 기한 중 가장 이른 때까지 허용하며 음성은 저장하지 않습니다.', 'withdrawal': '이 기기의 해당 방 음성 송신을 중단하고 대기 중인 음성을 지웁니다. 이미 전달된 음성은 되돌릴 수 없습니다.', 'refusal': '이 기기에서 해당 방에 목소리를 보낼 수 없습니다. 음성 듣기는 별도로 선택합니다.'}]}}
        with psycopg.connect(self.h.dsn)as conn:
            row=conn.execute('SELECT protected FROM native_room_voice_authorizations WHERE grant_id=%s AND room_id=%s',(tx['grantId'],room['id'])).fetchone()
            value=VisitCipher().restore('native-room-voice',tx['grantId']+':'+room['id'],row[0]);value.update(roomVoiceDisclosureVersion=old['disclosureVersion'],roomVoiceDisclosureSha256=old['disclosureSha256'],disclosureSnapshot=old['disclosure'])
            oldcipher=VisitCipher().protect('native-room-voice',tx['grantId']+':'+room['id'],value)
            conn.execute('UPDATE native_room_voice_authorizations SET protected=%s WHERE grant_id=%s AND room_id=%s',(oldcipher,tx['grantId'],room['id']))
        self.assertEqual(listing(tx)['items'],[],'old audio consent must not silently add room-name projection')
        ownpath='/v1/devices/'+tx['deviceId']+'/rooms/'+room['id']+'/voice-permissions'
        snapshot=self.expect(self.h.call(ownpath,session=owner),200,'old consent current notice read only')
        self.assertTrue(snapshot['permissions']['transmitVoice'],'old audio authority unchanged')
        stale={k:v for k,v in snapshot.items()if k not in('deviceId','roomId','expiresAt')};stale.update(roomVoiceDisclosureVersion=old['disclosureVersion'],roomVoiceDisclosureSha256=old['disclosureSha256'])
        self.expect(self.h.call(ownpath,stale,'PUT',session=owner),409,'old cached notice rejected')
        with psycopg.connect(self.h.dsn)as conn:self.assertEqual(bytes(conn.execute('SELECT protected FROM native_room_voice_authorizations WHERE grant_id=%s AND room_id=%s',(tx['grantId'],room['id'])).fetchone()[0]),bytes(oldcipher))
        self.permissions(owner,tx,room['id'],transmit=True)
        # UGC sharing is independent of positive Voice membership/consent.
        review='/v1/social/rooms/'+room['id']+'/review-request'
        self.expect(self.h.call(review,dict(consent=True),'PATCH',session=bob,who='bob'),200,'name review request')
        inspected=self.expect(self.h.call('/v1/moderation/content/room/'+room['id'],session=owner),200,'current submitted name')
        decision=dict(checksum=inspected['review']['checksum'],decision='approved',reviewer='Synthetic operator',reviewNote='Synthetic name review; not real user-content approval')
        self.expect(self.h.call('/v1/moderation/content/room/'+room['id'],decision,'POST',session=owner),200,'explicit name review')
        self.assertEqual(listing(tx)['items'][0]['name'],'Private other-owner Voice room')
        self.expect(self.h.call(review,dict(consent=False),'PATCH',session=bob,who='bob'),200,'name share withdrawal')
        self.assertEqual(listing(tx)['items'][0]['name'],'여행방','voice row stays; raw/old name does not')
        self.factory.approve(third,other,['room-voice:transmit'],'eve');self.assertEqual(listing(other)['items'],[],'different account grant never inherits room approval')
        for suffix in ('?cursor=', '?cursor='+room['id']+'&cursor='+room['id'], '?other='+room['id'], '?access_token=not-a-credential', '?cursor='+'A'*32, '?cursor='+'a'*33):
            result=self.factory.native(tx,endpoint+suffix);print('QA_VOICE_SELECTOR_QUERY',suffix,result[0],flush=True);self.assertEqual(result[0],400)
        async def unused_socket_io(*args):raise AssertionError('Query predicate must not do socket I/O')
        scope=dict(type='websocket',scheme='ws',path=endpoint,query_string=b'cursor='+b'a'*32,headers=[])
        self.assertFalse(native_query_allowed(WebSocket(scope,unused_socket_io,unused_socket_io)));scope['query_string']=b'';self.assertTrue(native_query_allowed(WebSocket(scope,unused_socket_io,unused_socket_io)))
        self.expect(self.h.call(ownpath,method='DELETE',session=owner),200,'own room consent revoke')
        self.assertEqual(listing(tx)['items'],[]);self.assertEqual(len(listing(rx)['items']),1,'other owner receiver remains')
        # Seed only private synthetic room/member content to cross the public per-owner10-room creation cap.
        # Every positive device-room authority below is created by the real owner HTTP PUT.
        service=self.h.module.TEAM_AUTH.room_service;account=owner['user']['id'];seeded=[]
        with psycopg.connect(self.h.dsn)as conn:
            for number in range(1,22):
                rid=format(number,'032x');seeded.append(rid)
                payload=dict(name='Synthetic cursor room '+str(number),code='QA'+str(number),courseId=None,courseVersion=None,preference='balanced')
                conn.execute('INSERT INTO team_rooms(room_id,owner_id,code_hash,protected,expires_at) VALUES(%s,%s,%s,%s,now()+interval\'1 hour\')',(rid,account,format(number,'064x'),service.protect('owner:'+account,rid,payload)))
                conn.execute('INSERT INTO team_room_members(room_id,account_id,protected) VALUES(%s,%s,%s)',(rid,account,service.protect('member:'+account,rid,dict(role='member',consents=flags))))
        for rid in seeded:self.permissions(owner,tx,rid,transmit=True)
        first=listing(tx);self.assertEqual(len(first['items']),20);self.assertEqual(first['nextCursor'],seeded[19]);self.assertEqual([x['roomId']for x in first['items']],seeded[:20])
        second=listing(tx,endpoint+'?cursor='+first['nextCursor']);self.assertEqual([x['roomId']for x in second['items']],seeded[20:]);self.assertIsNone(second['nextCursor'])
        self.assertEqual(set(first['items'][0]),set(item));self.assertEqual(listing(other)['items'],[])
        # Two additional synthetic boundary transitions affect only their selected row.
        with psycopg.connect(self.h.dsn)as conn:
            conn.execute('UPDATE native_room_voice_authorizations SET expires_at=%s WHERE grant_id=%s AND room_id=%s',(int(time.time())-1,tx['grantId'],seeded[0]))
            conn.execute("UPDATE team_room_members SET joined_at=joined_at+interval'1 millisecond' WHERE account_id=%s AND room_id=%s",(account,seeded[1]))
        bounded=listing(tx);self.assertEqual(len(bounded['items']),19);self.assertIsNone(bounded['nextCursor'])
        self.assertFalse(set(seeded[:2])&{value['roomId']for value in bounded['items']},'expired and prior membership lineage omitted')
        self.factory.approve(owner,tx,[]);self.assertEqual(self.factory.native(tx,endpoint)[0],403)
        self.factory.approve(owner,tx,['room-voice:transmit']);self.assertEqual(listing(tx)['items'],[],'global reapproval cannot revive old room flags')
        self.assertEqual(self.factory.state(),baseline,'base6 grant/credential/cert/epoch/cipher authority unchanged')

if __name__=='__main__':unittest.main()
