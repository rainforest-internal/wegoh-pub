"""Actual safe snapshot while startup already owns the maintenance lock."""
import hashlib,secrets
from pathlib import Path
import psycopg
from native_access_retention import purge_grant_personal
import test_native_access_backup as fixture
from ops.live import backup

class StartupBackupTests(fixture.NativeAccessBackupTests):
    def test_60_pre_migration_safe_snapshot_reuses_held_lock_and_restores_private_zero(self):
        item=self.public_seed(unknown=True)
        content=self.work/"pre-start-content";content.mkdir(mode=0o700)
        base=self.work/"pre-start-backup";base.mkdir(mode=0o700)
        payload=b"Existing trip object preserved at startup"
        name=hashlib.sha256(payload).hexdigest();(content/name).write_bytes(payload)
        source=psycopg.conninfo.make_conninfo(host=str(self.socket),port=5432,user="fixtureowner",dbname="postgres")
        destination=psycopg.conninfo.make_conninfo(host=str(self.socket),port=5432,user="fixtureowner",dbname=self.target)
        tools=Path(self.tools["pg_ctl"]).parent
        layout=backup.Layout(source,content,base,str(tools/"pg_dump"),str(tools/"pg_restore"))
        with backup.maintenance_lock(base):
            archive=backup.snapshot(layout,maintenance_held=True)
        manifest=backup.authenticated_manifest(archive)
        self.assertEqual(manifest["nativeV2Auth"]["tables"]["native_v2_credentials"],[])
        self.assertEqual(manifest["nativeV2Auth"]["tables"]["native_v2_operations"],[])
        with self.connect() as conn:purge_grant_personal(conn,self.terminal(conn,item),revoked_at=self.now)
        work=self.work/"pre-start-restore";work.mkdir(mode=0o700)
        result=backup.verify_into(layout,archive,destination,work)
        self.assertEqual(result["nativeV2Auth"]["personalSessionsRestored"],0)
        self.assertEqual((work/"objects"/name).read_bytes(),payload)
        with self.destination() as conn:
            # This unknown-issuance fixture has never allocated a device or
            # personal token. No private pending grant is restored at all.
            self.assertEqual(conn.execute("SELECT count(*) AS n FROM native_v2_grants").fetchone()["n"],0)
            self.assertEqual(conn.execute("SELECT state FROM native_v2_connections").fetchone()["state"],"UNCERTAIN")
        self.originals_preserved()

