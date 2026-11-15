from pathlib import Path
import unittest

import psycopg
import test_team_auth as fixture


TABLES = ('team_driving_samples', 'team_driving_sessions', 'team_driving_grants')


class RetiredDrivingDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def test_fresh_schema_retains_legacy_tables_without_collection_or_analysis(self):
        with psycopg.connect(fixture.TeamTests.dsn) as conn:
            for table in TABLES:
                self.assertIsNotNone(conn.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0])
                self.assertEqual(conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        app = fixture.TeamTests.module.app
        self.assertFalse(any('/driving-data' in getattr(route, 'path', '') for route in app.routes))
        self.assertFalse(fixture.TeamTests.module.TEAM_AUTH.capabilities()['drivingData'])
        self.assertFalse(any('/driving-data' in path for path in app.openapi()['paths']))

    def test_cleanup_drops_only_legacy_tables_and_can_run_again(self):
        script = Path(__file__).with_name('ops').joinpath('retire-driving-data.sql').read_text()
        with psycopg.connect(fixture.TeamTests.dsn, autocommit=True) as conn:
            conn.execute('CREATE SCHEMA driving_cleanup_fixture')
            conn.execute('SET search_path TO driving_cleanup_fixture')
            conn.execute('CREATE TABLE team_driving_grants(id int PRIMARY KEY)')
            conn.execute('CREATE TABLE team_driving_sessions(id int PRIMARY KEY, grant_id int REFERENCES team_driving_grants(id))')
            conn.execute('CREATE TABLE team_driving_samples(id int PRIMARY KEY, session_id int REFERENCES team_driving_sessions(id))')
            conn.execute('INSERT INTO team_driving_grants VALUES(1)')
            conn.execute('INSERT INTO team_driving_sessions VALUES(2,1)')
            conn.execute('INSERT INTO team_driving_samples VALUES(3,2)')
            for _ in range(2):
                conn.execute(script)
                for table in TABLES:
                    self.assertIsNone(conn.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0])
            for table in (*TABLES, 'team_accounts', 'team_trips', 'team_history_visits'):
                self.assertIsNotNone(conn.execute('SELECT to_regclass(%s)', (f'public.{table}',)).fetchone()[0])


if __name__ == '__main__':
    unittest.main()
