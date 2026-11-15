"""Owned HTTP/PG cutoff and additive mapping checks; no production/CF mutation."""
import ast,base64,importlib.util,json,math,os,secrets,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import psycopg,uvicorn
from fastapi import HTTPException
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import test_team_auth as fixture
from test_enrollment import SyntheticIssuer,make_csr,CA_ID
from enrollment_app import create_app
from enrollment_crypto import challenge,proof_message,validate_csr
from private_records import VisitCipher
from native_legacy_transition import LegacyTransition,legacy_certificate,CUTOFF,SUNSET
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('owned_transition_apply',ROOT/'server/ops/live/native_transition_apply.py')
apply=importlib.util.module_from_spec(spec);spec.loader.exec_module(apply)

class LegacyPolicyTests(unittest.TestCase):
    def test_exact_timestamp_boundary_missing_policy_and_no_root_app_import(self):
        self.assertIsNone(LegacyTransition.environment({}))
        for value in ({},{CUTOFF:'true',SUNSET:'200'},{CUTOFF:'201',SUNSET:'200'},{CUTOFF:'0100',SUNSET:'200'}):
            with self.assertRaises(RuntimeError):LegacyTransition.environment(value,required=True)
        policy=LegacyTransition.environment({CUTOFF:'100',SUNSET:'200'})
        self.assertTrue(policy.creation_open(99.999));self.assertFalse(policy.creation_open(100))
        with self.assertRaises(HTTPException) as failure:policy.require_creation(100)
        self.assertEqual(failure.exception.status_code,410);self.assertNotIn('Link',failure.exception.headers)
        tree=ast.parse((ROOT/'server/ops/live/native_transition.py').read_text())
        imports={node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module}
        imports|={alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
        self.assertTrue(imports<={'argparse','hashlib','http','json','os','re','secrets','shlex','ssl','stat','subprocess','sys','pathlib'})
        source=(ROOT/'server/ops/live/native_transition.py').read_text()
        self.assertIn('User=wegohdemo',source);self.assertIn('LoadCredential=visit.key:',source)
        self.assertNotIn('LoadCredential=cf-api',source);self.assertNotIn('WEGOH_API_KEY',source)

    def test_cf_leaf_without_ku_keeps_eku_and_present_ku_restrictions(self):
        import datetime as dt
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.x509.oid import ExtendedKeyUsageOID
        from native_access_legacy import NativeAccessLegacy
        from native_authorization import NativeAuthorizationError
        issuer=SyntheticIssuer();_,csr_pem=make_csr();csr=x509.load_pem_x509_csr(csr_pem.encode())
        class ReachedMapping(Exception):pass
        class OwnedImporter(NativeAccessLegacy):
            def now(self):return time.time()
            def db(self):raise ReachedMapping()  # No DB access; only certificate boundary is exercised.
        cases=[('absent',None,True,False,True),('valid',(True,False,False),True,False,True),
            ('no-signature',(False,False,False),True,False,False),('cert-sign',(True,True,False),True,False,False),
            ('crl-sign',(True,False,True),True,False,False),('no-eku',None,None,False,False),
            ('server-only',None,False,False,False),('ca',None,True,True,False)]
        for label,usage,client_auth,ca,accepted in cases:
            with self.subTest(label=label):
                now=dt.datetime.now(dt.timezone.utc)
                builder=(x509.CertificateBuilder().subject_name(csr.subject).issuer_name(issuer.name)
                    .public_key(csr.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now-dt.timedelta(seconds=30)).not_valid_after(now+dt.timedelta(hours=1))
                    .add_extension(x509.BasicConstraints(ca=ca,path_length=None),critical=True))
                if usage is not None:
                    signature,cert_sign,crl_sign=usage
                    builder=builder.add_extension(x509.KeyUsage(digital_signature=signature,content_commitment=False,
                        key_encipherment=False,data_encipherment=False,key_agreement=False,key_cert_sign=cert_sign,
                        crl_sign=crl_sign,encipher_only=False,decipher_only=False),critical=True)
                if client_auth is not None:
                    builder=builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH if client_auth else ExtendedKeyUsageOID.SERVER_AUTH]),critical=False)
                cert=builder.sign(issuer.key,hashes.SHA256());pem=cert.public_bytes(serialization.Encoding.PEM).decode()
                fingerprint=cert.fingerprint(hashes.SHA256()).hex()
                if accepted:
                    self.assertEqual(legacy_certificate(pem)['certificateSha256'],fingerprint)
                    with self.assertRaises(ReachedMapping):OwnedImporter()._import_mapped_certificate({'certificatePem':pem},fingerprint)
                else:
                    with self.assertRaises(RuntimeError):legacy_certificate(pem)
                    with self.assertRaises(NativeAuthorizationError):OwnedImporter()._import_mapped_certificate({'certificatePem':pem},fingerprint)

