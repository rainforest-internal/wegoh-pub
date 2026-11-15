"""Stable per-trip car ordinal upgrade with original protected rows preserved."""
import json
import subprocess
import unittest

import psycopg
from ops.live import migration_pipeline as migration
from ops.live.test_migration_integrity import MigrationIntegrityTests, SERVER, SCHEMA_NAMES


class TripCarOrdinalMigrationTests(MigrationIntegrityTests):
    def test_populated_upgrade_reapply_and_nonreuse_counter(self):
        manifest = migration.load_manifest(SERVER)
        step = next(item for item in manifest['migrations'] if item['path'] == 'migrations/0023_trip_car_ordinals.sql')
        states = {item['version']: item for item in manifest['states']}
        with psycopg.connect(self.source) as conn:
            for old in manifest['migrations']:
                if old['id'] == step['id']:
                    break
                conn.execute((SERVER / old['path']).read_text())
            self.assertEqual(migration.catalog_digest(conn), states[step['from']]['catalogSha256'])
            accounts = [row[0] for row in conn.execute('SELECT account_id FROM team_accounts ORDER BY account_id LIMIT 2')]
            trip = 'a' * 32
            conn.execute('INSERT INTO team_trips(trip_id,owner_id,protected)VALUES(%s,%s,%s)', (trip, accounts[0], b'original-trip'))
            for index, account in enumerate(accounts, 1):
                conn.execute('INSERT INTO team_trip_members(trip_id,account_id,protected)VALUES(%s,%s,%s)', (trip, account, b'original-member'))
                conn.execute('INSERT INTO team_trip_cars(trip_id,car_id,driver_id,protected,created_at)VALUES(%s,%s,%s,%s,%s)',
                    (trip, str(index) * 32, account, b'original-car-' + bytes([index]), '2026-01-01T00:00:00Z'))
            old_rows = conn.execute('SELECT car_id,driver_id,protected,created_at FROM team_trip_cars ORDER BY car_id').fetchall()
            conn.execute((SERVER / step['path']).read_text())
            self.assertEqual(migration.catalog_digest(conn), states[step['to']]['catalogSha256'])
            self.assertEqual(conn.execute('SELECT car_id,driver_id,protected,created_at FROM team_trip_cars ORDER BY car_id').fetchall(), old_rows)
            self.assertEqual(conn.execute('SELECT ordinal FROM team_trip_cars WHERE trip_id=%s ORDER BY ordinal', (trip,)).fetchall(), [(1,), (2,)])
            self.assertEqual(conn.execute('SELECT next_car_ordinal FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()[0], 3)
            conn.execute('DELETE FROM team_trip_cars WHERE trip_id=%s AND ordinal=2', (trip,))
            conn.execute((SERVER / step['path']).read_text())
            self.assertEqual(conn.execute('SELECT next_car_ordinal FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()[0], 3)
            self.assertEqual(migration.catalog_digest(conn), states[step['to']]['catalogSha256'])
        self.assertEqual((step['rollbackFloor'], step['oldCodeCompatible']), (step['to'], False))

    def test_fresh_matches_upgrade_and_earlier_manifest_is_immutable(self):
        manifest = migration.load_manifest(SERVER)
        with psycopg.connect(self.source) as conn:
            for step in manifest['migrations']:
                conn.execute((SERVER / step['path']).read_text())
            upgraded = migration.catalog_digest(conn)
        fresh = self.database('ordinal_fresh')
        with psycopg.connect(fresh) as conn:
            for name in SCHEMA_NAMES:
                conn.execute((SERVER / name).read_text())
            self.assertEqual(migration.catalog_digest(conn), upgraded)
        original = json.loads(subprocess.check_output(['git', 'show', '7fdcf536:server/migrations/manifest.json'], cwd=SERVER.parent))
        self.assertEqual(manifest['states'][:len(original['states'])], original['states'])
        self.assertEqual(manifest['migrations'][:len(original['migrations'])], original['migrations'])


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(TripCarOrdinalMigrationTests(name) for name in TripCarOrdinalMigrationTests.__dict__ if name.startswith('test_'))
