from concurrent.futures import ThreadPoolExecutor
import secrets
import unittest
from unittest.mock import patch

import psycopg
from fastapi import HTTPException
from account_handles import create_account
from private_records import VisitCipher
from team_rooms import CONSENTS
from team_trip_context import resolve_trip_context
import test_team_trips as trip_fixture


class TripMergeMemberTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = trip_fixture.TripTests
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)

    def setUp(self):
        self.h = self.fixture(methodName='test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.dsn, self.service = self.h.dsn, self.h.module.TEAM_TRIPS
        self.a, self.b, self.e = self.h.sessions()

    def internal(self, trip, account):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT r.room_id,r.owner_id,r.code_hash,r.expires_at,m.protected,m.joined_at,m.left_at '
                'FROM team_rooms r LEFT JOIN team_room_members m ON m.room_id=r.room_id AND m.account_id=%s '
                'WHERE r.trip_id=%s', (account['user']['id'], trip)).fetchone()
            member = self.h.module.TEAM_ROOMS.member_payload(account['user']['id'], row[0], row[4]) if row[4] else None
        return row, member

    def context(self, trip, session, **kwargs):
        with psycopg.connect(self.dsn) as conn:
            return resolve_trip_context(self.h.module.TEAM_AUTH, conn, trip, session['user']['id'], **kwargs)

    def test_creation_accept_retry_rejoin_and_pending_atomicity(self):
        self.h.befriend(self.a, self.b)
        trip = self.h.new_trip(self.a, members=(self.b,))
        row, member = self.internal(trip, self.a)
        self.assertEqual(row[1:4], (self.a['user']['id'], None, None))
        self.assertEqual(member, dict(role='member', consents={key:key == 'voice' for key in CONSENTS}))
        self.assertIsNone(self.internal(trip, self.b)[0][4])
        self.assertEqual(self.h.respond(trip, self.b)[0], 200)
        context = self.context(trip, self.a)
        with psycopg.connect(self.dsn) as conn:
            self.service.set_role(conn, trip, self.a['user']['id'], self.b['user']['id'], 'dj', context['revision'])
            self.service.set_sharing(conn, trip, self.b['user']['id'], {key:key == 'status' for key in CONSENTS})
        before = self.internal(trip, self.b)
        self.assertEqual(self.h.respond(trip, self.b)[0], 200)
        self.h.join(trip, self.a, self.b)
        self.assertEqual(self.internal(trip, self.b), before)
        path = '/' + trip + '/members/' + self.b['user']['id']
        self.assertEqual(self.h.trip(path, method='DELETE', session=self.b)[0], 200)
        self.assertIsNotNone(self.internal(trip, self.b)[0][6])
        self.h.join(trip, self.a, self.b)
        after, member = self.internal(trip, self.b)
        self.assertGreater(after[5], before[0][5])
        self.assertIsNone(after[6])
        self.assertEqual(member, dict(role='member', consents={key:key == 'voice' for key in CONSENTS}))

    def test_member_write_failure_rolls_back_trip_and_room(self):
        self.h.befriend(self.a, self.b)
        trip = self.h.new_trip(self.a, members=(self.b,))
        with patch('team_trips.activate_member', side_effect=HTTPException(409, 'Synthetic failure')):
            self.assertEqual(self.h.respond(trip, self.b)[0], 409)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(self.service.members(conn, trip)[self.b['user']['id']]['state'], 'pending')
        self.assertIsNone(self.internal(trip, self.b)[0][4])
        with patch('team_trips.create_internal_room', side_effect=HTTPException(409, 'Synthetic failure')):
            status = self.h.trip(data=dict(title='Rollback',description='',memberIds=[]),method='POST',session=self.a)[0]
        self.assertEqual(status, 409)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trips').fetchone()[0], 1)

    def test_lifecycle_owner_conflicts_idempotence_and_terminal_preservation(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        revision = self.context(trip, self.a)['revision']
        with psycopg.connect(self.dsn) as conn:
            with self.assertRaises(HTTPException) as error:
                self.service.transition(conn, trip, self.b['user']['id'], 'start', revision)
            self.assertEqual(error.exception.status_code, 403)
        with psycopg.connect(self.dsn) as conn:
            started = self.service.transition(conn, trip, self.a['user']['id'], 'start', revision)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(self.service.transition(conn, trip, self.a['user']['id'], 'start', revision), started)
        self.h.trip('/'+trip,dict(title='Changed',description=''),'PATCH',session=self.a)
        with psycopg.connect(self.dsn) as conn:
            with self.assertRaises(HTTPException) as error:
                self.service.transition(conn, trip, self.a['user']['id'], 'start', revision)
            self.assertEqual(error.exception.status_code, 409)
            with self.assertRaises(HTTPException) as error:
                self.service.transition(conn, trip, self.a['user']['id'], 'start', started['revision'])
            self.assertEqual(error.exception.status_code, 409)
        revision = self.context(trip, self.a)['revision']
        def finish():
            with psycopg.connect(self.dsn) as conn:
                return self.service.transition(conn, trip, self.a['user']['id'], 'finish', revision)
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _:finish(), range(2)))
        self.assertEqual(values[0], values[1])
        self.assertEqual(values[0]['state'], 'completed')
        self.assertIsNone(self.internal(trip, self.b)[0][6])
        self.assertEqual([(item['id'], item['state']) for item in self.h.trip(session=self.a)[2]['trips']],
            [(trip, 'completed')])
        self.assertEqual(self.h.trip('/'+trip,dict(title='No',description=''),'PATCH',session=self.a)[0], 409)
        self.assertEqual(self.h.trip('/'+trip,method='DELETE',session=self.a)[0], 200)
        self.assertEqual(self.h.trip(session=self.a)[2]['trips'], [])
        with psycopg.connect(self.dsn) as conn:
            for action in ('start', 'cancel'):
                with self.assertRaises(HTTPException) as error:
                    self.service.transition(conn, trip, self.a['user']['id'], action, values[0]['revision'])
                self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_members WHERE trip_id=%s', (trip,)).fetchone()[0], 2)

    def test_start_cancel_race_has_one_winner(self):
        trip = self.h.new_trip(self.a)
        revision = self.context(trip, self.a)['revision']
        def transition(action):
            try:
                with psycopg.connect(self.dsn) as conn:
                    return self.service.transition(conn, trip, self.a['user']['id'], action, revision)['state']
            except HTTPException as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(transition, ('start', 'cancel')))
        self.assertEqual(results.count(409), 1)
        self.assertEqual(sum(result in ('active', 'cancelled') for result in results), 1)

    def test_dj_replacement_and_closed_or_former_member_sharing_only_revoke(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        enabled = {key:key == 'status' for key in CONSENTS}
        disabled = {key:False for key in CONSENTS}
        with psycopg.connect(self.dsn) as conn:
            context = resolve_trip_context(self.h.module.TEAM_AUTH, conn, trip, self.a['user']['id'])
            result = self.service.set_role(conn, trip, self.a['user']['id'], self.a['user']['id'], 'dj', context['revision'])
            self.service.set_role(conn, trip, self.a['user']['id'], self.b['user']['id'], 'dj', result['revision'])
            self.service.set_sharing(conn, trip, self.a['user']['id'], enabled)
            self.service.set_sharing(conn, trip, self.b['user']['id'], enabled)
        self.assertEqual(self.internal(trip, self.a)[1]['role'], 'member')
        self.assertEqual(self.internal(trip, self.b)[1]['role'], 'dj')
        self.h.trip('/'+trip+'/members/'+self.b['user']['id'],method='DELETE',session=self.b)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(self.service.set_sharing(conn, trip, self.b['user']['id'], disabled)['consents'], disabled)
            with self.assertRaises(HTTPException) as error:
                self.service.set_sharing(conn, trip, self.b['user']['id'], enabled)
            self.assertEqual(error.exception.status_code, 409)
        self.h.close_trip(trip, self.a)
        with psycopg.connect(self.dsn) as conn:
            self.service.set_sharing(conn, trip, self.a['user']['id'], disabled)
            with self.assertRaises(HTTPException) as error:
                self.service.set_sharing(conn, trip, self.a['user']['id'], enabled)
            self.assertEqual(error.exception.status_code, 409)

    def test_block_between_members_preserves_both_owner_block_removes_nonowner(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        self.h.join(trip, self.a, self.e)
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.e['user']['id']), 'POST')[0], 201)
        for session in (self.b, self.e):
            self.assertEqual(self.context(trip, session)['state'], 'planned')
            self.assertIsNone(self.internal(trip, session)[0][6])
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.a['user']['id']), 'POST')[0], 201)
        self.assertIsNotNone(self.internal(trip, self.b)[0][6])
        with self.assertRaises(HTTPException) as error:
            self.context(trip, self.b)
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.context(trip, self.a)['state'], 'planned')

    def test_room_row_alone_never_grants_trip_access_and_mismatch_is_not_repaired(self):
        trip = self.h.new_trip(self.a)
        self.h.join(trip, self.a, self.b)
        row, _ = self.internal(trip, self.b)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('DELETE FROM team_trip_members WHERE trip_id=%s AND account_id=%s', (trip, self.b['user']['id']))
        with self.assertRaises(HTTPException) as error:
            self.context(trip, self.b)
        self.assertEqual(error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as error:
            self.context(trip, self.a)
        self.assertEqual(error.exception.detail, 'TRIP_MEMBERSHIP_INCONSISTENT')
        self.assertEqual(self.internal(trip, self.b)[0], row)

    def test_twenty_members_and_only_open_trips_count_toward_owner_limit(self):
        trip = self.h.new_trip(self.a)
        with psycopg.connect(self.dsn) as conn:
            for _ in range(19):
                account = 'team-' + secrets.token_hex(20)
                create_account(conn, account, VisitCipher().protect('team-account:'+account, 'identity', dict(email='synthetic@example.invalid')))
                self.service.save_member(conn, trip, account, 'accepted')
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_members WHERE room_id=(SELECT room_id FROM team_rooms WHERE trip_id=%s)', (trip,)).fetchone()[0], 20)
        token = self.h.trip('/'+trip+'/link', method='POST', session=self.a)[2]['token']
        self.assertEqual(self.h.link_request('trip', token, self.b, action='join')[0], 409)
        for _ in range(19):
            self.h.new_trip(self.a)
        data = dict(title='Limit', description='', memberIds=[])
        self.assertEqual(self.h.trip(data=data,method='POST',session=self.a)[0], 409)
        self.h.close_trip(trip, self.a)
        self.assertEqual(self.h.trip(data=data,method='POST',session=self.a)[0], 201)


if __name__ == '__main__':
    unittest.main(verbosity=2)
