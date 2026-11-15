"""Actual private PostgreSQL schema smoke. No live DB/key/Cloudflare access."""
import concurrent.futures
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import psycopg

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("native_v2_owned_pg", ROOT / "server/ops/dev.py")
_dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dev)
SCHEMA = ROOT / "server/native_access_schema.sql"


class NativeAccessSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="wegoh-v2-schema-", dir="/tmp")
        cls.base = Path(cls.temp.name)
        cls.cluster, cls.socket = cls.base / "pg", cls.base / "socket"
        cls.socket.mkdir(mode=0o700)
        cls.tools = _dev.pg_tools()
        cls.addClassCleanup(cls.shutdown)
        subprocess.run([cls.tools["initdb"], "-D", str(cls.cluster), "-U", "fixtureowner",
            "--encoding=UTF8", "--locale=C", "--auth-local=trust", "--auth-host=reject"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        _dev.validate_cluster(cls.cluster)
        subprocess.run([cls.tools["pg_ctl"], "-D", str(cls.cluster), "-l", str(cls.base / "pg.log"),
            "-o", "-h '' -k " + str(cls.socket) + " -p 5432", "-w", "start"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        with cls.connect(autocommit=True) as conn:
            conn.execute("CREATE ROLE isolatedissuer NOINHERIT LOGIN")
            conn.execute("CREATE TABLE synthetic_history(id int PRIMARY KEY, data bytea NOT NULL)")
            conn.execute("INSERT INTO synthetic_history VALUES (1,%s)", (b"preserved-original",))
            conn.execute(SCHEMA.read_text())

    @classmethod
    def connect(cls, user="fixtureowner", autocommit=False):
        return psycopg.connect(host=str(cls.socket), port=5432, user=user, dbname="postgres",
            connect_timeout=3, autocommit=autocommit)

    @classmethod
    def shutdown(cls):
        if (cls.cluster / "postmaster.pid").exists():
            subprocess.run([cls.tools["pg_ctl"], "-D", str(cls.cluster), "-m", "fast", "-w", "stop"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20)
        cls.temp.cleanup()

    def test_01_additive_rerun_preserves_existing_history_and_full_inventory(self):
        with self.connect() as conn:
            before = conn.execute("SELECT * FROM synthetic_history ORDER BY id").fetchall()
            conn.execute(SCHEMA.read_text())
            self.assertEqual(conn.execute("SELECT * FROM synthetic_history ORDER BY id").fetchall(), before)
            tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
            self.assertEqual(tables, {"synthetic_history", "native_v2_installations", "native_v2_connections",
                "native_v2_approvals", "native_v2_grants", "native_v2_certificates", "native_v2_credentials",
                "native_v2_operations", "native_v2_legacy_certificates", "native_v2_renewals"})
            views = {r[0] for r in conn.execute("SELECT viewname FROM pg_views WHERE schemaname='public'")}
            self.assertEqual(views, {"native_v2_issuer_approvals", "native_v2_certificate_recovery"})

    def test_02_invalid_epoch_key_and_issued_without_receipt_fail_at_database(self):
        for key, epoch in (("G" * 64, 1), ("a" * 64, 0), ("b" * 64, 9007199254740992)):
            with self.subTest(epoch=epoch), self.assertRaises(psycopg.errors.CheckViolation):
                with self.connect() as conn:
                    conn.execute("INSERT INTO native_v2_installations(installation_key_id,revision,created_at) VALUES(%s,%s,0)", (key, epoch))
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connect() as conn:
                conn.execute("INSERT INTO native_v2_connections(connection_id,operation_id,installation_key_id,kind,user_code,original_begin_hash,code_challenge,proof_nonce,state,expires_at,created_at,protected_request) VALUES(%s,%s,%s,'INSTALL','ABCDEFGH',%s,%s,%s,'ISSUED',300,0,%s)",
                    ("a" * 32, "b" * 32, "c" * 64, "d" * 64, "E" * 43, "F" * 43, b"x" * 32))

    def test_03_new_objects_do_not_give_issuer_personal_access_or_write(self):
        # A fresh issuer receives zero implicit v2 privileges. Runtime grants are
        # a separate reviewed deployment step, never inferred from view existence.
        with self.connect("isolatedissuer") as conn:
            objects = [r[0] for r in conn.execute("SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND relkind IN ('r','v')")]
            for name in objects:
                for permission in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    self.assertFalse(conn.execute("SELECT has_table_privilege(%s,%s)", ("public." + name, permission)).fetchone()[0], (name, permission))

    def test_04_parallel_compare_and_swap_has_exactly_one_slot_winner(self):
        key = "e" * 64
        with self.connect() as conn:
            conn.execute("INSERT INTO native_v2_installations(installation_key_id,created_at) VALUES(%s,0)", (key,))
        def compete():
            with self.connect() as conn:
                return conn.execute("UPDATE native_v2_installations SET slot_revision=slot_revision+1 WHERE installation_key_id=%s AND slot_revision=1 RETURNING slot_revision", (key,)).fetchone()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: compete(), range(2)))
        self.assertEqual(sum(v == (2,) for v in values), 1)
        self.assertEqual(sum(v is None for v in values), 1)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT slot_revision FROM native_v2_installations WHERE installation_key_id=%s", (key,)).fetchone(), (2,))


if __name__ == "__main__":
    unittest.main()
