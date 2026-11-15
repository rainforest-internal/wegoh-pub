"""Actual local TLS1.3 staged-leaf mTLS handshake, isolated synthetic CA/API."""
import contextlib,hashlib,http.server,io,json,socket,ssl,threading,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID
import test_native_connect as fixture
client=fixture.client
codec=fixture.codec

class NativeRenewalTransportTests(unittest.TestCase):
    setUp=fixture.NativeConnectTest.setUp
    tearDown=fixture.NativeConnectTest.tearDown

    def test_staged_leaf_is_actual_rebind_mtls_and_new_leaf_protects_account_check(self):
        with client.Profile(self.path) as profile:
            api=fixture.RenewalAPI(profile);key_before=(self.path/'identity.pem').read_bytes()
            now=datetime.now(timezone.utc);name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic CA')])
            ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(api.ca.public_key())
                .serial_number(11).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(api.ca,hashes.SHA256()))
            server_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            server=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'isolated API')])).issuer_name(name).public_key(server_key.public_key())
                .serial_number(12).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('enroll-wegoh.devforest.io'),x509.DNSName('api-wegoh.devforest.io')]),False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False).sign(api.ca,hashes.SHA256()))
            ca_file=self.root/'ca.pem';server_file=self.root/'server.pem';server_key_file=self.root/'server.key'
            for path,raw in ((ca_file,ca.public_bytes(serialization.Encoding.PEM)),(server_file,server.public_bytes(serialization.Encoding.PEM)),
                (server_key_file,server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))):client.exclusive(path,raw)
            observations=[];failures=[]
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):self.respond('POST')
                def do_GET(self):self.respond('GET')
                def respond(self,method):
                    try:
                        host='enroll' if self.path.startswith('/v1/connections') or self.path=='/v1/installations/certificate-renew' else 'native'
                        der=self.connection.getpeercert(binary_form=True)
                        fingerprint=hashlib.sha256(der).hexdigest() if der else None
                        observations.append((self.path,self.connection.version(),fingerprint))
                        if host=='native':
                            expected=api.staged if self.path=='/v1/device-sessions/rebind' else api.certificate
                            assert fingerprint==expected['certificateSha256']
                        else:assert fingerprint is None
                        body=None
                        if method=='POST':
                            data=codec.decode_json(self.rfile.read(int(self.headers['Content-Length'])))
                            if self.path.endswith('/claim'):
                                action='CERTIFICATE_RENEW_CLAIM' if any(v['connectionId'] in self.path for v in api.renewals.values()) else 'CONNECTION_CLAIM'
                            else:
                                action=next(k for k,v in client.OPERATIONS.items() if v['host']==host and v['path']==self.path)
                            body=codec.decode_request(action,data)
                        token=self.headers.get('Authorization','').removeprefix('Bearer ') or None
                        status,raw=api(profile,host,self.path,method,body,token)
                    except Exception as error:
                        failures.append(type(error).__name__);status=500;raw=b'{}'
                    self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_3
            context.load_cert_chain(str(server_file),str(server_key_file));context.load_verify_locations(cafile=str(ca_file));context.verify_mode=ssl.CERT_OPTIONAL
            httpd.socket=context.wrap_socket(httpd.socket,server_side=True)
            thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
            original_socket=socket.create_connection;original_context=ssl.create_default_context
            def local(address,*args,**kwargs):return original_socket(('127.0.0.1',httpd.server_port),*args,**kwargs)
            def trusted(*args,**kwargs):return original_context(cafile=str(ca_file))
            try:
                with patch.object(socket,'create_connection',local),patch.object(client.ssl,'create_default_context',trusted),patch.object(client,'wait_for_poll'),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(client.connect(profile,self.args),{'status':'connected'})
                    old=profile.state['certificate']['certificateSha256']
                    self.assertEqual(client.check_with_recovery(profile),{'status':'connected'})
                    current_file=self.path/('certificate-'+profile.state['certificate']['certificateSha256']+'.pem')
                    exact_public=current_file.read_bytes();current_file.unlink()
                    self.assertEqual(client.check_account(profile),{'status':'connected'})
                    self.assertEqual(current_file.read_bytes(),exact_public)
                self.assertEqual(failures,[]);self.assertEqual({version for _,version,_ in observations},{'TLSv1.3'})
                current=profile.state['certificate']['certificateSha256'];self.assertNotEqual(old,current)
                self.assertIn(('/v1/device-sessions/rebind','TLSv1.3',current),observations)
                self.assertEqual([f for path,_,f in observations if path=='/v1/account'][-1],current)
                self.assertEqual(api.issued,2);self.assertEqual((self.path/'identity.pem').read_bytes(),key_before)
            finally:httpd.shutdown();httpd.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()
