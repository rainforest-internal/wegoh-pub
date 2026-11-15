"""Private PostgreSQL renewal/CAS tests, synthetic CA only, no production key."""
import base64,secrets
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import native_access_codec as codec
import test_native_authorization as fixture
from native_authorization_runtime import NativeAuthorizationRuntime
from native_authorization import NativeAuthorizationError,restore
from enrollment_crypto import challenge,IssuanceUncertain

class RenewalTests(fixture.NativeAuthorizationTests):
    def setUp(self):
        super().setUp()
        type(self).service=NativeAuthorizationRuntime(self.auth,issuer=self.issuer,clock=lambda:type(self).now,enabled=True)
        self.issued_result=None;self.lost=False;self.reconcile_calls=0
        original=self.issuer.issue
        # The parent fixture is class-shared; restore the actual original method.
        from test_enrollment import SyntheticIssuer
        def issue(csr):
            result=SyntheticIssuer.issue(self.issuer,csr)
            self.issued_result=result
            if self.lost:raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
            return result
        def reconcile(csr,excluded):
            self.reconcile_calls+=1
            if self.issued_result and self.issued_result["certificateSha256"] not in excluded:
                return self.issued_result
            return None
        self.issuer.issue=issue;self.issuer.reconcile=reconcile
        self.ca_revoked=False
        def active(*args):
            from enrollment_crypto import EnrollmentError
            if self.ca_revoked:raise EnrollmentError("INSTALLATION_REVOKED")
            return True
        self.issuer.require_active_certificate=active

    def sign_renew(self,action,value,connection=None,challenge_value=None):
        value=dict(value,proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        transcript=codec.proof_transcript(action,codec.decode_request(action,value),
            installation_key_id=self.key_id,code_challenge=challenge_value or self.renew_challenge,
            connection_id=connection)
        value["proof"]=base64.urlsafe_b64encode(self.key.sign(transcript,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        return value

    def renew(self,receipt):
        self.renew_verifier=secrets.token_urlsafe(32);self.renew_challenge=challenge(self.renew_verifier)
        value=self.sign_renew("CERTIFICATE_RENEW_BEGIN",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            csrPem=self.csr,installationKeyId=self.key_id,grantId=receipt["grantId"],deviceId=receipt["deviceId"],
            recoveryCapability=receipt["recoveryCapability"],expectedGeneration=receipt["generation"],
            codeChallenge=self.renew_challenge,proofNonce="certificate-renewal"))
        status,pending=self.service.renew_begin(value);self.assertEqual(status,201)
        return value,pending

    def renew_claim(self,pending):
        value=self.sign_renew("CERTIFICATE_RENEW_CLAIM",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            codeVerifier=self.renew_verifier,proofNonce=pending["proofNonce"]),pending["connectionId"])
        return self.service.claim(pending["connectionId"],value)

    def rebind_request(self,old,pending):
        return dict(authorizationVersion=1,operationId=secrets.token_hex(16),connectionId=pending["connectionId"],
            grantId=old["grantId"],deviceId=old["deviceId"],recoveryCapability=old["recoveryCapability"])

    def test_20_same_grant_renewal_stages_until_atomic_rebind_and_old_cert_denied(self):
        _,_,_,old=self.connected();value,pending=self.renew(old)
        self.assertEqual(self.service.renew_begin(value)[0],200)
        staged=self.renew_claim(pending)[1]["certificateReceipt"]
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_generation FROM native_v2_installations").fetchone()[0],1)
            # The issuer-readable bootstrap never stores a personal capability.
            blob=conn.execute("SELECT protected_request FROM native_v2_connections WHERE connection_id=%s",(pending["connectionId"],)).fetchone()[0]
            self.assertNotIn("recoveryCapability",restore("connection",pending["connectionId"],blob))
        with self.service.db() as conn:
            with self.assertRaises(NativeAuthorizationError):self.service._certificate(conn,staged["certificateSha256"])
        request=self.rebind_request(old,pending)
        new=self.service.rebind(request,staged["certificateSha256"])[1]["credentialReceipt"]
        for key in ("grantId","deviceId","accountId","scopes","consentVersion","slotRevision","grantExpiresAt","installationKeyId"):
            self.assertEqual(new[key],old[key],key)
        self.assertEqual(new["generation"],2);self.assertGreater(new["credentialEpoch"],old["credentialEpoch"])
        self.assertEqual(self.service.rebind(request,staged["certificateSha256"])[1]["credentialReceipt"],new)
        with self.assertRaises(NativeAuthorizationError) as rejected:self.service.authenticate(self.request(old))
        self.assertEqual((rejected.exception.status,rejected.exception.code),(401,"INVALID_CREDENTIAL"))
        with self.service.db() as conn:
            with self.assertRaises(NativeAuthorizationError):self.service._certificate(conn,old["certificateSha256"])
        self.assertEqual(self.service.authenticate(self.request(new))["deviceId"],old["deviceId"])
        with self.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_grants").fetchone()[0],1)
        self.assertEqual(self.issuer.calls,2)

    def test_21_uncertain_post_reconciles_get_without_second_post(self):
        _,_,_,old=self.connected();_,pending=self.renew(old);self.lost=True
        result=self.renew_claim(pending)
        self.assertEqual(result[1]["state"],"UNCERTAIN");calls=self.issuer.calls
        type(self).now+=5;self.lost=False
        staged=self.renew_claim(pending)[1]["certificateReceipt"]
        self.assertEqual(self.issuer.calls,calls);self.assertGreaterEqual(self.reconcile_calls,2)
        new=self.service.rebind(self.rebind_request(old,pending),staged["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(new["grantExpiresAt"],old["grantExpiresAt"])

    def test_22_revoke_before_rebind_rejects_staged_and_purges_personal_auth(self):
        _,_,_,old=self.connected();_,pending=self.renew(old);staged=self.renew_claim(pending)[1]["certificateReceipt"]
        self.service.revoke(old["deviceId"],dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=old["grantId"],revokeCapability=old["revokeCapability"]),old["certificateSha256"])
        with self.assertRaises(NativeAuthorizationError):self.service.rebind(self.rebind_request(old,pending),staged["certificateSha256"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_generation FROM native_v2_installations").fetchone()[0],1)
            row=conn.execute("SELECT account_id,protected_consent,recovery_hash,revoke_hash FROM native_v2_grants").fetchone()
            self.assertEqual(row[:3],(None,None,None));self.assertIsNotNone(row[3])
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_operations").fetchone()[0],0)

    def test_23_scope_change_before_rebind_invalidates_lease_and_recovers_only_subset(self):
        from native_access_retention import reduce_grant_scopes
        _,_,_,old=self.connected();_,pending=self.renew(old);staged=self.renew_claim(pending)[1]["certificateReceipt"]
        with self.service.db() as conn:
            self.service.lock(conn,self.key_id)
            grant=conn.execute("SELECT * FROM native_v2_grants FOR UPDATE").fetchone()
            reduce_grant_scopes(conn,grant,["account:read","device:self:manage"],expected_consent_version=1)
        with self.assertRaises(NativeAuthorizationError) as error:self.service.rebind(self.rebind_request(old,pending),staged["certificateSha256"])
        self.assertEqual(error.exception.code,"STALE_EPOCH")
        with self.assertRaises(NativeAuthorizationError):
            self.service.session("SESSION_REFRESH",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
                grantId=old["grantId"],deviceId=old["deviceId"],refreshToken=old["refreshToken"]),old["certificateSha256"])
        new=self.service.session("SESSION_RECOVER",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=old["grantId"],deviceId=old["deviceId"],recoveryCapability=old["recoveryCapability"]),
            old["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(new["scopes"],["account:read","device:self:manage"])
        self.assertEqual(new["grantExpiresAt"],old["grantExpiresAt"])



    def test_24_explicit_old_ca_revocation_blocks_begin_claim_and_final_rebind(self):
        _,_,_,old=self.connected();self.ca_revoked=True
        with self.assertRaises(NativeAuthorizationError) as error:self.renew(old)
        self.assertEqual(error.exception.code,"INSTALLATION_REVOKED")
        self.ca_revoked=False;_,pending=self.renew(old)
        self.ca_revoked=True
        with self.assertRaises(NativeAuthorizationError) as error:self.renew_claim(pending)
        self.assertEqual(error.exception.code,"INSTALLATION_REVOKED");self.assertEqual(self.issuer.calls,1)
        self.ca_revoked=False;staged=self.renew_claim(pending)[1]["certificateReceipt"]
        self.ca_revoked=True
        with self.assertRaises(NativeAuthorizationError) as error:self.service.rebind(self.rebind_request(old,pending),staged["certificateSha256"])
        self.assertEqual(error.exception.code,"INSTALLATION_REVOKED")
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_generation FROM native_v2_installations").fetchone()[0],1)
