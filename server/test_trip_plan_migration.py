from pathlib import Path
import hashlib
import secrets
import subprocess
import tempfile
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from ops.live.migration_pipeline import catalog_digest, load_manifest, plan_transition, schema_version
from test_trip_merge_api import TripApiFixture


def historical_route_server(test):
    revision='f175cda782199c6c6ab4e87374e73673e368a837'
    root=Path(__file__).resolve().parents[1]
    temporary=tempfile.TemporaryDirectory(prefix='wegoh-route20-contract-')
    test.addCleanup(temporary.cleanup)
    server=Path(temporary.name)/'server'
    paths=['server/'+name for name in ('schema.sql','enrollment_schema.sql','native_access_schema.sql','native_functional_schema.sql')]
    paths+=subprocess.check_output(['git','ls-tree','-r','--name-only',revision,'--','server/migrations'],cwd=root).decode().splitlines()
    for name in paths:
        target=Path(temporary.name)/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','show',revision+':'+name],cwd=root))
    historical=load_manifest(server)
    current=load_manifest(root/'server')
    test.assertEqual(current['states'][:len(historical['states'])],historical['states'])
    test.assertEqual(current['migrations'][:len(historical['migrations'])],historical['migrations'])
    return server


class TripMigrationContractTests(unittest.TestCase):
    def test_score_release_is_recognized_and_segmented_route_blocks_code_rollback(self):
        server=historical_route_server(self)
        manifest=load_manifest(server)
        states={state['version']:state for state in manifest['states']}
        score=states['trip_driving_scores_v1']
        route=states['trip_route_segments_v2']
        self.assertEqual(schema_version(manifest,score['schemaFiles']),'trip_driving_scores_v1')
        step=next(step for step in manifest['migrations'] if step['id']=='trip_driving_scores_v1')
        self.assertEqual((step['from'],step['rollbackFloor'],step['oldCodeCompatible']),
            ('trip_course_waypoints_v1','trip_course_waypoints_v1',True))
        plan=plan_transition(server,server,score['schemaFiles'],route['schemaFiles'])
        self.assertEqual(plan['schema'],
            {'from':'trip_driving_scores_v1','to':'trip_route_segments_v2','rollbackFloor':'trip_route_segments_v2'})
        self.assertFalse(plan['canRollback'])
        self.assertEqual([item['id'] for item in plan['migrations']],['trip_route_segments_v2'])


