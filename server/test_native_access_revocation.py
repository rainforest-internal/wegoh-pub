"""Lost exchange/logout race: strict candidate15, private PG and synthetic CA."""
import json,secrets
from pathlib import Path
from unittest.mock import patch
import test_native_access_reauthorization as fixture
import native_access_codec as codec
from native_authorization_runtime import NativeAuthorizationRuntime
from native_authorization import NativeAuthorizationError,hash_secret
from enrollment_crypto import challenge,digest,public_bytes,validate_csr
from test_enrollment import make_csr
CANDIDATE=Path(__file__).resolve().parents[1]/"docs/evidence/native-key-api-unit/p1/revocation-wire-candidate.json"

class RevocationTests(fixture.ReauthorizationTests):
    def setUp(self):
        super().setUp()
        wire=json.loads(CANDIDATE.read_text())
        for name,value in (("_WIRE",wire),("_OPERATIONS",{o["action"]:o for o in wire["operations"]})):
            scope=patch.object(codec,name,value);scope.start();self.addCleanup(scope.stop)
        type(self).service=NativeAuthorizationRuntime(self.auth,issuer=self.issuer,clock=lambda:type(self).now,enabled=True)
        self.begin["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.verifier,self.key_id,self.begin["operationId"]))

    def revoke_request(self,grant):
        return dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=grant,
            revokeCapability=codec.derive_revoke_capability(self.verifier,self.key_id,self.begin["operationId"]))

    def test_40_revoke_approved_before_delayed_first_exchange_needs_no_device_id(self):
        pending=self.start();issued=self.claim(pending)[1];grant=issued["grantId"];fp=issued["certificateReceipt"]["certificateSha256"]
        request=self.revoke_request(grant)
        status,ack=self.service.revoke_grant(request,fp)
        self.assertEqual(status,200);self.assertEqual(ack["grantId"],grant);self.assertNotIn("deviceId",ack)
        self.assertEqual(self.service.revoke_grant(request,fp)[1],ack)
        with self.assertRaises(NativeAuthorizationError):
            self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
                grantId=grant,codeVerifier=self.verifier),fp)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)
            row=conn.execute("SELECT state,device_id,account_id,recovery_hash,revoke_hash FROM native_v2_grants").fetchone()
            self.assertEqual(row[:4],("REVOKED",None,None,None));self.assertEqual(row[4],self.begin["revokeCommitment"])

    def test_41_committed_exchange_response_lost_logout_only_uses_purpose_cap(self):
        pending=self.start();issued=self.claim(pending)[1];grant=issued["grantId"];fp=issued["certificateReceipt"]["certificateSha256"]
        exchange=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=grant,codeVerifier=self.verifier)
        self.service.session("SESSION_EXCHANGE",exchange,fp)  # Drop the complete response.
        # The logout outbox needs no access/refresh/verifier/recovery/deviceId.
        outbox=self.revoke_request(grant)
        self.assertEqual(set(outbox),{"authorizationVersion","operationId","grantId","revokeCapability"})
        self.assertEqual(self.service.revoke_grant(outbox,fp)[1]["state"],"REVOKED")
        with self.assertRaises(NativeAuthorizationError):self.service.session("SESSION_EXCHANGE",exchange,fp)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_operations").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)

    def test_42_commitment_substitution_and_wrong_purpose_never_exchange(self):
        self.begin["revokeCommitment"]="f"*64
        pending=self.start();issued=self.claim(pending)[1];fp=issued["certificateReceipt"]["certificateSha256"]
        with self.assertRaises(NativeAuthorizationError) as error:
            self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
                grantId=issued["grantId"],codeVerifier=self.verifier),fp)
        self.assertEqual(error.exception.code,"INVALID_PROOF")
        with self.assertRaises(NativeAuthorizationError):
            self.service.revoke_grant(self.revoke_request(issued["grantId"]),fp)
        with self.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)

    def test_43_two_accounts_installations_and_capabilities_cannot_cross_revoke(self):
        _,_,_,alice=self.connected();alice_cap=self.revoke_request(alice["grantId"])
        owner_a=self.owner;owner_b=dict(id="team-"+"b"*40,displayName="Other",role="admin")
        old_current=self.auth.current_account
        self.auth.current_account=lambda account,**kwargs:owner_a if account==owner_a["id"] else owner_b if account==owner_b["id"] else old_current(account,**kwargs)
        self.addCleanup(lambda:setattr(self.auth,"current_account",old_current))
        self.owner=owner_b
        self.key,self.csr=make_csr();self.key_id=digest(public_bytes(validate_csr(self.csr).public_key()))
        self.verifier=secrets.token_urlsafe(32)
        self.begin=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Other install",
            csrPem=self.csr,codeChallenge=challenge(self.verifier),requestedScopes=self.scopes)
        self.begin["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.verifier,self.key_id,self.begin["operationId"]))
        _,_,_,bob=self.connected();bob_cap=self.revoke_request(bob["grantId"])
        with self.assertRaises(NativeAuthorizationError):self.service.revoke_grant(alice_cap,bob["certificateSha256"])
        with self.assertRaises(NativeAuthorizationError):self.service.revoke_grant(dict(bob_cap,revokeCapability=alice_cap["revokeCapability"]),bob["certificateSha256"])
        self.assertEqual(self.service.revoke_grant(alice_cap,alice["certificateSha256"])[1]["state"],"REVOKED")
        self.assertEqual(self.service.authenticate(self.request(bob))["id"],owner_b["id"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_certificates").fetchone()[0],2)
            self.assertEqual(conn.execute("SELECT state FROM native_v2_grants WHERE grant_id=%s",(bob["grantId"],)).fetchone()[0],"TOKEN_ISSUED")



    def test_44_staged_reauthorization_leaf_can_only_revoke_its_exact_fresh_grant(self):
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        _,_,_,old=self.connected();type(self).now+=604801
        verifier=secrets.token_urlsafe(32);operation=secrets.token_hex(16)
        capability=codec.derive_revoke_capability(verifier,self.key_id,operation)
        value=dict(authorizationVersion=1,operationId=operation,name="Same installed vehicle",
            csrPem=self.csr,codeChallenge=challenge(verifier),requestedScopes=self.scopes,
            installationKeyId=self.key_id,expectedGeneration=1,proofNonce="account-reauthorization",
            revokeCommitment=hash_secret("revoke",capability),
            proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        message=codec.proof_transcript("CONNECTION_REAUTHORIZE",codec.decode_request("CONNECTION_REAUTHORIZE",value),
            installation_key_id=self.key_id,code_challenge=value["codeChallenge"])
        value["proof"]=base64.urlsafe_b64encode(self.key.sign(message,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        pending=self.service.begin(value)[1];self.approve_once(pending)
        self.verifier=verifier;self.begin["codeChallenge"]=value["codeChallenge"]
        issued=self.claim(pending)[1];staged=issued["certificateReceipt"]
        with self.service.db() as conn:
            with self.assertRaises(NativeAuthorizationError):self.service._certificate(conn,staged["certificateSha256"])
        logout=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],revokeCapability=capability)
        ack=self.service.revoke_grant(logout,staged["certificateSha256"])[1]
        self.assertEqual(self.service.revoke_grant(logout,staged["certificateSha256"])[1],ack)
        with self.assertRaises(NativeAuthorizationError):
            self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
                grantId=issued["grantId"],codeVerifier=verifier),staged["certificateSha256"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_generation FROM native_v2_installations").fetchone()[0],1)

    def test_45_lost_revoke_ack_replay_confirms_original_terminal_grant(self):
        _,_,_,receipt=self.connected();grant=receipt["grantId"];fingerprint=receipt["certificateSha256"]
        request=self.revoke_request(grant)
        self.service.revoke_grant(request,fingerprint)
        with self.connect() as conn:
            original=conn.execute("SELECT state,revoked_at,credential_epoch,device_revision,revoke_hash "
                "FROM native_v2_grants WHERE grant_id=%s",(grant,)).fetchone()
            self.assertEqual(original[0],"REVOKED")
            self.assertEqual(original[4],hash_secret("revoke",request["revokeCapability"]))
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials WHERE grant_id=%s",(grant,)).fetchone()[0],0)
        type(self).now+=5
        for retry in (request,dict(request,operationId=secrets.token_hex(16))):
            status,ack=self.service.revoke_grant(retry,fingerprint)
            self.assertEqual(status,200)
            self.assertEqual(ack,dict(authorizationVersion=1,operation="GRANT_REVOKE",operationId=retry["operationId"],
                state="REVOKED",disposition="TERMINAL",serverTime=self.now,grantId=grant,revokedAt=original[1]))
            codec.decode_response("GRANT_REVOKE",status,ack,expected_operation_id=retry["operationId"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT state,revoked_at,credential_epoch,device_revision,revoke_hash "
                "FROM native_v2_grants WHERE grant_id=%s",(grant,)).fetchone(),original)

    def test_46_already_revoked_still_requires_exact_capability_grant_and_certificate(self):
        _,_,_,receipt=self.connected();request=self.revoke_request(receipt["grantId"])
        fingerprint=receipt["certificateSha256"]
        self.service.revoke_grant(request,fingerprint)
        for retry,certificate,expected in (
            (dict(request,revokeCapability=secrets.token_urlsafe(32)),fingerprint,(401,"INVALID_CREDENTIAL")),
            (dict(request,grantId=secrets.token_hex(16)),fingerprint,(401,"INVALID_CREDENTIAL")),
            (request,"f"*64,(403,"CERTIFICATE_BINDING_MISMATCH")),
        ):
            with self.subTest(expected=expected),self.assertRaises(NativeAuthorizationError) as error:
                self.service.revoke_grant(retry,certificate)
            self.assertEqual((error.exception.status,error.exception.code),expected)
        self.assertEqual(self.service.revoke_grant(request,fingerprint)[1]["grantId"],receipt["grantId"])
