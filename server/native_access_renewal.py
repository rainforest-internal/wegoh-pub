"""Technical same-key certificate maintenance; personal authority stays main-owned."""
import hmac,json,secrets,http.client
from datetime import datetime
from urllib.parse import urlsplit
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from enrollment_crypto import (EnrollmentError,IssuanceUncertain,challenge,digest,
    public_bytes,validate_csr,verify_proof,validate_issued)
from native_access_codec import canonical_request,proof_transcript,decode_response,decode_error
from native_authorization import (NativeAuthorizationError,fail,protect,restore,hash_secret,read_body,
    error_response,http_error_response,FIELDS,CODE_ALPHABET,TTL,INTERVAL,WIRE)

class NativeAccessRenewal:
    def _current_ca(self,conn,key,generation,operation_id):
        row=conn.execute("SELECT * FROM native_v2_certificate_recovery WHERE installation_key_id=%s AND generation=%s",
            (key,generation)).fetchone()
        if not row or row["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
        if row["current_generation"]!=generation:fail(409,"STALE_EPOCH")
        outcome=restore("generation",key+":"+str(generation),row["protected_receipt"])
        from native_access_issuer_status import require_active_status
        require_active_status(self.auth,self.issuer,outcome["provenance"],key,row["certificate_sha256"],operation_id)
        return row

    def _renew_grant(self,conn,value,key):
        grant=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE",
            (value["grantId"],)).fetchone()
        if not grant or grant["installation_key_id"]!=key:fail(401,"INVALID_CREDENTIAL")
        self._live(grant)
        installation=conn.execute("SELECT * FROM native_v2_installations WHERE installation_key_id=%s FOR UPDATE",(key,)).fetchone()
        if not installation or installation["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
        if (grant["state"]!="TOKEN_ISSUED" or grant["device_id"]!=value["deviceId"]
            or installation["active_grant_id"]!=grant["grant_id"]
            or not grant["recovery_hash"] or not hmac.compare_digest(grant["recovery_hash"],
                hash_secret("recovery",value["recoveryCapability"]))):fail(401,"INVALID_CREDENTIAL")
        return grant,installation

    def _renew_lease(self,conn,row,*,lock=False):
        lease=conn.execute("SELECT * FROM native_v2_renewals WHERE connection_id=%s"+
            (" FOR UPDATE" if lock else ""),(row["connection_id"],)).fetchone()
        if not lease:fail(404,"OPERATION_NOT_FOUND")
        return lease

    def _assert_renew_lease(self,conn,row,lease,grant,installation):
        if lease["expires_at"]<=self.now():fail(410,"AUTHORIZATION_EXPIRED")
        if (grant["grant_id"]!=lease["grant_id"] or grant["device_id"]!=lease["device_id"]
            or grant["credential_epoch"]!=lease["credential_epoch"]
            or grant["consent_version"]!=lease["consent_version"]
            or digest(bytes(grant["protected_consent"]))!=lease["consent_hash"]
            or grant["expires_at"]!=lease["grant_expires_at"]
            or installation["revision"]!=lease["installation_revision"]
            or installation["slot_revision"]!=lease["slot_revision"]
            or installation["current_generation"]!=lease["expected_generation"]):
            fail(409,"STALE_EPOCH")

    def renew_begin(self,raw):
        action="CERTIFICATE_RENEW_BEGIN";record=self.decode(action,raw);value=record.for_transport()
        csr=validate_csr(value["csrPem"]);key=digest(public_bytes(csr.public_key()))
        if key!=value["installationKeyId"]:fail(403,"INVALID_PROOF")
        try:verify_proof(csr,proof_transcript(action,record,installation_key_id=key,
            code_challenge=value["codeChallenge"]),value["proof"])
        except EnrollmentError:fail(403,"INVALID_PROOF")
        now=self.now();request_hash=digest(canonical_request(record))
        self.auth.rate("native-v2-renew-total",limit=30)
        with self.db() as conn:
            self.lock(conn,key);grant,installation=self._renew_grant(conn,value,key)
            old=conn.execute("SELECT "+FIELDS+" FROM native_v2_connections WHERE operation_id=%s FOR UPDATE",
                (value["operationId"],)).fetchone()
            if old:
                if old["kind"]!="RENEW" or old["original_begin_hash"]!=request_hash:fail(409,"OPERATION_CONFLICT")
                lease=self._renew_lease(conn,old)
                self._assert_renew_lease(conn,old,lease,grant,installation)
                return self.response(action,value,"APPROVED","CONTINUE_CLAIM",connectionId=old["connection_id"],
                    proofNonce=old["proof_nonce"],expiresAt=old["expires_at"],interval=INTERVAL)
            if installation["current_generation"]!=value["expectedGeneration"]:fail(409,"STALE_EPOCH")
            self._current_ca(conn,key,installation["current_generation"],value["operationId"])
            if conn.execute("SELECT 1 FROM native_v2_renewals WHERE installation_key_id=%s AND expires_at>%s "
                "AND installation_revision=%s AND credential_epoch=%s AND consent_version=%s",
                (key,now,installation["revision"],grant["credential_epoch"],grant["consent_version"])).fetchone():
                fail(409,"OPERATION_CONFLICT")
            if conn.execute("SELECT count(*) AS n FROM native_v2_connections").fetchone()["n"]>=1000:
                fail(429,"ENROLLMENT_STORAGE_LIMIT",3600)
            # A prior uncertain POST is durable evidence: this new approved lease
            # must reconcile it and cannot become a second blind issuance.
            uncertain=conn.execute("SELECT 1 FROM native_v2_connections WHERE installation_key_id=%s "
                "AND kind='RENEW' AND state IN ('ISSUING','UNCERTAIN') LIMIT 1",(key,)).fetchone()
            connection=secrets.token_hex(16);nonce=secrets.token_urlsafe(32)
            code="".join(secrets.choice(CODE_ALPHABET) for _ in range(8));expiry=min(now+TTL,grant["expires_at"])
            # Recovery capability/proof never persist in issuer-readable bootstrap.
            public={k:value[k] for k in ("authorizationVersion","operationId","csrPem","installationKeyId",
                "expectedGeneration","codeChallenge","proofNonce")}
            public["_revocationGrantHash"]=hash_secret("grant-link",grant["grant_id"])
            conn.execute("INSERT INTO native_v2_connections(connection_id,operation_id,installation_key_id,kind,user_code,"
                "original_begin_hash,code_challenge,proof_nonce,state,expires_at,created_at,protected_request) "
                "VALUES(%s,%s,%s,'RENEW',%s,%s,%s,%s,%s,%s,%s,%s)",(connection,value["operationId"],key,code,request_hash,
                 value["codeChallenge"],nonce,"UNCERTAIN" if uncertain else "PENDING",expiry,now,protect("connection",connection,public)))
            conn.execute("INSERT INTO native_v2_renewals(connection_id,installation_key_id,grant_id,device_id,"
                "installation_revision,expected_generation,slot_revision,credential_epoch,consent_version,consent_hash,"
                "protected_owner,grant_expires_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (connection,key,grant["grant_id"],grant["device_id"],installation["revision"],installation["current_generation"],
                 installation["slot_revision"],grant["credential_epoch"],grant["consent_version"],
                 digest(bytes(grant["protected_consent"])),protect("approval",connection,dict(accountId=grant["account_id"])),grant["expires_at"],expiry))
            return self.response(action,value,"APPROVED","CONTINUE_CLAIM",201,connectionId=connection,
                proofNonce=nonce,expiresAt=expiry,interval=INTERVAL)

    def renew_relay_boundary(self,request):
        # Routing conditions are necessary, never sufficient authentication:
        # renew_begin validates full key proof + live grant recovery capability.
        if (not self.enabled or not self.auth.enabled or self.issuer is not None
            or request.url.hostname!=urlsplit(self.origin).hostname or request.url.port not in (None,443)
            or not request.client or request.client.host not in ("127.0.0.1","::1")
            or request.method!="POST" or request.url.path!="/v1/installations/certificate-renew"
            or request.url.query or any(h in request.headers for h in ("origin","cookie","authorization"))):
            fail(404,"ROUTE_NOT_FOUND")

    def relay_renew_begin(self,raw):
        # Fixed loopback target; caller supplies no URL/headers. TLS1.3 remains on
        # browser/device->edge; loopback has bounded signed+cap-authenticated DTO.
        record=self.decode("CERTIFICATE_RENEW_BEGIN",raw);value=record.for_transport()
        connection=http.client.HTTPConnection("127.0.0.1",18082,timeout=10)
        try:
            connection.request("POST","/v1/installations/certificate-renew",body=json.dumps(value).encode("utf-8"),
                headers={"Host":urlsplit(WIRE["origins"]["enroll"]).hostname,"Content-Type":"application/json"})
            response=connection.getresponse();body=response.read(65537)
            if len(body)>65536:fail(503,"SERVICE_UNAVAILABLE")
            if response.status>=400:
                error=decode_error(response.status,body).for_transport()
                raise NativeAuthorizationError(response.status,error["error"],error.get("retryAfter"))
            result=decode_response("CERTIFICATE_RENEW_BEGIN",response.status,body,
                expected_operation_id=value["operationId"]).for_transport()
            return response.status,result
        except (OSError,ValueError):fail(503,"SERVICE_UNAVAILABLE")
        finally:connection.close()

    def claim(self,connection_id,raw):
        with self.db() as conn:initial=self._connection(conn,connection_id,lock=False)
        if initial["kind"]!="RENEW":return super().claim(connection_id,raw)
        action="CERTIFICATE_RENEW_CLAIM";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            self.lock(conn,initial["installation_key_id"]);row=self._connection(conn,connection_id)
            self._verify(action,record,row);approval=self._approval(conn,row)
            if not self._member(approval):fail(403,"CONSENT_REVOKED")
            if row["expires_at"]<=self.now():fail(410,"AUTHORIZATION_EXPIRED")
            if row["state"]=="ISSUED":return self._renew_result(conn,action,value,row)
            original=self._request(row)
            self._current_ca(conn,row["installation_key_id"],original["expectedGeneration"],value["operationId"])
            if row["next_poll"]>self.now():fail(429,"RATE_LIMITED",max(INTERVAL,row["next_poll"]-self.now()))
            conn.execute("UPDATE native_v2_connections SET next_poll=%s WHERE connection_id=%s",
                (self.now()+INTERVAL,connection_id))
            reconcile=row["state"] in ("ISSUING","UNCERTAIN")
            original=self._request(row)
            excluded={c["certificate_sha256"] for c in conn.execute("SELECT certificate_sha256 "
                "FROM native_v2_certificate_recovery WHERE installation_key_id=%s",(row["installation_key_id"],)).fetchall()}
            if not reconcile:
                self.require_new_issuance(conn,original["csrPem"])
                conn.execute("UPDATE native_v2_connections SET state='ISSUING' WHERE connection_id=%s",(connection_id,))
        # A durable ISSUING transaction always precedes upstream side effects.
        try:
            if reconcile:
                issued=self.issuer.reconcile(original["csrPem"],excluded)
                if issued is None:raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
            else:
                # Reuse a prior valid staged public leaf after withdrawal/switch.
                staged=self.issuer.reconcile(original["csrPem"],excluded)
                issued=staged if staged is not None else self.issuer.issue(original["csrPem"])
        except (IssuanceUncertain,EnrollmentError):
            with self.db() as conn:
                conn.execute("UPDATE native_v2_connections SET state='UNCERTAIN' WHERE connection_id=%s AND state='ISSUING'",
                    (connection_id,))
                return self._renew_result(conn,action,value,self._connection(conn,connection_id))
        with self.db() as conn:
            self.lock(conn,row["installation_key_id"]);current=self._connection(conn,connection_id)
            if current["state"] not in ("ISSUING","UNCERTAIN"):fail(409,"OPERATION_CONFLICT")
            generation=original["expectedGeneration"]+1
            receipt=dict(certificatePem=issued["certificatePem"],certificateSha256=issued["certificateSha256"],
                installationKeyId=row["installation_key_id"],generation=generation,generationOperationId=row["operation_id"],
                expiresAt=int(datetime.fromisoformat(issued["expiresAt"].replace("Z","+00:00")).timestamp()))
            conn.execute("UPDATE native_v2_connections SET state='ISSUED',protected_certificate=%s WHERE connection_id=%s",
                (protect("certificate",connection_id,dict(receipt=receipt,provenance=issued)),connection_id))
            return self._renew_result(conn,action,value,self._connection(conn,connection_id))

    def _renew_result(self,conn,action,value,row):
        if row["state"]=="ISSUED":
            receipt=restore("certificate",row["connection_id"],row["protected_certificate"])["receipt"]
            return self.response(action,value,"ISSUED","CERTIFICATE_RECEIPT",connectionId=row["connection_id"],certificateReceipt=receipt)
        if row["state"] in ("ISSUING","UNCERTAIN"):
            status=202 if action=="CERTIFICATE_RENEW_CLAIM" else 200
            fields=dict(connectionId=row["connection_id"],interval=INTERVAL)
            if action=="CONNECTION_RECOVER":fields["proofNonce"]=row["proof_nonce"]
            return self.response(action,value,row["state"],"RECONCILE",status,**fields)
        return self.response(action,value,"APPROVED","CONTINUE_CLAIM",connectionId=row["connection_id"],
            proofNonce=row["proof_nonce"],expiresAt=row["expires_at"],interval=INTERVAL)

    def _result(self,conn,action,value,row):
        if row["kind"]=="RENEW":return self._renew_result(conn,action,value,row)
        return super()._result(conn,action,value,row)

    def rebind(self,raw,fingerprint):
        action="CREDENTIAL_REBIND";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            initial=self._connection(conn,value["connectionId"],lock=False)
            if initial["kind"]!="RENEW":fail(403,"CERTIFICATE_BINDING_MISMATCH")
            key=initial["installation_key_id"];self.lock(conn,key)
            row=self._connection(conn,value["connectionId"]);grant,installation=self._renew_grant(conn,value,key)
            # An exact already-committed operation may return its encrypted receipt.
            existing=conn.execute("SELECT certificate_sha256 FROM native_v2_certificates WHERE installation_key_id=%s "
                "AND generation=%s",(key,installation["current_generation"])).fetchone()
            if existing and existing["certificate_sha256"]==fingerprint:
                certificate=self._certificate(conn,fingerprint);cached=self._cached(conn,action,record,grant,certificate)
                if cached:return 200,cached
            lease=self._renew_lease(conn,row,lock=True);self._assert_renew_lease(conn,row,lease,grant,installation)
            if row["state"]!="ISSUED" or row["protected_certificate"] is None:fail(409,"RECOVERY_NOT_ALLOWED")
            outcome=restore("certificate",row["connection_id"],row["protected_certificate"]);receipt=outcome["receipt"]
            if receipt["certificateSha256"]!=fingerprint or receipt["installationKeyId"]!=key:fail(403,"CERTIFICATE_BINDING_MISMATCH")
            certificate=x509.load_pem_x509_certificate(receipt["certificatePem"].encode("ascii"))
            if (digest(public_bytes(certificate.public_key()))!=key or certificate.fingerprint(hashes.SHA256()).hex()!=fingerprint
                or receipt["expiresAt"]<=self.now() or receipt["generation"]!=installation["current_generation"]+1):
                fail(403,"CERTIFICATE_BINDING_MISMATCH")
            self._current_ca(conn,key,lease["expected_generation"],value["operationId"])
            conn.execute("INSERT INTO native_v2_certificates(installation_key_id,generation,generation_operation_id,"
                "certificate_sha256,code_challenge,proof_nonce,expires_at,protected_receipt) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (key,receipt["generation"],receipt["generationOperationId"],fingerprint,row["code_challenge"],row["proof_nonce"],
                 receipt["expiresAt"],protect("generation",key+":"+str(receipt["generation"]),outcome)))
            updated=conn.execute("UPDATE native_v2_installations SET current_generation=%s,revision=revision+1 "
                "WHERE installation_key_id=%s AND revision=%s AND current_generation=%s AND active_grant_id=%s "
                "RETURNING installation_key_id",(receipt["generation"],key,lease["installation_revision"],
                 lease["expected_generation"],grant["grant_id"])).fetchone()
            if not updated:fail(409,"STALE_EPOCH")
            current=self._certificate(conn,fingerprint)
            return self._issue(conn,action,record,grant,current)

    def public_boundary(self,request):
        if request.url.path=="/v1/installations/certificate-renew":
            if (not self.enabled or not self.auth.enabled or self.issuer is None
                or request.url.hostname!=urlsplit(self.origin).hostname or request.url.port not in (None,443)
                or not request.client or request.client.host not in ("127.0.0.1","::1")
                or request.method!="POST" or request.url.query
                or any(h in request.headers for h in ("origin","cookie","authorization"))):fail(404,"ROUTE_NOT_FOUND")
            self.auth.rate("native-v2-renew-relay",limit=60);return
        return super().public_boundary(request)

    def issuer_router(self):
        router=super().issuer_router()
        @router.post("/v1/installations/certificate-renew")
        async def renew(request:Request):
            try:
                result=await run_in_threadpool(self.relay_renew_begin,await read_body(request))
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error:return error_response(error)
        return router

    def native_router(self):
        router=super().native_router()
        @router.post("/v1/device-sessions/rebind")
        async def rebind(request:Request):
            try:
                fingerprint=await run_in_threadpool(self.auth.native_certificate,request)
                result=await run_in_threadpool(self.rebind,await read_body(request),fingerprint)
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error:return error_response(error)
            except Exception as error:
                from fastapi import HTTPException
                if isinstance(error,HTTPException):return http_error_response(error)
                raise
        @router.post("/v1/installations/certificate-renew",include_in_schema=False)
        async def internal_renew(request:Request):
            try:
                self.renew_relay_boundary(request)
                result=await run_in_threadpool(self.renew_begin,await read_body(request))
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error:return error_response(error)
        return router
