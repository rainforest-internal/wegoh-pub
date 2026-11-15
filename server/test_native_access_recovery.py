"""Real private PG recovery transitions, same key, no live CA/user records."""
import secrets
import unittest
import test_native_authorization as direct
from enrollment_crypto import challenge,digest
from native_access_codec import canonical_request,decode_request
from native_access_recovery import NativeAccessRecovery
from native_authorization import NativeAuthorization,NativeAuthorizationError,hash_secret
from native_access_codec import derive_revoke_capability

class Runtime(NativeAccessRecovery,NativeAuthorization):pass

class RecoveryTests(direct.NativeAuthorizationTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service=Runtime(cls.auth,issuer=cls.issuer,clock=lambda:cls.now,enabled=True)

    def recover(self):
        return self.service.recover_connection(self.signed("CONNECTION_RECOVER",
            dict(authorizationVersion=1,operationId=self.begin["operationId"],csrPem=self.csr,
                originalBeginHash=digest(canonical_request(decode_request("CONNECTION_BEGIN",self.begin))),
                codeVerifier=self.verifier,proofNonce="begin-recovery")))

    def test_10_expired_not_issued_server_ticket_restarts_same_key_once(self):
        pending=self.service.begin(self.begin)[1]
        self.assertEqual(self.recover()[1]["state"],"PENDING")
        type(self).now+=301
        recovered=self.recover()[1]
        self.assertEqual(recovered["state"],"EXPIRED_NOT_ISSUED")
        self.assertEqual(self.recover()[1]["restartTicket"],recovered["restartTicket"])
        old_verifier=self.verifier;self.verifier=secrets.token_urlsafe(32)
        restart=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Same owned key",
            csrPem=self.csr,codeChallenge=challenge(self.verifier),requestedScopes=self.scopes,
            previousConnectionId=pending["connectionId"],restartTicket=recovered["restartTicket"],
            oldCodeVerifier=old_verifier,proofNonce=pending["proofNonce"])
        restart["revokeCommitment"]=hash_secret("revoke",derive_revoke_capability(self.verifier,self.key_id,restart["operationId"]))
        self.begin=restart
        restart=self.signed("CONNECTION_RESTART",restart)
        status,new=self.service.begin(restart);self.assertEqual(status,201)
        self.assertEqual(self.service.begin(restart)[0],200)
        reused=dict(restart,operationId=secrets.token_hex(16))
        reused=self.signed("CONNECTION_RESTART",{k:v for k,v in reused.items() if k!="proof"})
        with self.assertRaises(NativeAuthorizationError) as error:self.service.begin(reused)
        self.assertEqual(error.exception.code,"RECOVERY_NOT_ALLOWED")
        detail=self.service.detail(new["userCode"],self.owner)
        self.service.approve(new["userCode"],dict(authorizationVersion=1,consentVersion=1,approvedScopes=self.scopes,
            keepSignedIn=False,disclosureVersion=2,disclosureSha256=detail["disclosureSnapshot"]["disclosureSha256"]),self.owner)
        status,issued=self.claim(new);self.assertEqual(status,200)
        self.assertEqual(issued["certificateReceipt"]["installationKeyId"],self.key_id)
        self.assertEqual(self.issuer.calls,1)
        with self.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_connections").fetchone()[0],2)

    def test_11_uncertain_old_request_never_gets_restart_ticket_or_second_ca_post(self):
        pending=self.start();self.issuer.crash=True
        self.assertEqual(self.claim(pending)[1]["state"],"UNCERTAIN")
        type(self).now+=301
        recovered=self.recover()[1]
        self.assertEqual(recovered["state"],"UNCERTAIN")
        self.assertNotIn("restartTicket",recovered)
        self.assertEqual(self.claim(pending)[1]["state"],"UNCERTAIN")
        self.assertEqual(self.issuer.calls,1)

    def test_12_public_certificate_recovery_has_no_personal_grant_and_rejects_old_generation(self):
        pending,issued,exchange,personal=self.connected()
        request=dict(authorizationVersion=1,operationId=secrets.token_hex(16),installationKeyId=self.key_id,
            generationOperationId=issued["certificateReceipt"]["generationOperationId"],expectedGeneration=1,
            codeVerifier=self.verifier,proofNonce=pending["proofNonce"])
        signed=self.signed("CERTIFICATE_RECOVER",request)
        status,public=self.service.certificate_recover(signed);self.assertEqual(status,200)
        self.assertEqual(set(public),{"authorizationVersion","operation","operationId","state","disposition","serverTime","certificateReceipt"})
        self.service.revoke(personal["deviceId"],dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=personal["grantId"],revokeCapability=personal["revokeCapability"]),personal["certificateSha256"])
        self.assertEqual(self.service.certificate_recover(signed)[0],200)
        wrong=dict(request,proofNonce=secrets.token_urlsafe(32))
        with self.assertRaises(NativeAuthorizationError) as error:self.service.certificate_recover(self.signed("CERTIFICATE_RECOVER",wrong))
        self.assertEqual(error.exception.code,"INVALID_PROOF")
        with self.connect() as conn:conn.execute("UPDATE native_v2_installations SET current_generation=2 WHERE installation_key_id=%s",(self.key_id,))
        with self.assertRaises(NativeAuthorizationError) as error:self.service.certificate_recover(signed)
        self.assertEqual(error.exception.code,"STALE_EPOCH")

if __name__=="__main__":unittest.main()
