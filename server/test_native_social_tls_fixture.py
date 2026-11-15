"""Test-only local TLS/mTLS edge over actual isolated TeamTests PostgreSQL APIs.

No operating DB/CA/profile is used. No fake product endpoint, token getter or
certificate header from a client is trusted. Run in one fresh interpreter.
"""
from pathlib import Path
import datetime as dt
import hashlib
import http.server
import json
import re
import socket
import ssl
import threading
from contextlib import AbstractContextManager

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID,NameOID

import test_team_auth as product_fixture
from test_enrollment import SyntheticIssuer
from native_authorization import NativeAuthorizationError,error_response
from team_event_versions import PROTOCOL
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve
from websockets.sync.client import connect


def strict_object(raw):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('Duplicate field')
            out[key]=value
        return out
    def invalid(_):raise ValueError('Nonfinite number')
    value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid)
    if type(value)is not dict:raise ValueError('Object required')
    return value


class NativeSocialTlsFixture(AbstractContextManager):
    """Owner consent methods are private test-controller calls, never HTTP routes."""
    def __init__(self,*,approve_connection=False):
        self.approve_connection=approve_connection
        self.observations=[];self.errors=[];self._credential=None
        self._remote=set();self._event_number=0;self._lock=threading.Lock();self._holds={};self.http=None;self.events=None

    def __enter__(self):
        product_fixture.TeamTests.setUpClass()
        self.h=product_fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        self.h.setUp()
        self.owner=self.h.login();self.peer=self.h.login('bob')
        self.service=self.h.module.TEAM_NATIVE_AUTHORIZATION
        self._old_issuer=self.service.issuer
        class Issuer(SyntheticIssuer):
            def response(inner,csr):
                value=super().response(csr);now=dt.datetime.now(dt.timezone.utc)
                leaf=(x509.CertificateBuilder().subject_name(csr.subject).issuer_name(inner.name)
                    .public_key(csr.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now-dt.timedelta(seconds=30)).not_valid_after(now+dt.timedelta(days=35))
                    .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
                    .add_extension(x509.KeyUsage(True,False,False,False,False,False,False,False,False),True)
                    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),False)
                    .sign(inner.key,hashes.SHA256()))
                assert now+dt.timedelta(days=30)<leaf.not_valid_after_utc<x509.load_pem_x509_certificate(self.ca_pem).not_valid_after_utc
                value.update(certificate=leaf.public_bytes(serialization.Encoding.PEM).decode(),fingerprint_sha256=leaf.fingerprint(hashes.SHA256()).hex())
                return value
        self.issuer=Issuer();self.service.issuer=self.issuer
        now=dt.datetime.now(dt.timezone.utc)
        ca=(x509.CertificateBuilder().subject_name(self.issuer.name).issuer_name(self.issuer.name)
            .public_key(self.issuer.key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(minutes=1)).not_valid_after(now+dt.timedelta(days=40))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),True).sign(self.issuer.key,hashes.SHA256()))
        server_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        import ipaddress
        server=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Owned social loopback')]))
            .issuer_name(self.issuer.name).public_key(server_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-dt.timedelta(minutes=1)).not_valid_after(now+dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False).sign(self.issuer.key,hashes.SHA256()))
        self.ca_pem=ca.public_bytes(serialization.Encoding.PEM)
        ca_file=self.h.state/'social-ca.pem';ca_file.write_bytes(self.ca_pem)
        cert=self.h.state/'social-server.pem';cert.write_bytes(server.public_bytes(serialization.Encoding.PEM))
        key=self.h.state/'social-server.key';key.write_bytes(server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=tls.maximum_version=ssl.TLSVersion.TLSv1_3
        tls.load_cert_chain(cert,key);tls.load_verify_locations(cafile=str(ca_file));tls.verify_mode=ssl.CERT_OPTIONAL
        fixture=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def reply(self,status,value,headers=None):
                raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                for name,value in(headers or{}).items():
                    if name.lower()in('retry-after','cache-control'):self.send_header(name,value)
                self.end_headers();self.wfile.write(raw)
            def dispatch(self):
                try:
                    if self.connection.version()!='TLSv1.3':raise ValueError('TLS13 required')
                    lengths=self.headers.get_all('Content-Length',[])
                    if len(lengths)>1 or self.headers.get('Transfer-Encoding'):raise ValueError('Framing')
                    size=int(lengths[0])if lengths else 0
                    if not 0<=size<=16384:raise ValueError('Body limit')
                    body=strict_object(self.rfile.read(size))if size else None
                    if self.command=='POST'and self.path=='/v1/connections':
                        status,value=fixture.service.begin(body)
                        if fixture.approve_connection:fixture.approve_pending(value['userCode'])
                        fixture.observations.append(dict(stage='actual-begin',status=status))
                        return self.reply(status,value)
                    claim=re.fullmatch(r'/v1/connections/([a-f0-9]{32})/claim',self.path)
                    if self.command=='POST'and claim:
                        status,value=fixture.service.claim(claim[1],body)
                        fixture.observations.append(dict(stage='actual-claim',status=status))
                        return self.reply(status,value)
                    if self.command=='POST'and self.path=='/v1/connections/recover':
                        status,value=fixture.service.recover(body);return self.reply(status,value)
                    fingerprint=fixture.peer_fingerprint(self.connection)
                    if fingerprint is None:return self.reply(401,dict(authorizationVersion=1,error='INVALID_CREDENTIAL'))
                    authorization=self.headers.get_all('Authorization',[])
                    if len(authorization)>1:return self.reply(401,dict(authorizationVersion=1,error='INVALID_CREDENTIAL'))
                    token=None
                    if authorization:
                        if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}',authorization[0]):return self.reply(401,dict(authorizationVersion=1,error='INVALID_CREDENTIAL'))
                        token=authorization[0][7:]
                    # Only verified TLS peer DER supplies trusted-edge certificate metadata.
                    # Incoming CF assertions/certificate flags are never forwarded.
                    status,headers,value=fixture.h.call(self.path,body,self.command,who=None,host='api.wegoh.invalid',
                        origin=self.headers.get('Origin'),session={'cookie':self.headers['Cookie']}if'Cookie'in self.headers else None,
                        csrf=False,bearer=token,certificate=fingerprint)
                    if self.path=='/v1/device-sessions/exchange'and status==200:
                        fixture._credential=value['credentialReceipt']
                        from native_access_codec import decode_response,derive_capability,derive_revoke_capability
                        receipt=value['credentialReceipt']
                        try:
                            decode_response('SESSION_EXCHANGE',status,value,expected_operation_id=body['operationId'])
                            decoded=True
                        except Exception:decoded=False
                        fixture.observations.append(dict(stage='owned-exchange-diagnostic',pythonWireDecoder=decoded,
                            recoveryMatchesVerifier=receipt['recoveryCapability']==derive_capability(body['codeVerifier'],receipt['grantId'],'recovery'),
                            revokeMatchesPrecommit=receipt['revokeCapability']==derive_revoke_capability(body['codeVerifier'],receipt['installationKeyId'],body['operationId']),
                            generation=receipt['generation'],credentialEpoch=receipt['credentialEpoch'],slotRevision=receipt['slotRevision'],consentVersion=receipt['consentVersion'],
                            lifetimeSeconds=receipt['expiresAt']-value['serverTime']))
                    fixture.observations.append(dict(stage='actual-revoke'if self.path=='/v1/device-sessions/revoke'else'actual-native-api',method=self.command,status=status,tls='TLSv1.3',peerVerified=True))
                    with fixture._lock:held=fixture._holds.pop(self.path,None)if self.command=='GET'else None
                    if held:
                        held['status']=status;held['entered'].set()
                        if not held['release'].wait(9):raise TimeoutError('Owned response hold timeout')
                    try:self.reply(status,value,headers)
                    finally:
                        if held:held['completed'].set()
                except NativeAuthorizationError as error:
                    response=error_response(error);self.reply(response.status_code,json.loads(response.body),dict(response.headers))
                except(BrokenPipeError,ConnectionResetError):pass
                except Exception as error:
                    fixture.errors.append(type(error).__name__);self.reply(500,dict(error='OWNED_FIXTURE_FAILURE'))
            do_GET=dispatch
            do_POST=dispatch
            do_PUT=dispatch
        self.http=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.http.socket=tls.wrap_socket(self.http.socket,server_side=True);self.port=self.http.server_port
        self.http_thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.http_thread.start()
        self.events=serve(self._events,'127.0.0.1',0,ssl=tls,compression=None,subprotocols=[PROTOCOL])
        self.events_port=self.events.socket.getsockname()[1]
        self.events_thread=threading.Thread(target=self.events.serve_forever,daemon=True);self.events_thread.start()
        self.seed_social()
        return self

    def hold_next(self,path):
        if path not in('/v1/social/overview','/v1/social/history','/v1/device/functional-permissions'):raise ValueError('Exact held read required')
        value=dict(entered=threading.Event(),release=threading.Event(),completed=threading.Event(),status=None)
        with self._lock:
            if path in self._holds:raise RuntimeError('One held read at a time')
            self._holds[path]=value
        return value

    @staticmethod
    def peer_fingerprint(connection):
        if connection.version()!='TLSv1.3':return None
        der=connection.getpeercert(binary_form=True)
        return hashlib.sha256(der).hexdigest()if der else None

    def approve_pending(self,code):
        status,_,detail=self.h.call('/v1/connections/'+code,session=self.owner)
        if status!=200:raise AssertionError('Owned phone detail rejected')
        value=dict(authorizationVersion=1,consentVersion=detail['consentVersion'],approvedScopes=detail['requestedScopes'],
            keepSignedIn=True,disclosureVersion=detail['disclosureSnapshot']['disclosureVersion'],disclosureSha256=detail['disclosureSnapshot']['disclosureSha256'])
        status,_,_=self.h.call('/v1/connections/'+code,value,'POST',session=self.owner)
        if status!=200:raise AssertionError('Owned explicit approval rejected')
        self.observations.append(dict(stage='synthetic-owner-explicit-approval',status=status))

    def set_purposes(self,purposes):
        if self._credential is None:raise RuntimeError('Exchange required')
        path='/v1/devices/'+self._credential['deviceId']+'/functional-permissions'
        status,_,value=self.h.call(path,session=self.owner)
        if status!=200:raise AssertionError('Owned functional GET rejected')
        body={k:v for k,v in value.items()if k not in('deviceId','expiresAt')}
        body['approvedPurposes']=self.h.web_purposes(value,purposes)
        status,_,value=self.h.call(path,body,'PUT',session=self.owner)
        if status!=200:raise AssertionError('Owned explicit functional PUT rejected')
        self.observations.append(dict(stage='synthetic-owner-functional-consent',status=status,revision=value['revision']))
        return value['revision']

    def seed_social(self):
        status,_,_=self.h.call('/v1/social/friends/requests',dict(targetId=self.peer['user']['id']),'POST',session=self.owner)
        if status!=201:raise AssertionError('Owned friend seed rejected')
        status,_,_=self.h.call('/v1/social/friends/requests/'+self.owner['user']['id']+'/respond',dict(accept=True),'POST',session=self.peer,who='bob')
        if status!=200:raise AssertionError('Owned friend response rejected')
        status,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic SDK room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=self.owner)
        self.observations.append(dict(stage='owned-room-seed',status=status))
        if status!=201:raise AssertionError('Owned room seed rejected')
        self.room_id=room['id']
        status,_,_=self.h.call('/v1/social/rooms/'+self.room_id+'/consents',dict(consents={x:x=='status'for x in('status','location','visits','music','voice','control')}),'PATCH',session=self.owner)
        if status!=200:raise AssertionError('Owned status consent rejected')
        moment=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=10)).isoformat()
        status,_,history=self.h.call('/v1/social/history',dict(title='Synthetic SDK history',startedAt=moment,endedAt=None,courseId=None,courseVersion=None),'POST',session=self.owner)
        if status!=201:raise AssertionError('Owned history seed rejected')
        self.history_id=history['id']

    def _events(self,front):
        remote=None
        try:
            fingerprint=self.peer_fingerprint(front.socket)
            request=front.request;headers=request.headers
            auth=headers.get_all('Authorization')
            if fingerprint is None or request.path!='/v1/events'or len(auth)!=1 or not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}',auth[0])or'Origin'in headers or'Cookie'in headers:
                front.close(1008);return
            # This loopback trusted edge has verified the real peer certificate first.
            sock=socket.create_connection(('127.0.0.1',self.h.port),timeout=5)
            remote=connect('ws://api.wegoh.invalid/v1/events',sock=sock,origin=None,
                additional_headers={'Authorization':auth[0],'cf-cert-sha256':fingerprint,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'},
                open_timeout=5,close_timeout=1,subprotocols=[PROTOCOL])
            if remote.subprotocol != PROTOCOL:
                raise RuntimeError('Product event protocol was not negotiated')
            with self._lock:
                self._remote.add(remote);self._event_number+=1;stream=self._event_number
                self.observations.append(dict(stage='actual-owned-events-open',active=len(self._remote),tls='TLSv1.3',peerVerified=True))
            def client_closed():
                try:
                    for _ in front:front.close(1008);break
                except Exception:pass
                finally:remote.close()
            threading.Thread(target=client_closed,daemon=True).start()
            for message in remote:
                event=json.loads(message)
                self.observations.append(dict(stage='owned-event-forwarded',stream=stream,type=event.get('type'),resources=list(event.get('versions', {}))))
                front.send(message)
        except ConnectionClosed as error:
            code = error.rcvd.code if error.rcvd else 1011
            front.close(code if code in (1008, 4003, 1011) else 1011)
        except Exception:
            # Lease/auth rejection is an unavailable stream; no invented snapshot.
            try:front.close(1008)
            except Exception:pass
        finally:
            if remote:
                with self._lock:
                    self._remote.discard(remote)
                    self.observations.append(dict(stage='actual-owned-events-close',active=len(self._remote)))
                remote.close()

    def __exit__(self,*_):
        with self._lock:remotes=list(self._remote)
        for remote in remotes:remote.close()
        if self.events:self.events.shutdown();self.events_thread.join(5)
        if self.http:self.http.shutdown();self.http.server_close();self.http_thread.join(5)
        self.service.issuer=self._old_issuer
        product_fixture.TeamTests.tearDownClass()
