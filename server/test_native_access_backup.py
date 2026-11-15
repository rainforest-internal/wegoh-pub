"""Real isolated PostgreSQL + encrypted custom dump/restore, no live DB/CA."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import unittest
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from backup_vault import encrypt,decrypt
from native_access_backup import (TABLES,BackupProjectionError,capture_projection,
    dump_exclusion_args,restore_projection,validate_projection,validate_restored_projection)
from native_access_retention import purge_grant_personal
from test_native_access_retention import NativeAccessRetentionTests as Fixture

class NativeAccessBackupTests(unittest.TestCase):
    setUpClass=Fixture.__dict__['setUpClass']
    connect=Fixture.__dict__['connect']
    shutdown=Fixture.__dict__['shutdown']
    protect=Fixture.protect
    restore=Fixture.restore
    seed=Fixture.seed
    grant=Fixture.grant
    terminal=Fixture.terminal

    def setUp(self):
        Fixture.setUp(self)
        self.work=self.base/secrets.token_hex(8);self.work.mkdir(mode=0o700)
        self.target='restore_'+secrets.token_hex(8)
        with self.connect(autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(self.target)))
        self.addCleanup(self.drop_target)
        self.key_before=self.keyfile.read_bytes()
        self.original_archive=self.work/'existing-encrypted-original.enc'
        with self.original_archive.open('wb') as out:encrypt(io.BytesIO(b'Original unrelated encrypted archive'),out)
        self.archive_before=self.original_archive.read_bytes()

    def drop_target(self):
        with self.connect(autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.target)))

    def destination(self):
        return psycopg.connect(host=str(self.socket),port=5432,user='fixtureowner',dbname=self.target,
                              autocommit=False,row_factory=dict_row)

    def public_seed(self,*,unknown=False):
        item=self.seed(connection_state='UNCERTAIN' if unknown else 'ISSUED',issued=not unknown)
        receipt=dict(certificatePem='PUBLIC-SYNTHETIC-LEAF',certificateSha256='a'*64,
                     installationKeyId=item['key'],generation=1,generationOperationId='c'*32,
                     expiresAt=self.now+7776000)
        provenance=dict(certificatePem=receipt['certificatePem'],certificateSha256='a'*64,
                        issuerId='public-ca',certificateId='public-cert',expiresAt='2099-01-01T00:00:00Z',
                        privateOwner=item['owner'])
        public={'receipt':receipt,'provenance':provenance}
        with self.connect() as conn:
            if not unknown:
                conn.execute('UPDATE native_v2_connections SET protected_certificate=%s WHERE connection_id=%s',
                    (self.protect('certificate',item['connection'],public),item['connection']))
                conn.execute('UPDATE native_v2_certificates SET protected_receipt=%s WHERE installation_key_id=%s',
                    (self.protect('generation',item['key']+':1',public),item['key']))
            else:
                conn.execute('UPDATE native_v2_installations SET current_generation=0 WHERE installation_key_id=%s',(item['key'],))
        return item

    def snapshot(self):
        # The exact export used by capture is also used by pg_dump. Personal v2
        # rows are excluded by argv rather than post-processing a plaintext dump.
        with self.connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            snapshot=conn.execute('SELECT pg_export_snapshot() AS id').fetchone()['id']
            projection=capture_projection(conn)
            source_dsn=psycopg.conninfo.make_conninfo(host=str(self.socket),port=5432,user='fixtureowner',dbname='postgres')
            command=[str(Path(self.tools['pg_ctl']).with_name('pg_dump')),'--format=custom','--no-owner','--no-acl',
                     '--snapshot='+snapshot,*dump_exclusion_args(),'--dbname',source_dsn]
            raw=subprocess.run(command,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20).stdout
        archive=self.work/('database-'+secrets.token_hex(3)+'.dump.enc')
        with archive.open('wb') as target:encrypt(io.BytesIO(raw),target)
        manifest=self.work/('manifest-'+secrets.token_hex(3)+'.enc')
        body=json.dumps({'nativeV2Auth':projection,'archiveSha256':hashlib.sha256(archive.read_bytes()).hexdigest()}).encode()
        with manifest.open('wb') as target:encrypt(io.BytesIO(body),target)
        self.assertTrue(archive.read_bytes().startswith(b'WB01'))
        self.assertTrue(manifest.read_bytes().startswith(b'WB01'))
        return archive,manifest,projection

    def restored(self,archive,manifest):
        body=io.BytesIO()
        with manifest.open('rb') as source:decrypt(source);decrypt(source,body)
        value=json.loads(body.getvalue())
        self.assertEqual(value['archiveSha256'],hashlib.sha256(archive.read_bytes()).hexdigest())
        dump=io.BytesIO()
        with archive.open('rb') as source:decrypt(source);decrypt(source,dump)
        dsn=psycopg.conninfo.make_conninfo(host=str(self.socket),port=5432,user='fixtureowner',dbname=self.target)
        subprocess.run([str(Path(self.tools['pg_ctl']).with_name('pg_restore')),'--no-owner','--no-acl','--exit-on-error',
                        '--dbname',dsn],input=dump.getvalue(),check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
        with self.destination() as conn:
            # Inspect the actual decrypted/restored dump before adding its safe
            # projection: no original credential/consent rows are in the dump.
            for table in TABLES:self.assertEqual(conn.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n'],0)
            result=restore_projection(conn,value['nativeV2Auth'],restored_at=self.now+10)
            self.assertEqual(result['personalSessionsRestored'],0)
            validate_restored_projection(conn,value['nativeV2Auth'],restored_at=self.now+10)
        return value['nativeV2Auth']

    def originals_preserved(self):
        self.assertEqual(self.keyfile.read_bytes(),self.key_before)
        self.assertEqual(self.original_archive.read_bytes(),self.archive_before)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT data FROM synthetic_history WHERE id=1').fetchone()['data'],b'preserved-original')
        with self.destination() as conn:
            self.assertEqual(conn.execute('SELECT data FROM synthetic_history WHERE id=1').fetchone()['data'],b'preserved-original')

    def test_01_backup_before_withdrawal_restores_no_personal_authority_after_live_erasure(self):
        item=self.public_seed();archive,manifest,projection=self.snapshot()
        with self.connect() as conn:
            purge_grant_personal(conn,self.terminal(conn,item),revoked_at=self.now)
            self.assertIsNone(self.grant(conn,item)['account_id'])
        restored=self.restored(archive,manifest)
        self.assertEqual(restored,projection)
        with self.destination() as conn:
            grant=self.grant(conn,item)
            self.assertEqual(grant['state'],'REVOKED');self.assertEqual(grant['revoked_at'],self.now+10)
            self.assertIsNone(grant['account_id']);self.assertIsNone(grant['protected_consent']);self.assertIsNone(grant['recovery_hash'])
            self.assertEqual(grant['revoke_hash'],hashlib.sha256(item['capabilities']['revokeCapability'].encode()).hexdigest())
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM native_v2_credentials').fetchone()['n'],0)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM native_v2_operations').fetchone()['n'],0)
            connection=conn.execute('SELECT * FROM native_v2_connections').fetchone()
            request=self.restore('connection',item['connection'],connection['protected_request'])
            self.assertEqual(request['csrPem'],'synthetic-public-csr-a')
            self.assertNotIn('_legacySource',request);self.assertNotIn('name',request)
            certificate=conn.execute('SELECT * FROM native_v2_certificates').fetchone()
            receipt=self.restore('generation',item['key']+':1',certificate['protected_receipt'])
            self.assertEqual(receipt['receipt']['certificatePem'],'PUBLIC-SYNTHETIC-LEAF')
            self.assertNotIn('privateOwner',receipt['provenance'])
            self.assertIsNone(conn.execute('SELECT active_grant_id FROM native_v2_installations').fetchone()['active_grant_id'])
        self.originals_preserved()

    def test_02_backup_after_withdrawal_keeps_true_ack_time_and_unknown_issuance(self):
        item=self.public_seed(unknown=True)
        with self.connect() as conn:
            row=conn.execute('SELECT protected_request FROM native_v2_connections WHERE connection_id=%s',(item['connection'],)).fetchone()
            public=self.restore('connection',item['connection'],row['protected_request'])
            public['_revocationGrantHash']='e'*64
            conn.execute('UPDATE native_v2_connections SET protected_request=%s WHERE connection_id=%s',
                (self.protect('connection',item['connection'],public),item['connection']))
            purge_grant_personal(conn,self.terminal(conn,item),revoked_at=self.now)
        archive,manifest,projection=self.snapshot();self.restored(archive,manifest)
        with self.destination() as conn:
            row=conn.execute('SELECT * FROM native_v2_connections').fetchone()
            self.assertEqual(row['state'],'UNCERTAIN');self.assertEqual(row['proof_nonce'],'N'*43)
            self.assertEqual(self.restore('connection',item['connection'],row['protected_request'])['_revocationGrantHash'],'e'*64)
            self.assertEqual(self.restore('connection',item['connection'],row['protected_request'])['csrPem'],'synthetic-public-csr-a')
            self.assertEqual(conn.execute('SELECT current_generation FROM native_v2_installations').fetchone()['current_generation'],0)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM native_v2_certificates').fetchone()['n'],0)
        self.originals_preserved()

    def test_07_account_authorize_certificate_only_backup_restores_without_private_grant(self):
        item=self.public_seed()
        with self.connect() as conn:
            row=conn.execute('SELECT protected_request FROM native_v2_connections WHERE connection_id=%s',(item['connection'],)).fetchone()
            request=self.restore('connection',item['connection'],row['protected_request'])
            request.pop('csrPem');request['certificatePem']='PUBLIC-ACCOUNT-LEAF'
            conn.execute("UPDATE native_v2_connections SET kind='ACCOUNT',protected_request=%s WHERE connection_id=%s",
                (self.protect('connection',item['connection'],request),item['connection']))
        archive,manifest,projection=self.snapshot();self.restored(archive,manifest)
        with self.destination() as conn:
            row=conn.execute('SELECT * FROM native_v2_connections WHERE connection_id=%s',(item['connection'],)).fetchone()
            restored=self.restore('connection',item['connection'],row['protected_request'])
            self.assertEqual(row['kind'],'ACCOUNT');self.assertEqual(restored['certificatePem'],'PUBLIC-ACCOUNT-LEAF')
            self.assertEqual(set(restored),{'operationId','codeChallenge','certificatePem'})
            self.assertIsNone(self.grant(conn,item)['account_id'])
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM native_v2_credentials').fetchone()['n'],0)
        for extra in ({'csrPem':'unexpected-csr'},{'futurePrivate':'must-reject'}):
            invalid=copy.deepcopy(projection);row=invalid['tables']['native_v2_connections'][0]
            row['protected_request']={'bytea':__import__('base64').b64encode(self.protect('connection',row['connection_id'],dict(restored,**extra))).decode()}
            with self.assertRaises(BackupProjectionError):validate_projection(invalid)
        invalid=copy.deepcopy(projection);invalid['tables']['native_v2_connections'][0]['kind']='INSTALL'
        with self.assertRaises(BackupProjectionError):validate_projection(invalid)
        self.originals_preserved()

    def test_03_closed_projection_rejects_personal_payload_and_future_table(self):
        self.public_seed()
        with self.connect() as conn:projection=capture_projection(conn)
        bad=copy.deepcopy(projection)
        bad['tables']['native_v2_grants'][0]['account_id']='team-'+'a'*40
        with self.assertRaises(BackupProjectionError):validate_projection(bad)
        bad=copy.deepcopy(projection)
        row=bad['tables']['native_v2_connections'][0]
        import base64
        row['protected_request']={'bytea':base64.b64encode(self.protect('connection',row['connection_id'],
            {'csrPem':'public','name':'private'})).decode()}
        with self.assertRaises(BackupProjectionError):validate_projection(bad)
        bad=copy.deepcopy(projection);row=bad['tables']['native_v2_connections'][0]
        row['protected_request']={'bytea':base64.b64encode(self.protect('connection',row['connection_id'],
            {'csrPem':'public','_revocationGrantHash':'not-a-canonical-hash'})).decode()}
        with self.assertRaises(BackupProjectionError):validate_projection(bad)
        with self.connect() as conn:
            conn.execute('CREATE TABLE native_v2_future_private(secret text)')
            with self.assertRaises(BackupProjectionError):capture_projection(conn)
            conn.rollback()

    def test_05_live_backup_and_verify_hooks_use_same_safe_projection(self):
        from ops.live import backup as live_backup
        item=self.public_seed()
        content=self.work/'content';content.mkdir(mode=0o700)
        base=self.work/'backup-root';base.mkdir(mode=0o700)
        blob=b'Synthetic original journey photo bytes'
        object_id=hashlib.sha256(blob).hexdigest();(content/object_id).write_bytes(blob)
        source=psycopg.conninfo.make_conninfo(host=str(self.socket),port=5432,user='fixtureowner',dbname='postgres')
        destination=psycopg.conninfo.make_conninfo(host=str(self.socket),port=5432,user='fixtureowner',dbname=self.target)
        tools=Path(self.tools['pg_ctl']).parent
        layout=live_backup.Layout(source,content,base,str(tools/'pg_dump'),str(tools/'pg_restore'))
        snapshot=live_backup.snapshot(layout)
        manifest=live_backup.authenticated_manifest(snapshot)
        self.assertIsNotNone(manifest['nativeV2Auth'])
        with self.connect() as conn:purge_grant_personal(conn,self.terminal(conn,item),revoked_at=self.now)
        work=self.work/'verification';work.mkdir(mode=0o700)
        result=live_backup.verify_into(layout,snapshot,destination,work)
        self.assertTrue(result['verified']);self.assertEqual(result['nativeV2Auth']['personalSessionsRestored'],0)
        self.assertEqual((work/'objects'/object_id).read_bytes(),blob)
        self.assertEqual((content/object_id).read_bytes(),blob)
        with self.destination() as conn:
            grant=self.grant(conn,item)
            self.assertEqual(grant['state'],'REVOKED');self.assertIsNone(grant['account_id'])
            self.assertIsNone(grant['protected_consent']);self.assertIsNone(grant['recovery_hash'])
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM native_v2_credentials').fetchone()['n'],0)
            self.assertEqual(conn.execute('SELECT count(*) AS n FROM native_v2_operations').fetchone()['n'],0)
        self.originals_preserved()

    def test_04_restore_is_empty_target_only_and_no_source_mutation(self):
        item=self.public_seed()
        with self.connect() as conn:
            before=self.grant(conn,item)
            projection=capture_projection(conn)
            self.assertEqual(self.grant(conn,item),before)
            with self.assertRaises(BackupProjectionError):restore_projection(conn,projection,restored_at=self.now+10)
            self.assertEqual(self.grant(conn,item),before)

if __name__=='__main__':unittest.main()
