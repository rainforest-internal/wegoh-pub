"""Grant-only revoke uses only precommitted logout capability, even before exchange."""
import hmac
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from enrollment_crypto import digest,public_bytes
from native_authorization import NativeAuthorizationError,fail,restore,hash_secret,read_body,error_response,http_error_response,FIELDS

class NativeAccessRevocation:
    def _revoke_certificate(self,conn,grant,fingerprint):
        current=conn.execute("SELECT * FROM native_v2_installations WHERE installation_key_id=%s",
            (grant["installation_key_id"],)).fetchone()
        if not current or current["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
        certificate=conn.execute("SELECT * FROM native_v2_certificates WHERE installation_key_id=%s "
            "AND generation=%s AND certificate_sha256=%s AND expires_at>%s",
            (grant["installation_key_id"],current["current_generation"],fingerprint,self.now())).fetchone()
        if certificate:return
        # This exception is revocation-only, exact same grant and staged leaf.
        row=self._connection(conn,grant["connection_id"])
        candidates=[row]
        candidates.extend(conn.execute("SELECT "+FIELDS+" FROM native_v2_connections "
            "WHERE installation_key_id=%s AND kind='RENEW' AND state='ISSUED'",
            (grant["installation_key_id"],)).fetchall())
        for candidate in candidates:
            if candidate["state"]!="ISSUED" or candidate["protected_certificate"] is None:continue
            if candidate["kind"]=="RENEW":
                # After terminal purge the main lease can be absent. The same-key
                # receipt is still harmless only with this exact grant capability.
                lease=conn.execute("SELECT grant_id FROM native_v2_renewals WHERE connection_id=%s",
                    (candidate["connection_id"],)).fetchone()
                if lease and lease["grant_id"]!=grant["grant_id"]:continue
                link=self._request(candidate).get("_revocationGrantHash")
                if not link or not hmac.compare_digest(link,hash_secret("grant-link",grant["grant_id"])):continue
            elif not self._request(candidate).get("_reauthorization"):continue
            outcome=restore("certificate",candidate["connection_id"],candidate["protected_certificate"])
            receipt=outcome["receipt"]
            if (receipt["certificateSha256"]!=fingerprint or receipt["installationKeyId"]!=grant["installation_key_id"]
                or receipt["generation"]!=current["current_generation"]+1 or receipt["expiresAt"]<=self.now()):continue
            leaf=x509.load_pem_x509_certificate(receipt["certificatePem"].encode("ascii"))
            if (leaf.fingerprint(hashes.SHA256()).hex()==fingerprint
                and digest(public_bytes(leaf.public_key()))==grant["installation_key_id"]):return
        fail(403,"CERTIFICATE_BINDING_MISMATCH")

    def revoke_grant(self,raw,fingerprint):
        action="GRANT_REVOKE";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            initial=conn.execute("SELECT installation_key_id FROM native_v2_grants WHERE grant_id=%s",
                (value["grantId"],)).fetchone()
            if not initial:fail(401,"INVALID_CREDENTIAL")
            self.lock(conn,initial["installation_key_id"])
            grant=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE",(value["grantId"],)).fetchone()
            self._revoke_certificate(conn,grant,fingerprint)
            if not grant["revoke_hash"] or not hmac.compare_digest(grant["revoke_hash"],
                hash_secret("revoke",value["revokeCapability"])):fail(401,"INVALID_CREDENTIAL")
            self._revoke(conn,grant["grant_id"],self.now())
            terminal=conn.execute("SELECT revoked_at,expires_at FROM native_v2_grants WHERE grant_id=%s",(grant["grant_id"],)).fetchone()
            if terminal["expires_at"]<=self.now():
                return self.response(action,value,"REVOKED","TERMINAL",grantId=grant["grant_id"],expiredAt=terminal["expires_at"])
            return self.response(action,value,"REVOKED","TERMINAL",grantId=grant["grant_id"],revokedAt=terminal["revoked_at"])

    def native_router(self):
        router=super().native_router()
        @router.post("/v1/device-sessions/revoke")
        async def revoke(request:Request):
            try:
                fingerprint=await run_in_threadpool(self.auth.native_certificate,request)
                result=await run_in_threadpool(self.revoke_grant,await read_body(request),fingerprint)
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error:return error_response(error)
            except HTTPException as error:return http_error_response(error)
        return router

