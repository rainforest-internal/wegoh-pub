"""Owned temporary PostgreSQL + real TLS1.3 bootstrap / HTTP browser approval.

Synthetic CA/Access JWT only. No Cloudflare request, production credentials,
production DB, user data, or platform state is used or changed by these tests.
"""
import base64
import datetime as dt
import hashlib
import http.client
import importlib.util
import json
import os
import secrets
import ssl
import threading
import time
import unittest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from enrollment import EnrollmentService
from enrollment_app import apply_schema, create_app
from private_records import VisitCipher
from enrollment_crypto import (CloudflareIssuer, EnrollmentError, IssuanceUncertain,
    challenge, proof_message, validate_csr, validate_issued)
import test_team_auth as fixture

CA_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def make_csr(key=None, cn=None, extensions=False):
    key = key or rsa.generate_private_key(public_exponent=65537, key_size=2048)
    builder = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn or 'WegoH-' + secrets.token_hex(16))]))
    if extensions:
        builder = builder.add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    return key, builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode('ascii')


class SyntheticIssuer:
    def __init__(self):
        self.calls = 0
        self.crash = False
        self.after_issue = None
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Owned synthetic issuer')])

    def response(self, csr):
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(csr.subject).issuer_name(self.name)
            .public_key(csr.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(seconds=30)).not_valid_after(now + dt.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .sign(self.key, hashes.SHA256()))
        return dict(id='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', status='active',
            certificate_authority=dict(id=CA_ID), certificate=cert.public_bytes(serialization.Encoding.PEM).decode(),
            fingerprint_sha256=cert.fingerprint(hashes.SHA256()).hex())

    def issue(self, csr_pem):
        self.calls += 1
        if self.crash:
            raise IssuanceUncertain('ISSUANCE_UNCERTAIN')
        csr = validate_csr(csr_pem)
        value = validate_issued(csr, self.response(csr), CA_ID)
        if self.after_issue:
            self.after_issue()
        return value


class EnrollmentCryptoTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='wegoh-enrollment-crypto-')
        self.addCleanup(self.temporary.cleanup)
        self.state=Path(self.temporary.name)
        self.issuer=SyntheticIssuer()

    def test_05_csr_and_issuance_receipt_adversarial_contracts(self):
        key,pem=make_csr(); csr=validate_csr(pem)
        for bad in [pem+pem,pem+'PRIVATE KEY',make_csr(cn='email@example.invalid')[1],make_csr(extensions=True)[1],
            make_csr(rsa.generate_private_key(public_exponent=65537,key_size=3072))[1]]:
            with self.assertRaises(EnrollmentError): validate_csr(bad)
        good=self.issuer.response(csr); validate_issued(csr,good,CA_ID)
        for bad in [dict(good,status='revoked'),dict(good,fingerprint_sha256='0'*64),
            dict(good,certificate_authority=dict(id='cccccccc-cccc-cccc-cccc-cccccccccccc')),
            dict(good,certificate=good['certificate']+good['certificate'])]:
            with self.assertRaises(EnrollmentError): validate_issued(csr,bad,CA_ID)
        with self.assertRaises(EnrollmentError): validate_issued(validate_csr(make_csr()[1]),good,CA_ID)
        expired=dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=2)
        with self.assertRaises(EnrollmentError): validate_issued(csr,good,CA_ID,now=expired)

    def test_06_cloudflare_transport_fixed_host_token_file_no_redirect_or_retry(self):
        token_file=self.state/'synthetic-cf-token'; token_file.write_text('synthetic-only-'+'x'*32); token_file.chmod(0o600)
        issuer=CloudflareIssuer('a'*32,CA_ID,token_file); _,pem=make_csr()
        calls=[]
        class Response:
            status=302
            def read(self,n): return b'{}'
        class Connection:
            def __init__(self,host,**kw):
                calls.append(('connect',host,kw['context'].minimum_version,kw['context'].maximum_version))
            def request(self,method,path,body,headers):
                calls.append(('request',method,path,json.loads(body)['validity_days']))
            def getresponse(self): return Response()
            def close(self): calls.append(('close',))
        with patch('enrollment_crypto.http.client.HTTPSConnection',Connection):
            with self.assertRaises(IssuanceUncertain): issuer.issue(pem)
        self.assertEqual(calls[0],('connect','api.cloudflare.com',ssl.TLSVersion.TLSv1_3,ssl.TLSVersion.TLSv1_3))
        self.assertEqual(calls[1],('request','POST','/client/v4/zones/'+'a'*32+'/client_certificates',90))
        self.assertEqual(len([c for c in calls if c[0]=='request']),1)
        token_file.chmod(0o400); CloudflareIssuer('a'*32,CA_ID,token_file)
        for mode in (0o644,0o700,0o200):
            token_file.chmod(mode)
            with self.assertRaises(EnrollmentError): CloudflareIssuer('a'*32,CA_ID,token_file)

    def test_07_operator_metadata_is_read_only_bounded_and_redacted(self):
        from enrollment_operator import discover_ca
        token_file=self.state/'synthetic-operator-token'; token_file.write_text('synthetic-only-'+'x'*32); token_file.chmod(0o600)
        calls=[]
        payload=dict(success=True,result=[dict(status='active',certificate_authority=dict(id=CA_ID),
            certificate='DO_NOT_PRINT_PEM',csr='DO_NOT_PRINT_CSR',common_name='DO_NOT_PRINT_NAME')],
            result_info=dict(total_pages=1))
        class Response:
            status=200
            def read(self,n): return json.dumps(payload).encode()
        class Connection:
            def __init__(self,host,**kw): calls.append(('host',host))
            def request(self,method,path,headers): calls.append((method,path))
            def getresponse(self): return Response()
            def close(self): pass
        with patch('enrollment_operator.http.client.HTTPSConnection',Connection):
            result=discover_ca('a'*32,token_file)
            self.assertEqual(result,dict(issuerId=CA_ID,activeCertificatesMatched=1))
            self.assertNotIn('DO_NOT_PRINT',json.dumps(result)); self.assertEqual(calls[0],('host','api.cloudflare.com'))
            self.assertEqual(calls[1][0],'GET'); self.assertIn('status=active&per_page=50&page=1',calls[1][1])
            payload['result'].append(dict(status='active',certificate_authority=dict(id='cccccccc-cccc-cccc-cccc-cccccccccccc')))
            with self.assertRaises(EnrollmentError): discover_ca('a'*32,token_file)
            payload['result_info']['total_pages']=11
            with self.assertRaises(EnrollmentError): discover_ca('a'*32,token_file)

class EnrollmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        cls.addClassCleanup(fixture.TeamTests.tearDownClass)
        cls.api=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        cls.auth,cls.state=fixture.TeamTests.module.TEAM_AUTH,fixture.TeamTests.state
        cls.issuer=SyntheticIssuer()
        origin=fixture.TeamTests.module.TEAM_NATIVE_AUTHORIZATION.origin
        environment=patch.dict(os.environ,{'WEGOH_ENROLLMENT_ORIGIN':origin})
        environment.start();cls.addClassCleanup(environment.stop)
        cls.bootstrap=create_app(cls.auth,cls.issuer)
        cls.service=cls.bootstrap.state.native_authorization
        cls.host=origin.split('://',1)[1]
        cls.tls_port=fixture.free_port()
        now=dt.datetime.now(dt.timezone.utc)
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Owned current bootstrap TLS')])
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-dt.timedelta(minutes=1))
            .not_valid_after(now+dt.timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(__import__('ipaddress').ip_address('127.0.0.1'))]),critical=False)
            .sign(key,hashes.SHA256()))
        cls.certfile,cls.keyfile=cls.state/'enrollment-tls.pem',cls.state/'enrollment-tls.key'
        for path,raw in [(cls.certfile,cert.public_bytes(serialization.Encoding.PEM)),
            (cls.keyfile,key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))]:
            path.write_bytes(raw);path.chmod(0o600)
        config=uvicorn.Config(cls.bootstrap,host='127.0.0.1',port=cls.tls_port,proxy_headers=False,
            access_log=False,log_level='critical',ssl_certfile=str(cls.certfile),ssl_keyfile=str(cls.keyfile))
        config.load();config.ssl.minimum_version=config.ssl.maximum_version=ssl.TLSVersion.TLSv1_3
        cls.server=uvicorn.Server(config);cls.thread=threading.Thread(target=cls.server.run,daemon=True)
        cls.thread.start();cls.addClassCleanup(cls.stop)
        deadline=time.monotonic()+5
        while not cls.server.started and time.monotonic()<deadline:time.sleep(.02)
        if not cls.server.started:raise RuntimeError('Owned current bootstrap TLS fixture failed to start')
        cls.context=ssl.create_default_context(cafile=str(cls.certfile))
        cls.context.minimum_version=cls.context.maximum_version=ssl.TLSVersion.TLSv1_3

    @classmethod
    def stop(cls):
        cls.server.should_exit=True;cls.thread.join(5)
        if cls.thread.is_alive():raise RuntimeError('Owned bootstrap fixture failed to stop')

    def setUp(self):
        self.api.setUp()
        self.session=self.api.login()
        self.issuer.calls=0

    def snapshot(self):
        with psycopg.connect(self.auth.dsn) as conn:
            return {table:conn.execute('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text').fetchall()
                    for table in ('team_accounts','vehicle_enrollments','native_v2_connections','native_v2_grants','native_v2_certificates')}

    def call(self,path,data=None,method='POST',extra=None,host=None):
        headers={'Host':host or self.host,'Content-Type':'application/json'}
        headers.update(extra or {})
        conn=http.client.HTTPSConnection('127.0.0.1',self.tls_port,timeout=5,context=self.context)
        conn.connect();self.assertEqual(conn.sock.version(),'TLSv1.3')
        conn.request(method,path,json.dumps(data).encode(),headers)
        response=conn.getresponse();status=response.status;value=json.loads(response.read());conn.close()
        return status,value

    def assert_retired(self,path,method='POST',body=None,extra=None):
        before=self.snapshot()
        status,value=self.call(path,body,method,extra)
        self.assertEqual(status,404,value)
        self.assertEqual(self.issuer.calls,0)
        self.assertEqual(self.snapshot(),before)

    def test_retired_bootstrap_paths_never_issue_or_write_even_with_valid_csr(self):
        _,csr=make_csr()
        body=dict(name='Owned retired request',csrPem=csr,codeChallenge=challenge(secrets.token_urlsafe(32)))
        for path in ('/v1/enrollments','/v1/enrollments/'+'a'*32+'/claim','/v1/enrollments/'+'a'*32+'/cancel'):
            with self.subTest(path=path):self.assert_retired(path,body=body)

    def test_retired_requests_do_not_expand_with_credentials_headers_or_queries(self):
        for extra in ({},{'Origin':fixture.WEB},{'Cookie':'untrusted=value'},{'Authorization':'Bearer synthetic-forbidden'}):
            with self.subTest(headers=tuple(extra)):self.assert_retired('/v1/enrollments',extra=extra)
        self.assert_retired('/v1/enrollments?proof=synthetic-forbidden')
        self.assert_retired('/v1/enrollments','GET')
        self.assert_retired('/v1/enrollments','DELETE')

    def test_browser_approval_and_legacy_pairing_token_paths_remain_closed(self):
        before=self.snapshot()
        for path in ('/v1/enrollments/ABCDEFGH/approve','/v1/devices/pairings','/v1/devices/token','/v1/devices/token/refresh'):
            with self.subTest(path=path):
                self.assertEqual(self.api.call(path,{},'POST',session=self.session)[0],404)
                self.assertEqual(self.api.native(path,{},'POST')[0],404)
        self.assertEqual(self.issuer.calls,0)
        self.assertEqual(self.snapshot(),before)

    def test_current_runtime_does_not_mount_retired_routes_or_fall_back_on_invalid_input(self):
        from native_access_policy import is_retired_authorization_path
        routes=self.service.issuer_router().routes
        self.assertFalse(any(is_retired_authorization_path(getattr(route,'path','')) for route in routes))
        before=self.snapshot()
        self.assertEqual(self.call('/v1/connections',{})[0],400)
        self.assertEqual(self.issuer.calls,0)
        self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main()
