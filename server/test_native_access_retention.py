"""Actual private PostgreSQL: exact erasure/scope boundaries, no live data or CA."""
import hashlib
import json
import os
import secrets
import time
import unittest
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
import test_native_access_schema as fixture
from private_records import VisitCipher
from native_access_codec import derive_capability
from native_access_retention import (RetentionError, active_capabilities,
    purge_grant_personal, reduce_grant_scopes)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NativeAccessRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.NativeAccessSchemaTests.setUpClass.__func__(cls)
        cls.keyfile=cls.base/'retention.key';cls.keyfile.write_bytes(os.urandom(32));cls.keyfile.chmod(0o600)
        cls.environment=patch.dict(os.environ,{'WEGOH_VISIT_KEY_FILE':str(cls.keyfile)})
        cls.environment.start();cls.addClassCleanup(cls.environment.stop)

    @classmethod
    def connect(cls,user='fixtureowner',autocommit=False):
        return psycopg.connect(host=str(cls.socket),port=5432,user=user,dbname='postgres',
                              connect_timeout=3,autocommit=autocommit,row_factory=dict_row)

    shutdown=fixture.NativeAccessSchemaTests.__dict__['shutdown']

    def setUp(self):
        with self.connect() as conn:
            conn.execute('TRUNCATE native_v2_operations,native_v2_credentials,native_v2_approvals,'
                'native_v2_grants,native_v2_certificates,native_v2_connections,native_v2_installations CASCADE')
        self.cipher=VisitCipher();self.now=int(time.time())
        self.scopes=sorted(['account:read','courses:read','device:self:manage','playlists:read'])

    def protect(self,purpose,key,value):
        return self.cipher.protect('native-v2:'+purpose,key,value)

    def restore(self,purpose,key,value):
        return self.cipher.restore('native-v2:'+purpose,key,value)

    def seed(self,letter='a',*,connection_state='ISSUED',issued=True):
        key=letter*64;connection=secrets.token_hex(16);grant=secrets.token_hex(16);device=secrets.token_hex(16)
        owner='team-'+letter*40;op=secrets.token_hex(16);refresh=secrets.token_hex(16)
        name='Synthetic private '+letter
        request=dict(csrPem='synthetic-public-csr-'+letter,name=name,legacyDeviceId='f'*32,
                     codeChallenge='A'*43,operationId=connection,requestedScopes=self.scopes,
                     _legacySource=dict(accountId=owner,deviceId=device,certificateSha256=letter*64))
        consent=dict(name=name,scopes=self.scopes,keepSignedIn=False,disclosureVersion=2,disclosureSha256='e'*64)
        capabilities={p+'Capability':derive_capability('V'*43,grant,p) for p in ('recovery','revoke')}
        receipt=dict(accountId=owner,deviceId=device,grantId=grant,scopes=self.scopes,
                     accessToken='private-access-'+letter,refreshToken='private-refresh-'+letter,**capabilities)
        public={'receipt':{'publicKey':key,'certificate':'synthetic-public-cert-'+letter},'issuance':'preserve-public-provenance'}
        with self.connect() as conn:
            conn.execute('INSERT INTO native_v2_installations(installation_key_id,current_generation,active_grant_id,created_at) VALUES(%s,1,%s,%s)',(key,grant,self.now))
            conn.execute('INSERT INTO native_v2_connections(connection_id,operation_id,installation_key_id,kind,user_code,original_begin_hash,code_challenge,proof_nonce,state,expires_at,created_at,protected_request,protected_certificate) VALUES(%s,%s,%s,\'INSTALL\',%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (connection,secrets.token_hex(16),key,('A' if letter=='a' else 'B')*7+'2','c'*64,'A'*43,'N'*43,connection_state,self.now+300,self.now,
                 self.protect('connection',connection,request),self.protect('certificate',connection,public) if connection_state=='ISSUED' else None))
            conn.execute('INSERT INTO native_v2_grants(grant_id,connection_id,installation_key_id,account_id,device_id,state,consent_version,expires_at,recovery_hash,revoke_hash,protected_consent) VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s)',
                (grant,connection,key,owner,device if issued else None,'TOKEN_ISSUED' if issued else 'APPROVED',self.now+604800,
                 digest(capabilities['recoveryCapability']) if issued else None,digest(capabilities['revokeCapability']) if issued else None,self.protect('consent',grant,consent)))
            conn.execute('INSERT INTO native_v2_approvals(connection_id,grant_id,state,protected_owner,approved_at,exchange_expires_at) VALUES(%s,%s,\'APPROVED\',%s,%s,%s)',
                (connection,grant,self.protect('approval',connection,{'accountId':owner}),self.now,self.now+300))
            if connection_state=='ISSUED':
                conn.execute('INSERT INTO native_v2_certificates(installation_key_id,generation,generation_operation_id,certificate_sha256,code_challenge,proof_nonce,expires_at,protected_receipt) VALUES(%s,1,%s,%s,%s,%s,%s,%s)',
                    (key,secrets.token_hex(16),letter*64,'A'*43,'N'*43,self.now+7776000,self.protect('generation',key+':1',public)))
            if issued:
                conn.execute('INSERT INTO native_v2_credentials(grant_id,device_id,access_hash,refresh_hash,certificate_sha256,generation,slot_revision,credential_epoch,access_expires_at) VALUES(%s,%s,%s,%s,%s,1,1,1,%s)',
                    (grant,device,digest('access-'+letter),digest('refresh-'+letter),letter*64,self.now+900))
                for operation,action in [(op,'SESSION_EXCHANGE'),(refresh,'SESSION_REFRESH')]:
                    conn.execute('INSERT INTO native_v2_operations(operation_id,action,request_hash,grant_id,installation_key_id,credential_epoch,slot_revision,expires_at,protected_receipt) VALUES(%s,%s,%s,%s,%s,1,1,%s,%s)',
                        (operation,action,'d'*64,grant,key,self.now+900,self.protect('operation',operation,{'credentialReceipt':receipt})))
        return dict(grant=grant,connection=connection,key=key,device=device,owner=owner,name=name,receipt=receipt,capabilities=capabilities,original=op)

    def grant(self,conn,item):
        return conn.execute('SELECT * FROM native_v2_grants WHERE grant_id=%s FOR UPDATE',(item['grant'],)).fetchone()

    def terminal(self,conn,item):
        conn.execute("UPDATE native_v2_grants SET state='REVOKED',revoked_at=%s,credential_epoch=credential_epoch+1 WHERE grant_id=%s",(self.now,item['grant']))
        conn.execute('UPDATE native_v2_installations SET active_grant_id=NULL,slot_revision=slot_revision+1 WHERE installation_key_id=%s',(item['key'],))
        return self.grant(conn,item)

    def test_01_terminal_erasure_is_exact_idempotent_and_preserves_public_issuance_and_history(self):
        a=self.seed();b=self.seed('b')
        with self.connect() as conn:
            before_b=self.grant(conn,b)
            other_rows={table:conn.execute('SELECT * FROM '+table+' WHERE grant_id=%s ORDER BY grant_id',(b['grant'],)).fetchall()
                        for table in ('native_v2_credentials','native_v2_operations','native_v2_approvals')}
            generation=conn.execute('SELECT * FROM native_v2_certificates WHERE installation_key_id=%s',(a['key'],)).fetchone()
            original=self.grant(conn,a);expiry=original['expires_at'];revoke_hash=original['revoke_hash']
            ack=purge_grant_personal(conn,self.terminal(conn,a),revoked_at=self.now)
            self.assertEqual(ack,purge_grant_personal(conn,self.grant(conn,a),revoked_at=self.now))
            after=self.grant(conn,a)
            self.assertIsNone(after['account_id']);self.assertIsNone(after['protected_consent']);self.assertIsNone(after['recovery_hash'])
            self.assertEqual((after['expires_at'],after['device_id'],after['installation_key_id'],after['revoke_hash']),
                             (expiry,a['device'],a['key'],revoke_hash))
            for table in ('native_v2_credentials','native_v2_operations'):
                self.assertEqual(conn.execute('SELECT count(*) AS n FROM '+table+' WHERE grant_id=%s',(a['grant'],)).fetchone()['n'],0)
            approval=conn.execute('SELECT * FROM native_v2_approvals WHERE grant_id=%s',(a['grant'],)).fetchone()
            self.assertEqual(approval['state'],'REVOKED');self.assertIsNone(approval['protected_owner'])
            request=conn.execute('SELECT protected_request FROM native_v2_connections WHERE connection_id=%s',(a['connection'],)).fetchone()['protected_request']
            sanitized=self.restore('connection',a['connection'],request)
            self.assertNotIn('name',sanitized);self.assertNotIn('legacyDeviceId',sanitized)
            self.assertNotIn('_legacySource',sanitized)
            self.assertEqual(sanitized['csrPem'],'synthetic-public-csr-a')
            self.assertEqual(conn.execute('SELECT * FROM native_v2_certificates WHERE installation_key_id=%s',(a['key'],)).fetchone(),generation)
            self.assertEqual(self.grant(conn,b),before_b)
            for table,rows in other_rows.items():
                self.assertEqual(conn.execute('SELECT * FROM '+table+' WHERE grant_id=%s ORDER BY grant_id',(b['grant'],)).fetchall(),rows,table)
            self.assertEqual(conn.execute('SELECT data FROM synthetic_history WHERE id=1').fetchone()['data'],b'preserved-original')

    def test_02_unknown_issuance_csr_nonce_and_lease_are_not_erased_or_reissued(self):
        a=self.seed(connection_state='UNCERTAIN',issued=False)
        with self.connect() as conn:
            before=conn.execute('SELECT * FROM native_v2_connections WHERE connection_id=%s',(a['connection'],)).fetchone()
            purge_grant_personal(conn,self.terminal(conn,a),revoked_at=self.now)
            after=conn.execute('SELECT * FROM native_v2_connections WHERE connection_id=%s',(a['connection'],)).fetchone()
            for key in before:
                if key!='protected_request':self.assertEqual(before[key],after[key],key)
            self.assertEqual(self.restore('connection',a['connection'],after['protected_request'])['csrPem'],'synthetic-public-csr-a')
            self.assertEqual(after['state'],'UNCERTAIN')

    def test_03_optional_reduction_drops_old_credentials_but_keeps_only_same_grant_recovery_secrets(self):
        a=self.seed();required=sorted(['account:read','device:self:manage'])
        with self.connect() as conn:
            before=self.grant(conn,a)
            result=reduce_grant_scopes(conn,before,required,expected_consent_version=1)
            self.assertTrue(result['changed']);self.assertFalse(result['terminal'])
            after=self.grant(conn,a)
            self.assertEqual((after['consent_version'],after['credential_epoch'],after['device_revision']),(2,2,2))
            for key in ('grant_id','account_id','device_id','connection_id','installation_key_id','expires_at','revoke_hash','recovery_hash'):
                self.assertEqual(before[key],after[key],key)
            self.assertEqual(self.restore('consent',a['grant'],after['protected_consent'])['scopes'],required)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM native_v2_credentials WHERE grant_id=%s',(a['grant'],)).fetchone()['n'],0)
            operations=conn.execute('SELECT * FROM native_v2_operations WHERE grant_id=%s',(a['grant'],)).fetchall()
            self.assertEqual(len(operations),1);self.assertEqual(operations[0]['action'],'SESSION_EXCHANGE')
            carrier=self.restore('operation',operations[0]['operation_id'],operations[0]['protected_receipt'])
            self.assertEqual(carrier,{'capabilities':a['capabilities']});self.assertEqual(active_capabilities(carrier),a['capabilities'])
            self.assertNotIn(a['owner'],json.dumps(carrier));self.assertNotIn(a['receipt']['accessToken'],json.dumps(carrier))
            unchanged=reduce_grant_scopes(conn,after,required,expected_consent_version=2)
            self.assertFalse(unchanged['changed']);self.assertEqual(self.grant(conn,a),after)

    def test_04_expansion_stale_bool_and_required_scope_withdrawal_are_not_optional_updates(self):
        a=self.seed();required=sorted(['account:read','device:self:manage'])
        with self.connect() as conn:
            original=self.grant(conn,a)
            for scopes,version in [(['unknown:scope'],1),(self.scopes,True),(self.scopes,0)]:
                with self.assertRaises(RetentionError):reduce_grant_scopes(conn,original,scopes,expected_consent_version=version)
            self.assertEqual(self.grant(conn,a),original)
            terminal=reduce_grant_scopes(conn,original,[],expected_consent_version=1)
            self.assertTrue(terminal['terminal']);self.assertEqual(self.grant(conn,a),original)
            # Core consumes the terminal decision within this same transaction.
            purge_grant_personal(conn,self.terminal(conn,a),revoked_at=self.now)
            self.assertIsNone(self.grant(conn,a)['account_id'])
        b=self.seed('b')
        with self.connect() as conn:
            reduce_grant_scopes(conn,self.grant(conn,b),required,expected_consent_version=1)
            with self.assertRaisesRegex(RetentionError,'SCOPE_DENIED'):
                reduce_grant_scopes(conn,self.grant(conn,b),self.scopes,expected_consent_version=2)

    def test_05_live_purge_is_not_claimed_as_erasure_of_previously_captured_backup_bytes(self):
        a=self.seed()
        with self.connect() as conn:
            original=bytes(self.grant(conn,a)['protected_consent'])
            purge_grant_personal(conn,self.terminal(conn,a),revoked_at=self.now)
            self.assertIsNone(self.grant(conn,a)['protected_consent'])
            # Intentionally proves the separate backup boundary, not deletion:
            # an earlier encrypted snapshot is still decryptable with its key.
            self.assertEqual(self.restore('consent',a['grant'],original)['name'],a['name'])


if __name__=='__main__':unittest.main()
