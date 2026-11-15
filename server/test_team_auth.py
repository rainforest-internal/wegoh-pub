"""Real HTTP/WS, RSA JWT and isolated PostgreSQL adversarial team-demo contracts.

Run with the pinned server venv. Creates its own disposable cluster and keys;
never connects to WEGOH_DATABASE_DSN or modifies existing Studio/demo state.
Only the test process's JWKS key lookup is replaced with its generated RSA key.
"""
import base64
import hashlib
import http.client
import importlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
WEB = 'https://web.wegoh.invalid'
NATIVE = 'https://api.wegoh.invalid'
ISSUER = 'https://synthetic.cloudflareaccess.com'
AUD = 'synthetic-audience-for-isolated-tests'


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class TeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls=TeamTests
        from ops import dev
        cls.dev = dev
        cls.temporary = tempfile.TemporaryDirectory(prefix='wegoh-team-contract-')
        cls.state = Path(cls.temporary.name)
        cls.tools = dev.pg_tools()
        cls.dbport, cls.port = free_port(), free_port()
        password = secrets.token_urlsafe(48)
        dev.private_file(cls.state / 'db.password', password.encode())
        dev.private_file(cls.state / 'visits.key', os.urandom(32))
        dev.private_file(cls.state / 'native-relay.key', os.urandom(32))
        (cls.state / 'content').mkdir(mode=0o700)
        cls.members_file = cls.state / 'members.json'
        cls.members_rows = [dict(email=name+'@example.invalid', name=name, role=role) for name, role in
                            [('alice','admin'), ('bob','creator'), ('eve','viewer')]]
        cls.write_members(cls.members_rows)
        dev.init_cluster(cls.state / 'postgres', cls.state / 'db.password', cls.tools)
        dev.start_cluster(cls.state / 'postgres', cls.dbport, cls.tools)
        cls.dsn = ' '.join(f'{k}={v}' for k, v in dev.connection(cls.dbport, 'postgres').items()) + ' password=' + password
        with psycopg.connect(cls.dsn) as conn:
            conn.execute((ROOT / 'server/schema.sql').read_text())
            conn.execute((ROOT / 'server/enrollment_schema.sql').read_text())
            conn.execute((ROOT / 'server/native_access_schema.sql').read_text())
            conn.execute((ROOT / 'server/native_functional_schema.sql').read_text())
        cls.api_key = secrets.token_urlsafe(48)
        cls.old_env = dict(os.environ)
        os.environ.update(WEGOH_NATIVE_FUNCTIONAL_ENABLED='1', WEGOH_NATIVE_ACCESS_ENABLED='1',
            WEGOH_RETIRED_ISSUANCE_EXPECTED_COUNT='0', WEGOH_RETIRED_ISSUANCE_EXPECTED_DIGEST='4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945',
            WEGOH_LEGACY_NEW_DEVICE_CUTOFF=str(int(time.time())-1),
            WEGOH_LEGACY_ABSOLUTE_SUNSET=str(int(time.time())+604800), WEGOH_AUTH_MODE='cloudflare', WEGOH_PUBLIC_ORIGIN=WEB,
            WEGOH_NATIVE_RELAY_KEY_FILE=str(cls.state/'native-relay.key'),
            WEGOH_NATIVE_API_ORIGIN=NATIVE, WEGOH_ACCESS_ISSUER=ISSUER, WEGOH_ACCESS_AUD=AUD,
            WEGOH_TEAM_MEMBERS_FILE=str(cls.members_file), WEGOH_API_KEY=cls.api_key,
            WEGOH_DATABASE_DSN=cls.dsn, WEGOH_CONTENT_DIR=str(cls.state/'content'),
            WEGOH_VISIT_KEY_FILE=str(cls.state/'visits.key'), WEGOH_WEB_DIR=str(ROOT/'server/web'))
        os.environ.pop('WEGOH_LOCAL_STUDIO', None)
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.previous_app=sys.modules.pop('app',None)
        cls.previous_api_application=sys.modules.pop('api_application',None)
        cls.module = importlib.import_module('app')
        def test_lookup(token):
            if jwt.get_unverified_header(token).get('kid') != 'synthetic-key':
                raise jwt.InvalidTokenError('Unknown synthetic key')
            return types.SimpleNamespace(key=cls.private.public_key())
        cls.module.TEAM_AUTH.jwks = types.SimpleNamespace(get_signing_key_from_jwt=test_lookup)
        cls.server = uvicorn.Server(uvicorn.Config(cls.module.app, host='127.0.0.1', port=cls.port,
            proxy_headers=False, access_log=False, log_level='warning', ws='websockets'))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(.02)
        if not cls.server.started:
            raise RuntimeError('Synthetic API did not start')

    @classmethod
    def tearDownClass(cls):
        cls=TeamTests
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.dev.stop_cluster(cls.state / 'postgres', cls.tools)
        cls.temporary.cleanup()
        os.environ.clear(); os.environ.update(cls.old_env)
        if sys.modules.get('app') is cls.module:
            sys.modules.pop('app',None)
            if cls.previous_app is not None:sys.modules['app']=cls.previous_app
            sys.modules.pop('api_application',None)
            if cls.previous_api_application is not None:sys.modules['api_application']=cls.previous_api_application

    @classmethod
    def write_members(cls, rows):
        cls.members_file.write_text(json.dumps(rows))
        cls.members_file.chmod(0o600)

    def setUp(self):
        self._native_fingerprint='ab'*32
        self.write_members(self.members_rows)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('TRUNCATE vehicle_enrollment_rate_limits,vehicle_enrollments,native_device_refs,native_v2_operations,native_v2_credentials,native_v2_certificates,native_v2_grants,native_v2_approvals,native_v2_connections,native_v2_installations,team_content_review_events,team_resource_versions,team_socket_leases,team_playlists,team_rate_limits,'
                'team_devices,team_pairings,team_accounts,studio_sessions,visited_places,content_reports,'
                'pack_review_events,pack_reviews,pack_versions CASCADE')

    def assertion(self, who='alice', **changes):
        now = int(time.time())
        claims = dict(iss=ISSUER, aud=AUD, sub='subject-'+who, email=who+'@example.invalid', iat=now, exp=now+300)
        claims.update(changes)
        return jwt.encode(claims, self.private, algorithm='RS256', headers={'kid':'synthetic-key'})

    def call(self, path, data=None, method='GET', *, who='alice', session=None, host='web.wegoh.invalid',
             origin=WEB, csrf=True, assertion=None, bearer=None, raw=None, certificate=None):
        headers = {'Host':host, 'Content-Type':'application/json'}
        if certificate is not None:
            headers.update({'cf-cert-sha256':certificate,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'})
        if who:
            headers['Cf-Access-Jwt-Assertion'] = assertion or self.assertion(who)
        if origin:
            headers['Origin'] = origin
        if session:
            headers['Cookie'] = session['cookie']
            if csrf:
                headers['X-WegoH-CSRF'] = session['csrfToken']
        if bearer:
            headers['Authorization'] = 'Bearer ' + bearer
        payload = raw if raw is not None else json.dumps(data).encode() if data is not None else None
        connection = getattr(self, 'connection_factory', http.client.HTTPConnection)('127.0.0.1', self.port, timeout=5)
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        body = response.read(); status = response.status; values = dict(response.getheaders())
        connection.close()
        try: value = json.loads(body)
        except ValueError: value = body
        return status, values, value

    def login(self, who='alice', *, assertion=None):
        status, headers, value = self.call('/v1/auth/session', method='POST', who=who, assertion=assertion)
        self.assertEqual(status, 200, value)
        cookie = next(v for k,v in headers.items() if k.lower()=='set-cookie')
        self.assertIn('Secure', cookie); self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=strict', cookie)
        value['cookie'] = cookie.split(';',1)[0]
        return value

    def pack(self):
        return dict(schemaVersion=1, id='contract-'+secrets.token_hex(6), version=1, title='Synthetic route',
            author='caller cannot choose author', description='Synthetic GPS contract',
            stops=[dict(id='first',name='Synthetic stop',latitude=37.5,longitude=127.0,radiusMeters=100,
                        action=dict(type='chime',message='Synthetic arrival'))])

    def publish(self, pack, session, who='alice'):
        return self.call('/v1/packs', dict(rightsConfirmed=True,pack=pack), 'POST', session=session, who=who)

    def approve(self, pack, session, *, assertion=None):
        path=f"/v1/moderation/packs/{pack['id']}/versions/{pack['version']}"
        status,_,raw=self.call(path,session=session,assertion=assertion)
        self.assertEqual(status,200)
        canonical=json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        return self.call(path,dict(checksum=hashlib.sha256(canonical).hexdigest(),decision='approved',
            reviewer='ignored caller reviewer',reviewNote='Synthetic one-stop fixture explicitly reviewed'),
            'POST',session=session,assertion=assertion)

    def native(self, path, data=None, method='GET', token=None, certificate=None):
        # Synthetic trusted-edge metadata only; real certificate/TLS contracts use test_native_mtls.
        return self.call(path,data,method,who=None,host='api.wegoh.invalid',origin=None,bearer=token,certificate=certificate or getattr(self,'_native_fingerprint','ab'*32))

    @staticmethod
    def web_purposes(snapshot, purposes):
        receiver = 'device-commands:receive'
        return sorted((set(purposes) - {receiver}) | ({receiver} & set(snapshot['approvedPurposes'])))

    def set_command_receiver(self, credential, enabled, certificate=None):
        path = '/v1/device/command-receiver'
        auth = dict(token=credential['accessToken'], certificate=certificate)
        status, _, state = self.native(path, **auth)
        self.assertEqual(status, 200, state)
        if state['enabled'] != enabled:
            update = dict(grantId=state['grantId'], revision=state['revision'], enabled=enabled)
            status, _, state = self.native(path, update, 'PUT', **auth)
            self.assertEqual(status, 200, state)
        return state

    def pair(self, session, who='alice'):
        # Historical fixture method name only; every request uses the current
        # proof-checked connection/explicit scope consent, never old pair APIs.
        from test_enrollment import SyntheticIssuer,make_csr
        from enrollment_crypto import validate_csr,public_bytes,digest,challenge
        from native_access_codec import derive_revoke_capability,revoke_commitment,decode_request,proof_transcript
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        key,csr=make_csr();key_id=digest(public_bytes(validate_csr(csr).public_key()))
        verifier=secrets.token_urlsafe(32);operation=secrets.token_hex(16)
        scopes=sorted(['account:read','device:self:manage','courses:read','playlists:read'])
        service=self.module.TEAM_NATIVE_AUTHORIZATION;previous=service.issuer;service.issuer=SyntheticIssuer()
        try:
            pending=service.begin(dict(authorizationVersion=1,operationId=operation,name='Synthetic vehicle',csrPem=csr,
                codeChallenge=challenge(verifier),requestedScopes=scopes,revokeCommitment=revoke_commitment(derive_revoke_capability(verifier,key_id,operation))))[1]
            status,_,detail=self.call('/v1/connections/'+pending['userCode'],session=session,who=who)
            self.assertEqual(status,200,detail)
            approval=dict(authorizationVersion=1,consentVersion=detail['consentVersion'],approvedScopes=scopes,keepSignedIn=True,
                disclosureVersion=2,disclosureSha256=detail['disclosureSnapshot']['disclosureSha256'])
            status,_,response=self.call('/v1/connections/'+pending['userCode'],approval,'POST',session=session,who=who)
            self.assertEqual(status,200,response)
            claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=verifier,
                proofNonce=pending['proofNonce'],proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b'=').decode())
            transcript=proof_transcript('CONNECTION_CLAIM',decode_request('CONNECTION_CLAIM',claim),installation_key_id=key_id,
                code_challenge=challenge(verifier),connection_id=pending['connectionId'])
            claim['proof']=base64.urlsafe_b64encode(key.sign(transcript,padding.PKCS1v15(),hashes.SHA256())).rstrip(b'=').decode()
            issued=service.claim(pending['connectionId'],claim)[1]
            self._native_fingerprint=issued['certificateReceipt']['certificateSha256']
            status,_,value=self.native('/v1/device-sessions/exchange',dict(authorizationVersion=1,operationId=secrets.token_hex(16),
                grantId=issued['grantId'],codeVerifier=verifier),'POST')
            self.assertEqual(status,200,value)
            return pending,verifier,value['credentialReceipt']
        finally:service.issuer=previous

    def websocket(self, session=None, *, who='alice', origin=WEB, path='/v1/events', token=None, native=False):
        from websockets.sync.client import connect
        raw = socket.create_connection(('127.0.0.1',self.port), timeout=5)
        headers={}
        if who:headers['Cf-Access-Jwt-Assertion']=self.assertion(who)
        if session:headers['Cookie']=session['cookie']
        if token:headers['Authorization']='Bearer '+token
        if native:headers.update({'cf-cert-sha256':'ab'*32,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'})
        return connect('ws://'+('api' if native else 'web')+'.wegoh.invalid'+path,
                       sock=raw, additional_headers=headers, origin=origin, open_timeout=3, close_timeout=1)

    def test_01_jwt_verification_and_exact_hosts(self):
        self.assertEqual(self.call('/v1/auth/session',who=None)[0],401)
        for changes in [dict(iss='https://wrong.cloudflareaccess.com'),dict(aud='wrong'),dict(exp=int(time.time())-1),dict(iat=int(time.time())+50)]:
            self.assertEqual(self.call('/v1/auth/session',assertion=self.assertion(**changes))[0],401)
        other = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        claims=jwt.decode(self.assertion(),options={'verify_signature':False})
        forged=jwt.encode(claims,other,algorithm='RS256',headers={'kid':'synthetic-key'})
        self.assertEqual(self.call('/v1/auth/session',assertion=forged)[0],401)
        self.assertEqual(self.call('/v1/auth/session',who='outsider')[0],403)
        self.assertEqual(self.call('/v1/auth/session',host='unknown.invalid')[0],404)
        self.assertEqual(self.call('/health/ready',who=None,host='127.0.0.1',origin=None)[0],200)
        self.assertEqual(self.call('/health/ready',method='POST',who=None,host='127.0.0.1',origin=None)[0],404)

    def test_access_new_email_joins_with_existing_product_admin_permissions(self):
        from fastapi import HTTPException

        existing = self.login()
        newcomer = self.assertion('newcomer', type='app', role='viewer')
        path = '/v1/auth/session'
        status, _, before_login = self.call(path, assertion=newcomer, session=existing)
        self.assertEqual(status, 200, before_login)
        self.assertFalse(before_login['authenticated'])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT account_id FROM team_accounts').fetchall(),
                             [(existing['user']['id'],)])

        session = self.login(assertion=newcomer)
        account = session['user']
        self.assertEqual(account['role'], existing['user']['role'])
        self.assertEqual(account['role'], 'admin')
        self.assertNotEqual(account['id'], existing['user']['id'])
        self.assertNotEqual(account['handle'], existing['user']['handle'])
        self.assertTrue(account['displayName'])
        self.assertNotIn('newcomer', account['displayName'].casefold())
        self.assertEqual(self.call(path, assertion=newcomer, session=session)[2]['user'], account)
        self.assertEqual(self.login(assertion=newcomer)['user'], account)
        own_pack = self.pack()
        status, _, published = self.call('/v1/packs', dict(rightsConfirmed=True, pack=own_pack),
                                         'POST', assertion=newcomer, session=session)
        self.assertEqual(status, 201, published)
        other_pack = self.pack()
        self.assertEqual(self.publish(other_pack, existing)[0], 201)
        self.assertEqual(self.approve(other_pack, session, assertion=newcomer)[0], 200)
        self.assertEqual(self.call('/v1/operations/deployment', assertion=newcomer, session=session)[0], 403)
        self.assertEqual(self.call('/v1/operations/deployments', {'requestId': '5f1ca69b-fd9a-4833-b8e1-6ee4400d2117'},
                                  'POST', assertion=newcomer, session=session)[0], 403)
        self.assertEqual(self.call('/v1/connections/ABCDEFGH', assertion=newcomer, session=session)[0], 403)
        with self.assertRaises(HTTPException) as error:
            self.module.TEAM_AUTH.current_account(account['id'], require_roster=True)
        self.assertEqual(error.exception.status_code, 403)
        status, _, updated = self.call('/v1/profile',
            dict(displayName='새 팀원', expectedDisplayName=account['displayName']), 'PUT',
            assertion=newcomer, session=session)
        self.assertEqual(status, 200, updated)
        self.assertEqual(self.login(assertion=newcomer)['user'], dict(account, displayName='새 팀원'))
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_accounts').fetchone(), (2,))

    def reviewer_session(self, domain):
        token = self.assertion('reviewer', type='app', email='reviewer@' + domain)
        original = self.assertion
        self.assertion = lambda who='alice', **changes: token if who == 'reviewer' else original(who, **changes)
        self.addCleanup(vars(self).pop, 'assertion', None)
        return token, self.login(assertion=token)

    def test_reviewer_domain_connects_vehicle_as_creator_without_deployment(self):
        from unittest import mock
        from fastapi import HTTPException
        with mock.patch.dict(os.environ, {'WEGOH_REVIEWER_EMAIL_DOMAINS': ' Reviewer.example ,other.invalid'}):
            token, session = self.reviewer_session('reviewer.example')
            self.assertEqual(session['user']['role'], 'creator')
            self.assertEqual(self.login(assertion=token)['user'], session['user'])
            _, _, credential = self.pair(session, who='reviewer')
            self.assertEqual(self.native('/v1/playlists', token=credential['accessToken'])[0], 200)
            self.assertEqual(self.call('/v1/operations/deployment', assertion=token, session=session)[0], 403)
            self.assertEqual(self.call('/v1/operations/deployments', {'requestId': '5f1ca69b-fd9a-4833-b8e1-6ee4400d2117'},
                                       'POST', assertion=token, session=session)[0], 403)
            with self.assertRaises(HTTPException) as error:
                self.module.TEAM_AUTH.current_account(session['user']['id'], require_roster=True)
            self.assertEqual(error.exception.status_code, 403)

    def test_reviewer_domain_rejects_other_and_sub_domains(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {'WEGOH_REVIEWER_EMAIL_DOMAINS': 'reviewer.example'}):
            for domain in ('example.invalid', 'mail.reviewer.example', 'reviewer.example.invalid'):
                with self.subTest(domain=domain):
                    self.setUp()
                    token, session = self.reviewer_session(domain)
                    self.assertEqual(session['user']['role'], 'admin')
                    self.assertEqual(self.call('/v1/connections/ABCDEFGH', assertion=token, session=session)[0], 403)

    def test_reviewer_domain_unset_keeps_self_enrollment_behavior(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {'WEGOH_REVIEWER_EMAIL_DOMAINS': ''}):
            token, session = self.reviewer_session('reviewer.example')
            self.assertEqual(session['user']['role'], 'admin')
            self.assertEqual(self.call('/v1/connections/ABCDEFGH', assertion=token, session=session)[0], 403)

    def test_access_explicit_roster_role_takes_precedence_over_product_default(self):
        newcomer = self.assertion('newcomer', type='app', role='creator')
        session = self.login(assertion=newcomer)
        self.write_members(self.members_rows + [dict(email='newcomer@example.invalid',
                                                   name='Newcomer', role='viewer')])
        status, _, state = self.call('/v1/auth/session', assertion=newcomer, session=session)
        self.assertEqual(status, 200, state)
        self.assertEqual(state['user']['id'], session['user']['id'])
        self.assertEqual(state['user']['role'], 'viewer')
        self.assertEqual(self.call('/v1/moderation/packs', assertion=newcomer, session=session)[0], 403)
        self.assertEqual(self.login(assertion=newcomer)['user']['role'], 'viewer')

    def test_access_auto_join_rejects_wrong_application_and_invalid_user_identity(self):
        path = '/v1/auth/session'
        wrong_aud = self.assertion('newcomer', type='app', aud='different-application')
        self.assertEqual(self.call(path, method='POST', assertion=wrong_aud)[0], 401)
        forged_claims = jwt.decode(self.assertion('newcomer', type='app'),
                                   options={'verify_signature': False})
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(forged_claims, other_key, algorithm='RS256', headers={'kid':'synthetic-key'})
        self.assertEqual(self.call(path, method='POST', assertion=forged)[0], 401)
        for claims in (dict(type='org'), dict(type='app', email='invalid'), dict(type='app', sub=''),
                       dict(type='app', common_name='synthetic-service')):
            with self.subTest(claims=claims):
                token = self.assertion('newcomer', **claims)
                self.assertIn(self.call(path, method='POST', assertion=token)[0], (401, 403))
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_accounts').fetchone(), (0,))

    def test_access_auto_join_does_not_reactivate_or_reassign_accounts(self):
        path = '/v1/auth/session'
        self.login('bob')
        newcomer = self.assertion('newcomer', type='app')
        session = self.login(assertion=newcomer)
        changed_email = self.assertion('newcomer', type='app', email='other@example.invalid')
        self.write_members([member for member in self.members_rows if member['role'] != 'creator'])

        for token in (self.assertion('bob', type='app'), changed_email):
            status, _, value = self.call(path, method='POST', assertion=token, session=session)
            self.assertEqual((status, value), (403, {'detail':'Team access denied'}))
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s",
                         (session['user']['id'],))
        status, _, value = self.call(path, method='POST', assertion=newcomer, session=session)
        self.assertEqual((status, value), (403, {'detail':'Team access denied'}))

    def test_02_cookie_origin_csrf_owner_logout(self):
        session=self.login()
        self.assertTrue(self.call('/v1/auth/session',session=session)[2]['authenticated'])
        self.assertFalse(self.call('/v1/auth/session',who='bob',session=session)[2]['authenticated'])
        self.assertEqual(self.call('/v1/auth/session',method='POST',origin='https://evil.invalid')[0],403)
        self.assertEqual(self.call('/v1/auth/session',method='DELETE',session=session,csrf=False)[0],403)
        self.assertEqual(self.call('/v1/auth/session',method='DELETE',session=session,origin='https://evil.invalid')[0],403)
        self.assertEqual(self.call('/v1/auth/session',method='DELETE',session=session)[0],200)
        self.assertFalse(self.call('/v1/auth/session',session=session)[2]['authenticated'])
        self.assertEqual(self.call('/v1/studio/session',method='POST',session=session)[0],404)
        self.assertEqual(self.call('/v1/local/visits',{},'POST',session=session)[0],404)

    def test_03_course_owner_roles_direct_publication_and_report_gate(self):
        alice,bob,eve=self.login(),self.login('bob'),self.login('eve')
        pack=self.pack()
        self.assertEqual(self.publish(pack,alice)[0],201)
        self.assertEqual(self.publish(pack,bob,'bob')[0],409)
        pack['version']=2
        self.assertEqual(self.publish(pack,bob,'bob')[0],409)
        pack['version']=1
        self.assertEqual(self.publish(self.pack(),eve,'eve')[0],403)
        self.assertEqual(len(self.call('/v1/studio/packs',session=alice)[2]['packs']),1)
        self.assertEqual(self.call('/v1/studio/packs',session=bob,who='bob')[2]['packs'],[])
        own=f"/v1/studio/packs/{pack['id']}/versions/1"
        self.assertEqual(self.call(own,session=alice)[0],200)
        self.assertEqual(self.call(own,session=bob,who='bob')[0],404)
        public=f"/v1/packs/{pack['id']}/versions/1"
        self.assertEqual(self.call(public,session=alice)[0],200)
        self.assertEqual(self.call('/v1/moderation/packs',session=bob,who='bob')[0],403)
        self.assertEqual(self.approve(pack,alice)[0],200)
        self.assertEqual(self.call(public,session=bob,who='bob')[2]['author'],alice['user']['displayName'])
        self.assertEqual(self.call('/v1/packs',who=None)[0],401)
        self.assertEqual(self.call(public+'/reports',dict(reason='privacy'),'POST',session=bob,who='bob')[0],202)
        self.assertEqual(self.call(public,session=alice)[0],404)

    def test_04_private_visits_even_admin_cannot_read_other(self):
        from private_records import VisitCipher
        alice,bob=self.login(),self.login('bob')
        value=dict(place=dict(id='synthetic-place',provider='synthetic',name='Private synthetic place',address='',latitude=37.5,longitude=127),visitedAt=1700000000000)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('INSERT INTO visited_places(visit_id,creator_id,place,visited_at,protected) VALUES(%s,%s,NULL,1,%s)',
                ('visit',bob['user']['id'],VisitCipher().protect(bob['user']['id'],'visit',value)))
        self.assertEqual(self.call('/v1/places/visited',session=alice)[2]['places'],[])
        self.assertEqual(len(self.call('/v1/places/visited',session=bob,who='bob')[2]['places']),1)
        self.assertEqual(self.call('/v1/places/visited',method='DELETE',session=alice)[0],200)
        self.assertEqual(len(self.call('/v1/places/visited',session=bob,who='bob')[2]['places']),1)



    def test_07_encrypted_playlist_owner_revision_order_and_native_read(self):
        alice,bob=self.login(),self.login('bob')
        data=dict(name='Private commute',tracks=[dict(title='Private song',url='https://music.example.invalid/listen/1')])
        self.assertEqual(self.call('/v1/playlists',data,'POST',session=alice,csrf=False)[0],403)
        status,_,playlist=self.call('/v1/playlists',data,'POST',session=alice)
        self.assertEqual(status,201,playlist)
        path='/v1/playlists/'+playlist['id']
        self.assertEqual(self.call(path,session=bob,who='bob')[0],404)
        self.assertEqual(self.call(path,dict(data,revision=1),'PUT',session=bob,who='bob')[0],404)
        self.assertEqual(self.call(path,method='DELETE',session=bob,who='bob')[0],404)
        updated=dict(name='New list',tracks=[dict(title='Second',url='https://music.example.invalid/2'),dict(title='First',url='https://music.example.invalid/1')],revision=1)
        self.assertEqual(self.call(path,updated,'PUT',session=alice)[2]['revision'],2)
        self.assertEqual(self.call(path,updated,'PUT',session=alice)[0],409)
        bad=dict(name='Bad',tracks=[dict(title='Invalid',url='javascript:alert(1)')])
        self.assertEqual(self.call('/v1/playlists',bad,'POST',session=alice)[0],400)
        _,_,token=self.pair(alice)
        native=self.native(path,token=token['accessToken'])
        self.assertEqual(native[0],200)
        self.assertEqual([t['title'] for t in native[2]['tracks']],['Second','First'])
        with psycopg.connect(self.dsn) as conn:
            raw=conn.execute('SELECT protected FROM team_playlists').fetchone()[0]
        self.assertNotIn(b'New list',bytes(raw));self.assertNotIn(b'music.example',bytes(raw))
        self.assertEqual(self.call(path,method='DELETE',session=alice)[0],200)

    def test_08_rate_and_ephemeral_metadata_pruning(self):
        auth=self.module.TEAM_AUTH
        for _ in range(2):auth.rate('synthetic-limited',limit=2)
        with self.assertRaises(Exception) as error:auth.rate('synthetic-limited',limit=2)
        self.assertEqual(error.exception.status_code,429)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('INSERT INTO team_rate_limits VALUES(%s,%s,1)',('0'*64,int(time.time())//60-3))
        auth.rate('cleanup',limit=2)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_rate_limits WHERE scope_hash=%s',('0'*64,)).fetchone()[0],0)

    def test_09_websocket_origin_snapshot_owner_filter_reconnect_and_revoke(self):
        from websockets.exceptions import InvalidStatus, ConnectionClosed
        alice,bob=self.login(),self.login('bob')
        for origin,path in [('https://evil.invalid','/v1/events'),(WEB,'/v1/events?token=forbidden')]:
            with self.assertRaises(InvalidStatus):self.websocket(alice,origin=origin,path=path)
        with self.websocket(alice) as connection:
            snapshot=json.loads(connection.recv(timeout=2))
            self.assertEqual(snapshot['type'],'snapshot');self.assertEqual(snapshot['seq'],0)
            self.call('/v1/playlists',dict(name='B private',tracks=[]),'POST',who='bob',session=bob)
            with self.assertRaises(TimeoutError):connection.recv(timeout=1.3)
            self.call('/v1/playlists',dict(name='A private',tracks=[]),'POST',session=alice)
            event=json.loads(connection.recv(timeout=2))
            self.assertEqual(event['type'],'invalidate');self.assertEqual(event['resources'],['playlists'])
            self.assertNotIn('private',json.dumps(event))
            self.call('/v1/auth/session',method='DELETE',session=alice)
            with self.assertRaises(ConnectionClosed):connection.recv(timeout=2)
        alice=self.login()
        with self.websocket(alice) as connection:
            current=json.loads(connection.recv(timeout=2))
            self.assertEqual(current['seq'],0);self.assertNotEqual(current['epoch'],snapshot['epoch'])


if __name__=='__main__':
    unittest.main(verbosity=2)
