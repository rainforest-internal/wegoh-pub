"""Private PostgreSQL and synthetic generated CA only; no VM/real provider IO."""
import hashlib,secrets,os
from unittest.mock import patch
from datetime import datetime
from native_authorization import protect
from private_records import VisitCipher
from native_issuance_hold import HoldExpectation,HoldError,manifest_digest,inspect_holds,require_new_issuance
from test_native_authorization import NativeAuthorizationTests
from test_enrollment import make_csr

class IssuanceHoldTests(NativeAuthorizationTests):
    def test_10_private_pg_expected_manifest_and_double_loss_fail_closed(self):
        cipher=VisitCipher()
        with self.assertRaises(HoldError):HoldExpectation.environment({})
        empty=HoldExpectation(0,manifest_digest([]))
        with self.connect() as conn:self.assertEqual(inspect_holds(conn,cipher,empty).count,0)
        enrollment=secrets.token_hex(16)
        original=cipher.protect('enrollment',enrollment,dict(csrPem=self.csr,owner=self.owner['id'],name='Synthetic retired attempt'))
        raw=self.issuer.issue(self.csr)
        expiry=int(datetime.fromisoformat(raw['expiresAt'].replace('Z','+00:00')).timestamp())
        generation_operation=secrets.token_hex(16)
        receipt=dict(certificatePem=raw['certificatePem'],certificateSha256=raw['certificateSha256'],installationKeyId=self.key_id,
            generation=1,generationOperationId=generation_operation,expiresAt=expiry)
        provenance=dict(raw,source='authenticated-cloudflare-api',installationKeyId=self.key_id)
        marker=dict(enrollmentId=enrollment,originalCipherSha256=hashlib.sha256(original).hexdigest(),caInventorySha256='a'*64)
        outcome=dict(receipt=receipt,provenance=provenance,quarantinedEnrollment=marker)
        descriptor=dict(marker,installationKeyId=self.key_id,certificateSha256=receipt['certificateSha256'])
        expected=HoldExpectation(1,manifest_digest([descriptor]))
        with self.connect() as conn:
            conn.execute("INSERT INTO vehicle_enrollments(enrollment_id,user_code,public_key_hash,state,expires_at,protected) VALUES(%s,'ABCDEFGH',%s,'uncertain',1,%s)",(enrollment,self.key_id,original))
            conn.execute("INSERT INTO native_v2_installations(installation_key_id,current_generation,created_at) VALUES(%s,1,%s)",(self.key_id,self.now))
            conn.execute("INSERT INTO native_v2_certificates(installation_key_id,generation,generation_operation_id,certificate_sha256,code_challenge,proof_nonce,expires_at,protected_receipt) VALUES(%s,1,%s,%s,%s,%s,%s,%s)",
                (self.key_id,generation_operation,receipt['certificateSha256'],self.begin['codeChallenge'],secrets.token_urlsafe(32),expiry,protect('generation',self.key_id+':1',outcome)))
            self.assertEqual(inspect_holds(conn,cipher,expected).count,1)
            from native_authorization import NativeAuthorizationError
            from native_access_backup import capture_projection,restore_projection
            self.service.hold_expectation=expected
            with self.assertRaises(NativeAuthorizationError) as denied:self.service.require_new_issuance(conn,self.csr)
            self.assertEqual(denied.exception.status,409)
            from native_access_backup import BackupProjectionError,hold_manifest
            with patch.dict(os.environ,{'WEGOH_RETIRED_ISSUANCE_EXPECTED_COUNT':'1','WEGOH_RETIRED_ISSUANCE_EXPECTED_DIGEST':expected.digest}):
                projection=capture_projection(conn)
                self.assertEqual(hold_manifest(projection),{'count':1,'digest':expected.digest})
                with conn.transaction(force_rollback=True):
                    conn.execute('TRUNCATE native_v2_installations CASCADE')
                    restore_projection(conn,projection,restored_at=self.now)
                    self.assertEqual(inspect_holds(conn,cipher,expected).count,1)
                    self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_grants').fetchone()[0],0)
                with conn.transaction(force_rollback=True):
                    conn.execute('TRUNCATE native_v2_installations CASCADE')
                    conn.execute('DELETE FROM vehicle_enrollments')
                    lost={**projection,'tables':{key:[] for key in projection['tables']}}
                    with self.assertRaises(BackupProjectionError):restore_projection(conn,lost,restored_at=self.now)
                    with self.assertRaises(BackupProjectionError):capture_projection(conn)
                absent={key:value for key,value in projection.items() if key!='issuanceHold'}
                with self.assertRaises(BackupProjectionError):hold_manifest(absent)
            self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_grants').fetchone()[0],0)
            self.issuer.calls=0
            with self.assertRaises(HoldError) as caught:
                require_new_issuance(conn,cipher,expected,self.csr)
                self.issuer.issue(self.csr)
            self.assertEqual(caught.exception.code,'HELD_ISSUANCE_KEY');self.assertEqual(self.issuer.calls,0)
            _,other=make_csr();self.assertEqual(require_new_issuance(conn,cipher,expected,other).count,1)
            stored=conn.execute('SELECT state,protected FROM vehicle_enrollments WHERE enrollment_id=%s',(enrollment,)).fetchone()
            self.assertEqual(stored[0],'uncertain');self.assertEqual(bytes(stored[1]),original)
            with conn.transaction(force_rollback=True):
                conn.execute('DELETE FROM native_v2_certificates');conn.execute('DELETE FROM native_v2_installations');conn.execute('DELETE FROM vehicle_enrollments')
                with self.assertRaises(HoldError):inspect_holds(conn,cipher,expected)
                with self.assertRaises(HoldError):require_new_issuance(conn,cipher,expected,other)
