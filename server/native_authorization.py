"""Single-consent public authorization. Isolated issuer cannot mint personal credentials."""
import asyncio
from contextlib import nullcontext
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime
from urllib.parse import urlsplit
import psycopg
from psycopg.rows import dict_row
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from enrollment_crypto import (EnrollmentError, IssuanceUncertain, challenge, digest,
    public_bytes, validate_csr, verify_proof)
from native_access_codec import (CodecError, canonical_request, decode_request,
    decode_phone_request, decode_phone_response, decode_response, decode_error, derive_capability, disclosure_snapshot, decode_json,
    proof_transcript, wire_contract)
from native_access_policy import AUTHORIZATION_VERSION, MANDATORY_SCOPES, authorize_route, valid_grant_scopes
from native_principal import NativePrincipal
from native_functional_query import native_query_allowed
from native_issuance_hold import HoldExpectation,HoldError,inspect_holds,require_new_issuance as hold_require_new_issuance
from private_records import VisitCipher
from native_access_retention import purge_grant_personal, active_capabilities, reduce_grant_scopes

WIRE = wire_contract()
TTL, INTERVAL, BINDING_SECONDS, ACCESS_SECONDS = 300, 5, 604800, 900
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
FIELDS = ("connection_id,operation_id,installation_key_id,kind,user_code,"
    "original_begin_hash,code_challenge,proof_nonce,state,expires_at,next_poll,created_at,"
    "protected_request,protected_certificate,restart_hash,restart_expires_at,restart_consumed_at")

class NativeAuthorizationError(Exception):
    def __init__(self, status, code, retry=None):
        self.status, self.code, self.retry = status, code, retry
        super().__init__(code)

class VehicleConnectionLimit(NativeAuthorizationError):
    def __init__(self):
        super().__init__(409, 'OPERATION_CONFLICT')

def fail(status, code, retry=None): raise NativeAuthorizationError(status, code, retry)

def error_response(error):
    value = dict(authorizationVersion=1,error=error.code)
    if error.retry is not None: value["retryAfter"] = error.retry
    value=decode_error(error.status,value).for_transport()
    return JSONResponse(value,status_code=error.status,
        headers={"Retry-After":str(error.retry)} if error.retry is not None else None)

def http_error_response(error):
    status=error.status_code if error.status_code in (400,401,403,404,408,409,410,413,429,503) else 503
    code={400:'INVALID_REQUEST',401:'AUTHENTICATION_REQUIRED',403:'INVALID_PROOF',404:'ROUTE_NOT_FOUND',
        408:'REQUEST_TIMEOUT',409:'OPERATION_CONFLICT',410:'AUTHORIZATION_EXPIRED',413:'REQUEST_TOO_LARGE',
        429:'RATE_LIMITED',503:'SERVICE_UNAVAILABLE'}[status]
    retry=60 if status==429 else None
    return error_response(NativeAuthorizationError(status,code,retry))

def hash_secret(purpose,value):
    return hashlib.sha256(("WegoH native v2 "+purpose+"\n"+value).encode("ascii")).hexdigest()

def protect(purpose,key,value):
    return VisitCipher().protect("native-v2:"+purpose,key,value)

def restore(purpose,key,value):
    return VisitCipher().restore("native-v2:"+purpose,key,value)

async def read_body(request):
    if request.headers.get("content-type","").split(";",1)[0].strip()!="application/json":
        fail(400,"INVALID_REQUEST")
    raw=bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>12288: fail(413,"REQUEST_TOO_LARGE")
    except TimeoutError: fail(408,"REQUEST_TIMEOUT")
    return bytes(raw)

