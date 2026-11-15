"""Private purpose key and actual two HTTP peers with DIFFERENT account secrets."""
import http.client,json,os,secrets,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import native_access_issuer_status as bridge
from native_relay_credentials import load_relay_key
from native_authorization import NativeAuthorizationError

class NativeRelayCredentialsTests(unittest.TestCase):
    def test_01_private_exact_key_and_no_account_secret_fallback(self):
        with tempfile.TemporaryDirectory(prefix='wegoh-owned-relay-') as directory:
            key=Path(directory)/'relay.key';original=secrets.token_bytes(32)
            descriptor=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'wb') as stream:stream.write(original)
            self.assertEqual(load_relay_key({'WEGOH_NATIVE_RELAY_KEY_FILE':str(key)}),original)
            with self.assertRaises(RuntimeError):load_relay_key({})
            key.chmod(0o644)
            with self.assertRaises(RuntimeError):load_relay_key({'WEGOH_NATIVE_RELAY_KEY_FILE':str(key)})
            key.chmod(0o600);link=Path(directory)/'link';link.symlink_to(key)
            with self.assertRaises(OSError):load_relay_key({'WEGOH_NATIVE_RELAY_KEY_FILE':str(link)})
            self.assertEqual(key.read_bytes(),original)
        for auth in (SimpleNamespace(secret=b'a'*32),SimpleNamespace(secret=b'a'*32,native_relay_key=b'short')):
            with self.assertRaises(NativeAuthorizationError):bridge.mac(auth,b'request',{})
        with self.assertRaises(NativeAuthorizationError):bridge.mac(SimpleNamespace(native_relay_key=b'r'*32),b'account',{})

    def test_02_different_auth_secrets_actual_two_http_services_use_only_relay_key(self):
        relay=secrets.token_bytes(32)
        main_auth=SimpleNamespace(secret=secrets.token_bytes(48),native_relay_key=relay)
        issuer_auth=SimpleNamespace(secret=secrets.token_bytes(48),native_relay_key=relay)
        self.assertNotEqual(main_auth.secret,issuer_auth.secret)
        old=(main_auth.secret,issuer_auth.secret)
        issuer=SimpleNamespace(require_active_certificate=lambda *args:True)
        issuer_app=FastAPI();issuer_app.include_router(bridge.router(issuer_auth,issuer))
        main_app=FastAPI()
        provenance={'certificateId':'b'*8+'-'+('b'*4+'-')*3+'b'*12,'issuerId':'a'*8+'-'+('a'*4+'-')*3+'a'*12}
        @main_app.get('/owned-check')
        def check():
            try:
                bridge.query_status(main_auth,provenance,'a'*64,'b'*64,'c'*32)
                return {'status':'active'}
            except NativeAuthorizationError:return JSONResponse({'status':'unavailable'},status_code=503)
        import socket
        servers=[];threads=[];ports=[]
        for app in (issuer_app,main_app):
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False,log_level='critical'))
            thread=threading.Thread(target=server.run,daemon=True);thread.start()
            servers.append(server);threads.append(thread);ports.append(port)
        original=http.client.HTTPConnection
        def mapped(host,port=None,*args,**kwargs):return original(host,ports[0] if (host,port)==('127.0.0.1',18083) else port,*args,**kwargs)
        def call(port,path,method='GET',body=None,headers=None):
            connection=original('127.0.0.1',port,timeout=5)
            try:
                connection.request(method,path,body,headers=headers or {})
                response=connection.getresponse();return response.status,json.loads(response.read())
            finally:connection.close()
        try:
            deadline=time.monotonic()+5
            while not all(server.started for server in servers) and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(all(server.started for server in servers))
            with patch.object(bridge.http.client,'HTTPConnection',mapped):
                self.assertEqual(call(ports[1],'/owned-check'),(200,{'status':'active'}))
                issuer_auth.native_relay_key=secrets.token_bytes(32)
                self.assertEqual(call(ports[1],'/owned-check')[0],503)
                issuer_auth.native_relay_key=relay;del main_auth.native_relay_key
                self.assertEqual(call(ports[1],'/owned-check')[0],503)
                main_auth.native_relay_key=relay
                value=dict(version=1,operationId='c'*32,installationKeyId='a'*64,certificateSha256='b'*64,**provenance,timestamp=int(time.time()),nonce=secrets.token_urlsafe(32))
                wrong_purpose=bridge.mac(main_auth,b'response',value)
                self.assertEqual(call(ports[0],bridge.PATH,'POST',bridge.canonical(value),{'Host':'127.0.0.1','Content-Type':'application/json','X-WegoH-Issuer-Proof':wrong_purpose})[0],404)
                self.assertEqual(call(ports[1],'/owned-check')[0],200)
            self.assertEqual((main_auth.secret,issuer_auth.secret),old)
        finally:
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))

if __name__=='__main__':unittest.main()
