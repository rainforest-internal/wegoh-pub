"""Single private PG + generated CA quarantine and real encrypted scratch restore."""
import hashlib,json,secrets,tempfile,time,os
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from psycopg import sql
from private_records import VisitCipher
from enrollment_crypto import validate_csr
from native_issuance_hold import HoldExpectation,inspect_holds
from ops.live.native_hold_apply import register_hold
from test_native_authorization import NativeAuthorizationTests

class HoldOperationTests(NativeAuthorizationTests):
    def test_20_dry_apply_original_unchanged_and_encrypted_scratch_restore(self):
        from ops.live import backup
        cipher=VisitCipher();enrollment=secrets.token_hex(16)
        original=cipher.protect('enrollment',enrollment,{'csrPem':self.csr,'owner':'Synthetic old owner'})
        response=self.issuer.response(validate_csr(self.csr))
        from cryptography import x509
        leaf=x509.load_pem_x509_certificate(response['certificate'].encode())
        response['issued_on']=leaf.not_valid_before_utc.isoformat();response['expires_on']=leaf.not_valid_after_utc.isoformat()
        envelope={'expectedIssuerId':response['certificate_authority']['id'],'inventorySha256':'a'*64,
            'inventory':dict(statusFilter='all',totalPages=1,totalCount=1,pageResponseSha256=['b'*64],records=[response])}
        with self.connect() as conn:
            conn.execute("INSERT INTO vehicle_enrollments(enrollment_id,user_code,public_key_hash,state,expires_at,protected) VALUES(%s,'ABCDEFGH',%s,'uncertain',1,%s)",(enrollment,self.key_id,original))
            dry=register_hold(conn,cipher,envelope,now=self.now)
            self.assertFalse(dry['applied']);self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_installations').fetchone()[0],0)
            applied=register_hold(conn,cipher,envelope,apply=True,now=self.now)
            repeated=register_hold(conn,cipher,envelope,apply=True,now=self.now)
            self.assertEqual(dry['holdDigest'],applied['holdDigest']);self.assertEqual(applied,repeated)
            self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_grants').fetchone()[0],0)
            raw=conn.execute('SELECT state,protected FROM vehicle_enrollments WHERE enrollment_id=%s',(enrollment,)).fetchone()
            self.assertEqual(raw[0],'uncertain');self.assertEqual(bytes(raw[1]),original)
        self.assertEqual(self.issuer.calls,0)
        expected=HoldExpectation(1,dry['holdDigest']);target='holdrestore_'+secrets.token_hex(8)
        with self.connect(autocommit=True) as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
        try:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict,make_conninfo
            options=conninfo_to_dict(self.auth.dsn);options['dbname']=target;destination=make_conninfo(**options)
            tools=Path(self.tools['pg_ctl']).parent
            with tempfile.TemporaryDirectory(prefix='hold-backup-',dir=self.base) as directory:
                work=Path(directory);content=work/'content';content.mkdir(mode=0o700);vault=work/'backup';vault.mkdir(mode=0o700)
                original_file=b'Synthetic unrelated journey preserved';item=hashlib.sha256(original_file).hexdigest();(content/item).write_bytes(original_file)
                key_before=self.keyfile.read_bytes()
                with patch.dict(os.environ,{'WEGOH_RETIRED_ISSUANCE_EXPECTED_COUNT':'1','WEGOH_RETIRED_ISSUANCE_EXPECTED_DIGEST':expected.digest}):
                    layout=backup.Layout(self.auth.dsn,content,vault,str(tools/'pg_dump'),str(tools/'pg_restore'))
                    archive=backup.snapshot(layout);manifest=backup.authenticated_manifest(archive)
                    self.assertEqual(manifest['nativeIssuanceHold'],{'count':1,'digest':expected.digest})
                    self.assertEqual(manifest['nativeIssuanceHold'],manifest['nativeV2Auth']['issuanceHold'])
                    destination_work=work/'verify';destination_work.mkdir(mode=0o700)
                    result=backup.verify_into(layout,archive,destination,destination_work)
                    self.assertTrue(result['verified']);self.assertEqual(result['nativeV2Auth']['personalSessionsRestored'],0)
                    with psycopg.connect(destination) as restored:
                        self.assertEqual(inspect_holds(restored,cipher,expected).count,1)
                        old=restored.execute('SELECT state,protected FROM vehicle_enrollments WHERE enrollment_id=%s',(enrollment,)).fetchone()
                        self.assertEqual(old[0],'uncertain');self.assertEqual(bytes(old[1]),original)
                        self.assertEqual(restored.execute('SELECT count(*) FROM native_v2_grants').fetchone()[0],0)
                    self.assertEqual((destination_work/'objects'/item).read_bytes(),original_file)
                self.assertEqual(self.keyfile.read_bytes(),key_before);self.assertEqual((content/item).read_bytes(),original_file)
        finally:
            with self.connect(autocommit=True) as conn:conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
