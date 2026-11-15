"""Real owned TLS1.3/client-certificate + temporary-PG contracts.
The protocol adapter is a synthetic edge, not a Cloudflare deployment claim.
All generated CA/client keys and original records stay in the owned temp fixture.
"""
import datetime,hashlib,http.client,json,os,secrets,socket,ssl,threading,time,unittest
from unittest.mock import patch
from pathlib import Path
import psycopg,uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol
from websockets.sync.client import connect,ClientConnection
from websockets.exceptions import ConnectionClosed,InvalidStatus
from enrollment_app import create_app
from enrollment_crypto import challenge, digest, public_bytes
import test_enrollment
import test_native_authorization_http as auth_fixture
import test_team_auth as fixture
HEADER=b'cf-cert-sha256'
EDGE_HEADERS={HEADER,b'cf-cert-presented',b'cf-cert-verified',b'cf-cert-revoked'}

class SyntheticEdge:
    def connection_made(self,transport):
        super().connection_made(transport)
        tls=transport.get_extra_info('ssl_object')
        certificate=tls.getpeercert(binary_form=True)
        fingerprint=hashlib.sha256(certificate).hexdigest().encode()
        app=self.app
        async def forwarded(scope,receive,send):
            scope=dict(scope)
            # Remove all client-selected instances, even with a different case.
            headers=[(k,v)for k,v in scope['headers']if k.lower()not in EDGE_HEADERS]
            host=next((v for k,v in headers if k.lower()==b'host'),b'')
            if host==b'api.wegoh.invalid':
                headers.extend([(HEADER,fingerprint),(b'cf-cert-presented',b'true'),(b'cf-cert-verified',b'true'),(b'cf-cert-revoked',b'true'if fingerprint.decode()in self.config.synthetic_revoked else b'false')])
            scope['headers']=headers
            await app(scope,receive,send)
        self.app=forwarded
class EdgeHTTP(SyntheticEdge,H11Protocol):pass
class EdgeWSS(SyntheticEdge,WebSocketsSansIOProtocol):pass
class OwnedTLSConnection(ClientConnection):
    # Same pinned cleanup principle as the previously reviewed Voice TLS driver.
    # Preserve/re-raise original handshake errors; never hang its owned recv join.
    def close_socket(self):
        try:self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        super().close_socket()

class NativeMTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass();cls.api=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        cls.state=fixture.TeamTests.state;cls.auth=fixture.TeamTests.module.TEAM_AUTH
        cls.revoked=set();cls.port=fixture.free_port();cls.observations=[]
        now=datetime.datetime.now(datetime.timezone.utc)
        def make(name,issuer=None,issuer_key=None,server=False,ca=False):
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,name)])
            builder=x509.CertificateBuilder().subject_name(subject).issuer_name(issuer.subject if issuer else subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=ca,path_length=None),critical=True)
            if not ca:
                builder=builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH]),critical=False)
            if server:builder=builder.add_extension(x509.SubjectAlternativeName([x509.DNSName('api.wegoh.invalid'),x509.IPAddress(__import__('ipaddress').ip_address('127.0.0.1'))]),critical=False)
            cert=builder.sign(issuer_key or key,hashes.SHA256())
            certfile,keyfile=cls.state/(name+'.crt'),cls.state/(name+'.key')
            for path,raw in[(certfile,cert.public_bytes(serialization.Encoding.PEM)),(keyfile,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))]:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb')as stream:stream.write(raw)
            return cert,key,certfile,keyfile
        ca,key,ca_path,_=make('synthetic-ca',ca=True)
        cls.issuer=test_enrollment.SyntheticIssuer()
        cls.issuer.key=key
        cls.issuer.name=ca.subject
        with patch.dict(os.environ, WEGOH_ENROLLMENT_ORIGIN='https://enroll-wegoh.devforest.io'):
            cls.enrollment=create_app(cls.auth, cls.issuer)
        cls.enrollment_port=fixture.free_port()
        cls.enroll_server=uvicorn.Server(uvicorn.Config(cls.enrollment,host='127.0.0.1',port=cls.enrollment_port,
            proxy_headers=False,access_log=False,log_level='critical'))
        cls.enroll_thread=threading.Thread(target=cls.enroll_server.run,daemon=True);cls.enroll_thread.start()
        deadline=time.monotonic()+5
        while not cls.enroll_server.started and time.monotonic()<deadline:time.sleep(.02)
        if not cls.enroll_server.started:raise RuntimeError('Owned enrollment fixture did not start')
        _,_,server_cert,server_key=make('synthetic-server',ca,key,server=True)
        cls.clients={}
        for name in('a','b'):
            cert,_,cert_path,key_path=make('synthetic-client-'+name,ca,key)
            ctx=ssl.create_default_context(cafile=str(ca_path));ctx.minimum_version=ssl.TLSVersion.TLSv1_3;ctx.load_cert_chain(str(cert_path),str(key_path))
            cls.clients[name]=(ctx,cert.fingerprint(hashes.SHA256()).hex())
        cls.no_certificate=ssl.create_default_context(cafile=str(ca_path))
        config=uvicorn.Config(fixture.TeamTests.module.app,host='127.0.0.1',port=cls.port,http=EdgeHTTP,ws=EdgeWSS,proxy_headers=False,access_log=False,log_level='critical',ssl_certfile=str(server_cert),ssl_keyfile=str(server_key),ssl_ca_certs=str(ca_path),ssl_cert_reqs=ssl.CERT_REQUIRED)
        config.load();config.ssl.minimum_version=ssl.TLSVersion.TLSv1_3;config.synthetic_revoked=cls.revoked
        cls.server=uvicorn.Server(config);cls.thread=threading.Thread(target=cls.server.run,daemon=True);cls.thread.start()
        deadline=time.monotonic()+5
        while not cls.server.started and time.monotonic()<deadline:time.sleep(.02)
        if not cls.server.started:raise RuntimeError('Owned mTLS fixture did not start')
    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit=True;cls.thread.join(5)
        if cls.thread.is_alive():raise RuntimeError('Owned mTLS fixture failed to stop')
        cls.enroll_server.should_exit=True;cls.enroll_thread.join(5)
        if cls.enroll_thread.is_alive():raise RuntimeError('Owned enrollment fixture failed to stop')
        fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.api.setUp();self.revoked.clear()
    def native(self,path,data=None,method='GET',token=None,client='a',spoof=None,host='api.wegoh.invalid',context=None):
        ctx=context or self.clients[client][0]
        headers={'Host':host,'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        if isinstance(spoof,dict):headers.update(spoof)
        elif spoof is not None:headers[HEADER.decode()]=spoof
        connection=http.client.HTTPSConnection('127.0.0.1',self.port,context=ctx,timeout=5)
        try:
            connection.request(method,path,body=json.dumps(data).encode()if data is not None else None,headers=headers)
            tls=connection.sock.version();response=connection.getresponse();self.assertEqual(tls,'TLSv1.3')
            raw=response.read();self.observations.append({'status':response.status,'tls':tls})
            return response.status,json.loads(raw) if raw else None
        finally:connection.close()
    def approved_exchange(self):
        session=self.api.login()
        flow=auth_fixture.NativeAuthorizationHttpTests()
        flow.api=self.api
        flow.session=session
        flow.port=self.enrollment_port
        flow.key,flow.csr=test_enrollment.make_csr()
        flow.key_id=digest(public_bytes(flow.key.public_key()))
        flow.verifier=secrets.token_urlsafe(32)
        flow.challenge=challenge(flow.verifier)
        flow.scopes=['account:read','device:self:manage']
        issued=flow.issued_without_exchange()
        receipt=issued['certificateReceipt']
        cert=x509.load_pem_x509_certificate(receipt['certificatePem'].encode())
        self.assertEqual(cert.fingerprint(hashes.SHA256()).hex(),receipt['certificateSha256'])
        self.assertEqual(public_bytes(cert.public_key()),public_bytes(flow.key.public_key()))
        client_dir=self.state/('issued-'+secrets.token_hex(8))
        client_dir.mkdir(mode=0o700)
        cert_path,key_path=client_dir/'cert.pem',client_dir/'key.pem'
        self.api.dev.private_file(cert_path,receipt['certificatePem'].encode())
        self.api.dev.private_file(key_path,flow.key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        ctx=ssl.create_default_context(cafile=str(self.state/'synthetic-ca.crt'))
        ctx.minimum_version=ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(str(cert_path),str(key_path))
        self.clients['a']=(ctx,receipt['certificateSha256'])
        return session,dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=issued['grantId'],codeVerifier=flow.verifier)

    def pair(self):
        session,exchange=self.approved_exchange()
        status,result=self.native('/v1/device-sessions/exchange',exchange,'POST')
        self.assertEqual(status,200)
        return session,result['credentialReceipt']
    def websocket(self,token,client='a',*,subprotocols=None):
        raw=socket.create_connection(('127.0.0.1',self.port),timeout=5)
        return connect('wss://api.wegoh.invalid/v1/events',sock=raw,ssl=self.clients[client][0],server_hostname='api.wegoh.invalid',additional_headers={'Authorization':'Bearer '+token},open_timeout=5,close_timeout=1,create_connection=OwnedTLSConnection,proxy=None,subprotocols=subprotocols)
    def test_01_real_tls_certificate_and_protocol_floor(self):
        for path in('/v1/device-sessions/exchange','/v1/account'):
            with self.assertRaises((ssl.SSLError,ConnectionError,http.client.RemoteDisconnected)):
                self.native(path,context=self.no_certificate)
        self.assertEqual(self.native('/v1/account')[0],401) # Certificate alone is not a device token.
        old=ssl.create_default_context();old.check_hostname=False;old.verify_mode=ssl.CERT_NONE;old.maximum_version=ssl.TLSVersion.TLSv1_2
        with self.assertRaises(ssl.SSLError):self.native('/v1/account',context=old)
    def test_02_exchange_requires_issued_certificate_and_overwrites_spoofed_headers(self):
        session,exchange=self.approved_exchange()
        path='/v1/device-sessions/exchange'
        self.assertEqual(self.native(path,exchange,'POST',client='b',spoof=self.clients['a'][1])[0],403)
        status,result=self.native(path,exchange,'POST',spoof={'cf-cert-sha256':self.clients['b'][1],
            'cf-cert-presented':'false','cf-cert-verified':'false','cf-cert-revoked':'true'})
        self.assertEqual(status,200)
        receipt=result['credentialReceipt']
        key=receipt['accessToken']
        status,account=self.native('/v1/account',token=key)
        self.assertEqual(status,200)
        self.assertEqual(account['user']['id'],session['user']['id'])
        self.assertEqual(account['deviceId'],receipt['deviceId'])
        self.assertEqual(self.native('/v1/account',token=key,client='b',spoof=self.clients['a'][1])[0],403)
        self.assertEqual(self.native('/v1/account',token=key,host='web.wegoh.invalid')[0],401)
        with psycopg.connect(self.api.dsn) as conn:
            fingerprint=conn.execute('SELECT certificate_sha256 FROM native_v2_credentials WHERE grant_id=%s',
                (receipt['grantId'],)).fetchone()[0]
        self.assertEqual(fingerprint,self.clients['a'][1])

    def test_03_refresh_is_bound_and_rotates_without_rebinding(self):
        _,receipt=self.pair()
        path='/v1/device-sessions/refresh'
        body=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=receipt['grantId'],
                  deviceId=receipt['deviceId'],refreshToken=receipt['refreshToken'])
        self.assertEqual(self.native(path,body,'POST',client='b')[0],403)
        status,result=self.native(path,body,'POST')
        self.assertEqual(status,200)
        fresh=result['credentialReceipt']
        self.assertEqual(self.native('/v1/account',token=receipt['accessToken'])[0],401)
        self.assertEqual(self.native('/v1/account',token=fresh['accessToken'])[0],200)
        self.assertEqual(self.native(path,body,'POST')[1]['credentialReceipt'],fresh)
        self.assertEqual(self.native(path,dict(body,operationId=secrets.token_hex(16)),'POST')[0],401)
    def test_04_missing_malformed_or_duplicate_edge_header(self):
        _,token=self.pair()
        for value in(None,'','ab'*31,'AB'*32,'ab'*32+', '+'cd'*32):
            self.assertEqual(self.api.call('/v1/account',who=None,host='api.wegoh.invalid',origin=None,
                bearer=token['accessToken'],certificate=value)[0],401)
        connection=http.client.HTTPConnection('127.0.0.1',self.api.port,timeout=5)
        try:
            connection.putrequest('GET','/v1/account',skip_host=True);connection.putheader('Host','api.wegoh.invalid');connection.putheader('Authorization','Bearer '+token['accessToken'])
            connection.putheader('cf-cert-presented','true');connection.putheader('cf-cert-verified','true');connection.putheader('cf-cert-revoked','false')
            connection.putheader(HEADER.decode(),self.clients['a'][1]);connection.putheader(HEADER.decode(),self.clients['a'][1]);connection.endheaders()
            response=connection.getresponse();response.read();self.assertEqual(response.status,401)
        finally:connection.close()
    def test_05_expired_or_unregistered_leaf_never_rebinds_an_active_grant(self):
        session,token=self.pair()
        refresh=dict(authorizationVersion=1,operationId=secrets.token_hex(16),
                     grantId=token['grantId'],deviceId=token['deviceId'],refreshToken=token['refreshToken'])
        self.assertEqual(self.native('/v1/device-sessions/refresh',refresh,'POST',client='b')[0],403)
        with psycopg.connect(self.api.dsn) as conn:
            expires=conn.execute('SELECT expires_at FROM native_v2_certificates WHERE certificate_sha256=%s',
                                  (self.clients['a'][1],)).fetchone()[0]
        with patch.object(fixture.TeamTests.module.TEAM_NATIVE_AUTHORIZATION,'clock',return_value=expires):
            self.assertEqual(self.native('/v1/account',token=token['accessToken'])[0],403)
            self.assertEqual(self.native('/v1/device-sessions/refresh',refresh,'POST')[0],403)
        self.assertEqual(self.api.call('/v1/devices',session=session)[0],200)
        self.assertEqual(self.native('/v1/account',token=token['accessToken'])[0],200)
    def test_06_wss_cross_certificate_and_current_device_revocation(self):
        session,token=self.pair()
        with self.assertRaises(InvalidStatus)as error:self.websocket(token['accessToken'],'b')
        self.assertEqual(error.exception.response.status_code,403)
        with self.websocket(token['accessToken'])as ws:
            self.assertEqual(json.loads(ws.recv(timeout=3))['type'],'snapshot')
            self.assertEqual(self.api.call('/v1/devices/'+token['deviceId'],method='DELETE',session=session)[0],200)
            with self.assertRaises(ConnectionClosed)as closed:ws.recv(timeout=3)
            self.assertEqual(closed.exception.rcvd.code,4003)
    def test_07_verified_but_revoked_next_request_is_denied(self):
        _,token=self.pair();self.revoked.add(self.clients['a'][1])
        self.assertEqual(self.native('/v1/account',token=token['accessToken'],spoof=self.clients['a'][1])[0],401)
    def test_08_existing_socket_has_real_bounded_reconnect(self):
        _,token=self.pair();self.assertEqual(self.auth.native_socket_seconds,60)
        start=time.monotonic()
        with self.websocket(token['accessToken'])as ws:
            self.assertEqual(json.loads(ws.recv(timeout=3))['type'],'snapshot')
            # Revocation at the synthetic edge cannot mutate old handshake headers.
            self.revoked.add(self.clients['a'][1])
            try:
                while time.monotonic()-start<64:ws.recv(timeout=22)
                self.fail('Native WSS did not require a fresh edge handshake')
            except ConnectionClosed as closed:
                self.assertEqual(closed.rcvd.code,1008)
        elapsed=time.monotonic()-start;self.assertGreaterEqual(elapsed,59);self.assertLess(elapsed,64)

    def test_09_retired_pairing_and_token_paths_remain_closed_to_certified_clients(self):
        for path in ('/v1/devices/pairings','/v1/devices/token','/v1/devices/token/refresh'):
            with self.subTest(path=path):
                self.assertEqual(self.native(path,{},'POST',client='b')[0],404)

if __name__=='__main__':unittest.main(verbosity=2)
