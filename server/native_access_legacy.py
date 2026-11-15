"""Explicit same-key v1 migration; certificate possession never selects an account."""
import secrets
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from native_authorization import (NativeAuthorizationError,fail,protect,restore,read_body,error_response,http_error_response)
from enrollment_crypto import digest

class NativeAccessLegacy:
    def _import_mapped_certificate(self,value,fingerprint):
        certificate=x509.load_pem_x509_certificate(value["certificatePem"].encode("ascii"))
        if certificate.fingerprint(hashes.SHA256()).hex()!=fingerprint:fail(403,"CERTIFICATE_BINDING_MISMATCH")
        key=certificate.public_key()
        if not isinstance(key,rsa.RSAPublicKey) or key.key_size!=2048 or key.public_numbers().e!=65537:
            fail(403,"CERTIFICATE_BINDING_MISMATCH")
        installation=digest(key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo))
        try:
            try:usage=certificate.extensions.get_extension_for_class(x509.KeyUsage).value
            except x509.ExtensionNotFound:usage=None  # RFC5280: absent KU imposes no KU restriction.
            eku=certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            basic=certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
            if (basic.ca or usage is not None and (not usage.digital_signature or usage.key_cert_sign or usage.crl_sign)
                or ExtendedKeyUsageOID.CLIENT_AUTH not in eku or certificate.subject==certificate.issuer
                or certificate.signature_hash_algorithm.name not in ("sha256","sha384","sha512")
                or int(certificate.not_valid_before_utc.timestamp())>self.now()
                or int(certificate.not_valid_after_utc.timestamp())<=self.now()):
                fail(403,"CERTIFICATE_BINDING_MISMATCH")
        except x509.ExtensionNotFound:fail(403,"CERTIFICATE_BINDING_MISMATCH")
        with self.db() as conn:
            self.lock(conn,installation)
            known=conn.execute("SELECT certificate_sha256 FROM native_v2_certificates WHERE certificate_sha256=%s",(fingerprint,)).fetchone()
            if known:return
            mapping=conn.execute("SELECT * FROM native_v2_legacy_certificates WHERE certificate_sha256=%s",(fingerprint,)).fetchone()
            if not mapping or mapping["installation_key_id"]!=installation or mapping["expires_at"]<=self.now():
                fail(409,"MIGRATION_CONFLICT")
            provenance=restore("legacy-certificate",fingerprint,mapping["protected_provenance"])
            if (provenance.get("source")!="authenticated-cloudflare-api" or provenance.get("certificatePem")!=value["certificatePem"]
                or provenance.get("installationKeyId")!=installation or provenance.get("certificateSha256")!=fingerprint):
                fail(409,"MIGRATION_CONFLICT")
            current=conn.execute("SELECT current_generation,revoked_at,active_grant_id FROM native_v2_installations "
                "WHERE installation_key_id=%s FOR UPDATE",(installation,)).fetchone()
            if current and (current["revoked_at"] is not None or current["current_generation"]!=0 or current["active_grant_id"] is not None):
                fail(409,"MIGRATION_CONFLICT")
            conn.execute("INSERT INTO native_v2_installations(installation_key_id,current_generation,created_at) "
                "VALUES(%s,1,%s) ON CONFLICT(installation_key_id) DO UPDATE SET current_generation=1,revision=native_v2_installations.revision+1",
                (installation,self.now()))
            receipt=dict(certificatePem=value["certificatePem"],certificateSha256=fingerprint,installationKeyId=installation,
                generation=1,generationOperationId=value["operationId"],expiresAt=int(certificate.not_valid_after_utc.timestamp()))
            # A valid legacy CN is preserved, not emitted as a new WegoH-profile
            # certificate receipt. Future same-key renewal uses the new CSR profile.
            conn.execute("INSERT INTO native_v2_certificates(installation_key_id,generation,generation_operation_id,"
                "certificate_sha256,code_challenge,proof_nonce,expires_at,protected_receipt) VALUES(%s,1,%s,%s,%s,%s,%s,%s)",
                (installation,value["operationId"],fingerprint,value["codeChallenge"],secrets.token_urlsafe(32),
                 receipt["expiresAt"],protect("generation",installation+":1",dict(receipt=receipt,legacy=True,provenance=provenance))))

    def authorize_request(self,raw,request):
        value=self.decode("ACCOUNT_AUTHORIZE",raw).for_transport()
        fingerprint=self.auth.native_certificate(request)
        if request.headers.get("authorization"):fail(400,"INVALID_REQUEST")
        self._import_mapped_certificate(value,fingerprint)
        return super().account_authorize(raw,fingerprint)

    def native_router(self):
        router=super().native_router()
        router.routes[:]=[route for route in router.routes if route.path!="/v1/device-authorizations"]
        @router.post("/v1/device-authorizations")
        async def authorize(request:Request):
            try:
                result=await run_in_threadpool(self.authorize_request,await read_body(request),request)
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error:return error_response(error)
            except HTTPException as error:return http_error_response(error)
        return router
