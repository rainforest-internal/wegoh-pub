"""Populated immutable-schema upgrade tests in disposable PostgreSQL only."""
import json
import subprocess
import unittest

import psycopg
from ops.live import migration_pipeline as migration
from ops.live.test_migration_integrity import MigrationIntegrityTests, SCHEMA_NAMES, SERVER


class CourseDiscoveryMigrationTests(MigrationIntegrityTests):
    def to_previous(self):
        manifest = json.loads((SERVER / 'migrations/manifest.json').read_text())
        with psycopg.connect(self.source) as conn:
            for step in manifest['migrations']:
                if step['path'] == 'migrations/0022_course_discovery.sql':
                    break
                conn.execute((SERVER / step['path']).read_text())
            expected = next(state['catalogSha256'] for state in manifest['states'] if state['version'] == 'trip_driving_versus_v1')
            self.assertEqual(migration.catalog_digest(conn), expected)
        return manifest

    def test_populated_21_upgrade_reapply_and_rollback_floor(self):
        manifest = self.to_previous()
        before = self.row_snapshot()
        step = next(item for item in manifest['migrations'] if item['path']=='migrations/0022_course_discovery.sql')
        self.assertEqual((step['from'], step['to'], step['rollbackFloor'], step['oldCodeCompatible']),
            ('trip_driving_versus_v1', 'course_discovery_v1', 'course_discovery_v1', False))
        with psycopg.connect(self.source) as conn:
            conn.execute((SERVER / step['path']).read_text())
            first = migration.catalog_digest(conn)
            self.assertEqual(first, next(item['catalogSha256'] for item in manifest['states'] if item['version']==step['to']))
            conn.execute((SERVER / step['path']).read_text())
            self.assertEqual(migration.catalog_digest(conn), first)
            self.assertEqual(conn.execute("SELECT is_nullable FROM information_schema.columns WHERE table_name='team_remix_drafts' AND column_name='history_id'").fetchone()[0], 'YES')
            for table in ('team_course_tag_follows', 'team_course_discovery_reads', 'team_course_hidden'):
                self.assertEqual(conn.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
        after = self.row_snapshot()
        self.assertEqual({name: after[name] for name in before}, before)

    def test_fresh_catalogue_matches_upgraded_and_historical_manifest_is_immutable(self):
        manifest = self.to_previous()
        with psycopg.connect(self.source) as conn:
            conn.execute((SERVER / 'migrations/0022_course_discovery.sql').read_text())
            upgraded = migration.catalog_digest(conn)
            state=next(item for item in manifest['states'] if item['version']=='course_discovery_v1')
            self.assertEqual(upgraded,state['catalogSha256'])
            step=next(item for item in manifest['migrations'] if item['path']=='migrations/0022_course_discovery.sql')
            for later in manifest['migrations'][manifest['migrations'].index(step)+1:]:
                conn.execute((SERVER/later['path']).read_text())
            upgraded=migration.catalog_digest(conn)
        fresh = self.database('fresh')
        with psycopg.connect(fresh) as conn:
            for name in SCHEMA_NAMES:
                conn.execute((SERVER / name).read_text())
            self.assertEqual(migration.catalog_digest(conn), upgraded)
        original = json.loads(subprocess.check_output(['git', 'show', 'fff91ffb:server/migrations/manifest.json'], cwd=SERVER.parent))
        self.assertEqual(manifest['states'][:len(original['states'])], original['states'])
        self.assertEqual(manifest['migrations'][:len(original['migrations'])], original['migrations'])
        migration.load_manifest(SERVER)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(CourseDiscoveryMigrationTests(name) for name in CourseDiscoveryMigrationTests.__dict__ if name.startswith('test_'))
