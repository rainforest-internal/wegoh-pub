"""Course save times, aggregate metrics views and the read-only Grafana role."""
from datetime import datetime, time, timedelta
import os
import secrets
import subprocess
import unittest
from zoneinfo import ZoneInfo

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from ops.live import migration_pipeline as migration
from ops.live.test_migration_integrity import MigrationIntegrityTests, SERVER, SCHEMA_NAMES

SEOUL = ZoneInfo('Asia/Seoul')
ROLE_SQL = SERVER / 'ops/observability/grafana-postgres-role.sql'


def account(letter):
    return 'team-' + letter * 40


class ProductMetricsTests(MigrationIntegrityTests):
    def test_upgrade_adds_save_time_and_metrics_schemas(self):
        manifest = migration.load_manifest(SERVER)
        steps = {item['id']: item for item in manifest['migrations']}
        star, views = steps['course_star_times_v1'], steps['product_metrics_v1']
        states = {item['version']: item for item in manifest['states']}
        self.assertEqual((star['from'], star['to'], star['oldCodeCompatible']), ('iphone_push_v1', 'course_star_times_v1', True))
        self.assertEqual((views['from'], views['to'], views['oldCodeCompatible']), ('course_star_times_v1', 'product_metrics_v1', True))
        self.assertEqual(manifest['targetVersion'], 'product_metrics_v1')
        with psycopg.connect(self.source) as conn:
            for old in manifest['migrations']:
                if old['id'] == star['id']:
                    break
                conn.execute((SERVER / old['path']).read_text())
            self.assertEqual(migration.catalog_digest(conn), states[star['from']]['catalogSha256'])
            creator = conn.execute('SELECT account_id FROM team_accounts ORDER BY account_id LIMIT 1').fetchone()[0]
            conn.execute("INSERT INTO pack_versions(pack_id,version,creator_id,checksum,title,author,description,stop_count) "
                         "VALUES('old-course',1,%s,%s,'t','a','d',1)", (creator, 'c' * 64))
            conn.execute("INSERT INTO team_course_stars(pack_id,version,account_id) VALUES('old-course',1,%s)", (creator,))
            for step in (star, views):
                conn.execute((SERVER / step['path']).read_text())
                self.assertEqual(migration.catalog_digest(conn), states[step['to']]['catalogSha256'])
            self.assertIsNotNone(conn.execute('SELECT starred_at FROM team_course_stars').fetchone()[0])
            # The unchanged save statement records its own time through the default.
            conn.execute('DELETE FROM team_course_stars')
            conn.execute("INSERT INTO team_course_stars(pack_id,version,account_id) VALUES('old-course',1,%s)", (creator,))
            saved = conn.execute('SELECT starred_at, now() FROM team_course_stars').fetchone()
            self.assertEqual(saved[0], saved[1])
            for step in (star, views):
                conn.execute((SERVER / step['path']).read_text())
            self.assertEqual(migration.catalog_digest(conn), states[views['to']]['catalogSha256'])
        fresh = self.database('metrics_fresh')
        with psycopg.connect(fresh) as conn:
            for name in SCHEMA_NAMES:
                conn.execute((SERVER / name).read_text())
            self.assertEqual(migration.catalog_digest(conn), states[views['to']]['catalogSha256'])

    def fixture(self):
        dsn = self.database('metrics')
        today = datetime.now(SEOUL).date()

        def at(days_ago, hour=12):
            return datetime.combine(today - timedelta(days=days_ago), time(hour), SEOUL)

        a, b, c, d = (account(x) for x in 'abcd')
        with psycopg.connect(dsn) as conn:
            for name in SCHEMA_NAMES:
                conn.execute((SERVER / name).read_text())
            for who, status in ((a, 'active'), (b, 'active'), (c, 'active'), (d, 'deleted')):
                conn.execute('INSERT INTO team_accounts(account_id,protected,created_at,account_status) VALUES(%s,%s,%s,%s)',
                             (who, b'x', at(120), status))

            def trip(trip_id, members, started, ended=None, cars=()):
                state = 'completed' if ended is not None else 'active'
                conn.execute('INSERT INTO team_trips(trip_id,owner_id,protected,state,started_at,ended_at) VALUES(%s,%s,%s,%s,%s,%s)',
                             (trip_id, members[0], b'x', state, at(started), None if ended is None else at(ended)))
                for member in members:
                    conn.execute('INSERT INTO team_trip_members(trip_id,account_id,protected) VALUES(%s,%s,%s)', (trip_id, member, b'x'))
                for ordinal, driver in enumerate(cars, 1):
                    conn.execute('INSERT INTO team_trip_cars(trip_id,car_id,driver_id,protected,created_at,ordinal) '
                                 'VALUES(%s,%s,%s,%s,%s,%s)', (trip_id, str(ordinal) * 32, driver, b'x', at(started), ordinal))

            # A and B finish their first trip 99 days ago in two cars with B's course.
            conn.execute("INSERT INTO pack_versions(pack_id,version,creator_id,checksum,title,author,description,stop_count,created_at) "
                         "VALUES('b-course',1,%s,%s,'t','a','d',1,%s)", (b, 'b' * 64, at(110)))
            trip('1' * 32, [a, b], 100, 99, cars=(a, b))
            conn.execute('INSERT INTO team_trip_courses(trip_id,pack_id,added_by,protected,created_at) VALUES(%s,%s,%s,%s,%s)',
                         ('1' * 32, 'b-course', a, b'x', at(101)))
            # Day 30 after the first trip: A saves B's course (returns). Day 60: B only shares (outside the window).
            conn.execute("INSERT INTO team_course_stars(pack_id,version,account_id,starred_at) VALUES('b-course',1,%s,%s)", (a, at(69)))
            conn.execute("INSERT INTO pack_versions(pack_id,version,creator_id,checksum,title,author,description,stop_count,created_at) "
                         "VALUES('b-course',2,%s,%s,'t','a','d',1,%s)", (b, 'e' * 64, at(39)))
            # A starts a separate trip on day 90, B on day 91.
            trip('2' * 32, [a], 9)
            trip('3' * 32, [b], 8)
            # C finished a first trip 40 days ago, so the 30-59 day window is still open.
            trip('4' * 32, [c], 41, 40)
            # Today: A follows B, B raises a hand, C asks to control a vehicle, deleted D saves a course.
            conn.execute('INSERT INTO team_creator_follows(follower_id,creator_id,followed_at) VALUES(%s,%s,%s)', (a, b, at(0)))
            conn.execute('INSERT INTO team_rooms(room_id,owner_id,code_hash,protected,expires_at) VALUES(%s,%s,%s,%s,%s)',
                         ('r' * 32, b, 'f' * 64, b'x', at(-1)))
            conn.execute('INSERT INTO team_room_signals(signal_id,room_id,account_id,protected,created_at) VALUES(%s,%s,%s,%s,%s)',
                         ('s' * 32, 'r' * 32, b, b'x', at(0)))
            conn.execute("INSERT INTO native_device_refs(device_id,kind) VALUES(%s,'native')", ('d' * 32,))
            conn.execute('INSERT INTO friend_vehicle_commands(request_id,device_id,requester_id,owner_id,event_hash,protected,created_at) '
                         'VALUES(%s,%s,%s,%s,%s,%s,%s)', ('q1', 'd' * 32, c, a, 'h1', b'x', at(0)))
            conn.execute("INSERT INTO team_course_stars(pack_id,version,account_id,starred_at) VALUES('b-course',2,%s,%s)", (d, at(0)))
        activity = {(a, 100), (b, 100), (a, 101), (b, 110), (a, 69), (b, 39), (a, 9), (b, 8), (c, 41), (a, 0), (b, 0), (c, 0)}
        return dsn, today, activity

    def test_views_follow_the_submission_definitions(self):
        dsn, today, activity = self.fixture()
        with psycopg.connect(dsn) as conn:
            overview = conn.execute('SELECT today,dau,mau,total_users,vehicle_connected_users FROM metrics.overview').fetchone()
            month_start = today.replace(day=1)
            mau = len({who for who, days_ago in activity if today - timedelta(days=days_ago) >= month_start})
            self.assertEqual(overview, (today, 3, mau, 3, 0))
            daily = dict(conn.execute('SELECT day, active_users FROM metrics.daily_users').fetchall())
            self.assertEqual(daily[today - timedelta(days=100)], 2)
            self.assertEqual(daily[today - timedelta(days=50)], 0)
            self.assertEqual(len(daily), 121)
            self.assertEqual(conn.execute('SELECT total_users FROM metrics.daily_users WHERE day=%s', (today,)).fetchone()[0], 3)

            cohorts = {row[0]: row[1:] for row in conn.execute(
                'SELECT cohort_month, first_trip_users, returned_30_59_users, returned_30_59_measurable, returned_30_59_rate, '
                'returned_30_59_measurable_on, retrip_90_users, retrip_90_measurable, retrip_90_rate FROM metrics.retention_cohorts')}
            first = (today - timedelta(days=99)).replace(day=1)
            late = (today - timedelta(days=40)).replace(day=1)
            self.assertEqual(cohorts[first][:4], (2, 1, True, 0.5))
            self.assertEqual(cohorts[first][5:], (1, True, 0.5))
            self.assertEqual(cohorts[late], (1, 0, False, None, today + timedelta(days=20), 0, False, None))
            self.assertEqual(conn.execute('SELECT * FROM metrics.retention_overview').fetchone(),
                             (3, 2, 1, 0.5, today + timedelta(days=20), 2, 1, 0.5, today + timedelta(days=51)))

            trips = conn.execute('SELECT started_trips, multi_car_trips, multi_car_share, average_members '
                                 'FROM metrics.monthly_trips WHERE month=%s', ((today - timedelta(days=100)).replace(day=1),)).fetchone()
            self.assertEqual(trips[1:3], (1, 1))
            flow = conn.execute('SELECT courses_saved, others_courses_loaded, trips_with_others_course '
                                'FROM metrics.monthly_course_flow WHERE month=%s', ((today - timedelta(days=69)).replace(day=1),)).fetchone()
            self.assertEqual(flow[0], 1)
            group = conn.execute('SELECT hand_raises, vehicle_control_requests, hand_raise_replies '
                                 'FROM metrics.monthly_group_actions WHERE month=%s', (month_start,)).fetchone()
            self.assertEqual(group, (1, 1, 0))
            self.assertEqual(conn.execute('SELECT trips_with_others_course FROM metrics.monthly_course_flow WHERE month=%s',
                                          ((today - timedelta(days=100)).replace(day=1),)).fetchone()[0], 1)

            columns = conn.execute("SELECT table_name, column_name FROM information_schema.columns "
                                   "WHERE table_schema='metrics' ORDER BY 1, 2").fetchall()
            self.assertEqual({table for table, _ in columns}, {
                'daily_users', 'monthly_users', 'overview', 'retention_cohorts', 'retention_overview',
                'monthly_trips', 'monthly_group_actions', 'monthly_course_flow'})
            self.assertFalse([column for _, column in columns if 'account' in column or column.endswith('_id')])

    def test_grafana_role_reads_only_aggregate_views(self):
        dsn, today, _ = self.fixture()
        password = secrets.token_hex(32)
        password_file = self.work / 'grafana-postgres-password'
        password_file.write_text(password + '\n')
        params = conninfo_to_dict(dsn)
        owner = params['user']
        env = dict(os.environ, PGHOST=params['host'], PGPORT=str(params['port']), PGUSER=owner,
                   PGPASSWORD=params['password'], PGDATABASE=params['dbname'])
        command = [self.tools['psql'], '-X', '-q', '-v', f'password_file={password_file}', '-v', f'view_owner={owner}']
        with ROLE_SQL.open('rb') as script:
            subprocess.run(command, stdin=script, env=env, check=True, capture_output=True, timeout=30)
            script.seek(0)  # Re-running keeps the role and grants.
            subprocess.run(command, stdin=script, env=env, check=True, capture_output=True, timeout=30)
        grafana = make_conninfo(dsn, user='wegoh_grafana', password=password)
        with psycopg.connect(grafana) as conn:
            self.assertEqual(conn.execute('SELECT dau FROM overview').fetchone()[0], 3)
            self.assertEqual(conn.execute('SHOW statement_timeout').fetchone()[0], '5s')
            self.assertEqual(conn.execute('SHOW TimeZone').fetchone()[0], 'Asia/Seoul')
        for statement in ('SELECT count(*) FROM public.team_accounts', 'SELECT count(*) FROM public.team_course_stars',
                          'SELECT count(*) FROM metrics_private.account_activity'):
            with self.subTest(statement=statement), psycopg.connect(grafana) as conn:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(statement)
        with psycopg.connect(grafana) as conn:
            self.assertEqual(conn.execute('SHOW default_transaction_read_only').fetchone()[0], 'on')
        short = self.work / 'short-password'
        short.write_text('short\n')
        with ROLE_SQL.open('rb') as script:
            result = subprocess.run([self.tools['psql'], '-X', '-q', '-v', f'password_file={short}', '-v', f'view_owner={owner}'],
                                    stdin=script, env=env, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(ProductMetricsTests(name) for name in ProductMetricsTests.__dict__ if name.startswith('test_'))
