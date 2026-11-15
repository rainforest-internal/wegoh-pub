"""Same-key restart and public certificate receipt recovery, without personal data."""
import hmac
import secrets
from datetime import datetime
from cryptography.hazmat.primitives import hashes
from enrollment_crypto import IssuanceUncertain
from cryptography import x509
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from enrollment_crypto import EnrollmentError, challenge, digest, public_bytes, validate_csr, verify_proof
from native_access_codec import CodecError, canonical_request, decode_json, proof_transcript
from native_authorization import (NativeAuthorizationError, fail, error_response, protect, restore,
    read_body, FIELDS, CODE_ALPHABET, TTL)

class NativeAccessRecovery:
    def begin(self,raw):
        try: value=decode_json(raw) if isinstance(raw,bytes) else raw
        except CodecError:fail(400,"INVALID_REQUEST")
        if isinstance(value,dict) and "previousConnectionId" in value:
            return self.restart(raw)
        return super().begin(raw)

    def _reconcile_unknown_public(self,key,*,exclude=None):
        """One bounded GET-only old outcome; no grant/owner/credential mutation.

        Invoked only after a signed recovery proof or current phone-approved
        CLAIM proof. INSTALL may commit its public first generation. RENEW and
        REAUTHORIZE preserve a public staged receipt only; personal rebind or a
        fresh approved exchange remains the sole generation authority there.
        ACCOUNT never initiates certificate issuance and is not a CA source.
        """
        with self.db() as conn:
            self.lock(conn,key)
            row=conn.execute("SELECT "+FIELDS+" FROM native_v2_connections WHERE installation_key_id=%s "
                "AND kind IN ('INSTALL','RENEW') AND state IN ('ISSUING','UNCERTAIN') "
                "AND (%s::text IS NULL OR connection_id<>%s) ORDER BY created_at,connection_id LIMIT 1",
                (key,exclude,exclude)).fetchone()
            if not row:return True
            original=self._request(row)
            excluded={c["certificate_sha256"] for c in conn.execute("SELECT certificate_sha256 "
                "FROM native_v2_certificate_recovery WHERE installation_key_id=%s",(key,)).fetchall()}
        try:
            issued=self.issuer.reconcile(original["csrPem"],excluded)
            if issued is None:return False  # Unknown/absent is NEVER no-issue permission.
            cert=x509.load_pem_x509_certificate(issued["certificatePem"].encode("ascii"))
            fingerprint=cert.fingerprint(hashes.SHA256()).hex()
            if (digest(public_bytes(cert.public_key()))!=key or fingerprint!=issued["certificateSha256"]
                or fingerprint in excluded):return False
            generation=original.get("expectedGeneration",0)+1
            receipt=dict(certificatePem=issued["certificatePem"],certificateSha256=fingerprint,
                installationKeyId=key,generation=generation,generationOperationId=row["operation_id"],
                expiresAt=int(datetime.fromisoformat(issued["expiresAt"].replace("Z","+00:00")).timestamp()))
            if receipt["expiresAt"]<=self.now():return False
        except (EnrollmentError,IssuanceUncertain,AttributeError,ValueError,KeyError):return False
        with self.db() as conn:
            self.lock(conn,key);current=self._connection(conn,row["connection_id"])
            installation=conn.execute("SELECT current_generation,revision,revoked_at FROM native_v2_installations WHERE installation_key_id=%s FOR UPDATE",(key,)).fetchone()
            expected_generation=original.get("expectedGeneration",0)
            if installation and installation["current_generation"] not in (expected_generation,expected_generation+1):return False
            if installation and installation["current_generation"]==generation:
                committed=conn.execute("SELECT certificate_sha256 FROM native_v2_certificate_recovery WHERE installation_key_id=%s AND generation=%s",(key,generation)).fetchone()
                if not committed or committed["certificate_sha256"]!=fingerprint:return False
            if current["state"]=="ISSUED":
                settled=restore("certificate",current["connection_id"],current["protected_certificate"])["receipt"]
                if settled["certificateSha256"]!=fingerprint:return False
            elif current["state"] in ('ISSUING','UNCERTAIN'):
                if (current["operation_id"]!=row["operation_id"] or current["original_begin_hash"]!=row["original_begin_hash"]
                    or current["installation_key_id"]!=key):fail(409,"OPERATION_CONFLICT")
                outcome=dict(receipt=receipt,provenance=issued)
                if generation==1 and row["kind"]=="INSTALL" and not original.get("_reauthorization"):
                    if not installation:return False
                    if installation["current_generation"]==0 and installation["revoked_at"] is None:
                        conn.execute("INSERT INTO native_v2_certificates(installation_key_id,generation,generation_operation_id,"
                            "certificate_sha256,code_challenge,proof_nonce,expires_at,protected_receipt) VALUES(%s,1,%s,%s,%s,%s,%s,%s)",
                            (key,row["operation_id"],fingerprint,row["code_challenge"],row["proof_nonce"],receipt["expiresAt"],
                             protect("generation",key+":1",outcome)))
                        changed=conn.execute("UPDATE native_v2_installations SET current_generation=1,revision=revision+1 "
                            "WHERE installation_key_id=%s AND current_generation=0 AND revision=%s AND revoked_at IS NULL "
                            "RETURNING installation_key_id",(key,installation["revision"])).fetchone()
                        if not changed:fail(409,"OPERATION_CONFLICT")
                    elif installation["current_generation"]==1:
                        known=conn.execute("SELECT certificate_sha256 FROM native_v2_certificate_recovery WHERE installation_key_id=%s AND generation=1",(key,)).fetchone()
                        if not known or known["certificate_sha256"]!=fingerprint:return False
                conn.execute("UPDATE native_v2_connections SET state='ISSUED',protected_certificate=%s "
                    "WHERE connection_id=%s AND state IN ('ISSUING','UNCERTAIN')",
                    (protect("certificate",row["connection_id"],outcome),row["connection_id"]))
            else:return False
            return not bool(conn.execute("SELECT 1 FROM native_v2_connections WHERE installation_key_id=%s "
                "AND state IN ('ISSUING','UNCERTAIN') AND (%s::text IS NULL OR connection_id<>%s) LIMIT 1",
                (key,exclude,exclude)).fetchone())

    def _prepare_public_claim(self,connection_id,raw):
        record=self.decode("CONNECTION_CLAIM",raw);value=record.for_transport()
        with self.db() as conn:
            row=self._connection(conn,connection_id);self._verify("CONNECTION_CLAIM",record,row)
            if row["kind"]!="INSTALL" or row["state"]=="ISSUED":return None
            approval=self._approval(conn,row)
            if not self._member(approval) or approval["exchange_expires_at"]<=self.now():return None
            if row["expires_at"]<=self.now():fail(410,"AUTHORIZATION_EXPIRED")
            key=row["installation_key_id"]
        ready=self._reconcile_unknown_public(key,exclude=connection_id)
        with self.db() as conn:
            self.lock(conn,key);row=self._connection(conn,connection_id)
            if not ready:
                approval=self._approval(conn,row)
                if not self._member(approval):return self._result(conn,"CONNECTION_CLAIM",value,row)
                return self.response("CONNECTION_CLAIM",value,"PENDING","WAIT",202,
                    connectionId=row["connection_id"],interval=5)
            installation=conn.execute("SELECT current_generation,revoked_at FROM native_v2_installations WHERE installation_key_id=%s",(key,)).fetchone()
            if installation and installation["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
            original=self._request(row)
            if (row["state"]=="PENDING" and installation and installation["revoked_at"] is None
                and installation["current_generation"]>0 and not original.get("_reauthorization")):
                original.update(_reauthorization=True,_knownCsrRecovery=True,expectedGeneration=installation["current_generation"])
                conn.execute("UPDATE native_v2_connections SET protected_request=%s WHERE connection_id=%s",
                    (protect("connection",connection_id,original),connection_id))
        return None

    def claim(self,connection_id,raw):
        prepared=self._prepare_public_claim(connection_id,raw)
        if prepared is not None:return prepared
        with self.db() as conn:row=self._connection(conn,connection_id,lock=False)
        if self._request(row).get("_reauthorization"):return self.claim(connection_id,raw)
        return super().claim(connection_id,raw)

    def recover_connection(self,raw):
        action="CONNECTION_RECOVER";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            initial=self._connection(conn,value["operationId"],by="operation_id",lock=False)
            self.lock(conn,initial["installation_key_id"])
            row=self._connection(conn,initial["connection_id"]);self._verify(action,record,row)
            if not self._recovery_csr_matches(row,value["csrPem"]) or not hmac.compare_digest(value["originalBeginHash"],row["original_begin_hash"]):
                fail(403,"INVALID_PROOF")
            approval=self._approval(conn,row)
            if (row["kind"]=="INSTALL" and row["state"] in ("PENDING","EXPIRED_NOT_ISSUED")
                and row["expires_at"]<=self.now() and not (approval and approval["state"] in ("DENIED","REVOKED"))):
                original=self._request(row)
                ticket=original.get("_restartTicket");expiry=row["restart_expires_at"]
                if ticket is None or expiry<=self.now():
                    ticket=secrets.token_urlsafe(32);expiry=self.now()+300
                    original["_restartTicket"]=ticket
                    conn.execute("UPDATE native_v2_connections SET protected_request=%s,restart_hash=%s,"
                        "restart_expires_at=%s,state='EXPIRED_NOT_ISSUED' WHERE connection_id=%s",
                        (protect("connection",row["connection_id"],original),digest(ticket.encode("ascii")),expiry,row["connection_id"]))
                return self.response(action,value,"EXPIRED_NOT_ISSUED","USER_RESTART_ALLOWED",
                    connectionId=row["connection_id"],proofNonce=row["proof_nonce"],restartTicket=ticket,restartExpiresAt=expiry)
            reconcile=row["state"] in ('ISSUING','UNCERTAIN')
        if reconcile:self._reconcile_unknown_public(row["installation_key_id"])
        with self.db() as conn:return self._result(conn,action,value,self._connection(conn,row["connection_id"]))

    def restart(self,raw):
        action="CONNECTION_RESTART";record=self.decode(action,raw);value=record.for_transport();now=self.now()
        csr=validate_csr(value["csrPem"]);key=digest(public_bytes(csr.public_key()));request_hash=digest(canonical_request(record))
        with self.db() as conn:
            self.lock(conn,key)
            previous=conn.execute("SELECT "+FIELDS+" FROM native_v2_connections WHERE operation_id=%s FOR UPDATE",
                (value["operationId"],)).fetchone()
            if previous:
                if previous["installation_key_id"]!=key or previous["original_begin_hash"]!=request_hash:
                    fail(409,"OPERATION_CONFLICT")
                if previous["expires_at"]<=now:fail(410,"AUTHORIZATION_EXPIRED")
                return self.response(action,value,"PENDING","WAIT",**self._pending(previous))
            old=self._connection(conn,value["previousConnectionId"])
            if old["installation_key_id"]!=key or old["kind"]!="INSTALL":fail(403,"INVALID_PROOF")
            try:
                if (not hmac.compare_digest(challenge(value["oldCodeVerifier"]),old["code_challenge"])
                    or value["proofNonce"]!=old["proof_nonce"]):fail(403,"INVALID_PROOF")
                verify_proof(validate_csr(self._request(old)["csrPem"]),proof_transcript(action,record,
                    installation_key_id=key,code_challenge=value["codeChallenge"]),value["proof"])
            except EnrollmentError:fail(403,"INVALID_PROOF")
            if (old["state"]!="EXPIRED_NOT_ISSUED" or old["expires_at"]>now or old["restart_consumed_at"] is not None
                or old["restart_expires_at"] is None or old["restart_expires_at"]<=now or old["restart_hash"] is None
                or not hmac.compare_digest(old["restart_hash"],digest(value["restartTicket"].encode("ascii")))):
                fail(409,"RECOVERY_NOT_ALLOWED")
            installation=conn.execute("SELECT current_generation,revoked_at FROM native_v2_installations WHERE installation_key_id=%s",(key,)).fetchone()
            if installation and (installation["revoked_at"] is not None or installation["current_generation"]!=0):
                fail(409,"RECOVERY_NOT_ALLOWED")
            if conn.execute("SELECT 1 FROM native_v2_connections WHERE installation_key_id=%s AND connection_id<>%s "
                "AND (state IN ('ISSUING','UNCERTAIN','ISSUED') OR (state='PENDING' AND expires_at>%s AND NOT EXISTS "
                "(SELECT 1 FROM native_v2_issuer_approvals a WHERE a.connection_id=native_v2_connections.connection_id AND a.state='DENIED'))) LIMIT 1",
                (key,old["connection_id"],now)).fetchone():fail(409,"RECOVERY_NOT_ALLOWED")
            if conn.execute("SELECT count(*) AS n FROM native_v2_connections").fetchone()["n"]>=1000:fail(429,"ENROLLMENT_STORAGE_LIMIT",3600)
            connection=secrets.token_hex(16);code="".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            conn.execute("INSERT INTO native_v2_connections(connection_id,operation_id,installation_key_id,kind,user_code,"
                "original_begin_hash,code_challenge,proof_nonce,state,expires_at,created_at,protected_request,previous_connection_id) "
                "VALUES(%s,%s,%s,'INSTALL',%s,%s,%s,%s,'PENDING',%s,%s,%s,%s)",
                (connection,value["operationId"],key,code,request_hash,value["codeChallenge"],secrets.token_urlsafe(32),
                 now+TTL,now,protect("connection",connection,value),old["connection_id"]))
            conn.execute("UPDATE native_v2_connections SET restart_consumed_at=%s WHERE connection_id=%s",(now,old["connection_id"]))
            return self.response(action,value,"PENDING","WAIT",201,**self._pending(self._connection(conn,connection)))

    def certificate_recover(self,raw):
        action="CERTIFICATE_RECOVER";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            row=conn.execute("SELECT * FROM native_v2_certificate_recovery WHERE installation_key_id=%s AND generation=%s "
                "AND generation_operation_id=%s",(value["installationKeyId"],value["expectedGeneration"],value["generationOperationId"])).fetchone()
            if not row:fail(404,"OPERATION_NOT_FOUND")
            if row["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
            if row["generation"]!=row["current_generation"]:fail(409,"STALE_EPOCH")
            if row["expires_at"]<=self.now():fail(410,"RECEIPT_EXPIRED")
            payload=restore("generation",row["installation_key_id"]+":"+str(row["generation"]),row["protected_receipt"])
            try:
                proof_challenge=challenge(value["codeVerifier"])
                original=(hmac.compare_digest(proof_challenge,row["code_challenge"])
                    and value["proofNonce"]==row["proof_nonce"])
                if not original:
                    # A fresh, key-proved phone connection may reuse an already
                    # current public leaf. Its PKCE is a public-receipt recovery
                    # alias only: do not rewrite the generation's original proof
                    # or consult/restore any personal grant, owner or token.
                    aliases=conn.execute("SELECT connection_id,protected_certificate FROM native_v2_connections "
                        "WHERE installation_key_id=%s AND state='ISSUED' AND code_challenge=%s AND proof_nonce=%s "
                        "AND protected_certificate IS NOT NULL",(row["installation_key_id"],proof_challenge,value["proofNonce"])).fetchall()
                    if not any(restore("certificate",alias["connection_id"],alias["protected_certificate"]).get("receipt")
                        ==payload["receipt"] for alias in aliases):fail(403,"INVALID_PROOF")
                certificate=x509.load_pem_x509_certificate(payload["receipt"]["certificatePem"].encode("ascii"))
                verify_proof(certificate,proof_transcript(action,record,installation_key_id=row["installation_key_id"],
                    code_challenge=proof_challenge),value["proof"])
            except EnrollmentError:fail(403,"INVALID_PROOF")
            # This public-only response never contains a grant/account/token/capability.
            return self.response(action,value,"ISSUED","CERTIFICATE_RECEIPT",certificateReceipt=payload["receipt"])

    def issuer_router(self):
        router=super().issuer_router()
        @router.post("/v1/installations/certificate-recover")
        async def recover(request:Request):
            try:
                result=await run_in_threadpool(self.certificate_recover,await read_body(request))
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error:return error_response(error)
        return router