import test_enrollment as current_bootstrap

class LegacyTransitionHttpTests(current_bootstrap.EnrollmentTests):
    def test_01_cutoff_never_reopens_retired_creation_paths(self):
        for cutoff in (int(time.time())-60,int(time.time())+60):
            with patch.dict(os.environ,{CUTOFF:str(cutoff),SUNSET:str(int(time.time())+3600)}):
                self.assertEqual(LegacyTransition.environment().cutoff,cutoff)
                self.assert_retired('/v1/enrollments')
                self.assert_retired('/v1/enrollments/'+'a'*32+'/claim')
                before=self.snapshot()
                for path in ('/v1/devices/pairings','/v1/devices/token','/v1/devices/token/refresh'):
                    self.assertEqual(self.api.native(path,{},'POST')[0],404)
                self.assertEqual(self.snapshot(),before)
                self.assertEqual(self.issuer.calls,0)

    def test_02_exact_complete_mapping_and_sunset_apply_are_additive_and_fail_closed(self):
        token=dict(device=dict(id=secrets.token_hex(16)))
        _,csr=make_csr();raw=self.issuer.response(validate_csr(csr))
        identity=legacy_certificate(raw['certificate']);public=dict(identity,source='authenticated-cloudflare-api',issuerId=CA_ID,certificateId=raw['id'])
        cipher=VisitCipher()
        with psycopg.connect(self.auth.dsn) as conn:
            owner=self.session['user']['id'];device=token['device']['id']
            initial=cipher.protect('team-device:'+owner,device,dict(name='Retained synthetic legacy device'))
            conn.execute("INSERT INTO team_devices(device_id,account_id,protected,access_hash,access_expires_at,refresh_hash,expires_at) VALUES(%s,%s,%s,%s,clock_timestamp()+interval '15 minutes',%s,clock_timestamp()+interval '30 minutes')",(device,owner,initial,secrets.token_hex(32),secrets.token_hex(32)))
            row=conn.execute('SELECT account_id,protected,expires_at FROM team_devices WHERE device_id=%s',(token['device']['id'],)).fetchone()
            saved=cipher.restore('team-device:'+row[0],token['device']['id'],row[1]);saved['nativeCertificateSha256']=identity['certificateSha256']
            conn.execute('UPDATE team_devices SET protected=%s WHERE device_id=%s',(cipher.protect('team-device:'+row[0],token['device']['id'],saved),token['device']['id']))
            maximum=math.ceil(row[2].timestamp());policy=LegacyTransition(int(time.time())-1,maximum)
            with self.assertRaisesRegex(RuntimeError,'mapping incomplete'):policy.verify_cohort(conn,cipher=cipher)
            with self.assertRaises(RuntimeError):apply.install_mappings(conn,cipher,[public],LegacyTransition(policy.cutoff,maximum-1),apply=True)
            self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_legacy_certificates').fetchone()[0],0)
            self.assertFalse(apply.install_mappings(conn,cipher,[public],policy)['applied'])
            value=apply.install_mappings(conn,cipher,[public],policy,apply=True);self.assertEqual(value['authenticatedMappings'],1)
            self.assertEqual(policy.verify_cohort(conn,cipher=cipher)['mappedLegacyDevices'],1)
            apply.install_mappings(conn,cipher,[public],policy,apply=True)
            self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_legacy_certificates').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT expires_at FROM team_devices WHERE device_id=%s',(token['device']['id'],)).fetchone()[0],row[2])
            self.assertEqual(cipher.restore('team-device:'+row[0],token['device']['id'],conn.execute('SELECT protected FROM team_devices WHERE device_id=%s',(token['device']['id'],)).fetchone()[0]),saved)
            with self.assertRaises(RuntimeError):apply.install_mappings(conn,cipher,[public,public],policy,apply=True)

def load_tests(loader,tests,pattern):
    suite=loader.loadTestsFromTestCase(LegacyPolicyTests)
    suite.addTests(LegacyTransitionHttpTests(name) for name in LegacyTransitionHttpTests.__dict__ if name.startswith('test_'))
    return suite


if __name__=='__main__':unittest.main()
