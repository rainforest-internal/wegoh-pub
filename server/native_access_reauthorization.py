"""Expired-installation reauthorization: same key, fresh phone consent, no old grant revival."""
import hmac,secrets
from datetime import datetime
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from enrollment_crypto import (EnrollmentError,IssuanceUncertain,challenge,digest,public_bytes,validate_csr,verify_proof)
from native_access_codec import canonical_request,decode_json,proof_transcript,CodecError
from native_authorization import fail,protect,restore,FIELDS,TTL,INTERVAL,CODE_ALPHABET

class NativeAccessReauthorization:
    def begin(self,raw):
        try:value=decode_json(raw) if isinstance(raw,bytes) else raw
        except CodecError:fail(400,"INVALID_REQUEST")
        if isinstance(value,dict) and any(k in value for k in ("installationKeyId","expectedGeneration")):
            return self.reauthorize_begin(raw)
        return super().begin(raw)

    def reauthorize_begin(self,raw):
        action="CONNECTION_REAUTHORIZE";record=self.decode(action,raw);value=record.for_transport()
        csr=validate_csr(value["csrPem"]);key=digest(public_bytes(csr.public_key()))
        if key!=value["installationKeyId"]:fail(403,"INVALID_PROOF")
        try:verify_proof(csr,proof_transcript(action,record,installation_key_id=key,
            code_challenge=value["codeChallenge"]),value["proof"])
        except EnrollmentError:fail(403,"INVALID_PROOF")
        now=self.now();request_hash=digest(canonical_request(record))
        self.auth.rate("native-v2-reauthorize-total",limit=20)
        with self.db() as conn:
            current=conn.execute("SELECT * FROM native_v2_certificate_recovery WHERE installation_key_id=%s "
                "AND generation=%s",(key,value["expectedGeneration"])).fetchone()
            if not current:fail(404,"OPERATION_NOT_FOUND")
            if current["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
            if current["current_generation"]!=value["expectedGeneration"]:fail(409,"STALE_EPOCH")
            if current["expires_at"]>now:fail(409,"RECOVERY_NOT_ALLOWED")

            outcome=restore("generation",key+":"+str(current["generation"]),current["protected_receipt"])
        # Read-only exact CA state separates normal expiry from explicit revocation.
        # A generic network/401/403 error is NOT evidence that a certificate revoked.
        try:self.issuer.require_active_certificate(outcome["provenance"],key,current["certificate_sha256"])
        except EnrollmentError as error:
            fail(403,"INSTALLATION_REVOKED") if str(error)=="INSTALLATION_REVOKED" else fail(503,"SERVICE_UNAVAILABLE")
        except IssuanceUncertain:fail(503,"SERVICE_UNAVAILABLE")
        with self.db() as conn:
            self.lock(conn,key)
            installation=conn.execute("SELECT current_generation,revision,revoked_at FROM native_v2_installations "
                "WHERE installation_key_id=%s",(key,)).fetchone()
            if not installation or installation["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
            if installation["current_generation"]!=value["expectedGeneration"]:fail(409,"STALE_EPOCH")
            previous=conn.execute("SELECT "+FIELDS+" FROM native_v2_connections WHERE operation_id=%s FOR UPDATE",
                (value["operationId"],)).fetchone()
            if previous:
                if previous["original_begin_hash"]!=request_hash or not self._request(previous).get("_reauthorization"):
                    fail(409,"OPERATION_CONFLICT")
                if previous["expires_at"]<=now:fail(410,"AUTHORIZATION_EXPIRED")
                return self.response(action,value,"PENDING","WAIT",**self._pending(previous))
            if conn.execute("SELECT count(*) AS n FROM native_v2_connections").fetchone()["n"]>=1000:
                fail(429,"ENROLLMENT_STORAGE_LIMIT",3600)
            # Same as a fresh begin: this key-proved request replaces the
            # vehicle's own earlier unclaimed code instead of waiting for it.
            conn.execute("UPDATE native_v2_connections SET expires_at=GREATEST(created_at+1,%s) "
                "WHERE installation_key_id=%s AND state='PENDING' AND expires_at>%s AND NOT EXISTS "
                "(SELECT 1 FROM native_v2_issuer_approvals a WHERE a.connection_id=native_v2_connections.connection_id "
                "AND a.state IN ('DENIED','REVOKED'))",(now,key,now))
            connection=secrets.token_hex(16);code="".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            stored=dict(value,_reauthorization=True)
            stored.pop("proof")
            conn.execute("INSERT INTO native_v2_connections(connection_id,operation_id,installation_key_id,kind,user_code,"
                "original_begin_hash,code_challenge,proof_nonce,state,expires_at,created_at,protected_request) "
                "VALUES(%s,%s,%s,'INSTALL',%s,%s,%s,%s,'PENDING',%s,%s,%s)",
                (connection,value["operationId"],key,code,request_hash,value["codeChallenge"],secrets.token_urlsafe(32),
                 now+TTL,now,protect("connection",connection,stored)))
            return self.response(action,value,"PENDING","WAIT",201,**self._pending(self._connection(conn,connection)))

    def _reauthorization_consent(self,conn,row,request,consent):
        installation=conn.execute("SELECT * FROM native_v2_installations WHERE installation_key_id=%s FOR UPDATE",
            (row["installation_key_id"],)).fetchone()
        if not installation or installation["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
        if request.get("_reauthorization") and installation["current_generation"]!=request["expectedGeneration"]:
            fail(409,"STALE_EPOCH")
        consent["_installationSnapshot"]=dict(revision=installation["revision"],slotRevision=installation["slot_revision"],
            generation=installation["current_generation"],initial=(row["kind"]=="INSTALL" and not request.get("_reauthorization")
                and installation["current_generation"]==0))

    def _validate_exchange_snapshot(self,conn,grant,certificate):
        consent=restore("consent",grant["grant_id"],grant["protected_consent"])
        snapshot=consent.get("_installationSnapshot")
        if not isinstance(snapshot,dict):fail(409,"STALE_EPOCH")
        installation=conn.execute("SELECT * FROM native_v2_installations WHERE installation_key_id=%s",
            (grant["installation_key_id"],)).fetchone()
        initial=snapshot.get("initial",False)
        if (installation["current_generation"]!=snapshot["generation"]+(1 if initial else 0)
            or installation["revision"]!=snapshot["revision"]+(1 if initial else 0)
            or installation["slot_revision"]!=snapshot["slotRevision"]):
            fail(409,"STALE_EPOCH")

    def claim(self,connection_id,raw):
        with self.db() as conn:initial=self._connection(conn,connection_id,lock=False)
        if not self._request(initial).get("_reauthorization"):return super().claim(connection_id,raw)
        prepared=self._prepare_public_claim(connection_id,raw)
        if prepared is not None:return prepared
        action="CONNECTION_CLAIM";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            self.lock(conn,initial["installation_key_id"]);row=self._connection(conn,connection_id)
            self._verify(action,record,row)
            if row["state"]=="ISSUED":return self._result(conn,action,value,row)
            approval=self._approval(conn,row)
            if not self._member(approval) or approval["exchange_expires_at"]<=self.now():
                return self._result(conn,action,value,row)
            if row["expires_at"]<=self.now():fail(410,"AUTHORIZATION_EXPIRED")
            if row["next_poll"]>self.now():fail(429,"RATE_LIMITED",max(INTERVAL,row["next_poll"]-self.now()))
            original=self._request(row)
            current=conn.execute("SELECT * FROM native_v2_certificate_recovery WHERE installation_key_id=%s AND generation=%s",
                (row["installation_key_id"],original["expectedGeneration"])).fetchone()
            if not current or current["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
            if current["current_generation"]!=original["expectedGeneration"]:fail(409,"STALE_EPOCH")
            prior=restore("generation",row["installation_key_id"]+":"+str(current["generation"]),current["protected_receipt"])
            # Reuse an already verified valid public leaf after new phone consent.
            # This path emits no old grant/token and performs no new CA POST.
            if current["expires_at"]>self.now() and not prior.get("legacy"):
                from native_access_issuer_status import require_active_status
                require_active_status(self.auth,self.issuer,prior["provenance"],row["installation_key_id"],
                    current["certificate_sha256"],value["operationId"])
                conn.execute("UPDATE native_v2_connections SET state='ISSUED',protected_certificate=%s WHERE connection_id=%s",
                    (protect("certificate",connection_id,prior),connection_id))
                return self._result(conn,action,value,self._connection(conn,connection_id))
            excluded={c["certificate_sha256"] for c in conn.execute("SELECT certificate_sha256 FROM native_v2_certificate_recovery "
                "WHERE installation_key_id=%s",(row["installation_key_id"],)).fetchall()}
            reconcile=row["state"] in ("ISSUING","UNCERTAIN")
            if not reconcile:self.require_new_issuance(conn,original["csrPem"])
            conn.execute("UPDATE native_v2_connections SET next_poll=%s,state='ISSUING' WHERE connection_id=%s",
                (self.now()+INTERVAL,connection_id))
        try:
            self.issuer.require_active_certificate(prior["provenance"],row["installation_key_id"],current["certificate_sha256"])
            issued=self.issuer.reconcile(original["csrPem"],excluded)
            if issued is None:
                if reconcile:raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
                issued=self.issuer.issue(original["csrPem"])
        except EnrollmentError as error:
            fail(403,"INSTALLATION_REVOKED") if str(error)=="INSTALLATION_REVOKED" else fail(503,"SERVICE_UNAVAILABLE")
        except IssuanceUncertain:
            with self.db() as conn:
                conn.execute("UPDATE native_v2_connections SET state='UNCERTAIN' WHERE connection_id=%s AND state='ISSUING'",(connection_id,))
                return self._result(conn,action,value,self._connection(conn,connection_id))
        receipt=dict(certificatePem=issued["certificatePem"],certificateSha256=issued["certificateSha256"],
            installationKeyId=row["installation_key_id"],generation=original["expectedGeneration"]+1,
            generationOperationId=row["operation_id"],expiresAt=int(datetime.fromisoformat(issued["expiresAt"].replace("Z","+00:00")).timestamp()))
        with self.db() as conn:
            self.lock(conn,row["installation_key_id"]);current_row=self._connection(conn,connection_id)
            if current_row["state"] not in ("ISSUING","UNCERTAIN"):fail(409,"OPERATION_CONFLICT")
            conn.execute("UPDATE native_v2_connections SET state='ISSUED',protected_certificate=%s WHERE connection_id=%s",
                (protect("certificate",connection_id,dict(receipt=receipt,provenance=issued)),connection_id))
        with self.db() as conn:
            return self._result(conn,action,value,self._connection(conn,connection_id))

    def session(self,action,raw,fingerprint):
        if action!="SESSION_EXCHANGE":return super().session(action,raw,fingerprint)
        record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            known=conn.execute("SELECT 1 FROM native_v2_certificates c JOIN native_v2_installations i "
                "USING(installation_key_id) WHERE c.certificate_sha256=%s AND c.generation=i.current_generation "
                "AND c.expires_at>%s AND i.revoked_at IS NULL",(fingerprint,self.now())).fetchone()
        if known:return super().session(action,raw,fingerprint)
        with self.db() as conn:
            initial=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s",(value["grantId"],)).fetchone()
            if not initial:fail(401,"INVALID_CREDENTIAL")
            key=initial["installation_key_id"];self.lock(conn,key)
            grant=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE",(value["grantId"],)).fetchone()
            self._live(grant);row=self._connection(conn,grant["connection_id"]);original=self._request(row)
            if not original.get("_reauthorization") or row["state"]!="ISSUED":fail(403,"CERTIFICATE_BINDING_MISMATCH")
            approval=self._approval(conn,row)
            if grant["state"]!="APPROVED" or not self._member(approval) or approval["exchange_expires_at"]<=self.now():
                fail(410,"AUTHORIZATION_EXPIRED")
            if not hmac.compare_digest(challenge(value["codeVerifier"]),row["code_challenge"]):fail(403,"INVALID_PROOF")
            outcome=restore("certificate",row["connection_id"],row["protected_certificate"]);receipt=outcome["receipt"]
            if receipt["certificateSha256"]!=fingerprint or receipt["installationKeyId"]!=key or receipt["expiresAt"]<=self.now():
                fail(403,"CERTIFICATE_BINDING_MISMATCH")
            consent=restore("consent",grant["grant_id"],grant["protected_consent"]);snapshot=consent.get("_installationSnapshot")
            if not isinstance(snapshot,dict):fail(409,"STALE_EPOCH")
            # Final external CA state is checked just before the main CAS.
            # The remote CA and PostgreSQL are not one distributed transaction:
            # a later incident must also set the authoritative installation ban.
            prior=conn.execute("SELECT * FROM native_v2_certificate_recovery WHERE installation_key_id=%s AND generation=%s",
                (key,snapshot["generation"])).fetchone()
            if not prior or prior["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
            prior_outcome=restore("generation",key+":"+str(prior["generation"]),prior["protected_receipt"])
            from native_access_issuer_status import require_active_status
            require_active_status(self.auth,self.issuer,prior_outcome["provenance"],key,
                prior["certificate_sha256"],value["operationId"])
            updated=conn.execute("UPDATE native_v2_installations SET current_generation=%s,revision=revision+1 "
                "WHERE installation_key_id=%s AND current_generation=%s AND revision=%s AND slot_revision=%s "
                "AND revoked_at IS NULL RETURNING installation_key_id",(receipt["generation"],key,snapshot["generation"],
                 snapshot["revision"],snapshot["slotRevision"])).fetchone()
            if not updated or receipt["generation"]!=snapshot["generation"]+1:fail(409,"STALE_EPOCH")
            conn.execute("INSERT INTO native_v2_certificates(installation_key_id,generation,generation_operation_id,"
                "certificate_sha256,code_challenge,proof_nonce,expires_at,protected_receipt) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (key,receipt["generation"],row["operation_id"],fingerprint,row["code_challenge"],row["proof_nonce"],
                 receipt["expiresAt"],protect("generation",key+":"+str(receipt["generation"]),outcome)))
            certificate=self._certificate(conn,fingerprint)
            return self._issue(conn,action,record,grant,certificate,first=True)

