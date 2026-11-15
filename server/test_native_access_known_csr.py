"""One same-key public-leaf reuse/recovery edge in a private PostgreSQL fixture."""
import secrets,base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from enrollment_crypto import IssuanceUncertain
import native_access_codec as codec
from enrollment_crypto import challenge
from native_access_codec import derive_revoke_capability,revoke_commitment
from native_authorization import NativeAuthorizationError
from test_native_access_reauthorization import ReauthorizationTests
from test_enrollment import make_csr

def encoded(value):return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

class KnownCsrRecoveryTests(ReauthorizationTests):
    def test_40_fresh_phone_reuses_current_public_leaf_and_new_pkce_public_recovery_alias(self):
        pending,issued,exchange,old=self.connected()
        original_receipt=issued["certificateReceipt"]
        old_grant=old["grantId"];old_begin=dict(self.begin)
        self.service.approve(pending["userCode"],dict(authorizationVersion=1),self.owner,deny=True)
        self.verifier=secrets.token_urlsafe(32)
        self.begin=dict(old_begin,operationId=secrets.token_hex(16),codeChallenge=challenge(self.verifier))
        self.begin["revokeCommitment"]=revoke_commitment(derive_revoke_capability(self.verifier,self.key_id,self.begin["operationId"]))
        fresh_pending=self.start()
        fresh_issued=self.claim(fresh_pending)[1]
        self.assertEqual(fresh_issued["certificateReceipt"],original_receipt)
        self.assertNotEqual(original_receipt["generationOperationId"],self.begin["operationId"])
        self.assertEqual(self.issuer.calls,1)
        fresh=self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=fresh_issued["grantId"],codeVerifier=self.verifier),original_receipt["certificateSha256"])[1]["credentialReceipt"]
        self.assertNotEqual(fresh["grantId"],old_grant)
        self.assertEqual(self.service.authenticate(self.request(fresh))["deviceId"],fresh["deviceId"])
        self.service.approve(fresh_pending["userCode"],dict(authorizationVersion=1),self.owner,deny=True)
        body=dict(authorizationVersion=1,operationId=secrets.token_hex(16),installationKeyId=self.key_id,
            generationOperationId=original_receipt["generationOperationId"],expectedGeneration=1,
            codeVerifier=self.verifier,proofNonce=fresh_pending["proofNonce"])
        public=self.service.certificate_recover(self.signed("CERTIFICATE_RECOVER",body))[1]
        self.assertEqual(public["certificateReceipt"],original_receipt)
        self.assertEqual(set(public),{"authorizationVersion","operation","operationId","state","disposition","serverTime","certificateReceipt"})
        for field,value in (("codeVerifier",secrets.token_urlsafe(32)),("proofNonce",secrets.token_urlsafe(32)),
                            ("generationOperationId",secrets.token_hex(16)),("expectedGeneration",2)):
            with self.subTest(field=field),self.assertRaises(NativeAuthorizationError):
                self.service.certificate_recover(self.signed("CERTIFICATE_RECOVER",dict(body,**{field:value})))
        with self.connect() as conn:
            for grant in (old_grant,fresh["grantId"]):
                row=conn.execute("SELECT state,account_id,protected_consent FROM native_v2_grants WHERE grant_id=%s",(grant,)).fetchone()
                self.assertEqual(tuple(row),("REVOKED",None,None))
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_certificates").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)
        self.assertEqual(self.issuer.calls,1)

    def _fresh_phone_after_cancelled_unknown(self,kind):
        original_pending,_,_,old=self.connected()
        type(self).now+=3601 if kind=="RENEW" else 604801
        verifier=secrets.token_urlsafe(32);pkce=challenge(verifier)
        if kind=="RENEW":
            request=dict(authorizationVersion=1,operationId=secrets.token_hex(16),csrPem=self.csr,
                installationKeyId=self.key_id,grantId=old["grantId"],deviceId=old["deviceId"],recoveryCapability=old["recoveryCapability"],
                expectedGeneration=1,codeChallenge=pkce,proofNonce="certificate-renewal",proof=encoded(bytes(256)))
            request["proof"]=encoded(self.key.sign(codec.proof_transcript("CERTIFICATE_RENEW_BEGIN",codec.decode_request("CERTIFICATE_RENEW_BEGIN",request),
                installation_key_id=self.key_id,code_challenge=pkce),padding.PKCS1v15(),hashes.SHA256()))
            pending=self.service.renew_begin(request)[1];action="CERTIFICATE_RENEW_CLAIM"
        else:
            request=self.reauth(old);verifier=self.new_verifier;pkce=request["codeChallenge"]
            pending=self.service.begin(request)[1];self.approve_once(pending);action="CONNECTION_CLAIM"
        real_issue=self.issuer.issue;captured={}
        def lost(csr):
            captured["outcome"]=real_issue(csr)
            raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
        self.issuer.issue=lost
        prior_claim=dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=verifier,
            proofNonce=pending["proofNonce"],proof=encoded(bytes(256)))
        prior_claim["proof"]=encoded(self.key.sign(codec.proof_transcript(action,codec.decode_request(action,prior_claim),
            installation_key_id=self.key_id,code_challenge=pkce,connection_id=pending["connectionId"]),padding.PKCS1v15(),hashes.SHA256()))
        self.assertEqual(self.service.claim(pending["connectionId"],prior_claim)[1]["state"],"UNCERTAIN")
        self.service.approve((original_pending if kind=="RENEW" else pending)["userCode"],dict(authorizationVersion=1),self.owner,deny=True)
        calls=self.issuer.calls
        # Fresh same-key consent has no previous verifier/capability/owner data.
        self.verifier=secrets.token_urlsafe(32)
        self.begin=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Fresh same key",
            csrPem=self.csr,codeChallenge=challenge(self.verifier),requestedScopes=self.scopes)
        self.begin["revokeCommitment"]=revoke_commitment(derive_revoke_capability(self.verifier,self.key_id,self.begin["operationId"]))
        fresh=self.start()
        for outcome in (None,"uncertain"):
            def unknown(csr,excluded):
                if outcome=="uncertain":raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
                return None
            self.issuer.reconcile=unknown
            self.assertEqual(self.claim(fresh)[1]["state"],"PENDING")
            self.assertEqual(self.issuer.calls,calls)
        self.issuer.reconcile=lambda csr,excluded:captured["outcome"] if captured["outcome"]["certificateSha256"] not in excluded else None
        issued=self.claim(fresh)[1]
        self.assertEqual(issued["state"],"ISSUED");self.assertEqual(self.issuer.calls,calls)
        receipt=self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=issued["grantId"],codeVerifier=self.verifier),issued["certificateReceipt"]["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(receipt["generation"],2);self.assertNotEqual(receipt["grantId"],old["grantId"])
        self.assertEqual(self.service.authenticate(self.request(receipt))["deviceId"],receipt["deviceId"])
        self.assertEqual(self.issuer.calls,calls)

    def test_41_cancelled_reauthorize_unknown_get_only_fresh_phone_has_no_old_pkce(self):
        self._fresh_phone_after_cancelled_unknown("REAUTHORIZE")

    def test_42_cancelled_renewal_unknown_get_only_fresh_phone_has_no_old_capability(self):
        self._fresh_phone_after_cancelled_unknown("RENEW")

    def test_43_signed_recover_settles_current_unknown_without_second_phone_or_ca_post(self):
        pending=self.start();real_issue=self.issuer.issue;captured={}
        def lost(csr):
            captured["outcome"]=real_issue(csr)
            raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
        self.issuer.issue=lost
        self.assertEqual(self.claim(pending)[1]["state"],"UNCERTAIN")
        self.issuer.reconcile=lambda csr,excluded:captured["outcome"]
        body=dict(authorizationVersion=1,operationId=self.begin["operationId"],csrPem=self.csr,
            originalBeginHash=__import__("enrollment_crypto").digest(codec.canonical_request(codec.decode_request("CONNECTION_BEGIN",self.begin))),
            codeVerifier=self.verifier,proofNonce="begin-recovery")
        response=self.service.recover_connection(self.signed("CONNECTION_RECOVER",body))[1]
        self.assertEqual((response["state"],response["disposition"]),("ISSUED","EXCHANGE"))
        self.assertEqual(self.issuer.calls,1)
        receipt=self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=response["grantId"],codeVerifier=self.verifier),response["certificateReceipt"]["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(self.service.authenticate(self.request(receipt))["deviceId"],receipt["deviceId"])
        with self.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_approvals").fetchone()[0],1)

    def test_44_public_unknown_settlement_uses_real_column_limited_issuer_role(self):
        pending=self.start();real_issue=self.issuer.issue;captured={}
        def lost(csr):
            captured["outcome"]=real_issue(csr)
            raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
        self.issuer.issue=lost
        self.assertEqual(self.claim(pending)[1]["state"],"UNCERTAIN")
        self.service.approve(pending["userCode"],dict(authorizationVersion=1),self.owner,deny=True)
        with self.connect() as conn:
            conn.execute("CREATE ROLE publicoutcomeissuer NOLOGIN")
            conn.execute("GRANT USAGE ON SCHEMA public TO publicoutcomeissuer")
            from pathlib import Path
            grants=(Path(__file__).parent/"ops/live/enrollment-grants.sql").read_text()
            # Consume the actual reviewed v2 grants; do not mirror them in a fake
            # privileged fixture that could conceal a later query expansion.
            v2=grants[grants.index("GRANT SELECT,INSERT,UPDATE ON public.native_v2_connections"):]
            conn.execute(v2.replace("TO wegohenroll","TO publicoutcomeissuer"))
        original_db=self.service.db
        def issuer_db():
            connection=original_db();connection.execute("SET LOCAL ROLE publicoutcomeissuer");return connection
        self.service.db=issuer_db;self.addCleanup(lambda:setattr(self.service,"db",original_db))
        import psycopg
        for table in ("native_v2_installations","native_v2_certificates","native_v2_grants","native_v2_credentials"):
            with self.subTest(table=table),self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with issuer_db() as conn:conn.execute("SELECT * FROM "+table)
        self.issuer.reconcile=lambda csr,excluded:captured["outcome"]
        self.assertTrue(self.service._reconcile_unknown_public(self.key_id))
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT current_generation FROM native_v2_installations").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT state FROM native_v2_connections WHERE connection_id=%s",(pending["connectionId"],)).fetchone()[0],"ISSUED")
            self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)
        self.assertEqual(self.issuer.calls,1)

    def test_45_initial_normal_flow_uses_column_limited_issuer_begin_and_claim(self):
        # Public BEGIN/CLAIM use the same actual production column-limited SQL
        # role. Only phone approval and personal exchange use the owner/main.
        from pathlib import Path
        from native_authorization_runtime import NativeAuthorizationRuntime
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS team_accounts(account_id text PRIMARY KEY,protected bytea)")
            conn.execute("CREATE ROLE normalflowissuer NOLOGIN")
            conn.execute("GRANT USAGE ON SCHEMA public TO normalflowissuer")
            grants=(Path(__file__).parent/"ops/live/enrollment-grants.sql").read_text()
            # Exact full runtime grants, including existing v1 bootstrap reads.
            # Only isolated database/role names change; no right is added.
            conn.execute(grants.replace("ON DATABASE wegoh_live", "ON DATABASE postgres").replace("TO wegohenroll","TO normalflowissuer"))
        issuer_service=NativeAuthorizationRuntime(self.auth,issuer=self.issuer,clock=lambda:type(self).now,enabled=True)
        owner_db=issuer_service.db
        def issuer_db():
            connection=owner_db();connection.execute("SET LOCAL ROLE normalflowissuer");return connection
        issuer_service.db=issuer_db
        with issuer_db() as conn:self.assertEqual(conn.execute("SELECT current_user").fetchone()["current_user"],"normalflowissuer")
        status,pending=issuer_service.begin(self.begin)
        self.assertEqual(status,201,pending)
        self.approve_once(pending)  # Actual owner/main consent path only.
        status,issued=issuer_service.claim(pending["connectionId"],self.signed("CONNECTION_CLAIM",
            dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=self.verifier,
                proofNonce=pending["proofNonce"]),pending["connectionId"]))
        self.assertEqual(status,200,issued)
        self.assertEqual(issued["state"],"ISSUED")
        with self.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM native_v2_credentials").fetchone()[0],0)
        receipt=self.service.session("SESSION_EXCHANGE",dict(authorizationVersion=1,operationId=secrets.token_hex(16),
            grantId=issued["grantId"],codeVerifier=self.verifier),issued["certificateReceipt"]["certificateSha256"])[1]["credentialReceipt"]
        self.assertEqual(self.service.authenticate(self.request(receipt))["deviceId"],receipt["deviceId"])
        self.assertEqual(receipt["installationKeyId"],self.key_id)
        self.assertEqual(receipt["scopes"],self.scopes)
        self.assertEqual(self.issuer.calls,1)

    def enroll_role_service(self,role):
        # /v1/connections/cancel runs on the enroll host as wegohenroll.
        # Exact reviewed runtime grants; only isolated database/role names change.
        from pathlib import Path
        from native_authorization_runtime import NativeAuthorizationRuntime
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS team_accounts(account_id text PRIMARY KEY,protected bytea)")
            conn.execute("CREATE ROLE "+role+" NOLOGIN")
            conn.execute("GRANT USAGE ON SCHEMA public TO "+role)
            grants=(Path(__file__).parent/"ops/live/enrollment-grants.sql").read_text()
            conn.execute(grants.replace("ON DATABASE wegoh_live","ON DATABASE postgres").replace("TO wegohenroll","TO "+role))
        service=NativeAuthorizationRuntime(self.auth,issuer=self.issuer,clock=lambda:type(self).now,enabled=True)
        owner_db=service.db
        def enroll_db():
            connection=owner_db();connection.execute("SET LOCAL ROLE "+role);return connection
        service.db=enroll_db
        import psycopg
        for table in ("native_v2_grants","native_v2_approvals"):
            with self.subTest(table=table),self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with enroll_db() as conn:conn.execute("SELECT 1 FROM "+table)
        return service

    def enroll_claim(self,service,pending):
        return service.claim(pending["connectionId"],self.signed("CONNECTION_CLAIM",
            dict(authorizationVersion=1,operationId=secrets.token_hex(16),codeVerifier=self.verifier,
                proofNonce=pending["proofNonce"]),pending["connectionId"]))

    def test_46_enroll_role_cancel_ends_pending_install_code(self):
        enroll=self.enroll_role_service("cancelpendingenroll")
        status,pending=enroll.begin(self.begin);self.assertEqual(status,201,pending)
        type(self).now+=2
        status,ended=self.cancel(self.begin["operationId"],service=enroll)
        self.assertEqual((status,ended["state"],ended["disposition"]),(200,"EXPIRED","TERMINAL"))
        self.assertEqual(self.cancel(self.begin["operationId"],service=enroll),(status,ended))
        self.assert_expired(lambda:self.service.detail(pending["userCode"],self.owner),
            lambda:self.approve_once(pending),lambda:self.enroll_claim(enroll,pending))
        self.assertEqual(self.issuer.calls,0)

    def test_47_enroll_role_cancel_ends_approved_install_code_before_claim(self):
        enroll=self.enroll_role_service("cancelapprovedenroll")
        status,pending=enroll.begin(self.begin);self.assertEqual(status,201,pending)
        self.approve_once(pending)  # Owner/main consent path only.
        type(self).now+=2
        self.assertEqual(self.cancel(self.begin["operationId"],service=enroll)[1]["state"],"EXPIRED")
        self.assert_expired(lambda:self.enroll_claim(enroll,pending),lambda:self.service.detail(pending["userCode"],self.owner))
        self.assertEqual(self.issuer.calls,0)
        # The approval no longer holds the owner's single vehicle slot.
        other_key,other_csr=make_csr()
        self.approve_once(enroll.begin(dict(self.begin,operationId=secrets.token_hex(16),csrPem=other_csr))[1])

    def test_48_enroll_role_cancel_ends_approved_account_code_before_exchange(self):
        enroll=self.enroll_role_service("cancelaccountenroll")
        _,issued,_,receipt=self.connected();fingerprint=receipt["certificateSha256"]
        def approved_account():
            value=dict(authorizationVersion=1,operationId=secrets.token_hex(16),name="Test car",
                certificatePem=issued["certificateReceipt"]["certificatePem"],codeChallenge=challenge(self.verifier),
                requestedScopes=self.scopes)
            value["revokeCommitment"]=revoke_commitment(derive_revoke_capability(self.verifier,self.key_id,value["operationId"]))
            status,pending=self.service.account_authorize(value,fingerprint);self.assertEqual(status,201,pending)
            self.approve_once(pending)
            return value,self.service.account_authorize(value,fingerprint)[1]["grantId"]
        value,grant=approved_account()
        type(self).now+=2
        self.assertEqual(self.cancel(value["operationId"],service=enroll)[1]["state"],"EXPIRED")
        exchange=dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=grant,codeVerifier=self.verifier)
        self.assert_expired(lambda:self.service.account_authorize(value,fingerprint),
            lambda:self.service.session("SESSION_EXCHANGE",exchange,fingerprint))
        # Cancel ends only the code. A session already exchanged stays with
        # SESSION_REVOKE; the enroll role cannot see or touch the grant.
        type(self).now+=1
        value,grant=approved_account()
        fresh=self.service.session("SESSION_EXCHANGE",dict(exchange,operationId=secrets.token_hex(16),grantId=grant),
            fingerprint)[1]["credentialReceipt"]
        self.assertEqual(self.cancel(value["operationId"],service=enroll)[1]["state"],"EXPIRED")
        self.assertEqual(self.service.authenticate(self.request(fresh))["deviceId"],fresh["deviceId"])
