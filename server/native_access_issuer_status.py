"""Read-only issuer status bridge; main never receives a Cloudflare credential."""
import base64,hashlib,hmac,http.client,json,re,secrets,time
from urllib.parse import urlsplit
from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from enrollment_crypto import EnrollmentError,IssuanceUncertain
from native_access_codec import decode_json
from native_authorization import NativeAuthorizationError,fail,read_body

PATH="/internal/native-certificate-status"
REQUEST_FIELDS=frozenset(("version","operationId","installationKeyId","certificateSha256","certificateId","issuerId","timestamp","nonce"))
RESPONSE_FIELDS=frozenset(("version","requestSha256","checkedAt","result"))
B64=re.compile(r"[A-Za-z0-9_-]{43}")
CF_ID=re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
RESULTS=frozenset(("ACTIVE","REVOKED","UNAVAILABLE"))

def canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode("ascii")
def mac(auth,purpose,value):
    key=getattr(auth,"native_relay_key",None)
    if type(key) is not bytes or len(key)!=32 or purpose not in (b"request",b"response"):
        fail(503,"SERVICE_UNAVAILABLE")
    return base64.urlsafe_b64encode(hmac.new(key,b"WegoH issuer status "+purpose+b" v1\n"+canonical(value),hashlib.sha256).digest()).rstrip(b"=").decode("ascii")

def internal_route_boundary(request):
    if (request.url.path!=PATH or request.method!="POST" or request.url.hostname!="127.0.0.1"
        or request.url.port not in (None,80) or not request.client or request.client.host not in ("127.0.0.1","::1")
        or request.url.query or any(h in request.headers for h in ("origin","cookie","authorization"))):
        fail(404,"ROUTE_NOT_FOUND")

def validate_request(value):
    if type(value) is not dict or set(value)!=REQUEST_FIELDS or type(value["version"]) is not int or value["version"]!=1:
        fail(404,"ROUTE_NOT_FOUND")
    for name,length in (("operationId",32),("installationKeyId",64),("certificateSha256",64)):
        if type(value[name]) is not str or re.fullmatch("[a-f0-9]{"+str(length)+"}",value[name]) is None:fail(404,"ROUTE_NOT_FOUND")
    if (type(value["timestamp"]) is not int or abs(int(time.time())-value["timestamp"])>10
        or type(value["nonce"]) is not str or B64.fullmatch(value["nonce"]) is None
        or any(type(value[n]) is not str or CF_ID.fullmatch(value[n]) is None for n in ("certificateId","issuerId"))):
        fail(404,"ROUTE_NOT_FOUND")
    return value

def answer(auth,issuer,raw,signature):
    value=validate_request(decode_json(raw,maximum_bytes=4096))
    if type(signature) is not str or B64.fullmatch(signature) is None or not hmac.compare_digest(mac(auth,b"request",value),signature):
        fail(404,"ROUTE_NOT_FOUND")
    try:
        issuer.require_active_certificate(dict(certificateId=value["certificateId"],issuerId=value["issuerId"]),
            value["installationKeyId"],value["certificateSha256"])
        result="ACTIVE"
    except EnrollmentError as error:result="REVOKED" if str(error)=="INSTALLATION_REVOKED" else "UNAVAILABLE"
    except IssuanceUncertain:result="UNAVAILABLE"
    response=dict(version=1,requestSha256=hashlib.sha256(canonical(value)).hexdigest(),checkedAt=int(time.time()),result=result)
    return response,mac(auth,b"response",response)

def query_status(auth,provenance,key,fingerprint,operation_id):
    value=dict(version=1,operationId=operation_id,installationKeyId=key,certificateSha256=fingerprint,
        certificateId=provenance["certificateId"],issuerId=provenance["issuerId"],
        timestamp=int(time.time()),nonce=secrets.token_urlsafe(32))
    validate_request(value)
    connection=http.client.HTTPConnection("127.0.0.1",18083,timeout=20)
    try:
        connection.request("POST",PATH,body=canonical(value),headers={"Host":"127.0.0.1","Content-Type":"application/json",
            "X-WegoH-Issuer-Proof":mac(auth,b"request",value)})
        raw_response=connection.getresponse();raw=raw_response.read(4097)
        if raw_response.status!=200 or len(raw)>4096:fail(503,"SERVICE_UNAVAILABLE")
        response=decode_json(raw,maximum_bytes=4096)
        signature=raw_response.getheader("X-WegoH-Issuer-Proof","")
        if (set(response)!=RESPONSE_FIELDS or type(response["version"]) is not int or response["version"]!=1
            or type(response["checkedAt"]) is not int or abs(int(time.time())-response["checkedAt"])>10
            or response["requestSha256"]!=hashlib.sha256(canonical(value)).hexdigest()
            or type(response["result"]) is not str or response["result"] not in RESULTS
            or B64.fullmatch(signature) is None or not hmac.compare_digest(signature,mac(auth,b"response",response))):
            fail(503,"SERVICE_UNAVAILABLE")
        if response["result"]=="REVOKED":fail(403,"INSTALLATION_REVOKED")
        if response["result"]!="ACTIVE":fail(503,"SERVICE_UNAVAILABLE")
        return True
    except (OSError,ValueError,KeyError):fail(503,"SERVICE_UNAVAILABLE")
    finally:connection.close()

def router(auth,issuer):
    routes=APIRouter()
    @routes.post(PATH,include_in_schema=False)
    async def status(request:Request):
        try:
            internal_route_boundary(request)
            value,signature=await run_in_threadpool(answer,auth,issuer,await read_body(request),
                request.headers.get("X-WegoH-Issuer-Proof",""))
            return JSONResponse(value,headers={"X-WegoH-Issuer-Proof":signature})
        except (NativeAuthorizationError,ValueError):
            # Internal failure never exposes validation/CF details or credentials.
            return JSONResponse({"status":"unavailable"},status_code=404)
    return routes



def require_active_status(auth,issuer,provenance,key,fingerprint,operation_id):
    if issuer is None:return query_status(auth,provenance,key,fingerprint,operation_id)
    try:return issuer.require_active_certificate(provenance,key,fingerprint)
    except EnrollmentError as error:
        fail(403,"INSTALLATION_REVOKED") if str(error)=="INSTALLATION_REVOKED" else fail(503,"SERVICE_UNAVAILABLE")
    except (IssuanceUncertain,AttributeError):fail(503,"SERVICE_UNAVAILABLE")
