"""Owned PostgreSQL + real AES-GCM/CSR/signature; no production data or CA."""
import base64
import os
import secrets
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import psycopg
from psycopg.conninfo import make_conninfo
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import HTTPException
from starlette.requests import Request
import native_access_codec as codec
from enrollment_crypto import challenge, digest, public_bytes, validate_csr
from native_authorization import NativeAuthorization, NativeAuthorizationError, restore, hash_secret
import test_native_access_schema as schema_fixture
from test_enrollment import SyntheticIssuer, make_csr

class NativeAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema_fixture.NativeAccessSchemaTests.setUpClass.__func__(cls)
        with cls.connect() as conn:
            conn.execute((schema_fixture.ROOT/"server/enrollment_schema.sql").read_text())
            conn.execute("CREATE TABLE team_devices(device_id text,account_id text,protected bytea,revoked_at timestamptz,expires_at timestamptz)")
        cls.keyfile=cls.base/"visit.key"
        cls.keyfile.write_bytes(os.urandom(32));cls.keyfile.chmod(0o600)
        cls.env=patch.dict(os.environ,{"WEGOH_VISIT_KEY_FILE":str(cls.keyfile),"WEGOH_RETIRED_ISSUANCE_EXPECTED_COUNT":"0","WEGOH_RETIRED_ISSUANCE_EXPECTED_DIGEST":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"})
        cls.env.start();cls.addClassCleanup(cls.env.stop)
        cls.owner=dict(id="team-"+"a"*40,displayName="Owner",role="admin")
        def current(account, *, connection=None, require_roster=False, vehicle=False, identity=None):
            if account!=cls.owner["id"]: raise HTTPException(403,"denied")
            return cls.owner
        cls.auth=SimpleNamespace(dsn=make_conninfo(host=str(cls.socket),port=5432,user="fixtureowner",dbname="postgres"),
            enabled=True,current_account=current,rate=lambda *a,**k:None)
        cls.auth.native_certificate=lambda request:request.headers["test-certificate"]
        cls.now=int(time.time());cls.issuer=SyntheticIssuer()
        cls.service=NativeAuthorization(cls.auth,issuer=cls.issuer,clock=lambda:cls.now,enabled=True)

    connect=schema_fixture.NativeAccessSchemaTests.__dict__["connect"]
    shutdown=schema_fixture.NativeAccessSchemaTests.__dict__["shutdown"]

    def setUp(self):
        with self.connect() as conn:
            conn.execute("TRUNCATE native_v2_operations,native_v2_credentials,native_v2_certificates,"
                "native_v2_grants,native_v2_approvals,native_v2_connections,native_v2_installations,vehicle_enrollments CASCADE")
        type(self).now=int(time.time());self.issuer.calls=0;self.issuer.crash=False;self.issuer.after_issue=None
        self.issuer.issue=SyntheticIssuer.issue.__get__(self.issuer)
        self.issuer.response=SyntheticIssuer.response.__get__(self.issuer)
        self.key,self.csr=make_csr();self.key_id=digest(public_bytes(validate_csr(self.csr).public_key()))
        self.verifier=secrets.token_urlsafe(32)
        self.scopes=sorted(["account:read","device:self:manage","courses:read"])
        self.begin=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Test car",
            csrPem=self.csr,codeChallenge=challenge(self.verifier),requestedScopes=self.scopes)
        self.begin["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.verifier,self.key_id,self.begin["operationId"]))

    def signed(self,action,fields,connection=None):
        fields=dict(fields,proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        record=codec.decode_request(action,fields)
        transcript=codec.proof_transcript(action,record,installation_key_id=self.key_id,
            code_challenge=self.begin["codeChallenge"],connection_id=connection)
        fields["proof"]=base64.urlsafe_b64encode(self.key.sign(transcript,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        return fields

    def start(self,approved=None):
        status,pending=self.service.begin(self.begin);self.assertEqual(status,201)
        detail=self.service.detail(pending["userCode"],self.owner)
        snapshot=detail["disclosureSnapshot"]
        self.service.approve(pending["userCode"],dict(authorizationVersion=1,consentVersion=1,
            approvedScopes=self.scopes if approved is None else approved,keepSignedIn=False,
            disclosureVersion=2,disclosureSha256=snapshot["disclosureSha256"]),self.owner)
        return pending

    def claim(self,pending):
        return self.service.claim(pending["connectionId"],self.signed("CONNECTION_CLAIM",
            dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=self.verifier,
                proofNonce=pending["proofNonce"]),pending["connectionId"]))

    def connected(self):
        pending=self.start();status,issued=self.claim(pending);self.assertEqual(status,200)
        fingerprint=issued["certificateReceipt"]["certificateSha256"]
        request=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],codeVerifier=self.verifier)
        status,response=self.service.session("SESSION_EXCHANGE",request,fingerprint)
        self.assertEqual(status,200)
        return pending,issued,request,response["credentialReceipt"]

    def request(self,receipt,path="/v1/account"):
        return Request(dict(type="http",method="GET",scheme="https",server=("api-wegoh.devforest.io",443),
            path=path,raw_path=path.encode(),query_string=b"",client=("127.0.0.1",1),
            headers=[(b"host",b"api-wegoh.devforest.io"),(b"authorization",("Bearer "+receipt["accessToken"]).encode()),
                (b"test-certificate",receipt["certificateSha256"].encode())]))

    def test_01_single_consent_issues_once_exchanges_and_enforces_optional_scope(self):
        pending,issued,exchange,receipt=self.connected()
        self.assertEqual(self.issuer.calls,1)
        self.assertEqual(self.service.authenticate(self.request(receipt))["deviceId"],receipt["deviceId"])
        self.assertEqual(self.service.authenticate(self.request(receipt,"/v1/packs"))["scopes"],self.scopes)
        with self.assertRaises(NativeAuthorizationError) as error:self.service.authenticate(self.request(receipt,"/v1/playlists"))
        self.assertEqual((error.exception.status,error.exception.code),(403,"SCOPE_DENIED"))
        with self.assertRaises(NativeAuthorizationError) as error:self.service.authenticate(self.request(receipt,"/v1/social/history"))
        self.assertEqual(error.exception.status,404)
        again=self.service.session("SESSION_EXCHANGE",exchange,receipt["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(again,receipt)
        with self.connect() as conn:
            row=conn.execute("SELECT protected_consent FROM native_v2_grants WHERE grant_id=%s",(receipt["grantId"],)).fetchone()
            self.assertNotIn(b"Test car",bytes(row[0]))
            self.assertEqual(restore("consent",receipt["grantId"],row[0])["scopes"],self.scopes)

    def test_02_required_scope_denial_never_issues_certificate_or_personal_token(self):
        pending=self.start(approved=["courses:read"])
        with self.assertRaises(NativeAuthorizationError) as error:self.claim(pending)
        self.assertEqual(error.exception.code,"CONSENT_REVOKED")
        self.assertEqual(self.issuer.calls,0)
        # A deliberate same-key restart after refusal is not a new installation.
        again=dict(self.begin,operationId=secrets.token_hex(16))
        self.assertEqual(self.service.begin(again)[0],201)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_grants").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_certificates").fetchone()[0],0)

    def test_03_uncertain_ca_outcome_does_not_post_again(self):
        pending=self.start();self.issuer.crash=True
        self.assertEqual(self.claim(pending)[1]["state"],"UNCERTAIN")
        type(self).now+=5
        self.assertEqual(self.claim(pending)[1]["state"],"UNCERTAIN")
        self.assertEqual(self.issuer.calls,1)

    def test_04_refresh_recovery_rotate_and_revoke_is_terminal_idempotent(self):
        pending,issued,exchange,receipt=self.connected();fingerprint=receipt["certificateSha256"]
        request=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=receipt["grantId"],
            deviceId=receipt["deviceId"],refreshToken=receipt["refreshToken"])
        new=self.service.session("SESSION_REFRESH",request,fingerprint)[1]["credentialReceipt"]
        self.assertGreater(new["credentialEpoch"],receipt["credentialEpoch"])
        with self.assertRaises(NativeAuthorizationError) as rejected:self.service.authenticate(self.request(receipt))
        self.assertEqual((rejected.exception.status,rejected.exception.code),(401,"INVALID_CREDENTIAL"))
        recovered=self.service.session("SESSION_RECOVER",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=new["grantId"],deviceId=new["deviceId"],recoveryCapability=new["recoveryCapability"]),fingerprint)[1]["credentialReceipt"]
        revoke=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=new["grantId"],
            revokeCapability=new["revokeCapability"])
        first=self.service.revoke(new["deviceId"],revoke,fingerprint)
        self.assertEqual(first,self.service.revoke(new["deviceId"],revoke,fingerprint))
        with self.assertRaises(NativeAuthorizationError) as rejected:self.service.authenticate(self.request(recovered))
        self.assertEqual((rejected.exception.status,rejected.exception.code),(401,"INVALID_CREDENTIAL"))

    def test_05_legacy_uncertain_same_key_never_starts_second_issuance(self):
        from native_authorization import protect
        with self.connect() as conn:
            conn.execute("INSERT INTO vehicle_enrollments(enrollment_id,user_code,public_key_hash,state,expires_at,protected) "
                "VALUES(%s,'ABCDEFGH',%s,'uncertain',1,%s)",(secrets.token_hex(16),self.key_id,protect('synthetic','legacy',{})))
        with self.assertRaises(NativeAuthorizationError) as error:self.service.begin(self.begin)
        self.assertEqual(error.exception.code,'RECOVERY_NOT_ALLOWED')
        self.assertEqual(self.issuer.calls,0)


    def test_06_initial_lost_ca_response_reconciles_get_without_new_post_or_qr(self):
        from enrollment_crypto import IssuanceUncertain,validate_issued
        from test_enrollment import CA_ID
        pending=self.start();stored={};original_response=self.issuer.response
        def capture(csr):
            value=original_response(csr);stored["result"]=value;return value
        self.issuer.response=capture
        self.addCleanup(lambda:setattr(self.issuer,"response",original_response))
        def lost():raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
        self.issuer.after_issue=lost
        self.assertEqual(self.claim(pending)[1]["state"],"UNCERTAIN")
        self.assertEqual(self.issuer.calls,1)
        self.issuer.after_issue=None;reads=[]
        def reconcile(csr,excluded):
            reads.append(1)
            return validate_issued(validate_csr(csr),stored["result"],CA_ID)
        self.issuer.reconcile=reconcile
        self.addCleanup(lambda:delattr(self.issuer,"reconcile"))
        type(self).now+=5
        issued=self.claim(pending)[1]
        self.assertEqual(issued["state"],"ISSUED");self.assertEqual(self.issuer.calls,1);self.assertEqual(len(reads),1)
        receipt=self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=issued["grantId"],codeVerifier=self.verifier),issued["certificateReceipt"]["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(self.service.authenticate(self.request(receipt))["deviceId"],receipt["deviceId"])

    def fresh_begin(self):
        verifier=secrets.token_urlsafe(32)
        begin=dict(self.begin,operationId=secrets.token_hex(16),codeChallenge=challenge(verifier))
        begin["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(verifier,self.key_id,begin["operationId"]))
        return begin,verifier

    def approve(self,pending):
        snapshot=self.service.detail(pending["userCode"],self.owner)["disclosureSnapshot"]
        self.service.approve(pending["userCode"],dict(authorizationVersion=1,consentVersion=1,approvedScopes=self.scopes,
            keepSignedIn=False,disclosureVersion=2,disclosureSha256=snapshot["disclosureSha256"]),self.owner)

    def test_07_same_key_new_begin_replaces_its_dropped_unclaimed_code(self):
        # The vehicle showed and the phone even approved this code, then the
        # vehicle cancelled and dropped its verifier.
        old=self.start();old_begin=self.begin
        type(self).now+=2
        begin,verifier=self.fresh_begin()
        status,fresh=self.service.begin(begin)
        self.assertEqual(status,201);self.assertNotEqual(fresh["userCode"],old["userCode"])
        self.assertEqual(self.service.begin(begin),(200,dict(fresh,serverTime=self.now)))
        for call in (lambda:self.service.begin(old_begin),lambda:self.service.detail(old["userCode"],self.owner),
                lambda:self.claim(old)):
            with self.assertRaises(NativeAuthorizationError) as error:call()
            self.assertEqual((error.exception.status,error.exception.code),(410,"AUTHORIZATION_EXPIRED"))
        self.assertEqual(self.issuer.calls,0)
        # A rejected begin must not end the code that is still on screen.
        from native_authorization import protect
        with self.connect() as conn:
            conn.execute("INSERT INTO vehicle_enrollments(enrollment_id,user_code,public_key_hash,state,expires_at,protected) "
                "VALUES(%s,'ABCDEFGH',%s,'uncertain',1,%s)",(secrets.token_hex(16),self.key_id,protect('synthetic','legacy',{})))
        with self.assertRaises(NativeAuthorizationError) as error:self.service.begin(self.fresh_begin()[0])
        self.assertEqual(error.exception.code,"RECOVERY_NOT_ALLOWED")
        with self.connect() as conn:conn.execute("DELETE FROM vehicle_enrollments")
        # The new code is the only live one and completes the normal flow.
        self.begin,self.verifier=begin,verifier
        self.approve(fresh)
        status,issued=self.claim(fresh)
        self.assertEqual((status,issued["state"]),(200,"ISSUED"));self.assertEqual(self.issuer.calls,1)

    def test_07b_cancelled_code_stays_usable_only_when_a_different_key_begins(self):
        # the vehicle keeps its installation key across "취소"; the same key
        # replaces the code even for the phone's account-decision lookup/approve.
        old=self.start()
        type(self).now+=2
        status,fresh=self.service.begin(self.fresh_begin()[0]);self.assertEqual(status,201)
        for call in (lambda:self.service.detail(old["userCode"],self.owner,account_decision=True),
                lambda:self.approve_as_phone(old)):
            with self.assertRaises(NativeAuthorizationError) as error:call()
            self.assertEqual((error.exception.status,error.exception.code),(410,"AUTHORIZATION_EXPIRED"))
        # Only a begin under another key leaves the earlier code alive.
        other_key,other_csr=make_csr()
        other=dict(self.begin,operationId=secrets.token_hex(16),csrPem=other_csr)
        type(self).now+=2
        self.assertEqual(self.service.begin(other)[0],201)
        self.assertEqual(self.service.detail(fresh["userCode"],self.owner,account_decision=True)["state"],"PENDING")

    def test_07c_certified_vehicle_new_account_code_replaces_its_cancelled_one(self):
        # after logout a certified vehicle asks with ACCOUNT_AUTHORIZE, not
        # BEGIN. "취소" then a new code must end the earlier code for the phone too.
        _,issued,_,receipt=self.connected();fingerprint=receipt["certificateSha256"]
        def authorize():
            value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Test car",
                certificatePem=issued["certificateReceipt"]["certificatePem"],codeChallenge=challenge(self.verifier),
                requestedScopes=self.scopes)
            value["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.verifier,self.key_id,value["operationId"]))
            status,pending=self.service.account_authorize(value,fingerprint);self.assertEqual(status,201)
            return value,pending
        old_value,old=authorize()
        type(self).now+=2
        _,fresh=authorize()
        for call in (lambda:self.service.detail(old["userCode"],self.owner,account_decision=True),
                lambda:self.approve_as_phone(old),lambda:self.service.account_authorize(old_value,fingerprint)):
            with self.assertRaises(NativeAuthorizationError) as error:call()
            self.assertEqual((error.exception.status,error.exception.code),(410,"AUTHORIZATION_EXPIRED"))
        self.assertEqual(self.service.detail(fresh["userCode"],self.owner,account_decision=True)["state"],"PENDING")

    def approve_as_phone(self,pending):
        self.service.approve(pending["userCode"],dict(authorizationVersion=1,consentVersion=1,approvedScopes=self.scopes,
            keepSignedIn=False,disclosureVersion=2,disclosureSha256="0"*64),self.owner,account_decision=True)

    def test_08_code_replaced_within_its_first_second_ends_on_the_next_second(self):
        old=self.service.begin(self.begin)[1]
        status,fresh=self.service.begin(self.fresh_begin()[0])
        self.assertEqual(status,201)
        type(self).now+=1
        with self.assertRaises(NativeAuthorizationError) as error:self.service.detail(old["userCode"],self.owner)
        self.assertEqual(error.exception.code,"AUTHORIZATION_EXPIRED")
        self.assertEqual(self.service.detail(fresh["userCode"],self.owner)["state"],"PENDING")

    def cancel(self,operation_id,verifier=None,key=None,service=None):
        fields=dict(authorizationVersion=1,operationId=operation_id,codeVerifier=verifier or self.verifier,
            proofNonce="connection-cancel",proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        record=codec.decode_request("CONNECTION_CANCEL",fields)
        transcript=codec.proof_transcript("CONNECTION_CANCEL",record,installation_key_id=self.key_id,
            code_challenge=self.begin["codeChallenge"])
        fields["proof"]=base64.urlsafe_b64encode((key or self.key).sign(transcript,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        return (service or self.service).cancel(fields)

    def assert_expired(self,*calls):
        for call in calls:
            with self.assertRaises(NativeAuthorizationError) as error:call()
            self.assertEqual((error.exception.status,error.exception.code),(410,"AUTHORIZATION_EXPIRED"))

    def test_09_vehicle_cancel_ends_its_own_code_at_once(self):
        # "취소" alone, with no new code requested afterwards.
        status,old=self.service.begin(self.begin);self.assertEqual(status,201)
        other_key,other_csr=make_csr()
        other=dict(self.begin,operationId=secrets.token_hex(16),csrPem=other_csr)
        _,untouched=self.service.begin(other)
        type(self).now+=2
        # Another key, a wrong verifier or an unknown operation cannot end it.
        for call,expected in ((lambda:self.cancel(self.begin["operationId"],key=other_key),(403,"INVALID_PROOF")),
                (lambda:self.cancel(self.begin["operationId"],verifier=secrets.token_urlsafe(32)),(403,"INVALID_PROOF")),
                (lambda:self.cancel(secrets.token_hex(16)),(404,"OPERATION_NOT_FOUND"))):
            with self.assertRaises(NativeAuthorizationError) as error:call()
            self.assertEqual((error.exception.status,error.exception.code),expected)
        self.assertEqual(self.service.detail(old["userCode"],self.owner)["state"],"PENDING")
        status,ended=self.cancel(self.begin["operationId"])
        self.assertEqual((status,ended["state"],ended["disposition"],ended["connectionId"]),
            (200,"EXPIRED","TERMINAL",old["connectionId"]))
        self.assertEqual(self.cancel(self.begin["operationId"]),(status,ended))
        self.assert_expired(lambda:self.service.detail(old["userCode"],self.owner),
            lambda:self.service.detail(old["userCode"],self.owner,account_decision=True),
            lambda:self.approve_as_phone(old),lambda:self.service.begin(self.begin),lambda:self.claim(old))
        self.assertEqual(self.issuer.calls,0)
        # The other key's code on screen elsewhere stays live.
        self.assertEqual(self.service.detail(untouched["userCode"],self.owner)["state"],"PENDING")

    def test_09b_cancel_after_phone_approval_still_ends_the_unclaimed_code(self):
        pending=self.start()
        type(self).now+=2
        self.assertEqual(self.cancel(self.begin["operationId"])[1]["state"],"EXPIRED")
        self.assert_expired(lambda:self.service.detail(pending["userCode"],self.owner),lambda:self.claim(pending))
        self.assertEqual(self.issuer.calls,0)
        # Its approval no longer holds the owner's single vehicle slot.
        other_key,other_csr=make_csr()
        other=dict(self.begin,operationId=secrets.token_hex(16),csrPem=other_csr)
        self.approve(self.service.begin(other)[1])

    def test_09c_certified_vehicle_cancels_its_account_code_with_its_key(self):
        _,issued,_,receipt=self.connected();fingerprint=receipt["certificateSha256"]
        value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Test car",
            certificatePem=issued["certificateReceipt"]["certificatePem"],codeChallenge=challenge(self.verifier),
            requestedScopes=self.scopes)
        value["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.verifier,self.key_id,value["operationId"]))
        status,pending=self.service.account_authorize(value,fingerprint);self.assertEqual(status,201)
        type(self).now+=2
        with self.assertRaises(NativeAuthorizationError) as error:self.cancel(value["operationId"],key=make_csr()[0])
        self.assertEqual((error.exception.status,error.exception.code),(403,"INVALID_PROOF"))
        self.assertEqual(self.cancel(value["operationId"])[1]["state"],"EXPIRED")
        self.assert_expired(lambda:self.service.detail(pending["userCode"],self.owner,account_decision=True),
            lambda:self.approve_as_phone(pending),lambda:self.service.account_authorize(value,fingerprint))

    def test_09e_account_code_approved_but_not_taken_up_ends_with_its_grant_unusable(self):
        _,issued,_,receipt=self.connected();fingerprint=receipt["certificateSha256"]
        def account():
            value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Test car",
                certificatePem=issued["certificateReceipt"]["certificatePem"],codeChallenge=challenge(self.verifier),
                requestedScopes=self.scopes)
            value["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.verifier,self.key_id,value["operationId"]))
            _,pending=self.service.account_authorize(value,fingerprint)
            snapshot=self.service.detail(pending["userCode"],self.owner,account_decision=True)["disclosureSnapshot"]
            self.service.approve(pending["userCode"],dict(authorizationVersion=1,consentVersion=1,approvedScopes=self.scopes,
                keepSignedIn=False,disclosureVersion=2,disclosureSha256=snapshot["disclosureSha256"]),self.owner,account_decision=True)
            return value
        value=account()
        grant=self.service.account_authorize(value,fingerprint)[1]["grantId"]
        type(self).now+=2
        self.assertEqual(self.cancel(value["operationId"])[1]["state"],"EXPIRED")
        exchange=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=grant,codeVerifier=self.verifier)
        self.assert_expired(lambda:self.service.account_authorize(value,fingerprint),
            lambda:self.service.session("SESSION_EXCHANGE",exchange,fingerprint))
        # Cancel ends only the code. A session already exchanged is closed by
        # SESSION_REVOKE; cancel never touches its grant.
        type(self).now+=1
        value=account()
        grant=self.service.account_authorize(value,fingerprint)[1]["grantId"]
        status,exchanged=self.service.session("SESSION_EXCHANGE",dict(exchange,operationId=secrets.token_hex(16),
            grantId=grant),fingerprint)
        self.assertEqual(status,200)
        self.assertEqual(self.cancel(value["operationId"])[1]["state"],"EXPIRED")
        receipt=exchanged["credentialReceipt"]
        self.assertEqual(self.service.authenticate(self.request(receipt))["deviceId"],receipt["deviceId"])

    def test_09d_cancel_cannot_undo_a_claimed_code(self):
        pending=self.start();self.assertEqual(self.claim(pending)[1]["state"],"ISSUED")
        with self.assertRaises(NativeAuthorizationError) as error:self.cancel(self.begin["operationId"])
        self.assertEqual((error.exception.status,error.exception.code),(409,"OPERATION_CONFLICT"))

if __name__=="__main__":unittest.main()
