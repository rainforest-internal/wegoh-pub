"""Four common expiry cells with the current strict shared wire."""
import base64,json,secrets
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509.oid import ExtendedKeyUsageOID
import native_access_codec as codec
import test_native_authorization as fixture
from native_authorization_runtime import NativeAuthorizationRuntime
from native_authorization import NativeAuthorizationError,protect
from enrollment_crypto import challenge,EnrollmentError,IssuanceUncertain,validate_issued
from test_enrollment import CA_ID,SyntheticIssuer

CANDIDATE=Path(__file__).with_name("native_access_wire.json")

class ReauthorizationTests(fixture.NativeAuthorizationTests):
    def setUp(self):
        super().setUp()
        value=json.loads(CANDIDATE.read_text())
        # Reuse the exact current contract. Earlier candidate executions remain
        # preserved in their original evidence; this execution is current wire.
        for name,replacement in (("_WIRE",value),("_OPERATIONS",{o["action"]:o for o in value["operations"]})):
            scope=patch.object(codec,name,replacement);scope.start();self.addCleanup(scope.stop)
        type(self).service=NativeAuthorizationRuntime(self.auth,issuer=self.issuer,clock=lambda:type(self).now,enabled=True)
        self.duration=3600;self.ca_state="active";self.public_result=None;self.ca_checks=0
        def response(csr):
            now=datetime.fromtimestamp(type(self).now,timezone.utc)
            cert=(x509.CertificateBuilder().subject_name(csr.subject).issuer_name(self.issuer.name)
                .public_key(csr.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now-timedelta(seconds=30)).not_valid_after(now+timedelta(seconds=self.duration))
                .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=False,
                    data_encipherment=False,key_agreement=False,key_cert_sign=False,crl_sign=False,
                    encipher_only=False,decipher_only=False),critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),critical=False)
                .sign(self.issuer.key,hashes.SHA256()))
            return dict(id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",status="active",
                certificate_authority=dict(id=CA_ID),certificate=cert.public_bytes(serialization.Encoding.PEM).decode(),
                fingerprint_sha256=cert.fingerprint(hashes.SHA256()).hex())
        self.issuer.response=response
        def issue(csr):
            from enrollment_crypto import validate_csr
            self.issuer.calls+=1
            if self.issuer.crash:raise IssuanceUncertain('ISSUANCE_UNCERTAIN')
            request=validate_csr(csr)
            result=validate_issued(request,self.issuer.response(request),CA_ID,
                now=datetime.fromtimestamp(type(self).now,timezone.utc))
            if self.issuer.after_issue:self.issuer.after_issue()
            self.public_result=result;return result
        self.issuer.issue=issue
        self.issuer.reconcile=lambda csr,excluded:None
        def ca_check(provenance,key,fingerprint):
            self.ca_checks+=1
            if self.ca_state=="unknown":raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
            if self.ca_state!="active":raise EnrollmentError("INSTALLATION_REVOKED")
            return True
        self.issuer.require_active_certificate=ca_check

    def reauth(self,old):
        self.new_verifier=secrets.token_urlsafe(32);new_challenge=challenge(self.new_verifier)
        value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Same installed vehicle",
            csrPem=self.csr,codeChallenge=new_challenge,requestedScopes=self.scopes,
            installationKeyId=self.key_id,expectedGeneration=old["generation"],proofNonce="account-reauthorization",
            proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        from native_authorization import hash_secret
        value["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.new_verifier,self.key_id,value["operationId"]))
        message=codec.proof_transcript("CONNECTION_REAUTHORIZE",codec.decode_request("CONNECTION_REAUTHORIZE",value),
            installation_key_id=self.key_id,code_challenge=new_challenge)
        value["proof"]=base64.urlsafe_b64encode(self.key.sign(message,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        return value

    def approve_once(self,pending):
        snapshot=self.service.detail(pending["userCode"],self.owner)["disclosureSnapshot"]
        self.service.approve(pending["userCode"],dict(authorizationVersion=1,consentVersion=1,
            approvedScopes=self.scopes,keepSignedIn=False,disclosureVersion=2,
            disclosureSha256=snapshot["disclosureSha256"]),self.owner)

    def test_30_both_expired_same_key_one_new_phone_consent_and_fresh_main_exchange(self):
        _,_,_,old=self.connected();type(self).now+=604801
        value=self.reauth(old);status,pending=self.service.begin(value);self.assertEqual(status,201)
        self.assertEqual(self.service.begin(value)[0],200)
        before=self.issuer.calls;self.approve_once(pending)
        self.verifier=self.new_verifier;self.begin["codeChallenge"]=value["codeChallenge"]
        status,issued=self.claim(pending);self.assertEqual(status,200,issued)
        staged=issued["certificateReceipt"]
        with self.service.db() as conn:
            with self.assertRaises(NativeAuthorizationError):self.service._certificate(conn,staged["certificateSha256"])
        request=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=issued["grantId"],codeVerifier=self.new_verifier)
        new=self.service.session("SESSION_EXCHANGE",request,staged["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(new["installationKeyId"],old["installationKeyId"])
        self.assertEqual(new["generation"],2);self.assertNotEqual(new["grantId"],old["grantId"])
        self.assertGreater(new["grantExpiresAt"],old["grantExpiresAt"])
        self.assertEqual(self.issuer.calls,before+1);self.assertGreaterEqual(self.ca_checks,2)
        self.assertEqual(self.service.authenticate(self.request(new))["deviceId"],new["deviceId"])
        with self.connect() as conn:
            row=conn.execute("SELECT state,account_id,recovery_hash FROM native_v2_grants WHERE grant_id=%s",(old["grantId"],)).fetchone()
            self.assertEqual(row,("REVOKED",None,None))
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_installations").fetchone()[0],1)

    def test_31_expired_certificate_live_grant_uses_automatic_renewal_no_phone(self):
        import test_native_access_renewal as renewal
        _,_,_,old=self.connected();type(self).now+=3601
        self.new_verifier=secrets.token_urlsafe(32);ch=challenge(self.new_verifier)
        value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),csrPem=self.csr,
            installationKeyId=self.key_id,grantId=old["grantId"],deviceId=old["deviceId"],
            recoveryCapability=old["recoveryCapability"],expectedGeneration=1,codeChallenge=ch,
            proofNonce="certificate-renewal",proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        record=codec.decode_request("CERTIFICATE_RENEW_BEGIN",value)
        msg=codec.proof_transcript("CERTIFICATE_RENEW_BEGIN",record,installation_key_id=self.key_id,code_challenge=ch)
        value["proof"]=base64.urlsafe_b64encode(self.key.sign(msg,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        pending=self.service.renew_begin(value)[1]
        claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=self.new_verifier,
            proofNonce=pending["proofNonce"],proof=base64.urlsafe_b64encode(bytes(256)).rstrip(b"=").decode())
        msg=codec.proof_transcript("CERTIFICATE_RENEW_CLAIM",codec.decode_request("CERTIFICATE_RENEW_CLAIM",claim),
            installation_key_id=self.key_id,code_challenge=ch,connection_id=pending["connectionId"])
        claim["proof"]=base64.urlsafe_b64encode(self.key.sign(msg,padding.PKCS1v15(),hashes.SHA256())).rstrip(b"=").decode()
        staged=self.service.claim(pending["connectionId"],claim)[1]["certificateReceipt"]
        rebind=dict(authorizationVersion=1,operationId=secrets.token_hex(16),connectionId=pending["connectionId"],
            grantId=old["grantId"],deviceId=old["deviceId"],recoveryCapability=old["recoveryCapability"])
        new=self.service.rebind(rebind,staged["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual((new["grantId"],new["deviceId"],new["grantExpiresAt"]),(old["grantId"],old["deviceId"],old["grantExpiresAt"]))
        with self.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_approvals").fetchone()[0],1)

    def test_32_valid_certificate_expired_grant_same_certificate_phone_only(self):
        self.duration=7776000
        _,issued,_,old=self.connected();type(self).now+=604801
        self.new_verifier=secrets.token_urlsafe(32);self.verifier=self.new_verifier
        self.begin["codeChallenge"]=challenge(self.new_verifier)
        value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Same car",
            certificatePem=issued["certificateReceipt"]["certificatePem"],codeChallenge=self.begin["codeChallenge"],
            requestedScopes=self.scopes)
        from native_authorization import hash_secret
        value["revokeCommitment"]=hash_secret("revoke",codec.derive_revoke_capability(self.new_verifier,self.key_id,value["operationId"]))
        pending=self.service.account_authorize(value,old["certificateSha256"])[1];self.approve_once(pending)
        approved=self.service.account_authorize(value,old["certificateSha256"])[1]
        new=self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=approved["grantId"],codeVerifier=self.new_verifier),old["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(new["generation"],1);self.assertEqual(self.issuer.calls,1)

    def test_33_explicit_ca_revocation_unknown_and_install_ban_never_reissue(self):
        _,_,_,old=self.connected();type(self).now+=604801
        for state in ("revoked","pending_revocation","pending_reactivation","unknown"):
            self.ca_state=state
            with self.subTest(state=state),self.assertRaises(NativeAuthorizationError) as error:self.service.begin(self.reauth(old))
            self.assertIn(error.exception.status,(403,503))
        self.ca_state="active"
        with self.connect() as conn:conn.execute("UPDATE native_v2_installations SET revoked_at=%s",(type(self).now,))
        with self.assertRaises(NativeAuthorizationError) as error:self.service.begin(self.reauth(old))
        self.assertEqual(error.exception.code,"INSTALLATION_REVOKED");self.assertEqual(self.issuer.calls,1)



    def test_34_ca_revoked_after_claim_cannot_commit_staged_fresh_grant(self):
        _,_,_,old=self.connected();type(self).now+=604801
        value=self.reauth(old);pending=self.service.begin(value)[1];self.approve_once(pending)
        self.verifier=self.new_verifier;self.begin["codeChallenge"]=value["codeChallenge"]
        staged=self.claim(pending)[1]["certificateReceipt"]
        self.ca_state="revoked"
        with self.assertRaises(NativeAuthorizationError) as error:
            self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
                grantId=self._staged_grant(pending),
                codeVerifier=self.new_verifier),staged["certificateSha256"])
        self.assertEqual(error.exception.code,"INSTALLATION_REVOKED")
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_generation FROM native_v2_installations").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_grants WHERE state='TOKEN_ISSUED' AND expires_at>%s",
                (type(self).now,)).fetchone()[0],0)

    def test_35_new_reauthorization_replaces_the_dropped_unclaimed_code(self):
        _,_,_,old=self.connected();type(self).now+=604801
        status,first=self.service.begin(self.reauth(old));self.assertEqual(status,201)
        type(self).now+=2
        value=self.reauth(old);status,pending=self.service.begin(value)
        self.assertEqual(status,201);self.assertNotEqual(pending["userCode"],first["userCode"])
        with self.assertRaises(NativeAuthorizationError) as error:self.service.detail(first["userCode"],self.owner)
        self.assertEqual((error.exception.status,error.exception.code),(410,"AUTHORIZATION_EXPIRED"))
        self.approve_once(pending)
        self.verifier=self.new_verifier;self.begin["codeChallenge"]=value["codeChallenge"]
        status,issued=self.claim(pending);self.assertEqual((status,issued["state"]),(200,"ISSUED"))

    def _staged_grant(self,pending):
        with self.connect() as conn:
            return conn.execute("SELECT grant_id FROM native_v2_approvals WHERE connection_id=%s",
                (pending["connectionId"],)).fetchone()[0]
