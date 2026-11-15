"""Read-only internal bridge/CA status proof, synthetic HTTP peers and secrets."""
import json,secrets,ssl,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import Request
import native_access_issuer_status as bridge
from native_authorization import NativeAuthorizationError
from enrollment_crypto import CloudflareIssuer,EnrollmentError,IssuanceUncertain,digest,public_bytes,validate_csr
from test_enrollment import SyntheticIssuer,make_csr,CA_ID

class IssuerStatusTests(unittest.TestCase):
    def setUp(self):
        self.auth=SimpleNamespace(secret=b"synthetic-private-server-secret"*2,native_relay_key=secrets.token_bytes(32))
        self.key,self.csr=make_csr();self.key_id=digest(public_bytes(validate_csr(self.csr).public_key()))
        self.synthetic=SyntheticIssuer()
        self.receipt=self.synthetic.response(validate_csr(self.csr))
        self.fp=self.receipt["fingerprint_sha256"]
        self.provenance=dict(certificateId=self.receipt["id"],issuerId=CA_ID)
        self.value=dict(version=1,operationId="a"*32,installationKeyId=self.key_id,certificateSha256=self.fp,
            certificateId=self.receipt["id"],issuerId=CA_ID,timestamp=int(time.time()),nonce=secrets.token_urlsafe(32))

    def test_01_bridge_requires_signed_request_response_exact_nonce_and_host(self):
        issuer=SimpleNamespace(require_active_certificate=lambda *a:True)
        signature=bridge.mac(self.auth,b"request",self.value)
        response,signed=bridge.answer(self.auth,issuer,bridge.canonical(self.value),signature)
        self.assertEqual(response["result"],"ACTIVE")
        with self.assertRaises(NativeAuthorizationError):bridge.answer(self.auth,issuer,bridge.canonical(self.value),"x"*43)
        wrong=dict(self.value,certificateSha256="f"*64)
        with self.assertRaises(NativeAuthorizationError):bridge.answer(self.auth,issuer,bridge.canonical(wrong),signature)
        old=dict(self.value,timestamp=int(time.time())-11)
        with self.assertRaises(NativeAuthorizationError):bridge.answer(self.auth,issuer,bridge.canonical(old),bridge.mac(self.auth,b"request",old))
        request=Request(dict(type="http",method="POST",scheme="http",server=("127.0.0.1",80),
            path=bridge.PATH,raw_path=bridge.PATH.encode(),query_string=b"",client=("127.0.0.1",123),
            headers=[(b"host",b"enroll-wegoh.devforest.io")]))
        with self.assertRaises(NativeAuthorizationError):bridge.internal_route_boundary(request)

    def test_02_main_rejects_forged_signed_response_and_unknown_is_not_revoked(self):
        auth=self.auth;issuer=SimpleNamespace(require_active_certificate=lambda *a:True)
        class Connection:
            tamper=False
            def __init__(self,host,port,timeout):
                self.assertion=(host,port,timeout)
                if (host,port)!=("127.0.0.1",18083):raise AssertionError("not fixed loopback")
            def request(self,method,path,body,headers):
                self.response,self.signature=bridge.answer(auth,issuer,body,headers["X-WegoH-Issuer-Proof"])
            def getresponse(self):
                value=dict(self.response)
                if self.tamper:value["result"]="REVOKED"
                return SimpleNamespace(status=200,read=lambda n:bridge.canonical(value),
                    getheader=lambda *a:self.signature)
            def close(self):pass
        with patch.object(bridge.http.client,"HTTPConnection",Connection):
            self.assertTrue(bridge.query_status(auth,self.provenance,self.key_id,self.fp,"a"*32))
            Connection.tamper=True
            with self.assertRaises(NativeAuthorizationError) as error:bridge.query_status(auth,self.provenance,self.key_id,self.fp,"a"*32)
            self.assertEqual(error.exception.code,"SERVICE_UNAVAILABLE")
        def invalid(*a):raise EnrollmentError("INVALID_ISSUANCE_RECEIPT")
        response,_=bridge.answer(auth,SimpleNamespace(require_active_certificate=invalid),bridge.canonical(self.value),
            bridge.mac(auth,b"request",self.value))
        self.assertEqual(response["result"],"UNAVAILABLE")

    def test_03_exact_cloudflare_get_checks_status_binding_tls13_and_never_posts(self):
        state={"status":"active","http":200};calls=[];receipt=self.receipt
        class Connection:
            def __init__(self,host,timeout,context):
                if host!="api.cloudflare.com" or context.minimum_version!=ssl.TLSVersion.TLSv1_3 or context.maximum_version!=ssl.TLSVersion.TLSv1_3:
                    raise AssertionError("TLS1.3 exact trust required")
            def request(self,method,path,headers):calls.append((method,path))
            def getresponse(self):
                value=dict(receipt,status=state["status"])
                return SimpleNamespace(status=state["http"],read=lambda n:json.dumps(dict(success=True,result=value)).encode())
            def close(self):pass
        issuer=CloudflareIssuer.__new__(CloudflareIssuer);issuer.zone="a"*32;issuer.ca_id=CA_ID;issuer._token=lambda:"synthetic-token-only"
        with patch("enrollment_crypto.http.client.HTTPSConnection",Connection):
            self.assertTrue(issuer.require_active_certificate(self.provenance,self.key_id,self.fp))
            for status in ("revoked","pending_revocation","pending_reactivation"):
                state["status"]=status
                with self.subTest(status=status),self.assertRaises(EnrollmentError) as error:
                    issuer.require_active_certificate(self.provenance,self.key_id,self.fp)
                self.assertEqual(str(error.exception),"INSTALLATION_REVOKED")
            state["status"]="unknown"
            with self.assertRaises(IssuanceUncertain):issuer.require_active_certificate(self.provenance,self.key_id,self.fp)
            state["http"]=403
            with self.assertRaises(IssuanceUncertain):issuer.require_active_certificate(self.provenance,self.key_id,self.fp)
        self.assertTrue(all(method=="GET" for method,path in calls))
        self.assertTrue(all(path.endswith("/"+self.receipt["id"]) for method,path in calls))


    def test_04_uncertain_issuance_reconcile_is_bounded_authenticated_get_only(self):
        state={"http":200,"pages":1,"items":[self.receipt]};calls=[];receipt=self.receipt
        class Connection:
            def __init__(self,host,timeout,context):
                if host!="api.cloudflare.com" or context.minimum_version!=ssl.TLSVersion.TLSv1_3 or context.maximum_version!=ssl.TLSVersion.TLSv1_3:
                    raise AssertionError("TLS1.3 exact")
            def request(self,method,path,headers):
                calls.append((method,path))
                if not headers.get("Authorization","").startswith("Bearer "):raise AssertionError("authenticated CA GET")
            def getresponse(self):
                return SimpleNamespace(status=state["http"],read=lambda n:json.dumps(dict(success=True,
                    result=state["items"],result_info=dict(total_pages=state["pages"],page=1))).encode())
            def close(self):pass
        issuer=CloudflareIssuer.__new__(CloudflareIssuer);issuer.zone="a"*32;issuer.ca_id=CA_ID;issuer._token=lambda:"synthetic-token-only"
        with patch("enrollment_crypto.http.client.HTTPSConnection",Connection):
            found=issuer.reconcile(self.csr,())
            self.assertEqual(found["certificateSha256"],self.fp)
            self.assertIsNone(issuer.reconcile(self.csr,{self.fp}))
            state["items"]=[receipt,self.synthetic.response(validate_csr(self.csr))]
            with self.assertRaises(IssuanceUncertain):issuer.reconcile(self.csr,())
            state["items"]=[];state["pages"]=6
            with self.assertRaises(IssuanceUncertain):issuer.reconcile(self.csr,())
            state["http"]=403
            with self.assertRaises(IssuanceUncertain):issuer.reconcile(self.csr,())
        self.assertTrue(all(method=="GET" for method,path in calls))
        self.assertTrue(all("?status=active&per_page=50&page=1" in path for method,path in calls))

if __name__=="__main__":unittest.main()

