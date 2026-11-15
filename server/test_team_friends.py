"""Isolated signed-JWT/HTTP/WS/concurrency friendship contracts, no real accounts."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import sys
import time
import unittest

import psycopg
import test_team_auth as auth_fixture


class FriendTests(auth_fixture.TeamTests):
    def friend(self, path, data=None, method='GET', *, who='alice', session=None, **kwargs):
        return self.call('/v1/social'+path,data,method,who=who,session=session,**kwargs)

    def sessions(self):
        return self.login(),self.login('bob'),self.login('eve')

    def request_friend(self, sender, target, who='alice'):
        return self.friend('/friends/requests',dict(targetId=target['user']['id']),'POST',session=sender,who=who)

    def test_10_capabilities_browser_only_strict_inputs(self):
        alice,bob,_=self.sessions()
        # Exercise the declared browser core without freezing unrelated added feature flags.
        capabilities=alice['capabilities'];self.assertTrue(all(type(value)is bool for value in capabilities.values()))
        for key in ('friends','playlists','pairing','rooms','history','historyVisits','historyTraceIngest'):self.assertTrue(capabilities[key],key)
        for key in ('vehicles','historyTraceCapture','historyReplay','historyExport'):self.assertFalse(capabilities[key],key)
        self.assertEqual(self.friend('/overview')[0],401)
        status,_,overview=self.friend('/overview',session=alice)
        self.assertEqual(status,200);self.assertEqual(overview['rooms'],[]);self.assertEqual(overview['history'],[])
        self.assertTrue(overview['capabilities']['friends'])
        _,headers,_=self.call('/v1/auth/session',session=alice)
        csp=next(v for k,v in headers.items() if k.lower()=='content-security-policy')
        self.assertIn("connect-src 'self' wss://web.wegoh.invalid;",csp)
        self.assertNotIn('evil.invalid',csp)
        self.assertNotIn('@example.invalid',json.dumps(overview))
        data=dict(targetId=bob['user']['id'])
        self.assertEqual(self.friend('/friends/requests',data,'POST',session=alice,csrf=False)[0],403)
        self.assertEqual(self.friend('/friends/requests',data,'POST',session=alice,origin='https://evil.invalid')[0],403)
        self.assertEqual(self.friend('/friends/requests',dict(data,ownerId=bob['user']['id']),'POST',session=alice)[0],400)
        self.assertEqual(self.friend('/friends/requests',method='POST',session=alice,raw=b'x'*4097)[0],413)
        self.assertEqual(self.friend('/friends/requests',dict(targetId=alice['user']['id']),'POST',session=alice)[0],400)
        self.assertEqual(self.friend('/friends/requests',dict(targetId='team-'+'0'*40),'POST',session=alice)[0],404)
        _,_,device=self.pair(alice)
        self.assertEqual(self.native('/v1/social/overview',token=device['accessToken'])[0],200)
        self.assertEqual(self.native('/v1/social/friends/requests',data,'POST',device['accessToken'])[0],400)

    def test_11_sender_recipient_and_third_party_authority(self):
        alice,bob,eve=self.sessions();a,b=alice['user']['id'],bob['user']['id']
        self.assertEqual(self.request_friend(alice,bob)[0],201)
        self.assertEqual(self.request_friend(alice,bob)[0],200)
        self.assertEqual(self.friend('/friends/requests/'+b+'/respond',dict(accept=True),'POST',session=alice)[0],404)
        self.assertEqual(self.friend('/friends/requests/'+a+'/respond',dict(accept=True),'POST',session=eve,who='eve')[0],404)
        self.assertEqual(self.friend('/friends/'+a,method='DELETE',session=bob,who='bob')[0],403)
        self.assertEqual(self.friend('/friends/requests/'+a+'/respond',dict(accept=True),'POST',session=bob,who='bob')[0],200)
        self.assertEqual([p['id'] for p in self.friend('/overview',session=alice)[2]['friends']],[b])
        self.assertEqual(self.friend('/overview',session=eve,who='eve')[2]['friends'],[])
        self.assertEqual(self.friend('/friends/'+b,method='DELETE',session=alice)[0],200)
        self.assertEqual(self.friend('/friends/'+b,method='DELETE',session=alice)[0],200)
        self.assertEqual(self.friend('/overview',session=bob,who='bob')[2]['friends'],[])
        # Viewer is allowed to manage its own friendship; admin is not its owner.
        self.assertEqual(self.request_friend(eve,alice,'eve')[0],201)
        self.assertEqual(self.friend('/friends/'+eve['user']['id'],method='DELETE',session=alice)[0],403)

    def test_12_decline_cancel_and_crossed_request(self):
        alice,bob,_=self.sessions();a,b=alice['user']['id'],bob['user']['id']
        self.assertEqual(self.request_friend(alice,bob)[0],201)
        self.assertEqual(self.request_friend(bob,alice,'bob')[0],409)
        self.assertEqual(self.friend('/friends/requests/'+a+'/respond',dict(accept=False),'POST',session=bob,who='bob')[2]['status'],'declined')
        self.assertEqual(self.friend('/friends/requests/'+a+'/respond',dict(accept=False),'POST',session=bob,who='bob')[0],404)
        self.assertEqual(self.request_friend(alice,bob)[0],201)
        self.assertEqual(self.friend('/friends/'+b,method='DELETE',session=alice)[0],200)
        self.assertEqual(self.friend('/overview',session=bob,who='bob')[2]['requests'],[])
        self.assertEqual(self.friend('/friends/requests/'+a+'/respond',dict(accept='true'),'POST',session=bob,who='bob')[0],400)

    def test_13_mutual_blocks_are_individual_and_do_not_restore_friendship(self):
        alice,bob,eve=self.sessions();a,b=alice['user']['id'],bob['user']['id']
        self.request_friend(alice,bob)
        self.assertEqual(self.friend('/blocks',dict(targetId=b),'POST',session=alice)[0],201)
        self.assertEqual(self.friend('/blocks',dict(targetId=b),'POST',session=alice)[0],200)
        self.assertEqual(self.request_friend(bob,alice,'bob')[0],404)
        self.assertNotIn(a,[p['id'] for p in self.friend('/overview',session=bob,who='bob')[2]['people']])
        self.assertEqual(self.friend('/blocks',dict(targetId=a),'POST',session=bob,who='bob')[0],201)
        self.assertEqual(self.friend('/blocks/'+b,method='DELETE',session=alice)[0],200)
        self.assertEqual(self.request_friend(alice,bob)[0],404)
        # A third account cannot remove Bob's block on Alice.
        self.assertEqual(self.friend('/blocks/'+a,method='DELETE',session=eve,who='eve')[0],200)
        self.assertEqual(self.request_friend(alice,bob)[0],404)
        self.assertEqual(self.friend('/blocks/'+a,method='DELETE',session=bob,who='bob')[0],200)
        overview=self.friend('/overview',session=alice)[2]
        self.assertEqual(overview['people'],[]);self.assertEqual(overview['friends'],[]);self.assertEqual(overview['requests'],[])

    def test_14_account_suspension_hides_identity_but_owner_can_clean_relationship(self):
        alice,bob,_=self.sessions();b=bob['user']['id']
        self.request_friend(alice,bob)
        self.write_members([r for r in self.members_rows if r['name']!='bob'])
        self.assertEqual(self.friend('/overview',session=bob,who='bob')[0],403)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s", (b,))
        overview=self.friend('/overview',session=alice)[2]
        self.assertNotIn(b,[p['id'] for p in overview['people']]);self.assertEqual(overview['requests'],[])
        self.assertEqual(self.request_friend(alice,bob)[0],404)
        self.assertEqual(self.friend('/friends/'+b,method='DELETE',session=alice)[0],200)
        self.assertEqual(self.friend('/blocks',dict(targetId=b),'POST',session=alice)[0],201)
        item=self.friend('/overview',session=alice)[2]['blocks'][0]
        self.assertEqual(item,dict(id=b,name=None,available=False))
        self.assertEqual(self.friend('/blocks/'+b,method='DELETE',session=alice)[0],200)

    def test_15_relationship_payload_encryption_tamper_and_unknown_target_no_growth(self):
        alice,bob,eve=self.sessions()
        self.request_friend(alice,bob)
        with psycopg.connect(self.dsn) as conn:
            row=conn.execute('SELECT account_a,account_b,protected FROM team_friend_pairs').fetchone()
        self.assertNotIn(b'pending',bytes(row[2]));self.assertNotIn(b'requestedBy',bytes(row[2]));self.assertNotIn(b'blockedBy',bytes(row[2]))
        for action in ('/friends/','/blocks/'):
            self.assertEqual(self.friend(action+'team-'+'f'*40,method='DELETE',session=alice)[0],404)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_friend_pairs').fetchone()[0],1)
            bad=bytearray(row[2]);bad[-1]^=1
            conn.execute('UPDATE team_friend_pairs SET protected=%s',(bytes(bad),))
        self.assertEqual(self.friend('/overview',session=alice)[0],503)
        self.assertEqual(self.friend('/overview',session=eve,who='eve')[0],200)

    def test_16_concurrent_duplicate_crossed_requests_and_block_race(self):
        alice,bob,_=self.sessions();a,b=alice['user']['id'],bob['user']['id']
        with ThreadPoolExecutor(max_workers=6) as pool:
            statuses=list(pool.map(lambda _:self.request_friend(alice,bob)[0],range(6)))
        self.assertEqual(statuses.count(201),1);self.assertEqual(statuses.count(200),5)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_friend_pairs').fetchone()[0],1)
            conn.execute('TRUNCATE team_friend_pairs')
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls=[pool.submit(self.request_friend,alice,bob),pool.submit(self.request_friend,bob,alice,'bob')]
            self.assertEqual(sorted(f.result()[0] for f in calls),[201,409])
        with psycopg.connect(self.dsn) as conn:conn.execute('TRUNCATE team_friend_pairs')
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls=[pool.submit(self.request_friend,alice,bob),
                   pool.submit(self.friend,'/blocks',dict(targetId=a),'POST',session=bob,who='bob')]
            self.assertTrue(all(f.result()[0] in (201,404) for f in calls))
        self.assertEqual(self.friend('/overview',session=alice)[2]['friends'],[])
        self.assertEqual(self.request_friend(alice,bob)[0],404)

    def test_17_real_websocket_friend_invalidation_and_scope(self):
        alice,bob,eve=self.sessions()
        with self.websocket(bob,who='bob') as receiver, self.websocket(eve,who='eve') as unrelated:
            self.assertEqual(json.loads(receiver.recv(timeout=2))['type'],'snapshot')
            self.assertEqual(json.loads(unrelated.recv(timeout=2))['type'],'snapshot')
            self.assertEqual(self.request_friend(alice,bob)[0],201)
            event=json.loads(receiver.recv(timeout=2))
            # Friendship changes also invalidate bilateral vehicle disclosure.
            self.assertEqual(event['type'],'invalidate');self.assertEqual(event['resources'],['friends','vehicle'])
            self.assertNotIn('alice',json.dumps(event));self.assertNotIn('bob',json.dumps(event))
            with self.assertRaises(TimeoutError):unrelated.recv(timeout=1.2)


def serve_fixture(path, fixture_class=None):
    """Explicit test-only private browser fixture; never a production route."""
    cls=fixture_class or FriendTests;cls.setUpClass()
    tls_server = tls_thread = None
    target=Path(path).absolute()
    try:
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if target.exists():raise RuntimeError('Existing fixture configuration preserved')
        from ops.dev import stage_web
        web=stage_web(cls.state)
        # app StaticFiles and root FileResponse were initialized with this web
        # root; stage the font files into the fixture source only via a new mount.
        from fastapi.staticfiles import StaticFiles
        cls.module.WEB=web
        cls.module.app.router.routes[-1]=type(cls.module.app.router.routes[-1])('/',app=StaticFiles(directory=web,html=True),name='studio')
        helper=cls(methodName='test_10_capabilities_browser_only_strict_inputs')
        accounts=[]
        for who in getattr(cls, 'browser_fixture_accounts', ('alice', 'bob')):
            session=helper.login(who)
            accounts.append(dict(id=session['user']['id'],displayName=session['user']['displayName'],handle=session['user']['handle'],accessJwt=helper.assertion(who,exp=int(time.time())+3600)))
        # Synthetic TLS on a high loopback port; Chromium test-only host mapping
        # preserves the exact logical HTTPS/WSS origin without root/host changes.
        from datetime import datetime, timedelta, timezone
        import ssl
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import threading, uvicorn
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'web.wegoh.invalid')])
        now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('web.wegoh.invalid')]),critical=False)
            .sign(key,hashes.SHA256()))
        certfile,keyfile=cls.state/'fixture.crt',cls.state/'fixture.key'
        for destination,raw in [(certfile,cert.public_bytes(serialization.Encoding.PEM)),
             (keyfile,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))]:
            fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(raw)
        tls_port=auth_fixture.free_port()
        tls_app=cls.tls_application(cls.module.app,accounts)if hasattr(cls,'tls_application')else cls.module.app
        config=uvicorn.Config(tls_app,host='127.0.0.1',port=tls_port,proxy_headers=False,
            access_log=False,log_level='warning',ws='websockets-sansio',ws_max_size=getattr(cls,'websocket_max_size',16777216),
            ssl_keyfile=str(keyfile),ssl_certfile=str(certfile))
        config.load();config.ssl.minimum_version=ssl.TLSVersion.TLSv1_3
        tls_server=uvicorn.Server(config);tls_thread=threading.Thread(target=tls_server.run,daemon=True);tls_thread.start()
        deadline=time.monotonic()+5
        while not tls_server.started and time.monotonic()<deadline:time.sleep(.02)
        if not tls_server.started:raise RuntimeError('Synthetic TLS fixture did not start')
        if hasattr(cls,'prepare_browser_fixture'): cls.prepare_browser_fixture(helper)
        data=dict(mode='isolated-test',baseURL='http://127.0.0.1:'+str(cls.port),origin=auth_fixture.WEB,
            tlsPort=tls_port,hostResolverRules='MAP web.wegoh.invalid 127.0.0.1:'+str(tls_port),accounts=accounts)
        if hasattr(cls,'browser_fixture_metadata'):data['fixtureMetadata']=cls.browser_fixture_metadata
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(data,stream)
        print('ISOLATED_FRIENDS_BROWSER_FIXTURE_READY',flush=True)
        while not target.with_suffix('.stop').exists():
            if hasattr(cls,'fixture_tick'): cls.fixture_tick(helper,target)
            time.sleep(.2)
    finally:
        if tls_server:
            tls_server.should_exit=True;tls_thread.join(5)
        cls.tearDownClass()


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--serve-fixture':serve_fixture(sys.argv[2])
    else:unittest.main(verbosity=2)