class NativeAuthorization:
    def __init__(self,auth,*,issuer=None,origin=None,clock=time.time,enabled=None):
        self.auth,self.issuer,self.clock=auth,issuer,clock
        self.enabled=(os.environ.get("WEGOH_NATIVE_ACCESS_ENABLED","0")=="1") if enabled is None else enabled
        if type(self.enabled) is not bool:raise ValueError("Explicit authorization enablement required")
        self.origin=origin or WIRE["origins"]["enroll"]
        self.hold_expectation=HoldExpectation.environment() if self.enabled and self.auth.enabled else None

    def verify_issuance_holds(self):
        try:
            with self.db() as conn:return inspect_holds(conn,VisitCipher(),self.hold_expectation)
        except HoldError:fail(503,"SERVICE_UNAVAILABLE")

    def require_new_issuance(self,conn,csr_pem):
        try:return hold_require_new_issuance(conn,VisitCipher(),self.hold_expectation,csr_pem)
        except HoldError as error:
            if error.code=="HELD_ISSUANCE_KEY":fail(409,"OPERATION_CONFLICT")
            fail(503,"SERVICE_UNAVAILABLE")

    def now(self): return int(self.clock())
    def db(self): return psycopg.connect(self.auth.dsn,row_factory=dict_row)

    def lock(self,conn,key):
        # Shared report/room graph precedes installation and authority row locks.
        # The isolated issuer has no room service and retains its minimal boundary.
        rooms=getattr(self.auth,'room_service',None)
        if rooms is not None:rooms.graph_lock(conn)
        conn.execute("SELECT pg_advisory_xact_lock(%s)",
            (int.from_bytes(bytes.fromhex(key)[:8],"big",signed=True),))

    def _require_vehicle_slot(self,conn,account,key,now):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ('native-vehicle-owner:'+account,))
        occupied=conn.execute(
            "SELECT EXISTS(SELECT 1 FROM native_v2_grants g "
            "JOIN native_v2_installations i ON i.installation_key_id=g.installation_key_id "
            "JOIN native_v2_connections c ON c.connection_id=g.connection_id "
            "JOIN native_v2_approvals a ON a.connection_id=g.connection_id "
            "WHERE g.account_id=%s AND g.installation_key_id<>%s AND g.expires_at>%s "
            "AND i.revoked_at IS NULL AND ((g.state='TOKEN_ISSUED' AND i.active_grant_id=g.grant_id) "
            "OR (g.state='APPROVED' AND a.state='APPROVED' AND a.exchange_expires_at>%s AND c.expires_at>%s))) AS occupied",
            (account,key,now,now,now)).fetchone()['occupied']
        if occupied:raise VehicleConnectionLimit()

    def decode(self,action,raw):
        try: return decode_request(action,raw)
        except (CodecError,EnrollmentError): fail(400,"INVALID_REQUEST")

    def response(self,action,value,state,disposition,status=200,**fields):
        payload=dict(authorizationVersion=1,operation=action,operationId=value["operationId"],
            state=state,disposition=disposition,serverTime=self.now(),**fields)
        decode_response(action,status,payload,expected_operation_id=value["operationId"])
        return status,payload

    def public_boundary(self,request):
        if (not self.enabled or not self.auth.enabled or self.issuer is None
            or request.url.hostname!=urlsplit(self.origin).hostname or request.url.port not in (None,443)
            or not request.client or request.client.host not in ("127.0.0.1","::1")
            or request.url.query or any(x in request.headers for x in ("origin","cookie","authorization"))):
            fail(404,"ROUTE_NOT_FOUND")
        path=request.url.path
        if request.method!="POST" or not (path in ("/v1/connections","/v1/connections/recover","/v1/connections/cancel",
            "/v1/installations/certificate-recover") or re.fullmatch(r"/v1/connections/[a-f0-9]{32}/claim",path)):
            fail(404,"ROUTE_NOT_FOUND")
        self.auth.rate("native-v2-public-total",limit=120)

    def _connection(self,conn,key,*,by="connection_id",lock=True):
        if by not in ("connection_id","operation_id","user_code"): raise ValueError("internal lookup")
        row=conn.execute("SELECT "+FIELDS+" FROM native_v2_connections WHERE "+by+"=%s"+
            (" FOR UPDATE" if lock else ""),(key,)).fetchone()
        if row is None: fail(404,"OPERATION_NOT_FOUND")
        return row

    def _request(self,row): return restore("connection",row["connection_id"],row["protected_request"])

    def _approval(self,conn,row):
        return conn.execute("SELECT connection_id,grant_id,state,protected_owner,exchange_expires_at "
            "FROM native_v2_issuer_approvals WHERE connection_id=%s",(row["connection_id"],)).fetchone()

    def _member(self,approval):
        if not approval or approval["state"]!="APPROVED": return False
        owner=restore("approval",approval["connection_id"],approval["protected_owner"])
        try:
            self.auth.current_account(owner["accountId"], vehicle=True); return True
        except HTTPException: return False

    def _pending(self,row):
        return dict(connectionId=row["connection_id"],userCode=row["user_code"],
            verificationUri=WIRE["phone"]["current"].replace("<UserCode>",row["user_code"]),
            proofNonce=row["proof_nonce"],expiresAt=row["expires_at"],interval=INTERVAL)

    def _end_unclaimed(self,conn,key,now):
        # A new code request proves the same key and means the vehicle has
        # dropped its earlier unclaimed request together with its verifier
        # (차량 "취소" or logout). End that code now, whatever kind it was, so
        # the phone can no longer look it up or approve it.
        conn.execute("UPDATE native_v2_connections SET expires_at=GREATEST(created_at+1,%s) "
            "WHERE installation_key_id=%s AND state='PENDING' AND expires_at>%s AND NOT EXISTS "
            "(SELECT 1 FROM native_v2_issuer_approvals a WHERE a.connection_id=native_v2_connections.connection_id "
            "AND a.state IN ('DENIED','REVOKED'))",(now,key,now))

    def begin(self,raw):
        action="CONNECTION_BEGIN";record=self.decode(action,raw);value=record.for_transport()
        csr=validate_csr(value["csrPem"]);key=digest(public_bytes(csr.public_key()))
        request_hash=digest(canonical_request(record));now=self.now()
        self.auth.rate("native-v2-begin-total",limit=20)
        with self.db() as conn:
            self.lock(conn,key)
            previous=conn.execute("SELECT "+FIELDS+" FROM native_v2_connections WHERE operation_id=%s FOR UPDATE",
                (value["operationId"],)).fetchone()
            if previous:
                if not hmac.compare_digest(previous["original_begin_hash"],request_hash): fail(409,"OPERATION_CONFLICT")
                if previous["expires_at"]<=now: fail(410,"AUTHORIZATION_EXPIRED")
                return self.response(action,value,"PENDING","WAIT",**self._pending(previous))
            if conn.execute("SELECT count(*) AS n FROM native_v2_connections").fetchone()["n"]>=1000:
                fail(429,"RATE_LIMITED",3600)
            installation=conn.execute("SELECT current_generation,revoked_at FROM native_v2_installations "
                "WHERE installation_key_id=%s",(key,)).fetchone()
            if installation and installation["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
            if not installation or installation["current_generation"]==0:
                old=conn.execute("SELECT 1 FROM vehicle_enrollments WHERE public_key_hash=%s AND "
                    "(state IN ('issuing','uncertain','issued') OR (state IN ('pending','approved') AND expires_at>%s)) LIMIT 1",
                    (key,now)).fetchone()
                if old:fail(409,'RECOVERY_NOT_ALLOWED')
            stored=dict(value)
            if installation and installation["current_generation"]>0:
                # Missing local public receipt is not a new key/installation.
                # New phone consent + the existing CLAIM key proof are required;
                # generation is selected from the server, never guessed by client.
                stored.update(_reauthorization=True,_knownCsrRecovery=True,
                    expectedGeneration=installation["current_generation"])
            self._end_unclaimed(conn,key,now)
            connection=secrets.token_hex(16);nonce=secrets.token_urlsafe(32)
            code="".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            conn.execute("INSERT INTO native_v2_connections(connection_id,operation_id,installation_key_id,kind,user_code,"
                "original_begin_hash,code_challenge,proof_nonce,state,expires_at,created_at,protected_request) "
                "VALUES(%s,%s,%s,'INSTALL',%s,%s,%s,%s,'PENDING',%s,%s,%s)",
                (connection,value["operationId"],key,code,request_hash,value["codeChallenge"],nonce,
                 now+TTL,now,protect("connection",connection,stored)))
            return self.response(action,value,"PENDING","WAIT",201,**self._pending(self._connection(conn,connection)))

    def detail(self,code,owner,*,account_decision=False):
        self.auth.current_account(owner['id'], vehicle=True, identity=owner)
        with self.db() as conn:
            row=self._connection(conn,code,by="user_code")
            expired=row["expires_at"]<=self.now()
            if expired and not account_decision: fail(410,"AUTHORIZATION_EXPIRED")
            value=self._request(row);approval=self._approval(conn,row)
            if approval and approval["state"]=="REVOKED":fail(404,"OPERATION_NOT_FOUND")
            if approval and approval["protected_owner"]:
                saved=restore("approval",row["connection_id"],approval["protected_owner"])
                if saved["accountId"]!=owner["id"]: fail(404,"OPERATION_NOT_FOUND")
            if expired: fail(410,"AUTHORIZATION_EXPIRED")
            result=dict(authorizationVersion=1,userCode=code,deviceName=value["name"],
                state=approval["state"] if approval else "PENDING",expiresAt=row["expires_at"],
                requestedScopes=value["requestedScopes"],requiredScopes=sorted(MANDATORY_SCOPES),
                consentVersion=1,keepSignedInDefault=False,currentAccountDisplayName=owner["displayName"],
                disclosureSnapshot=disclosure_snapshot(value["requestedScopes"]))
            return decode_phone_response("PHONE_STATUS",result,expected_user_code=code).for_transport()


    def approve(self,code,raw,owner,*,deny=False,account_decision=False):
        self.auth.current_account(owner['id'], vehicle=True, identity=owner)
        now=self.now()
        with self.db() as conn:
            initial=self._connection(conn,code,by="user_code",lock=False)
            self.lock(conn,initial["installation_key_id"]);row=self._connection(conn,initial["connection_id"])
            request=self._request(row)
            existing=self._approval(conn,row)
            if account_decision and existing:
                # An iPhone decision cannot withdraw a grant. The owner uses the
                # separate device revocation path after a vehicle connects.
                if existing["state"]=="REVOKED" or not existing["protected_owner"]:
                    fail(404,"OPERATION_NOT_FOUND")
                saved=restore("approval",row["connection_id"],existing["protected_owner"])
                if saved["accountId"]!=owner["id"]: fail(404,"OPERATION_NOT_FOUND")
                if row["expires_at"]<=now: fail(410,"AUTHORIZATION_EXPIRED")
                fail(409,"OPERATION_CONFLICT")
            if deny and existing:
                try:decode_phone_request("PHONE_DENY",raw)
                except CodecError:fail(400,"INVALID_REQUEST")
                if not existing["protected_owner"]:fail(404,"OPERATION_NOT_FOUND")
                saved=restore("approval",row["connection_id"],existing["protected_owner"])
                if saved["accountId"]!=owner["id"]:fail(404,"OPERATION_NOT_FOUND")
                if existing["state"]=="APPROVED" and existing["grant_id"]:
                    self._revoke(conn,existing["grant_id"],now)
                return decode_phone_response("PHONE_DENY",dict(authorizationVersion=1,state="DENIED",
                    userCode=code),expected_user_code=code).for_transport()
            if row["expires_at"]<=now: fail(410,"AUTHORIZATION_EXPIRED")
            try:
                parsed=decode_json(raw) if isinstance(raw,bytes) else raw
                if not deny and isinstance(parsed,dict) and set(parsed)==set(WIRE['phoneOperations'][1]['requestRequired']):
                    snapshot=disclosure_snapshot(request['requestedScopes'])
                    if (type(parsed.get('disclosureVersion')) is int and parsed['disclosureVersion']>0
                        and isinstance(parsed.get('disclosureSha256'),str)
                        and re.fullmatch(r'[a-f0-9]{64}',parsed['disclosureSha256'])
                        and (parsed['disclosureVersion']!=snapshot['disclosureVersion']
                             or parsed['disclosureSha256']!=snapshot['disclosureSha256'])):
                        fail(409,'CONSENT_CHANGED')
                value=decode_phone_request("PHONE_DENY" if deny else "PHONE_APPROVE",parsed,
                    requested_scopes=request["requestedScopes"]).for_transport()
            except CodecError: fail(400,"INVALID_REQUEST")
            if not deny and value["consentVersion"]!=1: fail(409,"CONSENT_CHANGED")
            if self._approval(conn,row): fail(409,"OPERATION_CONFLICT")
            approved=not deny and MANDATORY_SCOPES<=frozenset(value["approvedScopes"])
            if approved:self._require_vehicle_slot(conn,owner['id'],row['installation_key_id'],now)
            grant=secrets.token_hex(16) if approved else None
            if approved:
                conn.execute("INSERT INTO native_v2_installations(installation_key_id,created_at) "
                    "VALUES(%s,%s) ON CONFLICT DO NOTHING",(row["installation_key_id"],now))
                consent=dict(name=request["name"],scopes=value["approvedScopes"],keepSignedIn=value["keepSignedIn"],
                    disclosureVersion=value["disclosureVersion"],disclosureSha256=value["disclosureSha256"])
                hook=getattr(self,"_reauthorization_consent",None)
                if hook:hook(conn,row,request,consent)
                conn.execute("INSERT INTO native_v2_grants(grant_id,connection_id,installation_key_id,account_id,state,"
                    "consent_version,expires_at,protected_consent,revoke_hash) VALUES(%s,%s,%s,%s,'APPROVED',1,%s,%s,%s)",
                    (grant,row["connection_id"],row["installation_key_id"],owner["id"],now+BINDING_SECONDS,
                     protect("consent",grant,consent),request.get("revokeCommitment")))
            conn.execute("INSERT INTO native_v2_approvals(connection_id,grant_id,state,protected_owner,approved_at,"
                "exchange_expires_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (row["connection_id"],grant,"APPROVED" if approved else "DENIED",
                 protect("approval",row["connection_id"],dict(accountId=owner["id"])),now,now+TTL if approved else None))
            result=dict(authorizationVersion=1,state="APPROVED" if approved else "DENIED",userCode=code)
            if not deny:result['expiresAt']=row['expires_at']
            return decode_phone_response('PHONE_DENY' if deny else 'PHONE_APPROVE',result,expected_user_code=code).for_transport()

    def _verify(self,action,record,row):
        value=record.for_transport();original=self._request(row)
        try:
            if not hmac.compare_digest(challenge(value["codeVerifier"]),row["code_challenge"]): fail(403,"INVALID_PROOF")
            # Recover and cancel sign a fixed nonce: an ACCOUNT code never gave its nonce out.
            if action not in ("CONNECTION_RECOVER","CONNECTION_CANCEL") and value["proofNonce"]!=row["proof_nonce"]: fail(403,"INVALID_PROOF")
            if row["kind"]=="ACCOUNT":
                if action not in ("CONNECTION_RECOVER","CONNECTION_CANCEL"):fail(403,"INVALID_PROOF")
                identity=x509.load_pem_x509_certificate(original["certificatePem"].encode("ascii"))
                if digest(public_bytes(identity.public_key()))!=row["installation_key_id"]:fail(403,"INVALID_PROOF")
            else:identity=validate_csr(original["csrPem"])
            verify_proof(identity,proof_transcript(action,record,
                installation_key_id=row["installation_key_id"],code_challenge=row["code_challenge"],
                connection_id=row["connection_id"] if action in ("CONNECTION_CLAIM","CERTIFICATE_RENEW_CLAIM") else None),value["proof"])
        except EnrollmentError: fail(403,"INVALID_PROOF")

    def _result(self,conn,action,value,row):
        approval=self._approval(conn,row)
        if approval and approval["state"] in ("DENIED","REVOKED"):
            if action=="CONNECTION_CLAIM": fail(403,"CONSENT_REVOKED")
            return self.response(action,value,approval["state"],"TERMINAL",connectionId=row["connection_id"])
        if row["state"] in ("ISSUING","UNCERTAIN"):
            return self.response(action,value,row["state"],"RECONCILE",202 if action=="CONNECTION_CLAIM" else 200,
                **(dict(connectionId=row["connection_id"],interval=INTERVAL) if action=="CONNECTION_CLAIM" else dict(connectionId=row["connection_id"],proofNonce=row["proof_nonce"],interval=INTERVAL)))
        if row["state"]=="ISSUED":
            receipt=restore("certificate",row["connection_id"],row["protected_certificate"])["receipt"]
            if self._member(approval) and approval["exchange_expires_at"]>self.now():
                return self.response(action,value,"ISSUED","EXCHANGE",connectionId=row["connection_id"],certificateReceipt=receipt,
                    grantId=approval["grant_id"],proofNonce=row["proof_nonce"],exchangeExpiresAt=approval["exchange_expires_at"])
            return self.response(action,value,"ISSUED","REAUTHORIZE",connectionId=row["connection_id"],certificateReceipt=receipt)
        if row["expires_at"]<=self.now(): fail(410,"AUTHORIZATION_EXPIRED")
        if self._member(approval):
            return self.response(action,value,"APPROVED","CONTINUE_CLAIM",connectionId=row["connection_id"],proofNonce=row["proof_nonce"],
                expiresAt=row["expires_at"],interval=INTERVAL)
        fields=dict(connectionId=row["connection_id"],interval=INTERVAL)
        if action!="CONNECTION_CLAIM": fields.update(proofNonce=row["proof_nonce"],expiresAt=row["expires_at"])
        return self.response(action,value,"PENDING","WAIT",202 if action=="CONNECTION_CLAIM" else 200,**fields)

    def _recovery_csr_matches(self,row,requested_csr):
        original=self._request(row)
        if row["kind"]!="ACCOUNT":return requested_csr==original["csrPem"]
        # Public status only: an ACCOUNT request stored its certified identity,
        # not a CSR. Bind the caller's signed CSR to that exact installation key.
        csr=validate_csr(requested_csr)
        cert=x509.load_pem_x509_certificate(original["certificatePem"].encode("ascii"))
        return (digest(public_bytes(csr.public_key()))==row["installation_key_id"]
            and public_bytes(csr.public_key())==public_bytes(cert.public_key()))

    def recover_connection(self,raw):
        action="CONNECTION_RECOVER";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            row=self._connection(conn,value["operationId"],by="operation_id");self._verify(action,record,row)
            if not self._recovery_csr_matches(row,value["csrPem"]) or not hmac.compare_digest(value["originalBeginHash"],row["original_begin_hash"]):
                fail(403,"INVALID_PROOF")
            return self._result(conn,action,value,row)

    def cancel(self,raw):
        # 차량 "취소" drops the verifier with its code. The same key's proof over
        # the original operation ends that code now instead of at its TTL, so
        # the phone gets 410 for it. Issuance already under way is left
        # to its own claim/revoke path.
        # This runs on the enroll host as wegohenroll, which may change only
        # native_v2_connections. The ended code is that row in
        # EXPIRED_NOT_ISSUED with its expiry passed: claim and the phone stop
        # on the expiry, the vehicle slot frees with it, and ACCOUNT re-poll and
        # SESSION_EXCHANGE stop on the state, since an approval's exchange
        # window can outlive the code. Grants and approvals stay untouched; a
        # session already exchanged belongs to SESSION_REVOKE.
        action="CONNECTION_CANCEL";record=self.decode(action,raw);value=record.for_transport();now=self.now()
        with self.db() as conn:
            initial=self._connection(conn,value["operationId"],by="operation_id",lock=False)
            self.lock(conn,initial["installation_key_id"]);row=self._connection(conn,initial["connection_id"])
            if row["kind"] not in ("INSTALL","ACCOUNT"): fail(404,"OPERATION_NOT_FOUND")
            self._verify(action,record,row)
            if row["state"] not in ("PENDING","EXPIRED_NOT_ISSUED"): fail(409,"OPERATION_CONFLICT")
            conn.execute("UPDATE native_v2_connections SET state='EXPIRED_NOT_ISSUED',"
                "expires_at=LEAST(expires_at,GREATEST(created_at+1,%s)) WHERE connection_id=%s AND state='PENDING'",
                (now,row["connection_id"]))
            return self.response(action,value,"EXPIRED","TERMINAL",connectionId=row["connection_id"])

    def claim(self,connection_id,raw):
        action="CONNECTION_CLAIM";record=self.decode(action,raw);value=record.for_transport();now=self.now()
        with self.db() as conn:
            initial=self._connection(conn,connection_id,lock=False);self.lock(conn,initial["installation_key_id"])
            row=self._connection(conn,connection_id);self._verify(action,record,row)
            if row["next_poll"]>now: fail(429,"RATE_LIMITED",max(INTERVAL,row["next_poll"]-now))
            conn.execute("UPDATE native_v2_connections SET next_poll=%s WHERE connection_id=%s",(now+INTERVAL,connection_id))
            approval=self._approval(conn,row)
            reconcile=row["state"] in ("ISSUING","UNCERTAIN")
            if not reconcile:
                if row["state"]!="PENDING" or not self._member(approval): return self._result(conn,action,value,row)
                if row["expires_at"]<=now or approval["exchange_expires_at"]<=now: fail(410,"AUTHORIZATION_EXPIRED")
                incident=conn.execute("SELECT revoked_at FROM native_v2_installations WHERE installation_key_id=%s",(row["installation_key_id"],)).fetchone()
                if incident and incident["revoked_at"] is not None:fail(403,"INSTALLATION_REVOKED")
                self.require_new_issuance(conn,self._request(row)["csrPem"])
                conn.execute("UPDATE native_v2_connections SET state='ISSUING' WHERE connection_id=%s",(connection_id,))
            original=self._request(row)
        # Commit ISSUING before external IO. A later retry only reads the CA;
        # missing/unknown GET output never becomes permission for another POST.
        try:
            if reconcile:
                reader=getattr(self.issuer,"reconcile",None)
                issued=reader(original["csrPem"],()) if reader else None
                if issued is None:raise IssuanceUncertain("ISSUANCE_UNCERTAIN")
            else:issued=self.issuer.issue(original["csrPem"])
        except (IssuanceUncertain,EnrollmentError):
            with self.db() as conn:
                conn.execute("UPDATE native_v2_connections SET state='UNCERTAIN' WHERE connection_id=%s "
                    "AND state IN ('ISSUING','UNCERTAIN')",(connection_id,))
                return self._result(conn,action,value,self._connection(conn,connection_id))
        receipt=dict(certificatePem=issued["certificatePem"],certificateSha256=issued["certificateSha256"],
            installationKeyId=row["installation_key_id"],generation=1,generationOperationId=row["operation_id"],
            expiresAt=int(datetime.fromisoformat(issued["expiresAt"].replace("Z","+00:00")).timestamp()))
        with self.db() as conn:
            self.lock(conn,row["installation_key_id"]);current=self._connection(conn,connection_id)
            if current["state"]=="ISSUED":return self._result(conn,action,value,current)
            if current["state"] not in ("ISSUING","UNCERTAIN"): fail(409,"OPERATION_CONFLICT")
            conn.execute("INSERT INTO native_v2_certificates(installation_key_id,generation,generation_operation_id,"
                "certificate_sha256,code_challenge,proof_nonce,expires_at,protected_receipt) VALUES(%s,1,%s,%s,%s,%s,%s,%s)",
                (row["installation_key_id"],row["operation_id"],receipt["certificateSha256"],row["code_challenge"],
                 row["proof_nonce"],receipt["expiresAt"],protect("generation",row["installation_key_id"]+":1",
                    dict(receipt=receipt,provenance=issued))))
            updated=conn.execute("UPDATE native_v2_installations SET current_generation=1,revision=revision+1 "
                "WHERE installation_key_id=%s AND current_generation=0 AND revoked_at IS NULL RETURNING installation_key_id",
                (row["installation_key_id"],)).fetchone()
            if not updated: fail(409,"OPERATION_CONFLICT")
            conn.execute("UPDATE native_v2_connections SET state='ISSUED',protected_certificate=%s WHERE connection_id=%s",
                (protect("certificate",connection_id,dict(receipt=receipt,provenance=issued)),connection_id))
        # Persist the real public CA outcome even when personal consent was
        # withdrawn during IO. Returning a terminal personal error must not roll
        # back issuance evidence or force a duplicate CA request.
        with self.db() as conn:
            return self._result(conn,action,value,self._connection(conn,connection_id))

    def _certificate(self,conn,fingerprint):
        row=conn.execute("SELECT c.*,i.slot_revision,i.active_grant_id,i.revoked_at,i.current_generation "
            "FROM native_v2_certificates c JOIN native_v2_installations i USING(installation_key_id) "
            "WHERE c.certificate_sha256=%s",(fingerprint,)).fetchone()
        if not row or row["revoked_at"] is not None or row["generation"]!=row["current_generation"] or row["expires_at"]<=self.now():
            fail(403,"CERTIFICATE_BINDING_MISMATCH")
        return row

    def account_authorize(self,raw,fingerprint):
        action="ACCOUNT_AUTHORIZE";record=self.decode(action,raw);value=record.for_transport();now=self.now()
        stored=dict(value)
        cert=x509.load_pem_x509_certificate(value["certificatePem"].encode("ascii"))
        if cert.fingerprint(hashes.SHA256()).hex()!=fingerprint: fail(403,"CERTIFICATE_BINDING_MISMATCH")
        with self.db() as conn:
            certificate=self._certificate(conn,fingerprint);key=certificate["installation_key_id"];self.lock(conn,key)
            previous=conn.execute("SELECT "+FIELDS+" FROM native_v2_connections WHERE operation_id=%s FOR UPDATE",
                (value["operationId"],)).fetchone()
            if previous:
                if (previous["installation_key_id"]!=key or previous["original_begin_hash"]!=digest(canonical_request(record))
):
                    fail(409,"OPERATION_CONFLICT")
                # The vehicle cancelled this code (CONNECTION_CANCEL).
                if previous["state"]=="EXPIRED_NOT_ISSUED": fail(410,"AUTHORIZATION_EXPIRED")
                approval=self._approval(conn,previous)
                if approval:
                    if approval["state"]!="APPROVED": return self.response(action,value,"DENIED","TERMINAL",connectionId=previous["connection_id"])
                    if not self._member(approval) or approval["exchange_expires_at"]<=now: fail(410,"AUTHORIZATION_EXPIRED")
                    return self.response(action,value,"APPROVED","EXCHANGE",connectionId=previous["connection_id"],grantId=approval["grant_id"],
                        exchangeExpiresAt=approval["exchange_expires_at"])
                if previous["expires_at"]<=now: fail(410,"AUTHORIZATION_EXPIRED")
                fields=self._pending(previous);fields.pop("proofNonce")
                return self.response(action,value,"PENDING","WAIT",**fields)
            self._end_unclaimed(conn,key,now)
            connection=secrets.token_hex(16);code="".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            conn.execute("INSERT INTO native_v2_connections(connection_id,operation_id,installation_key_id,kind,user_code,"
                "original_begin_hash,code_challenge,proof_nonce,state,expires_at,created_at,protected_request) "
                "VALUES(%s,%s,%s,'ACCOUNT',%s,%s,%s,%s,'PENDING',%s,%s,%s)",
                (connection,value["operationId"],key,code,digest(canonical_request(record)),value["codeChallenge"],
                 secrets.token_urlsafe(32),now+TTL,now,protect("connection",connection,stored)))
            fields=self._pending(self._connection(conn,connection));fields.pop("proofNonce")
            return self.response(action,value,"PENDING","WAIT",201,**fields)

    def _grant(self,conn,grant_id,certificate):
        row=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE",(grant_id,)).fetchone()
        if not row or row["installation_key_id"]!=certificate["installation_key_id"]: fail(401,"INVALID_CREDENTIAL")
        return row

    def _live(self,grant,*,connection=None):
        if grant["state"]=="REVOKED": fail(403,"CONSENT_REVOKED")
        if grant["expires_at"]<=self.now(): fail(410,"GRANT_EXPIRED")
        if grant["state"] not in ("APPROVED","TOKEN_ISSUED"): fail(401,"INVALID_CREDENTIAL")
        try:
            return self.auth.current_account(grant["account_id"], connection=connection, vehicle=True)
        except HTTPException: fail(403,"CONSENT_REVOKED")

    def _cached(self,conn,action,record,grant,certificate):
        value=record.for_transport()
        row=conn.execute("SELECT * FROM native_v2_operations WHERE operation_id=%s",(value["operationId"],)).fetchone()
        if not row: return None
        if row["action"]!=action or row["grant_id"]!=grant["grant_id"] or row["request_hash"]!=digest(canonical_request(record)):
            fail(409,"OPERATION_CONFLICT")
        if row["credential_epoch"]!=grant["credential_epoch"] or row["slot_revision"]!=certificate["slot_revision"] or row["expires_at"]<=self.now():
            fail(409,"STALE_EPOCH")
        return restore("operation",value["operationId"],row["protected_receipt"])


    def _revoke(self,conn,grant_id,now):
        # Remove purpose-specific shared derivatives before private auth is erased.
        # The caller already holds graph -> installation -> grant locks.
        prior=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE",(grant_id,)).fetchone()
        functional=getattr(self.auth,'functional_access',None)
        if functional is not None and prior and prior['account_id'] and prior['device_id']:
            from native_functional_withdrawal import withdraw_report_effects
            from native_functional_policy import FunctionalError,PURPOSES
            try:withdraw_report_effects(conn,self.auth,prior['account_id'],prior['device_id'],PURPOSES)
            except FunctionalError:fail(503,'SERVICE_UNAVAILABLE')
        conn.execute("UPDATE native_v2_grants SET state='REVOKED',revoked_at=%s,credential_epoch=credential_epoch+1,"
            "device_revision=device_revision+1 WHERE grant_id=%s AND state IN ('APPROVED','TOKEN_ISSUED')",(now,grant_id))
        conn.execute("UPDATE native_v2_approvals SET state='REVOKED' WHERE grant_id=%s AND state='APPROVED'",(grant_id,))
        conn.execute("UPDATE native_v2_installations SET active_grant_id=NULL,slot_revision=slot_revision+1,revision=revision+1 "
            "WHERE active_grant_id=%s",(grant_id,))
        revoked=conn.execute("SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE",(grant_id,)).fetchone()
        if revoked and revoked["state"]=="REVOKED":
            conn.execute("DELETE FROM native_v2_renewals WHERE grant_id=%s",(grant_id,))
            purge_grant_personal(conn,revoked,revoked_at=revoked["revoked_at"])

    def _issue(self,conn,action,record,grant,certificate,*,first=False):
        value=record.for_transport();now=self.now();grant_id=grant["grant_id"];key=grant["installation_key_id"]
        consent=restore("consent",grant_id,grant["protected_consent"])
        if not MANDATORY_SCOPES<=frozenset(consent["scopes"]): fail(403,"SCOPE_DENIED")
        if first:
            self._require_vehicle_slot(conn,grant['account_id'],key,now)
            active=certificate["active_grant_id"]
            if active and active!=grant_id: self._revoke(conn,active,now)
            device=secrets.token_hex(16);slot=certificate["slot_revision"]+1;epoch=grant["credential_epoch"]
            conn.execute("UPDATE native_v2_installations SET active_grant_id=%s,slot_revision=%s,revision=revision+1 "
                "WHERE installation_key_id=%s",(grant_id,slot,key))
            recovery=derive_capability(value["codeVerifier"],grant_id,"recovery")
            revoke=derive_capability(value["codeVerifier"],grant_id,"revoke")
            original_request=self._request(self._connection(conn,grant["connection_id"]))
            if original_request.get("revokeCommitment") is not None:
                from native_access_codec import derive_revoke_capability
                revoke=derive_revoke_capability(value["codeVerifier"],key,original_request["operationId"])
                if not grant["revoke_hash"] or not hmac.compare_digest(hash_secret("revoke",revoke),grant["revoke_hash"]):
                    fail(403,"INVALID_PROOF")
            conn.execute("UPDATE native_v2_grants SET state='TOKEN_ISSUED',device_id=%s,recovery_hash=%s,revoke_hash=%s "
                "WHERE grant_id=%s",(device,hash_secret("recovery",recovery),hash_secret("revoke",revoke),grant_id))
        else:
            device=grant["device_id"];slot=certificate["slot_revision"];epoch=grant["credential_epoch"]+1
            original=conn.execute("SELECT operation_id,protected_receipt FROM native_v2_operations "
                "WHERE grant_id=%s AND action='SESSION_EXCHANGE'",(grant_id,)).fetchone()
            if not original: fail(401,"INVALID_CREDENTIAL")
            carrier=restore("operation",original["operation_id"],original["protected_receipt"])
            capabilities=active_capabilities(carrier)
            recovery,revoke=capabilities["recoveryCapability"],capabilities["revokeCapability"]
            conn.execute("UPDATE native_v2_grants SET credential_epoch=%s WHERE grant_id=%s",(epoch,grant_id))
        if getattr(self.auth,'functional_access',None) is not None:
            from native_device_reference import register_native
            register_native(conn,dict(grant,state='TOKEN_ISSUED',device_id=device))
        access,refresh=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        receipt=dict(accessToken=access,refreshToken=refresh,tokenType="Bearer",accountId=grant["account_id"],
            grantId=grant_id,deviceId=device,installationKeyId=key,certificateSha256=certificate["certificate_sha256"],
            generation=certificate["generation"],slotRevision=slot,credentialEpoch=epoch,consentVersion=grant["consent_version"],
            scopes=consent["scopes"],expiresAt=min(now+ACCESS_SECONDS,grant["expires_at"]),grantExpiresAt=grant["expires_at"],
            recoveryCapability=recovery,revokeCapability=revoke)
        conn.execute("INSERT INTO native_v2_credentials(grant_id,device_id,access_hash,refresh_hash,certificate_sha256,"
            "generation,slot_revision,credential_epoch,access_expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(grant_id) DO UPDATE SET access_hash=EXCLUDED.access_hash,refresh_hash=EXCLUDED.refresh_hash,"
            "certificate_sha256=EXCLUDED.certificate_sha256,generation=EXCLUDED.generation,slot_revision=EXCLUDED.slot_revision,"
            "credential_epoch=EXCLUDED.credential_epoch,access_expires_at=EXCLUDED.access_expires_at",
            (grant_id,device,hash_secret("access",access),hash_secret("refresh",refresh),certificate["certificate_sha256"],
             certificate["generation"],slot,epoch,receipt["expiresAt"]))
        _,payload=self.response(action,value,"TOKEN_ISSUED","CREDENTIAL_RECEIPT",credentialReceipt=receipt)
        conn.execute("INSERT INTO native_v2_operations(operation_id,action,request_hash,grant_id,installation_key_id,"
            "credential_epoch,slot_revision,expires_at,protected_receipt) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (value["operationId"],action,digest(canonical_request(record)),grant_id,key,epoch,slot,receipt["expiresAt"],
             protect("operation",value["operationId"],payload)))
        return 200,payload

    def session(self,action,raw,fingerprint):
        record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            certificate=self._certificate(conn,fingerprint);self.lock(conn,certificate["installation_key_id"])
            certificate=self._certificate(conn,fingerprint);grant=self._grant(conn,value["grantId"],certificate)
            self._live(grant);cached=self._cached(conn,action,record,grant,certificate)
            if cached: return 200,cached
            if action=="SESSION_EXCHANGE":
                connection=self._connection(conn,grant["connection_id"]);approval=self._approval(conn,connection)
                # EXPIRED_NOT_ISSUED: the vehicle cancelled the code before taking it up.
                if (grant["state"]!="APPROVED" or not self._member(approval) or approval["exchange_expires_at"]<=self.now()
                    or connection["state"]=="EXPIRED_NOT_ISSUED"):
                    fail(410,"AUTHORIZATION_EXPIRED")
                if not hmac.compare_digest(challenge(value["codeVerifier"]),connection["code_challenge"]): fail(403,"INVALID_PROOF")
                hook=getattr(self,"_validate_exchange_snapshot",None)
                if hook:hook(conn,grant,certificate)
                return self._issue(conn,action,record,grant,certificate,first=True)
            if grant["state"]!="TOKEN_ISSUED" or value["deviceId"]!=grant["device_id"] or certificate["active_grant_id"]!=grant["grant_id"]:
                fail(401,"INVALID_CREDENTIAL")
            credentials=conn.execute("SELECT * FROM native_v2_credentials WHERE grant_id=%s",(grant["grant_id"],)).fetchone()
            purpose,secret=("recovery",value["recoveryCapability"]) if action=="SESSION_RECOVER" else ("refresh",value["refreshToken"])
            expected=grant["recovery_hash"] if purpose=="recovery" else (credentials["refresh_hash"] if credentials else None)
            if not expected or not hmac.compare_digest(hash_secret(purpose,secret),expected): fail(401,"INVALID_CREDENTIAL")
            return self._issue(conn,action,record,grant,certificate)

    def revoke(self,device_id,raw,fingerprint):
        action="SESSION_REVOKE";record=self.decode(action,raw);value=record.for_transport()
        with self.db() as conn:
            certificate=self._certificate(conn,fingerprint);self.lock(conn,certificate["installation_key_id"])
            grant=self._grant(conn,value["grantId"],certificate)
            if grant["device_id"]!=device_id or not grant["revoke_hash"] or not hmac.compare_digest(
                grant["revoke_hash"],hash_secret("revoke",value["revokeCapability"])): fail(401,"INVALID_CREDENTIAL")
            if grant["expires_at"]<=self.now():
                self._revoke(conn,grant["grant_id"],self.now())
                return self.response(action,value,"REVOKED","TERMINAL",deviceId=device_id,expiredAt=grant["expires_at"])
            self._revoke(conn,grant["grant_id"],self.now());grant=self._grant(conn,value["grantId"],certificate)
            return self.response(action,value,"REVOKED","TERMINAL",deviceId=device_id,revokedAt=grant["revoked_at"])

    def authenticate(self,request,*,enforce_route=True,connection=None):
        if not self.enabled:return None
        fingerprint=self.auth.native_certificate(request);header=request.headers.get("authorization","")
        if re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}",header) is None: fail(401,"INVALID_CREDENTIAL")
        with (nullcontext(connection) if connection is not None else self.db()) as conn:
            row=conn.execute("SELECT * FROM native_v2_credentials WHERE access_hash=%s",
                (hash_secret("access",header[7:]),)).fetchone()
            if not row: fail(401,"INVALID_CREDENTIAL")
            if not native_query_allowed(request) or any(x in request.headers for x in ('origin','cookie')):fail(400,'INVALID_REQUEST')
            certificate=self._certificate(conn,fingerprint);grant=self._grant(conn,row["grant_id"],certificate);identity=self._live(grant,connection=conn if connection is not None else None)
            if (grant["state"]!="TOKEN_ISSUED" or certificate["active_grant_id"]!=grant["grant_id"]
                or row["certificate_sha256"]!=fingerprint or row["generation"]!=certificate["current_generation"]
                or row["credential_epoch"]!=grant["credential_epoch"] or row["slot_revision"]!=certificate["slot_revision"]
                or row["access_expires_at"]<=self.now()): fail(401,"INVALID_CREDENTIAL")
            consent=restore("consent",grant["grant_id"],grant["protected_consent"])
            try: valid_grant_scopes(frozenset(consent["scopes"]))
            except ValueError: fail(403,"SCOPE_DENIED")
            functional={}
            if enforce_route:
                try: authorize_route(AUTHORIZATION_VERSION,request.method,request.url.path,frozenset(consent["scopes"]))
                except ValueError as error:
                    from native_functional_policy import is_functional_route,authorize as authorize_function,FunctionalError
                    service=getattr(self.auth,'functional_access',None)
                    if str(error)!="ROUTE_NOT_FOUND" or service is None or not service.enabled or not is_functional_route(request.method,request.url.path):
                        fail(404 if str(error)=="ROUTE_NOT_FOUND" else 403,str(error))
                    try:
                        snapshot=service.snapshot(conn,grant)
                        authorize_function(request.method,request.url.path,frozenset(snapshot['approvedPurposes']))
                    except FunctionalError as denied:fail(denied.status,denied.code)
                    functional=dict(functionalRevision=snapshot['revision'],approvedPurposes=snapshot['approvedPurposes'])
            return NativePrincipal(identity,deviceId=grant["device_id"],authorizationVersion=1,grantId=grant["grant_id"],
                scopes=consent["scopes"],keepSignedIn=consent["keepSignedIn"],consentVersion=grant["consent_version"],
                grantExpiresAt=grant["expires_at"],credentialEpoch=grant["credential_epoch"],slotRevision=certificate["slot_revision"],**functional)

    def revoke_authenticated(self,identity):
        with self.db() as conn:
            initial=conn.execute('SELECT installation_key_id FROM native_v2_grants WHERE grant_id=%s',
                (identity['grantId'],)).fetchone()
            if not initial: fail(401,'INVALID_CREDENTIAL')
            self.lock(conn,initial['installation_key_id'])
            grant=conn.execute('SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE',
                (identity['grantId'],)).fetchone()
            if (grant['account_id']!=identity['id'] or grant['device_id']!=identity['deviceId']
                or grant['credential_epoch']!=identity['credentialEpoch']): fail(401,'INVALID_CREDENTIAL')
            self._revoke(conn,grant['grant_id'],self.now())
        return dict(status='revoked')

    def issuer_router(self):
        router=APIRouter()
        async def execute(request,function,*args):
            try:
                result=await run_in_threadpool(function,*args,await read_body(request))
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error: return error_response(error)
            except HTTPException as error: return http_error_response(error)
        @router.post("/v1/connections")
        async def begin(request:Request): return await execute(request,self.begin)
        @router.post("/v1/connections/recover")
        async def recover(request:Request): return await execute(request,self.recover_connection)
        @router.post("/v1/connections/cancel")
        async def cancel(request:Request): return await execute(request,self.cancel)
        @router.post("/v1/connections/{connection_id}/claim")
        async def claim(connection_id:str,request:Request): return await execute(request,self.claim,connection_id)
        return router

    def browser_router(self):
        router=APIRouter()
        @router.get("/v1/connections/{user_code}")
        def detail(user_code:str,request:Request):
            try: return self.detail(user_code,self.auth.browser(request))
            except NativeAuthorizationError as error: return error_response(error)
            except HTTPException as error: return http_error_response(error)
        async def decide(user_code,request,deny):
            try:
                owner=await run_in_threadpool(self.auth.browser,request,mutate=True)
                return await run_in_threadpool(self.approve,user_code,await read_body(request),owner,deny=deny)
            except NativeAuthorizationError as error: return error_response(error)
            except HTTPException as error: return http_error_response(error)
        @router.post("/v1/connections/{user_code}")
        async def approve(user_code:str,request:Request): return await decide(user_code,request,False)
        @router.delete("/v1/connections/{user_code}")
        async def deny(user_code:str,request:Request): return await decide(user_code,request,True)
        from iphone_vehicles import register_iphone_vehicle_routes
        register_iphone_vehicle_routes(router,self)
        return router

    def native_router(self):
        router=APIRouter()
        async def execute(request,action):
            try:
                fingerprint=await run_in_threadpool(self.auth.native_certificate,request)
                result=await run_in_threadpool(self.session,action,await read_body(request),fingerprint)
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error: return error_response(error)
            except HTTPException as error: return http_error_response(error)
        @router.post("/v1/device-authorizations")
        async def authorize(request:Request):
            try:
                fingerprint=await run_in_threadpool(self.auth.native_certificate,request)
                result=await run_in_threadpool(self.account_authorize,await read_body(request),fingerprint)
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error: return error_response(error)
            except HTTPException as error: return http_error_response(error)
        @router.post("/v1/device-sessions/exchange")
        async def exchange(request:Request): return await execute(request,"SESSION_EXCHANGE")
        @router.post("/v1/device-sessions/recover")
        async def recover(request:Request): return await execute(request,"SESSION_RECOVER")
        @router.post("/v1/device-sessions/refresh")
        async def refresh(request:Request): return await execute(request,"SESSION_REFRESH")
        @router.post("/v1/device-sessions/{device_id}/revoke")
        async def revoke(device_id:str,request:Request):
            try:
                fingerprint=await run_in_threadpool(self.auth.native_certificate,request)
                result=await run_in_threadpool(self.revoke,device_id,await read_body(request),fingerprint)
                return JSONResponse(result[1],status_code=result[0])
            except NativeAuthorizationError as error: return error_response(error)
            except HTTPException as error: return http_error_response(error)
        return router
