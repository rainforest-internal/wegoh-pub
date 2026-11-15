import unittest

import psycopg
from psycopg import sql

from ops.live import migration_pipeline as migration
from ops.live.test_migration_integrity import MigrationIntegrityTests


class DrivingVersusMigrationTests(MigrationIntegrityTests):
    def test_0021_preserves_populated_previous_schema_and_matches_fresh_catalog(self):
        manifest = migration.load_manifest(self.candidate)
        states = {item['version']: item for item in manifest['states']}
        step = next(item for item in manifest['migrations'] if item['path']=='migrations/0021_trip_driving_versus.sql')
        self.assertEqual((step['from'], step['to']), ('trip_route_segments_v2', 'trip_driving_versus_v1'))
        with psycopg.connect(self.source) as conn:
            index=manifest['migrations'].index(step)
            for old in manifest['migrations'][:index]:
                conn.execute((self.candidate / old['path']).read_text())
            self.assertEqual(migration.catalog_digest(conn), states[step['from']]['catalogSha256'])
            tables = [item[0] for item in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
            def snapshot():
                return {table: conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text').format(
                    sql.Identifier(table))).fetchall() for table in tables}
            before = snapshot()
            conn.execute((self.candidate / step['path']).read_text())
            conn.execute((self.candidate / step['path']).read_text())
            self.assertEqual(snapshot(), before)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_driving_versus').fetchone()[0], 0)
            self.assertEqual(migration.catalog_digest(conn), states[step['to']]['catalogSha256'])
            for later in manifest['migrations'][index+1:]:
                conn.execute((self.candidate/later['path']).read_text())
            upgraded=migration.catalog_digest(conn)
            self.assertEqual(upgraded,states[manifest['targetVersion']]['catalogSha256'])
        fresh = self.database('versus_fresh')
        with psycopg.connect(fresh) as conn:
            for name in ('schema.sql', 'enrollment_schema.sql', 'native_access_schema.sql', 'native_functional_schema.sql'):
                conn.execute((self.candidate / name).read_text())
            self.assertEqual(migration.catalog_digest(conn), upgraded)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([DrivingVersusMigrationTests('test_0021_preserves_populated_previous_schema_and_matches_fresh_catalog')])
