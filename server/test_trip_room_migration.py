import secrets
import unittest
from unittest.mock import patch

import psycopg
from fastapi import HTTPException
from private_records import PrivateRecordError
from team_rooms import TeamRooms, CONSENTS
from team_trips import TeamTrips
from trip_room_migration import TripRoomMigration
import test_team_rooms as room_fixture


class TripRoomMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = room_fixture.RoomTests
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)

    def setUp(self):
        self.h = self.fixture(methodName='test_18_room_owner_member_roles_and_explicit_close')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.dsn = self.h.dsn
        self.migration = TripRoomMigration(self.h.module.TEAM_AUTH)
        self.a, self.b, self.e = self.h.sessions()

    def migrate(self, room):
        with psycopg.connect(self.dsn) as conn:
            return self.migration.migrate_room(conn, room)

    def original(self, room):
        with psycopg.connect(self.dsn) as conn:
            return dict(room=conn.execute('SELECT room_id,owner_id,protected,created_at,archived_music FROM team_rooms WHERE room_id=%s', (room,)).fetchone(),
                members=conn.execute('SELECT * FROM team_room_members WHERE room_id=%s ORDER BY account_id', (room,)).fetchall(),
                signals=conn.execute('SELECT * FROM team_room_signals WHERE room_id=%s ORDER BY signal_id', (room,)).fetchall(),
                history=conn.execute('SELECT * FROM team_room_history_saves WHERE room_id=%s ORDER BY account_id', (room,)).fetchall())

    def test_open_room_preserves_ciphertext_ids_consent_and_joined_time_on_retry(self):
        room = self.h.new_room(self.a, name='가'*80)
        rid = room['id']
        self.assertEqual(self.h.join(self.b, room['code'], status=True, location=True)[0], 200)
        self.assertEqual(self.h.room('/rooms/'+rid+'/role', dict(accountId=self.b['user']['id'], role='dj'), 'PATCH', session=self.a)[0], 200)
        self.h.room('/rooms/'+rid+'/signals', dict(kind='rest'), 'POST', 'bob', self.b)
        before = self.original(rid)
        self.assertTrue(self.migrate(rid))
        self.assertFalse(self.migrate(rid))
        self.assertEqual(self.original(rid), before)
        with psycopg.connect(self.dsn) as conn:
            trip, expiry, code = conn.execute('SELECT trip_id,expires_at,code_hash FROM team_rooms WHERE room_id=%s', (rid,)).fetchone()
            self.assertIsNone(expiry)
            self.assertIsNone(code)
            owner, value = self.migration.trips.load(conn, trip)
            self.assertEqual(value['title'], '가'*40)
            self.assertEqual(conn.execute('SELECT state,source_kind,started_at=created_at FROM team_trips WHERE trip_id=%s', (trip,)).fetchone(), ('active','legacy_room',True))
            self.assertEqual(len(self.migration.trips.members(conn, trip)), 2)
            self.assertEqual(self.migration.verify(conn), dict(trips=1, invalidTrips=0, unlinkedRooms=0))
        self.assertEqual(self.h.join(self.e, room['code'], who='eve')[0], 404)
        self.assertEqual(self.h.detail(rid, self.a)[0], 409)
        self.assertEqual(self.h.detail(rid, self.e, 'eve')[0], 404)

    def test_promoted_room_denies_legacy_service_routes_and_requires_explicit_context(self):
        room = self.h.new_room(self.a)
        rid = room['id']
        self.assertEqual(self.h.join(self.b, room['code'], music=True)[0], 200)
        self.assertEqual(self.h.share(rid, self.a, music=True)[0], 200)
        paths = ('/music', '/missions')
        retired='/rooms/'+rid+'/driving-data'
        self.assertEqual(self.h.room(retired,session=self.a)[0],404)
        for path in paths:
            self.assertEqual(self.h.room('/rooms/'+rid+path, session=self.a)[0], 200)
        self.assertTrue(self.migrate(rid))
        for session,who in ((self.a,'alice'),(self.b,'bob'),(self.e,'eve')):
            self.assertEqual(self.h.room(retired,session=session,who=who)[0],404)
        for path in paths:
            for session, who, status in ((self.a, 'alice', 409), (self.b, 'bob', 409), (self.e, 'eve', 404)):
                with self.subTest(path=path, who=who):
                    response = self.h.room('/rooms/'+rid+path, session=session, who=who)
                    self.assertEqual(response[0], status, response[2])
                    if status == 409:
                        self.assertEqual(response[2], dict(detail='TRIP_CLIENT_UPDATE_REQUIRED'))
        with psycopg.connect(self.dsn) as conn:
            rooms = self.migration.rooms
            for session, status in ((self.a, 409), (self.b, 409), (self.e, 404)):
                with self.assertRaises(HTTPException) as error:
                    rooms.access(conn, rid, session['user']['id'])
                self.assertEqual(error.exception.status_code, status)
            access = rooms.access(conn, rid, self.a['user']['id'], 'music', trip_context=True)
            self.assertIsNone(access['expiresAt'])
            self.assertIsNotNone(access['tripId'])
            with self.assertRaises(HTTPException) as error:
                rooms.access(conn, rid, self.e['user']['id'], trip_context=True)
            self.assertEqual(error.exception.status_code, 404)
            with self.assertRaises(HTTPException) as error:
                self.h.module.TEAM_AUTH.vehicle_service.member(conn, rid, self.a['user']['id'])
            self.assertEqual(error.exception.status_code, 409)

    def test_linked_room_ciphertext_and_payload_corruption_fail_verification_and_retry(self):
        room = self.h.new_room(self.a)['id']
        owner = self.a['user']['id']
        self.assertTrue(self.migrate(room))
        with psycopg.connect(self.dsn) as conn:
            trip, original = conn.execute('SELECT trip_id,protected FROM team_rooms WHERE room_id=%s', (room,)).fetchone()
        payload = TeamRooms.restore('owner:'+owner, room, original)
        corruptions = {
            'damaged': b'not-a-ciphertext',
            'wrong_owner': TeamRooms.protect('owner:'+self.b['user']['id'], room, payload),
            'wrong_room': TeamRooms.protect('owner:'+owner, secrets.token_hex(16), payload),
            'missing_field': TeamRooms.protect('owner:'+owner, room, {'name':payload['name']}),
            'invalid_name': TeamRooms.protect('owner:'+owner, room, dict(payload, name=[])),
            'invalid_code': TeamRooms.protect('owner:'+owner, room, dict(payload, code=42)),
            'invalid_course': TeamRooms.protect('owner:'+owner, room, dict(payload, courseVersion=True)),
            'invalid_preference': TeamRooms.protect('owner:'+owner, room, dict(payload, preference=[])),
        }
        for name, raw in corruptions.items():
            with self.subTest(corruption=name):
                try:
                    with psycopg.connect(self.dsn) as conn:
                        conn.execute('UPDATE team_rooms SET protected=%s WHERE room_id=%s', (raw, room))
                        self.assertEqual(self.migration.verify(conn), dict(trips=1, invalidTrips=1, unlinkedRooms=0))
                        with self.assertRaises(PrivateRecordError):
                            self.migration.migrate_trip(conn, trip)
                    with self.assertRaises(PrivateRecordError):
                        self.migrate(room)
                    self.assertEqual(self.migration.run(), dict(succeeded=0, skipped=0, failed=1,
                        trips=1, invalidTrips=1, unlinkedRooms=0))
                    with psycopg.connect(self.dsn) as conn:
                        self.assertEqual(conn.execute('SELECT trip_id,protected FROM team_rooms WHERE room_id=%s', (room,)).fetchone(), (trip, raw))
                finally:
                    with psycopg.connect(self.dsn) as conn:
                        conn.execute('UPDATE team_rooms SET protected=%s WHERE room_id=%s', (original, room))
        self.assertFalse(self.migrate(room))
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(self.migration.verify(conn), dict(trips=1, invalidTrips=0, unlinkedRooms=0))

    def test_expired_and_closed_rooms_preserve_former_members_without_rejoining(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                room = self.h.new_room(self.a)
                rid = room['id']
                self.h.join(self.b, room['code'])
                self.h.join(self.e, room['code'], who='eve')
                self.h.room('/rooms/'+rid+'/leave', method='POST', who='eve', session=self.e)
                with psycopg.connect(self.dsn) as conn:
                    conn.execute("UPDATE team_rooms SET created_at=now()-interval '2 days' WHERE room_id=%s", (rid,))
                    if expired:
                        conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 hour' WHERE room_id=%s", (rid,))
                    else:
                        conn.execute('UPDATE team_rooms SET closed_at=clock_timestamp(),archived_at=clock_timestamp() WHERE room_id=%s', (rid,))
                members = self.original(rid)['members']
                self.assertTrue(self.migrate(rid))
                with psycopg.connect(self.dsn) as conn:
                    trip = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s', (rid,)).fetchone()[0]
                    self.assertEqual(conn.execute('SELECT state FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()[0], 'completed')
                    self.assertNotIn(self.e['user']['id'], self.migration.trips.members(conn, trip))
                self.assertEqual(self.original(rid)['members'], members)

    def test_existing_trip_preserves_id_pending_and_creates_default_members(self):
        trip = secrets.token_hex(16)
        with psycopg.connect(self.dsn) as conn:
            owner = self.a['user']['id']
            conn.execute('INSERT INTO team_trips(trip_id,owner_id,protected) VALUES(%s,%s,%s)',
                (trip, owner, TeamTrips.protect('owner:'+owner, trip, dict(title='Existing',description=''))))
            for session, state in ((self.a,'accepted'),(self.b,'accepted'),(self.e,'pending')):
                account = session['user']['id']
                value = dict(state=state, via='friend', permissions=dict(invite=account==owner, edit=account==owner))
                conn.execute('INSERT INTO team_trip_members VALUES(%s,%s,%s)',
                    (trip, account, TeamTrips.protect('member:'+account, trip, value)))
            original = conn.execute('SELECT protected FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0]
            self.assertEqual(self.migration.verify(conn)['invalidTrips'], 1)
            self.assertTrue(self.migration.migrate_trip(conn, trip))
            self.assertFalse(self.migration.migrate_trip(conn, trip))
            room = self.migration.validate_trip(conn, trip)
            self.assertEqual(conn.execute('SELECT protected FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0], original)
            rows = conn.execute('SELECT account_id,protected FROM team_room_members WHERE room_id=%s',(room,)).fetchall()
            self.assertEqual(len(rows), 2)
            for account, raw in rows:
                self.assertEqual(TeamRooms(self.h.module.TEAM_AUTH).member_payload(account,room,raw),
                    dict(role='member',consents={key:key=='voice' for key in CONSENTS}))

    def test_interruption_rolls_back_one_room_and_retry_does_not_duplicate(self):
        room = self.h.new_room(self.a)['id']
        before = self.original(room)
        with patch.object(self.migration, 'validate_trip', side_effect=PrivateRecordError('Synthetic interruption')):
            with self.assertRaises(PrivateRecordError):
                self.migrate(room)
        self.assertEqual(self.original(room), before)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trips').fetchone()[0], 0)
            self.assertIsNone(conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s', (room,)).fetchone()[0])
        self.assertTrue(self.migrate(room))
        self.assertFalse(self.migrate(room))

    def test_missing_owner_membership_stops_without_manufacturing_consent(self):
        room = self.h.new_room(self.a)['id']
        with psycopg.connect(self.dsn) as conn:
            conn.execute('DELETE FROM team_room_members WHERE room_id=%s', (room,))
        with self.assertRaises(PrivateRecordError):
            self.migrate(room)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trips').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_members').fetchone()[0], 0)
            self.assertEqual(self.migration.verify(conn)['unlinkedRooms'], 1)

    def test_owner_limit_does_not_discard_legacy_rooms_and_invalid_rows_stay_unlinked(self):
        owner = self.a['user']['id']
        with psycopg.connect(self.dsn) as conn:
            for _ in range(21):
                room = secrets.token_hex(16)
                payload = dict(name='Legacy',code='ABCDEFGH',courseId=None,courseVersion=None,preference='balanced')
                conn.execute("INSERT INTO team_rooms(room_id,owner_id,code_hash,protected,expires_at) VALUES(%s,%s,%s,%s,now()+interval '1 day')",
                    (room,owner,secrets.token_hex(32),TeamRooms.protect('owner:'+owner,room,payload)))
                member = dict(role='member',consents={key:False for key in CONSENTS})
                conn.execute('INSERT INTO team_room_members(room_id,account_id,protected) VALUES(%s,%s,%s)',
                    (room,owner,TeamRooms.protect('member:'+owner,room,member)))
        report = self.migration.run()
        self.assertEqual((report['succeeded'],report['failed'],report['invalidTrips'],report['unlinkedRooms']), (21,0,0,0))
        self.assertEqual(self.migration.run()['skipped'],21)
        with psycopg.connect(self.dsn) as conn:
            room = conn.execute('SELECT room_id FROM team_rooms ORDER BY room_id LIMIT 1').fetchone()[0]
            conn.execute('UPDATE team_room_members SET left_at=clock_timestamp() WHERE room_id=%s', (room,))
            self.assertEqual(self.migration.verify(conn)['invalidTrips'],1)
        status, _, value = self.h.room('/rooms', dict(name='Bad',courseId=None,courseVersion=None,expiresInHours=1), 'POST', who='bob', session=self.b)
        self.assertEqual(status, 201)
        bad = value['id']
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE team_rooms SET protected=%s WHERE room_id=%s', (b'not-a-ciphertext',bad))
        with self.assertRaises(PrivateRecordError):
            self.migrate(bad)
        with psycopg.connect(self.dsn) as conn:
            self.assertIsNone(conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s',(bad,)).fetchone()[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
