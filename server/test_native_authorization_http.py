"""Actual HTTP/WS routes with synthetic Access JWT, edge metadata and private PG.
TLS/Cloudflare edge/real issuance are separate acceptance stages, not claimed here.
"""
import base64
import http.client
import json
import os
import secrets
import socket
import threading
import time
import unittest
from unittest.mock import patch
import psycopg
import uvicorn
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
import test_team_auth as fixture
from test_enrollment import SyntheticIssuer, make_csr
from enrollment_app import create_app
from enrollment_crypto import challenge, digest, public_bytes, validate_csr
from native_access_codec import decode_request, proof_transcript, decode_phone_response, derive_revoke_capability
from team_data import changed
from native_authorization import NativeAuthorizationError, protect, restore, hash_secret

class NativeAuthorizationHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        cls.addClassCleanup(fixture.TeamTests.tearDownClass)
        cls.api=fixture.TeamTests("test_01_jwt_verification_and_exact_hosts")
        cls.auth=fixture.TeamTests.module.TEAM_AUTH
        cls.main=fixture.TeamTests.module.TEAM_NATIVE_AUTHORIZATION
        old=os.environ.get("WEGOH_ENROLLMENT_ORIGIN")
        os.environ["WEGOH_ENROLLMENT_ORIGIN"]="https://enroll-wegoh.devforest.io"
        def restore_env():
            if old is None:os.environ.pop("WEGOH_ENROLLMENT_ORIGIN",None)
            else:os.environ["WEGOH_ENROLLMENT_ORIGIN"]=old
        cls.addClassCleanup(restore_env)
        cls.issuer=SyntheticIssuer()
        cls.enrollment=create_app(cls.auth,cls.issuer)
        cls.bootstrap=cls.enrollment.state.native_authorization
        cls.port=fixture.free_port()
        cls.server=uvicorn.Server(uvicorn.Config(cls.enrollment,host="127.0.0.1",port=cls.port,
            proxy_headers=False,access_log=False,log_level="critical"))
        cls.thread=threading.Thread(target=cls.server.run,daemon=True);cls.thread.start()
        cls.addClassCleanup(cls.stop)
        deadline=time.monotonic()+5
        while not cls.server.started and time.monotonic()<deadline:time.sleep(.02)
        if not cls.server.started:raise RuntimeError("Owned authorization bootstrap failed")

    @classmethod
    def stop(cls):
        cls.server.should_exit=True;cls.thread.join(5)
        if cls.thread.is_alive():raise RuntimeError("Owned bootstrap did not stop")

    def setUp(self):
        with psycopg.connect(self.auth.dsn) as conn:
            conn.execute("TRUNCATE native_v2_operations,native_v2_credentials,native_v2_certificates,"
                "native_v2_grants,native_v2_approvals,native_v2_connections,native_v2_installations CASCADE")
        self.api.setUp()
        self.session=self.api.login()
        self.key,self.csr=make_csr()
        self.key_id=digest(public_bytes(validate_csr(self.csr).public_key()))
        self.verifier=secrets.token_urlsafe(32)
        self.challenge=challenge(self.verifier)
        self.scopes=sorted(["account:read","courses:read","device:self:manage"])
        self.issuer.calls=0;self.issuer.crash=False;self.issuer.after_issue=None
        self.issuer.issue=SyntheticIssuer.issue.__get__(self.issuer,type(self.issuer))
        self.issuer.response=SyntheticIssuer.response.__get__(self.issuer,type(self.issuer))
        for name in ('reconcile','require_active_certificate'):
            self.issuer.__dict__.pop(name,None)

    def enroll(self,path,value,host="enroll-wegoh.devforest.io",extra=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.port,timeout=5)
        headers={"Host":host,"Content-Type":"application/json"}
        headers.update(extra or {})
        connection.request("POST",path,body=json.dumps(value).encode(),headers=headers)
        response=connection.getresponse();raw=response.read();status=response.status;connection.close()
        return status,json.loads(raw)

    def native(self,path,value=None,method="GET",token=None,certificate=None):
        return self.api.native(path,value,method,token=token,certificate=certificate or self.fingerprint)

    def start(self, **browser_options):
        begin=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Owned test vehicle",
            csrPem=self.csr,codeChallenge=self.challenge,requestedScopes=self.scopes)
        self.begin_operation_id=begin["operationId"]
        self.revoke_capability=derive_revoke_capability(self.verifier,self.key_id,self.begin_operation_id)
        begin["revokeCommitment"]=hash_secret("revoke",self.revoke_capability)
        status,pending=self.enroll("/v1/connections",begin);self.assertEqual(status,201,pending)
        code=pending["userCode"]
        status,_,detail=self.api.call("/v1/connections/"+code,session=self.session,**browser_options)
        self.assertEqual(status,200,detail)
        body=dict(authorizationVersion=1,consentVersion=detail["consentVersion"],
            approvedScopes=self.scopes,keepSignedIn=True,disclosureVersion=2,
            disclosureSha256=detail["disclosureSnapshot"]["disclosureSha256"])
        return pending,body

    def issued_without_exchange(self):
        pending,approval=self.start()
        status,_,value=self.api.call("/v1/connections/"+pending["userCode"],approval,"POST",session=self.session)
        self.assertEqual(status,200,value)
        return self.claim(pending)

    def claim(self, pending):
        claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            codeVerifier=self.verifier,proofNonce=pending["proofNonce"],
            proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        message=proof_transcript("CONNECTION_CLAIM",decode_request("CONNECTION_CLAIM",claim),
            installation_key_id=self.key_id,code_challenge=self.challenge,connection_id=pending["connectionId"])
        claim["proof"]=base64.urlsafe_b64encode(self.key.sign(message,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        status,issued=self.enroll("/v1/connections/"+pending["connectionId"]+"/claim",claim)
        self.assertEqual(status,200,issued)
        self.fingerprint=issued["certificateReceipt"]["certificateSha256"]
        return issued

    def connected(self):
        return self.exchange(self.issued_without_exchange())

    def exchange(self, issued):
        exchange=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],codeVerifier=self.verifier)
        status,_,connected=self.native("/v1/device-sessions/exchange",exchange,"POST")
        self.assertEqual(status,200,connected)
        return connected["credentialReceipt"]

    def assert_default_history_permissions(self, receipt):
        path = "/v1/social/history"
        token = receipt["accessToken"]
        record = dict(title="Synthetic owner history", startedAt="2026-10-01T12:00:00Z",
                      endedAt=None, courseId=None, courseVersion=None)
        status, _, own = self.api.call(path, record, "POST", session=self.session)
        self.assertEqual(status, 201, own)
        bob = self.api.login("bob")
        status, _, private = self.api.call(path, dict(record, title="Synthetic private history"),
                                          "POST", who="bob", session=bob)
        self.assertEqual(status, 201, private)

        status, _, listing = self.native(path, token=token)
        self.assertEqual(status, 200, listing)
        self.assertEqual(set(listing), {"history", "friends", "nextCursor", "nativeReadOnly", "capabilities"})
        self.assertIs(listing["nativeReadOnly"], True)
        self.assertEqual(listing["friends"], [])
        self.assertIsNone(listing["nextCursor"])
        self.assertEqual(listing["capabilities"], dict(history=True, historyRemix=False, historyTraceIngest=False,
            historyPhotos=False, historyPhotoUpload=False, historyReplay=True, historyExport=False, cautions=False))
        self.assertEqual([item["id"] for item in listing["history"]], [own["id"]])
        item = listing["history"][0]
        self.assertEqual(item["ownerId"], receipt["accountId"])
        self.assertIs(item["own"], True)
        self.assertEqual(item["sharedWith"], [])
        self.assertIsNone(item["permissionRevision"])
        private_path = path + "/" + private["id"]
        self.assertEqual(self.native(private_path, token=token)[0], 404)
        self.assertEqual(self.native(private_path, dict(record, revision=private["revision"], functionalRevision=1),
                                     "PUT", token=token)[0], 404)

        status, _, created = self.native(path, dict(record, functionalRevision=1), "POST", token=token)
        self.assertEqual(status, 201, created)
        created_path = path + "/" + created["id"]
        status, _, saved = self.native(created_path, token=token)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["ownerId"], receipt["accountId"])
        self.assertEqual(saved["source"]["kind"], "device-reported")

        status, _, permission = self.api.call(created_path + "/permissions",
            dict(permissionRevision=created["permissionRevision"], collectTrace=True), "PATCH", session=self.session)
        self.assertEqual(status, 200, permission)
        self.assertIs(permission["permissions"]["collectTrace"], True)
        batch = dict(revision=created["revision"], batchId="a"*32, streamId="b"*32, label="Synthetic trace",
                     points=[dict(latitude=37.0, longitude=127.0, capturedAt=record["startedAt"], accuracyMeters=5)],
                     functionalRevision=1)
        self.assertEqual(self.native(created_path + "/trace-batches", batch, "POST", token=token)[0], 403)

    def ws(self,token):
        raw=socket.create_connection(("127.0.0.1",fixture.TeamTests.port),timeout=5)
        return connect("ws://api.wegoh.invalid/v1/events",sock=raw,origin=None,open_timeout=3,close_timeout=1,
            additional_headers={"Authorization":"Bearer "+token,"cf-cert-sha256":self.fingerprint,
                "cf-cert-presented":"true","cf-cert-verified":"true","cf-cert-revoked":"false"})

    def test_01_real_browser_consent_requires_session_csrf_and_enroll_host_is_closed(self):
        pending,approval=self.start();path="/v1/connections/"+pending["userCode"]
        self.assertEqual(self.api.call(path)[0],401)
        self.assertEqual(self.api.call(path,approval,"POST",session=self.session,csrf=False)[0],403)
        self.assertEqual(self.api.call(path,dict(approval,disclosureVersion=1),"POST",session=self.session)[0],409)
        self.assertEqual(self.api.call(path,dict(approval,disclosureSha256='0'*64),"POST",session=self.session)[0],409)
        self.assertEqual(self.api.call(path,approval,"POST",session=self.session,origin="https://evil.invalid")[0],403)
        self.assertEqual(self.enroll("/v1/connections",{},extra={"Authorization":"Bearer "+secrets.token_urlsafe(32)})[0],404)
        self.assertEqual(self.issuer.calls,0)

    def test_01a_iphone_decision_and_owner_revocation_reuse_vehicle_credentials(self):
        pending, approval = self.start()
        code = pending['userCode']
        owner = self.session['user']
        other = self.api.login('bob')['user']

        def assert_error(status, expected, function, *args, **kwargs):
            with self.assertRaises(NativeAuthorizationError) as failure:
                function(*args, **kwargs, account_decision=True)
            self.assertEqual((failure.exception.status, failure.exception.code), (status, expected))

        detail = self.main.detail(code, owner, account_decision=True)
        self.assertEqual((detail['state'], detail['userCode'], detail['deviceName']),
                         ('PENDING', code, 'Owned test vehicle'))
        self.assertEqual(detail['expiresAt'], pending['expiresAt'])
        self.assertEqual(detail['requestedScopes'], self.scopes)
        self.assertEqual(self.main.list_owned_devices(owner['id']), [])
        unknown = ('B' if code[0] == 'A' else 'A') + code[1:]
        assert_error(404, 'OPERATION_NOT_FOUND', self.main.detail, unknown, owner)
        assert_error(409, 'CONSENT_CHANGED', self.main.approve, code,
                     dict(approval, disclosureSha256='0' * 64), owner)
        with patch.object(self.main, 'clock', return_value=pending['expiresAt']):
            assert_error(410, 'AUTHORIZATION_EXPIRED', self.main.detail, code, owner)
            assert_error(410, 'AUTHORIZATION_EXPIRED', self.main.approve, code, approval, owner)

        self.assertEqual(self.main.approve(code, approval, owner, account_decision=True)['state'], 'APPROVED')
        assert_error(409, 'OPERATION_CONFLICT', self.main.approve, code, approval, owner)
        assert_error(409, 'OPERATION_CONFLICT', self.main.approve, code,
                     {'authorizationVersion': 1}, owner, deny=True)
        assert_error(404, 'OPERATION_NOT_FOUND', self.main.detail, code, other)
        assert_error(404, 'OPERATION_NOT_FOUND', self.main.approve, code, approval, other)
        self.assertEqual(self.main.detail(code, owner, account_decision=True)['state'], 'APPROVED')
        self.assertEqual(self.main.list_owned_devices(owner['id']), [])

        credential = self.exchange(self.claim(pending))
        device = credential['deviceId']
        token = credential['accessToken']
        self.assertEqual([row['id'] for row in self.main.list_owned_devices(owner['id'])], [device])
        self.assertEqual(self.main.list_owned_devices(other['id']), [])
        self.assertFalse(self.main.revoke_owned_device(other['id'], device))
        self.assertEqual(self.native('/v1/account', token=token)[0], 200)
        self.assertTrue(self.main.revoke_owned_device(owner['id'], device))
        self.assertFalse(self.main.revoke_owned_device(owner['id'], device))
        self.assertEqual(self.main.list_owned_devices(owner['id']), [])
        self.assertEqual(self.native('/v1/account', token=token)[0], 401)

    def test_01b_iphone_decline_reconciles_to_denied(self):
        pending, _ = self.start()
        code = pending['userCode']
        owner = self.session['user']
        value = {'authorizationVersion': 1}
        self.assertEqual(self.main.approve(code, value, owner, deny=True, account_decision=True),
                         dict(value, state='DENIED', userCode=code))
        with self.assertRaises(NativeAuthorizationError) as failure:
            self.main.approve(code, value, owner, deny=True, account_decision=True)
        self.assertEqual((failure.exception.status, failure.exception.code), (409, 'OPERATION_CONFLICT'))
        self.assertEqual(self.main.detail(code, owner, account_decision=True)['state'], 'DENIED')
        self.assertEqual(self.issuer.calls, 0)

    def test_02_real_rest_scope_and_revoked_unknown_tokens_never_gain_legacy_access(self):
        receipt=self.connected();token=receipt["accessToken"]
        status,_,account=self.native("/v1/account",token=token)
        self.assertEqual(status,200,account);self.assertNotIn("role",account["user"])
        status,_,permissions=self.native("/v1/device/permissions",token=token)
        self.assertEqual(status,200,permissions);self.assertTrue(permissions["keepSignedIn"])
        self.assertEqual(permissions["scopes"],self.scopes)
        self.assertEqual(self.native("/v1/playlists",token=token)[0],403)
        self.assert_default_history_permissions(receipt)
        self.assertEqual(self.native("/v1/account",token=secrets.token_urlsafe(32))[0],401)
        refresh=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=receipt["grantId"],
            deviceId=receipt["deviceId"],refreshToken=receipt["refreshToken"])
        status,_,fresh=self.native("/v1/device-sessions/refresh",refresh,"POST");self.assertEqual(status,200,fresh)
        self.assertEqual(self.native("/v1/account",token=token)[0],401)
        new=fresh["credentialReceipt"]
        self.assertEqual(self.native("/v1/device",method="DELETE",token=new["accessToken"])[0],200)
        self.assertEqual(self.native("/v1/account",token=new["accessToken"])[0],401)

    def test_03_real_websocket_hides_unapproved_resources_and_closes_after_refresh(self):
        receipt=self.connected()
        with self.ws(receipt["accessToken"]) as channel:
            snapshot=json.loads(channel.recv(timeout=2))
            self.assertEqual(snapshot["resources"],["courses","devices"])
            self.assertEqual(snapshot["seq"],0)
            with psycopg.connect(self.auth.dsn) as conn:changed(conn,receipt["accountId"],"playlists")
            with self.assertRaises(TimeoutError):channel.recv(timeout=.3)
            with psycopg.connect(self.auth.dsn) as conn:changed(conn,receipt["accountId"],"courses")
            visible=json.loads(channel.recv(timeout=3))
            self.assertEqual((visible["resources"],visible["seq"]),(["courses"],1))
            refresh=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=receipt["grantId"],
                deviceId=receipt["deviceId"],refreshToken=receipt["refreshToken"])
            self.assertEqual(self.native("/v1/device-sessions/refresh",refresh,"POST")[0],200)
            with self.assertRaises(ConnectionClosed):channel.recv(timeout=3)

    def test_04_zero_or_single_required_scope_is_denied_before_websocket_101(self):
        receipt=self.connected()
        for scopes in ([],['account:read'],['device:self:manage']):
            with self.subTest(scopes=scopes):
                with psycopg.connect(self.auth.dsn) as conn:
                    raw=conn.execute('SELECT protected_consent FROM native_v2_grants WHERE grant_id=%s',
                        (receipt['grantId'],)).fetchone()[0]
                    consent=restore('consent',receipt['grantId'],raw);consent['scopes']=scopes
                    conn.execute('UPDATE native_v2_grants SET protected_consent=%s WHERE grant_id=%s',
                        (protect('consent',receipt['grantId'],consent),receipt['grantId']))
                with self.assertRaises(InvalidStatus) as error:self.ws(receipt['accessToken'])
                self.assertEqual(error.exception.response.status_code,403)

    def test_05_exact_public_wire_asset_requires_access_and_is_not_native_route(self):
        status,headers,value=self.api.call('/native-access-wire.json',session=self.session)
        self.assertEqual(status,200)
        expected=json.loads((fixture.ROOT/'server/native_access_wire.json').read_text())
        self.assertEqual(value,expected)
        self.assertEqual(self.api.call('/native-access-wire.json',who=None)[0],401)
        self.fingerprint='ab'*32
        self.assertEqual(self.native('/native-access-wire.json')[0],404)

    def test_06_explicit_phone_denial_matches_closed_phone_dto_and_never_issues(self):
        pending,_=self.start()
        status,_,value=self.api.call('/v1/connections/'+pending['userCode'],
            dict(authorizationVersion=1),'DELETE',session=self.session)
        self.assertEqual(status,200,value)
        self.assertEqual(decode_phone_response('PHONE_DENY',value,expected_user_code=pending['userCode']).for_transport(),value)
        self.assertEqual(set(value),{'authorizationVersion','state','userCode'})
        self.assertEqual(self.issuer.calls,0)


    def test_07_browser_owner_device_list_remote_revoke_preserves_other_account_and_history(self):
        alice=self.connected();alice_session=self.session
        original_call=self.api.call
        self.addCleanup(lambda:setattr(self.api,"call",original_call))
        self.api.call=lambda *args,**kwargs:original_call(*args,**dict({"who":"bob"},**kwargs))
        self.session=self.api.login("bob")
        self.key,self.csr=make_csr();self.key_id=digest(public_bytes(validate_csr(self.csr).public_key()))
        self.verifier=secrets.token_urlsafe(32);self.challenge=challenge(self.verifier)
        bob=self.connected();bob_session=self.session
        self.api.call=original_call;self.session=alice_session
        status,_,listing=self.api.call("/v1/devices",session=alice_session)
        self.assertEqual(status,200,listing)
        self.assertEqual({d["id"] for d in listing["devices"]},{alice["deviceId"]})
        self.assertEqual(listing["devices"][0]["authorizationVersion"],1)
        self.assertIsNone(listing["devices"][0]["lastUsedAt"])
        status,_,listing_b=self.api.call("/v1/devices",session=bob_session,who="bob")
        self.assertEqual(status,200,listing_b)
        self.assertEqual({d["id"] for d in listing_b["devices"]},{bob["deviceId"]})
        target="/v1/devices/"+alice["deviceId"]
        self.assertEqual(self.api.call(target,method="DELETE",session=bob_session,who="bob")[0],404)
        self.assertEqual(self.api.call(target,method="DELETE",session=alice_session,csrf=False)[0],403)
        visit="preserved-"+secrets.token_hex(8);protected=protect("synthetic-history",visit,{"note":"Original trip"})
        with psycopg.connect(self.auth.dsn) as conn:
            conn.execute("INSERT INTO visited_places(visit_id,creator_id,visited_at,protected) VALUES(%s,%s,%s,%s)",
                (visit,alice["accountId"],int(time.time()),protected))
        self.fingerprint=alice["certificateSha256"]
        with self.ws(alice["accessToken"]) as channel:
            self.assertEqual(json.loads(channel.recv(timeout=2))["type"],"snapshot")
            self.assertEqual(self.api.call(target,method="DELETE",session=alice_session)[0],200)
            with self.assertRaises(ConnectionClosed):channel.recv(timeout=3)
        self.assertEqual(self.native("/v1/account",token=alice["accessToken"])[0],401)
        self.assertEqual(self.native("/v1/account",token=bob["accessToken"],certificate=bob["certificateSha256"])[0],200)
        with psycopg.connect(self.auth.dsn) as conn:
            self.assertEqual(bytes(conn.execute("SELECT protected FROM visited_places WHERE visit_id=%s",(visit,)).fetchone()[0]),protected)
            row=conn.execute("SELECT account_id,protected_consent,recovery_hash FROM native_v2_grants WHERE grant_id=%s",
                (alice["grantId"],)).fetchone();self.assertEqual(row,(None,None,None))
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_certificates").fetchone()[0],2)
        self.assertEqual(self.api.call("/v1/devices",session=alice_session)[2]["devices"],[])

    def test_08_browser_optional_scope_cut_closes_socket_and_recovers_subset_without_qr(self):
        receipt=self.connected();path="/v1/devices/"+receipt["deviceId"]+"/permissions"
        status,_,value=self.api.call(path,session=self.session);self.assertEqual(status,200,value)
        self.assertEqual(value["scopes"],self.scopes);self.assertNotIn("permissions",value)
        subset=["account:read","device:self:manage"]
        body=dict(revision=value["revision"],scopes=subset)
        duplicate=('{"revision":1,"revision":1,"scopes":'+json.dumps(subset)+'}').encode()
        self.assertEqual(self.api.call(path,method="PUT",session=self.session,raw=duplicate)[0],400)

        self.assertEqual(self.api.call(path,body,"PUT",session=self.session,csrf=False)[0],403)
        self.assertEqual(self.api.call(path,dict(revision=value["revision"],scopes=sorted(self.scopes+["playlists:read"])),
            "PUT",session=self.session)[0],403)
        with self.ws(receipt["accessToken"]) as channel:
            channel.recv(timeout=2)
            status,_,reduced=self.api.call(path,body,"PUT",session=self.session)
            self.assertEqual(status,200,reduced);self.assertEqual(reduced["scopes"],subset)
            self.assertEqual(reduced["grantExpiresAt"],receipt["grantExpiresAt"])
            with self.assertRaises(ConnectionClosed):channel.recv(timeout=3)
        self.assertEqual(self.native("/v1/account",token=receipt["accessToken"])[0],401)
        recover=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=receipt["grantId"],
            deviceId=receipt["deviceId"],recoveryCapability=receipt["recoveryCapability"])
        status,_,result=self.native("/v1/device-sessions/recover",recover,"POST")
        self.assertEqual(status,200,result);fresh=result["credentialReceipt"]
        self.assertEqual(fresh["scopes"],subset);self.assertEqual(fresh["grantExpiresAt"],receipt["grantExpiresAt"])
        self.assertEqual(self.native("/v1/packs",token=fresh["accessToken"])[0],403)
        status,_,terminal=self.api.call(path,dict(revision=reduced["revision"],scopes=[]),"PUT",session=self.session)
        self.assertEqual(status,200,terminal);self.assertEqual(terminal["status"],"revoked")
        self.assertEqual(self.native("/v1/account",token=fresh["accessToken"])[0],401)



    def test_09_http_exchange_complete_response_loss_then_cap_only_logout(self):
        issued=self.issued_without_exchange()
        exchange=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],
            codeVerifier=self.verifier)
        committed=threading.Event();release=threading.Event();original=self.main.session
        def delayed(action,raw,fingerprint):
            result=original(action,raw,fingerprint)
            committed.set();release.wait(3)
            return result
        self.main.session=delayed
        connection=http.client.HTTPConnection("127.0.0.1",fixture.TeamTests.port,timeout=5)
        try:
            connection.request("POST","/v1/device-sessions/exchange",body=json.dumps(exchange).encode(),
                headers={"Host":"api.wegoh.invalid","Content-Type":"application/json",
                    "cf-cert-sha256":self.fingerprint,"cf-cert-presented":"true",
                    "cf-cert-verified":"true","cf-cert-revoked":"false"})
            self.assertTrue(committed.wait(3))
            # No response header/body is read by this client after the actual
            # server commit. Close while the response is still withheld.
            connection.close()
        finally:
            release.set();self.main.session=original;connection.close()
        logout=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],
            revokeCapability=self.revoke_capability)
        self.assertNotIn("deviceId",logout);self.assertNotIn("codeVerifier",logout)
        status,_,ack=self.native("/v1/device-sessions/revoke",logout,"POST")
        self.assertEqual(status,200,ack);self.assertEqual(ack["grantId"],issued["grantId"])
        status,_,again=self.native("/v1/device-sessions/revoke",logout,"POST")
        self.assertEqual(status,200,again);self.assertEqual(again["revokedAt"],ack["revokedAt"])
        self.assertEqual(self.native("/v1/device-sessions/exchange",exchange,"POST")[0],403)
        with psycopg.connect(self.auth.dsn) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT account_id,protected_consent FROM native_v2_grants WHERE grant_id=%s",
                (issued["grantId"],)).fetchone(),(None,None))

    def test_10_http_approved_grant_revoke_prevents_late_first_exchange(self):
        issued=self.issued_without_exchange()
        logout=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],
            revokeCapability=self.revoke_capability)
        self.assertEqual(self.native("/v1/device-sessions/revoke",logout,"POST")[0],200)
        exchange=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],codeVerifier=self.verifier)
        self.assertEqual(self.native("/v1/device-sessions/exchange",exchange,"POST")[0],403)
        with psycopg.connect(self.auth.dsn) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)


    def test_11_real_renewal_relay_staged_binding_generation_and_wss_epoch(self):
        from unittest.mock import patch
        import native_access_renewal as renewal
        from native_access_codec import decode_response
        old=self.connected();new_verifier=secrets.token_urlsafe(32);new_challenge=challenge(new_verifier)
        value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),csrPem=self.csr,
            installationKeyId=self.key_id,grantId=old["grantId"],deviceId=old["deviceId"],
            recoveryCapability=old["recoveryCapability"],expectedGeneration=1,codeChallenge=new_challenge,
            proofNonce="certificate-renewal",proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        msg=proof_transcript("CERTIFICATE_RENEW_BEGIN",decode_request("CERTIFICATE_RENEW_BEGIN",value),
            installation_key_id=self.key_id,code_challenge=new_challenge)
        value["proof"]=base64.urlsafe_b64encode(self.key.sign(msg,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        connection_factory=http.client.HTTPConnection
        def route(host,port=None,*args,**kwargs):
            if host=="127.0.0.1" and port==18082:port=fixture.TeamTests.port
            elif host=="127.0.0.1" and port==18083:port=self.port
            return connection_factory(host,port,*args,**kwargs)
        had_reader=hasattr(self.issuer,"reconcile");old_reader=getattr(self.issuer,"reconcile",None)
        self.issuer.reconcile=lambda *args:None
        self.issuer.require_active_certificate=lambda *args:True
        self.addCleanup(lambda:setattr(self.issuer,"reconcile",old_reader) if had_reader else delattr(self.issuer,"reconcile"))
        with self.ws(old["accessToken"]) as channel:
            channel.recv(timeout=2)
            with patch.object(renewal.http.client,"HTTPConnection",route):
                status,pending=self.enroll("/v1/installations/certificate-renew",value)
            self.assertEqual(status,201,pending)
            claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=new_verifier,
                proofNonce=pending["proofNonce"],proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
            msg=proof_transcript("CERTIFICATE_RENEW_CLAIM",decode_request("CERTIFICATE_RENEW_CLAIM",claim),
                installation_key_id=self.key_id,code_challenge=new_challenge,connection_id=pending["connectionId"])
            claim["proof"]=base64.urlsafe_b64encode(self.key.sign(msg,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
            status,issued=self.enroll("/v1/connections/"+pending["connectionId"]+"/claim",claim)
            self.assertEqual(status,200,issued)
            decode_response("CERTIFICATE_RENEW_CLAIM",status,issued,expected_operation_id=claim["operationId"])
            staged=issued["certificateReceipt"];stage_fp=staged["certificateSha256"]
            self.assertEqual(self.native("/v1/account",token=old["accessToken"],certificate=stage_fp)[0],403)
            rebind=dict(authorizationVersion=1,operationId=secrets.token_hex(16),connectionId=pending["connectionId"],
                grantId=old["grantId"],deviceId=old["deviceId"],recoveryCapability=old["recoveryCapability"])
            with patch.object(renewal.http.client,"HTTPConnection",route):
                status,_,result=self.native("/v1/device-sessions/rebind",rebind,"POST",certificate=stage_fp)
            self.assertEqual(status,200,result);new=result["credentialReceipt"]
            self.assertEqual(new["generation"],2);self.assertEqual(new["grantExpiresAt"],old["grantExpiresAt"])
            self.assertEqual(new["revokeCapability"],old["revokeCapability"])
            with self.assertRaises(ConnectionClosed):channel.recv(timeout=3)
        self.assertEqual(self.native("/v1/account",token=old["accessToken"],certificate=old["certificateSha256"])[0],401)
        self.assertEqual(self.native("/v1/account",token=new["accessToken"],certificate=stage_fp)[0],200)
        self.assertEqual(self.enroll("/internal/native-certificate-status",{})[0],404)
        with psycopg.connect(self.auth.dsn) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_approvals").fetchone()[0],1)
        self.assertEqual(self.issuer.calls,2)


    def test_12_phone_withdrawal_late_public_leaf_and_known_csr_fresh_phone_reuse(self):
        from enrollment_crypto import IssuanceUncertain,validate_issued
        from test_enrollment import CA_ID
        pending,body=self.start()
        self.assertEqual(self.api.call("/v1/connections/"+pending["userCode"],body,"POST",session=self.session)[0],200)
        original_response=self.issuer.response;stored={}
        def capture(csr):
            value=original_response(csr);stored["result"]=value;return value
        self.issuer.response=capture
        self.addCleanup(lambda:setattr(self.issuer,"response",original_response))
        def lost():raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
        self.issuer.after_issue=lost
        self.addCleanup(lambda:setattr(self.issuer,"after_issue",None))
        claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=self.verifier,
            proofNonce=pending["proofNonce"],proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        msg=proof_transcript("CONNECTION_CLAIM",decode_request("CONNECTION_CLAIM",claim),
            installation_key_id=self.key_id,code_challenge=self.challenge,connection_id=pending["connectionId"])
        claim["proof"]=base64.urlsafe_b64encode(self.key.sign(msg,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        self.assertEqual(self.enroll("/v1/connections/"+pending["connectionId"]+"/claim",claim)[1]["state"],"UNCERTAIN")
        bob_session=self.api.login("bob")
        path="/v1/connections/"+pending["userCode"]
        self.assertEqual(self.api.call(path,dict(authorizationVersion=1),"DELETE",session=bob_session,who="bob")[0],404)
        self.assertEqual(self.api.call(path,dict(authorizationVersion=1),"DELETE",session=self.session,csrf=False)[0],403)
        self.assertEqual(self.api.call(path,dict(authorizationVersion=1),"DELETE",session=self.session)[0],200)
        self.issuer.after_issue=None
        self.issuer.reconcile=lambda csr,excluded:validate_issued(validate_csr(csr),stored["result"],CA_ID)
        self.issuer.require_active_certificate=lambda *args:True
        with psycopg.connect(self.auth.dsn) as conn:
            old_grant=conn.execute("SELECT grant_id FROM native_v2_approvals WHERE connection_id=%s",
                (pending["connectionId"],)).fetchone()[0]
            conn.execute("UPDATE native_v2_connections SET next_poll=0 WHERE connection_id=%s",(pending["connectionId"],))
        # The canceled purpose/old PKCE are no longer available. A new explicit
        # same-key phone request must reconcile the old CA via GET, never POST.
        self.verifier=secrets.token_urlsafe(32);self.challenge=challenge(self.verifier)
        fresh_pending,fresh_body=self.start()
        self.assertEqual(self.api.call("/v1/connections/"+fresh_pending["userCode"],fresh_body,"POST",session=self.session)[0],200)
        fresh_claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=self.verifier,
            proofNonce=fresh_pending["proofNonce"],proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        msg=proof_transcript("CONNECTION_CLAIM",decode_request("CONNECTION_CLAIM",fresh_claim),
            installation_key_id=self.key_id,code_challenge=self.challenge,connection_id=fresh_pending["connectionId"])
        fresh_claim["proof"]=base64.urlsafe_b64encode(self.key.sign(msg,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        self.issuer.reconcile=lambda csr,excluded:None
        status,waiting=self.enroll("/v1/connections/"+fresh_pending["connectionId"]+"/claim",fresh_claim)
        self.assertEqual(status,202,waiting);self.assertEqual(waiting["state"],"PENDING");self.assertEqual(self.issuer.calls,1)
        self.issuer.reconcile=lambda csr,excluded:validate_issued(validate_csr(csr),stored["result"],CA_ID)
        status,issued=self.enroll("/v1/connections/"+fresh_pending["connectionId"]+"/claim",fresh_claim)
        self.assertEqual(status,200,issued)
        self.fingerprint=issued["certificateReceipt"]["certificateSha256"]
        status,_,result=self.native("/v1/device-sessions/exchange",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=issued["grantId"],codeVerifier=self.verifier),"POST")
        self.assertEqual(status,200,result);fresh=result["credentialReceipt"]
        self.assertEqual(fresh["generation"],1)
        self.assertEqual(self.issuer.calls,1)  # Existing public leaf reused.
        self.assertEqual(self.native("/v1/account",token=fresh["accessToken"])[0],200)
        with psycopg.connect(self.auth.dsn) as conn:
            old=conn.execute("SELECT state,account_id,protected_consent FROM native_v2_grants WHERE grant_id=%s",(old_grant,)).fetchone()
            self.assertEqual(old,("REVOKED",None,None))
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_installations").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_certificates").fetchone()[0],1)

    def test_13_cancelled_account_operation_public_recovery_binds_original_cert_csr_pkce_and_hash(self):
        from native_access_codec import canonical_request
        old=self.connected();public_cert=None
        with psycopg.connect(self.auth.dsn) as conn:
            row=conn.execute("SELECT protected_receipt FROM native_v2_certificates WHERE installation_key_id=%s",(self.key_id,)).fetchone()
            public_cert=restore("generation",self.key_id+":1",row[0])["receipt"]["certificatePem"]
        verifier=secrets.token_urlsafe(32);pkce=challenge(verifier)
        account=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Same car account",
            certificatePem=public_cert,codeChallenge=pkce,requestedScopes=self.scopes)
        account["revokeCommitment"]=hash_secret("revoke",derive_revoke_capability(verifier,self.key_id,account["operationId"]))
        status,_,pending=self.native("/v1/device-authorizations",account,"POST")
        self.assertEqual(status,201,pending)
        original_hash=digest(canonical_request(decode_request("ACCOUNT_AUTHORIZE",account)))
        body=dict(authorizationVersion=1,operationId=account["operationId"],csrPem=self.csr,
            originalBeginHash=original_hash,codeVerifier=verifier,proofNonce="begin-recovery")
        def signed(action,raw,connection=None):
            value=dict(raw,proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
            transcript=proof_transcript(action,decode_request(action,value),installation_key_id=self.key_id,
                code_challenge=pkce,connection_id=connection)
            value["proof"]=base64.urlsafe_b64encode(self.key.sign(transcript,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
            return value
        status,waiting=self.enroll("/v1/connections/recover",signed("CONNECTION_RECOVER",body))
        self.assertEqual(status,200,waiting);self.assertEqual(waiting["state"],"PENDING")
        for field,value in (("originalBeginHash","f"*64),("codeVerifier",secrets.token_urlsafe(32)),("csrPem",make_csr()[1])):
            with self.subTest(field=field):self.assertEqual(self.enroll("/v1/connections/recover",signed("CONNECTION_RECOVER",dict(body,**{field:value})))[0],403)
        claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=verifier,proofNonce=waiting["proofNonce"])
        self.assertEqual(self.enroll("/v1/connections/"+pending["connectionId"]+"/claim",signed("CONNECTION_CLAIM",claim,pending["connectionId"]))[0],403)
        path="/v1/connections/"+pending["userCode"]
        status,_,detail=self.api.call(path,session=self.session);self.assertEqual(status,200,detail)
        approval=dict(authorizationVersion=1,consentVersion=1,approvedScopes=self.scopes,keepSignedIn=False,
            disclosureVersion=2,disclosureSha256=detail["disclosureSnapshot"]["disclosureSha256"])
        self.assertEqual(self.api.call(path,approval,"POST",session=self.session)[0],200)
        self.assertEqual(self.api.call(path,dict(authorizationVersion=1),"DELETE",session=self.session)[0],200)
        status,terminal=self.enroll("/v1/connections/recover",signed("CONNECTION_RECOVER",body))
        self.assertEqual(status,200,terminal);self.assertEqual(terminal["state"],"REVOKED")
        self.assertEqual(set(terminal),{"authorizationVersion","operation","operationId","state","disposition","serverTime","connectionId"})
        self.assertEqual(self.issuer.calls,1)
        self.assertEqual(self.native("/v1/account",token=old["accessToken"])[0],200)

    def test_13b_vehicle_cancel_reaches_enroll_host_and_ends_the_phone_code(self):
        # the public enroll boundary admits the cancel path; the phone then gets 410.
        self.connected()
        with psycopg.connect(self.auth.dsn) as conn:
            row=conn.execute("SELECT protected_receipt FROM native_v2_certificates WHERE installation_key_id=%s",(self.key_id,)).fetchone()
            public_cert=restore("generation",self.key_id+":1",row[0])["receipt"]["certificatePem"]
        verifier=secrets.token_urlsafe(32);pkce=challenge(verifier)
        account=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Same car account",
            certificatePem=public_cert,codeChallenge=pkce,requestedScopes=self.scopes)
        account["revokeCommitment"]=hash_secret("revoke",derive_revoke_capability(verifier,self.key_id,account["operationId"]))
        status,_,pending=self.native("/v1/device-authorizations",account,"POST")
        self.assertEqual(status,201,pending)
        body=dict(authorizationVersion=1,operationId=account["operationId"],codeVerifier=verifier,
            proofNonce="connection-cancel",proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        transcript=proof_transcript("CONNECTION_CANCEL",decode_request("CONNECTION_CANCEL",body),
            installation_key_id=self.key_id,code_challenge=pkce)
        body["proof"]=base64.urlsafe_b64encode(self.key.sign(transcript,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        self.assertEqual(self.enroll("/v1/connections/cancel",dict(body,codeVerifier=secrets.token_urlsafe(32)))[0],403)
        with patch.object(self.bootstrap,"clock",return_value=pending["expiresAt"]-298):
            status,ended=self.enroll("/v1/connections/cancel",body)
        self.assertEqual(status,200,ended)
        self.assertEqual((ended["state"],ended["disposition"],ended["connectionId"]),("EXPIRED","TERMINAL",pending["connectionId"]))
        with patch.object(self.main,"clock",return_value=pending["expiresAt"]-297):
            status,_,detail=self.api.call("/v1/connections/"+pending["userCode"],session=self.session)
        self.assertEqual((status,detail.get("error")),(410,"AUTHORIZATION_EXPIRED"),detail)

    def test_14_single_public_contract_has_no_old_route_or_version_fallback(self):
        from native_access_codec import revoke_commitment
        from fastapi.routing import iter_route_contexts
        from fastapi.openapi.utils import _get_api_route_for_openapi
        def effective_paths(application):
            return {route.path for context in iter_route_contexts(application.routes)
                if (route := _get_api_route_for_openapi(context)) is not None}
        main_routes=effective_paths(fixture.TeamTests.module.app)
        issuer_routes=effective_paths(self.enrollment)
        for path in main_routes|issuer_routes:
            self.assertFalse(path.startswith("/v2/"),path)
            self.assertFalse(path.startswith(("/v1/enrollments","/v1/devices/pairings","/v1/devices/token")),path)
        for path in ("/v1/account","/v1/studio/packs","/v1/playlists","/v1/devices"):
            self.assertIn(path,main_routes)
        for path in ("/v2/connections","/v1/enrollments"):
            self.assertEqual(self.enroll(path,{})[0],404)
        for path in ("/v1/devices/pairings","/v1/devices/token","/v1/enrollments"):
            self.assertEqual(self.api.call(path,{},"POST",session=self.session)[0],404)
        operation=secrets.token_hex(16)
        body=dict(authorizationVersion=2,operationId=operation,name="Synthetic owned device",csrPem=self.csr,
            codeChallenge=self.challenge,requestedScopes=self.scopes,
            revokeCommitment=revoke_commitment(derive_revoke_capability(self.verifier,self.key_id,operation)))
        status,value=self.enroll("/v1/connections",body)
        self.assertEqual(status,400);self.assertEqual(value,{"authorizationVersion":1,"error":"INVALID_REQUEST"})
        self.assertEqual(self.issuer.calls,0)
        with psycopg.connect(self.auth.dsn) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_connections").fetchone()[0],0)

    def test_15_hold_transition_preserves_only_completed_unrelated_modern_grant(self):
        # Synthetic historical modern storage; no old binary/provider execution.
        import hashlib
        from datetime import datetime,timezone
        from cryptography import x509
        from private_records import VisitCipher
        from enrollment_crypto import validate_csr,public_bytes,digest
        from ops.live.native_hold_apply import register_hold
        token=self.connected();cipher=VisitCipher();owner=self.session['user']['id']
        legacy_token=secrets.token_urlsafe(32);legacy_id=secrets.token_hex(16)
        enrollment=secrets.token_hex(16);_,held_csr=make_csr()
        held_key=digest(public_bytes(validate_csr(held_csr).public_key()))
        original=cipher.protect('enrollment',enrollment,{'csrPem':held_csr})
        record=self.issuer.response(validate_csr(held_csr))
        leaf=x509.load_pem_x509_certificate(record['certificate'].encode())
        record['issued_on']=leaf.not_valid_before_utc.isoformat();record['expires_on']=leaf.not_valid_after_utc.isoformat()
        envelope=dict(expectedIssuerId=record['certificate_authority']['id'],inventorySha256='a'*64,
            inventory=dict(statusFilter='all',totalPages=1,totalCount=1,pageResponseSha256=['b'*64],records=[record]))
        def personal(conn):
            # All values are owned synthetic fixture data, never production data.
            return {table:conn.execute('SELECT * FROM '+table+' WHERE '+field+'=%s ORDER BY 1,2',(value,)).fetchall()
                for table,field,value in [('native_v2_installations','installation_key_id',self.key_id),
                    ('native_v2_connections','connection_id',connection),('native_v2_approvals','connection_id',connection),
                    ('native_v2_grants','grant_id',token['grantId']),('native_v2_credentials','grant_id',token['grantId']),
                    ('native_v2_operations','grant_id',token['grantId']),('native_v2_renewals','grant_id',token['grantId'])]}
        with psycopg.connect(self.auth.dsn) as conn:
            connection=conn.execute('SELECT connection_id FROM native_v2_grants WHERE grant_id=%s',(token['grantId'],)).fetchone()[0]
            operation,raw=conn.execute("SELECT operation_id,protected_receipt FROM native_v2_operations WHERE grant_id=%s AND action='SESSION_EXCHANGE'",(token['grantId'],)).fetchone()
            past=restore('operation',operation,raw);past['authorizationVersion']=2
            conn.execute('UPDATE native_v2_operations SET protected_receipt=%s WHERE operation_id=%s',(protect('operation',operation,past),operation))
            conn.execute("INSERT INTO vehicle_enrollments(enrollment_id,user_code,public_key_hash,state,expires_at,protected) VALUES(%s,'ABCDEFGH',%s,'uncertain',1,%s)",(enrollment,held_key,original))
            protected=cipher.protect('team-device:'+owner,legacy_id,dict(name='Synthetic old manual device',nativeCertificateSha256=self.fingerprint))
            conn.execute("INSERT INTO team_devices(device_id,account_id,protected,access_hash,access_expires_at,refresh_hash,expires_at) VALUES(%s,%s,%s,%s,now()+interval '15 minutes',%s,now()+interval '7 days')",
                (legacy_id,owner,protected,hashlib.sha256(legacy_token.encode()).hexdigest(),hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()))
            before=personal(conn);self.issuer.calls=0
            dry=register_hold(conn,cipher,envelope)
            applied=register_hold(conn,cipher,envelope,apply=True)
            self.assertFalse(dry['applied']);self.assertTrue(applied['applied'])
            self.assertEqual(dry['holdDigest'],applied['holdDigest']);self.assertEqual(personal(conn),before)
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_grants WHERE state='TOKEN_ISSUED' AND expires_at>extract(epoch from now())").fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT state,protected FROM vehicle_enrollments WHERE enrollment_id=%s',(enrollment,)).fetchone(),('uncertain',original))
            self.assertEqual(restore('operation',operation,conn.execute('SELECT protected_receipt FROM native_v2_operations WHERE operation_id=%s',(operation,)).fetchone()[0])['authorizationVersion'],2)
            for state in ('ISSUING','UNCERTAIN','PENDING'):
                with self.subTest(inFlight=state),conn.transaction(force_rollback=True):
                    conn.execute('UPDATE native_v2_connections SET state=%s,expires_at=extract(epoch from now())::bigint+300 WHERE connection_id=%s',(state,connection))
                    with self.assertRaises(ValueError):register_hold(conn,cipher,envelope,apply=True)
            with conn.transaction(force_rollback=True):
                conn.execute("UPDATE native_v2_grants SET state='APPROVED' WHERE grant_id=%s",(token['grantId'],))
                with self.assertRaises(ValueError):register_hold(conn,cipher,envelope,apply=True)
            with conn.transaction(force_rollback=True):
                # Any nonnull target slot remains a hard denial, even invalid input.
                conn.execute('UPDATE native_v2_installations SET active_grant_id=%s WHERE installation_key_id=%s',(token['grantId'],held_key))
                with self.assertRaises(ValueError):register_hold(conn,cipher,envelope,apply=True)
            self.assertEqual(personal(conn),before)
        self.assertEqual(self.issuer.calls,0)
        status,_,account=self.native('/v1/account',token=token['accessToken'])
        self.assertEqual(status,200,account);self.assertEqual(account['user']['id'],token['accountId'])
        self.assertEqual(self.native('/v1/packs',token=token['accessToken'])[0],200)
        self.assertEqual(self.native('/v1/playlists',token=token['accessToken'])[0],403)
        self.assert_default_history_permissions(token)
        self.assertEqual(self.native('/v1/account',token=legacy_token)[0],401)
        self.assertEqual(self.native('/v2/connections',{},'POST',token=token['accessToken'])[0],404)


if __name__=="__main__":unittest.main()