class TripPlanMigrationTests(TripApiFixture):
    def test_fresh_upgrade_reapply_and_populated_ciphertext_preservation(self):
        server=historical_route_server(self)
        manifest=load_manifest(server)
        states={state['version']: state['catalogSha256'] for state in manifest['states']}
        step=(server/'migrations/0009_trip_plan.sql').read_bytes()
        iphone_step=(server/'migrations/0011_iphone_sessions.sql').read_bytes()
        tags_step=(server/'migrations/0012_course_tags.sql').read_bytes()
        priority_step=(server/'migrations/0013_trip_course_priority.sql').read_bytes()
        cover_step=(server/'migrations/0016_pack_course_covers.sql').read_bytes()
        message_step=(server/'migrations/0017_trip_messages.sql').read_bytes()
        waypoint_step=(server/'migrations/0018_trip_course_waypoints.sql').read_bytes()
        score_step=(server/'migrations/0019_trip_driving_scores.sql').read_bytes()
        route_step=(server/'migrations/0020_trip_route_segments.sql').read_bytes()
        full_schema=(server/'schema.sql').read_bytes()
        self.assertTrue(full_schema.endswith(b'\n'+route_step))
        score_schema=full_schema.removesuffix(b'\n'+route_step)
        self.assertEqual(score_schema.count(b'\n'+score_step),1)
        legacy_schema=score_schema.replace(b'\n'+score_step,b'',1)
        self.assertEqual(hashlib.sha256(legacy_schema).hexdigest(),
            next(state for state in manifest['states'] if state['version']=='trip_course_waypoints_v1')['schemaFiles']['server/schema.sql'])
        self.assertEqual(hashlib.sha256(score_schema).hexdigest(),
            next(state for state in manifest['states'] if state['version']=='trip_driving_scores_v1')['schemaFiles']['server/schema.sql'])
        self.assertEqual(hashlib.sha256(full_schema).hexdigest(),
            next(state for state in manifest['states'] if state['version']=='trip_route_segments_v2')['schemaFiles']['server/schema.sql'])
        trip_schema=legacy_schema.removesuffix(waypoint_step).removesuffix(b'\n'+message_step).removesuffix(cover_step).removesuffix(b'\n'+priority_step).removesuffix(tags_step).removesuffix(iphone_step)
        before=trip_schema.removesuffix(b'\n'+step)
        remote_step=(server/'migrations/0010_trip_remote_grants.sql').read_bytes()
        functional_before=(server/'native_functional_schema.sql').read_bytes().removesuffix(b'\n'+remote_step)
        names=['schema.sql','enrollment_schema.sql','native_access_schema.sql','native_functional_schema.sql']
        databases=[]
        def cleanup():
            with psycopg.connect(self.dsn,autocommit=True) as conn:
                for name in databases:
                    conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        self.addCleanup(cleanup)
        digests=[]
        for upgrade in (False,True):
            name='trip_plan_'+secrets.token_hex(8)
            with psycopg.connect(self.dsn,autocommit=True) as conn:
                conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
            databases.append(name)
            with psycopg.connect(make_conninfo(self.dsn,dbname=name)) as conn:
                for schema in names:
                    if schema=='schema.sql':
                        conn.execute((before if upgrade else full_schema).decode())
                    elif upgrade and schema=='native_functional_schema.sql':
                        conn.execute(functional_before.decode())
                    else:
                        conn.execute((server/schema).read_text())
                if upgrade:
                    self.assertEqual(catalog_digest(conn),states['trip_room_merge_v1'])
                    account='team-'+'a'*40;trip='b'*32
                    conn.execute('INSERT INTO team_accounts(account_id,protected) VALUES(%s,%s)',(account,b'opaque-account'))
                    conn.execute('INSERT INTO team_trips(trip_id,owner_id,protected) VALUES(%s,%s,%s)',(trip,account,b'opaque-trip'))
                    conn.execute(step.decode())
                    self.assertEqual(conn.execute('SELECT protected,start_date,end_date FROM team_trips WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-trip',None,None))
                    self.assertEqual(catalog_digest(conn),states['trip_plan_v1'])
                    conn.execute(remote_step.decode())
                    self.assertEqual(catalog_digest(conn),states['trip_remote_grants_v1'])
                    conn.execute(iphone_step.decode())
                    self.assertEqual(catalog_digest(conn),states['iphone_sessions_v1'])
                    conn.execute(tags_step.decode())
                    self.assertEqual(catalog_digest(conn),states['course_tags_v1'])
                    conn.execute('INSERT INTO team_trip_courses(trip_id,pack_id,added_by,protected) VALUES(%s,%s,%s,%s)',
                        (trip,'legacy-course',account,b'opaque-course'))
                    conn.execute(priority_step.decode())
                    self.assertEqual(conn.execute('SELECT protected,priority FROM team_trip_courses WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-course',None))
                    self.assertEqual(catalog_digest(conn),states['trip_course_priority_v1'])
                    conn.execute(cover_step.decode())
                    self.assertEqual(catalog_digest(conn),states['pack_course_covers_v1'])
                    conn.execute(message_step.decode())
                    self.assertEqual(catalog_digest(conn),states['trip_messages_v1'])
                    conn.execute('INSERT INTO team_trip_messages(trip_id,sender_id,message_id,protected) VALUES(%s,%s,%s,%s)',
                        (trip,account,'c'*32,b'opaque-message'))
                    self.assertEqual(conn.execute('SELECT protected FROM team_trips WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-trip',))
                    conn.execute(waypoint_step.decode())
                    self.assertEqual(conn.execute('SELECT protected,waypoints FROM team_trip_courses WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-course',None))
                    self.assertEqual(catalog_digest(conn),states['trip_course_waypoints_v1'])
                    conn.execute(score_step.decode())
                    self.assertEqual(catalog_digest(conn),states['trip_driving_scores_v1'])
                    conn.execute('INSERT INTO team_trip_members(trip_id,account_id,protected) VALUES(%s,%s,%s)',
                        (trip,account,b'opaque-member'))
                    car='d'*32
                    conn.execute('INSERT INTO team_trip_cars(trip_id,car_id,driver_id,protected) VALUES(%s,%s,%s,%s)',
                        (trip,car,account,b'opaque-car'))
                    conn.execute('INSERT INTO pack_versions(pack_id,version,creator_id,checksum,title,author,description,stop_count) '
                        'VALUES(%s,1,%s,%s,%s,%s,%s,1)',
                        ('legacy-course',account,'e'*64,'legacy','legacy',''))
                    conn.execute('INSERT INTO team_trip_car_driving_scores(trip_id,car_id,pack_id,version,protected) '
                        'VALUES(%s,%s,%s,1,%s)',(trip,car,'legacy-course',b'opaque-score'))
                    conn.execute(route_step.decode())
                    self.assertEqual(catalog_digest(conn),states['trip_route_segments_v2'])
                    conn.execute('INSERT INTO team_trip_route_plans(trip_id,protected) VALUES(%s,%s)',
                        (trip,b'opaque-route-plan'))
                digest=catalog_digest(conn)
                conn.execute(step.decode())
                conn.execute(remote_step.decode())
                conn.execute(iphone_step.decode())
                conn.execute(tags_step.decode())
                conn.execute(priority_step.decode())
                conn.execute(cover_step.decode())
                conn.execute(message_step.decode())
                conn.execute(waypoint_step.decode())
                conn.execute(score_step.decode())
                conn.execute(route_step.decode())
                if upgrade:
                    self.assertEqual(conn.execute('SELECT protected FROM team_trip_messages WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-message',))
                    self.assertEqual(conn.execute('SELECT protected FROM team_trips WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-trip',))
                    self.assertEqual(conn.execute('SELECT protected,waypoints FROM team_trip_courses WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-course',None))
                    self.assertEqual(conn.execute('SELECT protected FROM team_trip_car_driving_scores WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-score',))
                    self.assertEqual(conn.execute('SELECT protected FROM team_trip_route_plans WHERE trip_id=%s',(trip,)).fetchone(),
                        (b'opaque-route-plan',))
                self.assertEqual(catalog_digest(conn),digest)
                self.assertEqual(digest,states['trip_route_segments_v2'])
                digests.append(digest)
        self.assertEqual(digests[0],digests[1])


if __name__ == '__main__':
    unittest.main()
