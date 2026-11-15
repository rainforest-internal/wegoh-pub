"""Exact handle discovery against synthetic accounts and isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import unittest
import time
from unittest.mock import patch
from urllib.parse import quote

from fastapi import HTTPException
import psycopg
from account_handles import create_account, default_handle, normalize_handle
from private_records import VisitCipher
import test_team_auth as fixture

SEED_PATH = Path(__file__).parent / 'ops/dev/seed_friend_accounts.py'
spec = importlib.util.spec_from_file_location('seed_friend_accounts', SEED_PATH)
seed_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_module)


class HandleFormatTests(unittest.TestCase):
    def test_generated_handle_is_stable_valid_and_collision_attempt_changes_it(self):
        first = default_handle('team-synthetic')
        self.assertEqual(first, default_handle('team-synthetic'))
        self.assertRegex(first, r'^user_[0-9a-f]{15}$')
        self.assertEqual(normalize_handle(first), first)
        self.assertNotEqual(first, default_handle('team-synthetic', 1))
        self.assertNotEqual(first, default_handle('team-other'))

    def test_handle_request_schema_has_authored_field_descriptions(self):
        from copy import deepcopy
        from api_doc_catalog import describe_fields
        from team_api_docs import BODY
        schema = deepcopy(BODY[('put', '/v1/profile/handle')])
        describe_fields(schema)
        for field in ('handle', 'expectedHandle'):
            self.assertTrue(schema['properties'][field]['description'])

    def test_ascii_normalization_and_bounds(self):
        for raw, expected in [('Hana', 'hana'), ('@HANA', 'hana'), ('a_b.c', 'a_b.c'), ('a'*20, 'a'*20)]:
            self.assertEqual(normalize_handle(raw), expected)
        for raw in [None, 1, '', 'ab', 'a'*21, '.abc', '_abc', ' abc', 'abc ', 'a-b', 'a@b', '@@abc', '이름', 'Kelvin', 'a\n', 'a@example.invalid']:
            with self.subTest(raw=raw), self.assertRaises(HTTPException):
                normalize_handle(raw)

    def test_dev_seed_fails_closed_before_connection(self):
        valid = 'host=127.0.0.1 dbname=wegohdev user=wegohdev'
        seed_module.validate_target(valid, allowed=True, environment='development')
        for dsn, allowed, env in [(valid, False, 'development'), (valid, True, 'production'),
                ('host=remote dbname=wegohdev user=wegohdev', True, 'development'),
                ('host=127.0.0.1 dbname=wegoh_live user=wegohdemo', True, 'development'),
                (valid+' hostaddr=192.0.2.1', True, 'development')]:
            with self.subTest(dsn=dsn), self.assertRaises(ValueError):
                seed_module.validate_target(dsn, allowed=allowed, environment=env)


class AccountHandleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.api = fixture.TeamTests('test_01_jwt_verification_and_exact_hosts')
        self.api.setUp()
        self.dsn = self.api.dsn
        self.alice = self.api.login()
        self.bob = self.api.login('bob')
        self.a = self.alice['user']['id']
        self.b = self.bob['user']['id']

    def search(self, handle, *, session=None, who='alice'):
        return self.api.call('/v1/social/friends/search?handle='+quote(handle, safe=''), session=session or self.alice, who=who)

    def update(self, session, handle, *, who='alice', **kw):
        return self.api.call('/v1/profile/handle', dict(handle=handle, expectedHandle=session['user']['handle']), 'PUT', session=session, who=who, **kw)

    def test_handle_unique_format_csrf_cas_and_persistent_cooldown(self):
        self.assertEqual(self.update(self.alice, 'hana', csrf=False)[0], 403)
        self.assertEqual(self.update(self.alice, 'hana', origin='https://evil.invalid')[0], 403)
        self.assertEqual(self.update(self.alice, 'bad name')[0], 400)
        self.assertEqual(self.update(self.alice, '@Hana')[2], {'handle':'hana'})
        self.assertEqual(self.update(self.bob, 'HANA', who='bob')[0], 409)
        self.assertEqual(self.update(self.alice, 'other')[0], 409)
        self.alice['user']['handle'] = 'hana'
        self.assertEqual(self.update(self.alice, 'other')[0], 429)
        with psycopg.connect(self.dsn) as conn:
            conn.execute('TRUNCATE team_rate_limits')
        self.assertEqual(self.update(self.alice, 'other')[0], 429)
        self.assertEqual(self.update(self.alice, 'HANA')[0], 200)
        self.assertEqual(self.api.login()['user']['handle'], 'hana')
        with psycopg.connect(self.dsn) as conn:
            with self.assertRaises(psycopg.errors.UniqueViolation), conn.transaction():
                conn.execute('UPDATE team_accounts SET handle=%s WHERE account_id=%s', ('hana', self.b))
            with self.assertRaises(psycopg.errors.CheckViolation), conn.transaction():
                conn.execute('UPDATE team_accounts SET handle=%s WHERE account_id=%s', ('a-b', self.b))

    def test_concurrent_handle_claim_has_one_winner(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(self.update, self.alice, 'shared_name'), pool.submit(self.update, self.bob, 'SHARED_NAME', who='bob')]
            self.assertEqual(sorted(call.result()[0] for call in calls), [200, 409])

    def test_new_account_handle_collision_retries_and_preserves_existing_row(self):
        account = 'team-generated-collision'
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE team_accounts SET handle=%s WHERE account_id=%s', (default_handle(account), self.a))
            handle = create_account(conn, account, b'synthetic')
            self.assertEqual(handle, default_handle(account, 1))
            self.assertEqual(conn.execute('SELECT handle FROM team_accounts WHERE account_id=%s', (self.a,)).fetchone()[0], default_handle(account))
            with self.assertRaises(psycopg.errors.UniqueViolation), conn.transaction():
                create_account(conn, account, b'cannot overwrite')
            self.assertEqual(conn.execute('SELECT protected FROM team_accounts WHERE account_id=%s', (account,)).fetchone()[0], b'synthetic')

    def test_concurrent_new_accounts_retry_shared_initial_handle(self):
        def generated(account, attempt=0):
            return 'shared_generated' if attempt == 0 else default_handle(account, attempt)
        def create(account):
            with psycopg.connect(self.dsn) as conn:
                return create_account(conn, account, b'synthetic')
        with patch('account_handles.default_handle', side_effect=generated), ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(create, ['team-concurrent-one', 'team-concurrent-two']))
        self.assertEqual(len(set(values)), 2)
        self.assertIn('shared_generated', values)

    def test_new_account_handle_collision_retries_are_bounded(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE team_accounts SET handle=%s WHERE account_id=%s', ('reserved_generated', self.a))
            with patch('account_handles.default_handle', return_value='reserved_generated'), self.assertRaises(HTTPException) as raised:
                create_account(conn, 'team-never-created', b'synthetic')
            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(conn.execute("SELECT count(*) FROM team_accounts WHERE account_id='team-never-created'").fetchone()[0], 0)

    def test_exact_minimal_projection_self_and_request_states(self):
        self.assertEqual(self.update(self.bob, 'friend.bob', who='bob')[0], 200)
        for handle in ['bob', 'friend', 'unknown_user']:
            self.assertEqual(self.search(handle)[2], {'person':None})
        self.assertEqual(self.search('bob@example.invalid')[0], 400)
        person = self.search('@FRIEND.BOB')[2]['person']
        self.assertEqual(person, dict(id=self.b, name='bob', handle='friend.bob', relationship='none'))
        self.assertEqual(self.search(self.alice['user']['handle'])[2]['person']['relationship'], 'self')
        self.assertEqual(self.api.call('/v1/social/overview', session=self.alice)[2]['people'], [])
        self.assertEqual(self.api.call('/v1/social/friends/requests', dict(targetId=person['id']), 'POST', session=self.alice)[0], 201)
        self.assertEqual(self.search('friend.bob')[2]['person']['relationship'], 'outgoing')
        self.assertEqual(self.search(self.alice['user']['handle'], session=self.bob, who='bob')[2]['person']['relationship'], 'incoming')
        self.assertEqual(self.api.call('/v1/social/overview', session=self.alice)[2]['requests'], [dict(id=self.b, name='bob', direction='outgoing')])
        self.assertEqual(self.api.call('/v1/social/friends/requests/'+self.a+'/respond', dict(accept=True), 'POST', session=self.bob, who='bob')[0], 200)
        self.assertEqual(self.search('friend.bob')[2]['person']['relationship'], 'friend')
        self.assertEqual(self.api.call('/v1/social/friends/search?handle=friend.bob')[0], 401)
        self.assertEqual(self.api.call('/v1/social/friends/search?handle=bob&handle=alice', session=self.alice)[0], 400)
        self.assertEqual(self.api.native('/v1/social/friends/search?handle=friend.bob')[0], 404)
        self.assertEqual(self.api.native('/v1/profile/handle', dict(handle='abc', expectedHandle='def'), 'PUT')[0], 404)

    def test_block_hidden_both_directions_and_inactive(self):
        handle = self.bob['user']['handle']
        missing = self.search('missing_user')
        self.assertEqual(self.api.call('/v1/social/blocks', dict(targetId=self.b), 'POST', session=self.alice)[0], 201)
        blocked = self.search(handle)
        self.assertEqual((blocked[0], blocked[2]), (missing[0], missing[2]))
        self.assertEqual(blocked[1].get('cache-control'), missing[1].get('cache-control'))
        self.assertEqual(self.search(self.alice['user']['handle'], session=self.bob, who='bob')[2], {'person':None})
        self.assertEqual(self.api.call('/v1/social/friends/requests', dict(targetId=self.b), 'POST', session=self.alice)[0], 404)
        self.api.call('/v1/social/blocks/'+self.b, method='DELETE', session=self.alice)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s", (self.b,))
        self.assertEqual(self.search(handle)[2], {'person':None})
        self.assertEqual(self.api.call('/v1/social/friends/requests', dict(targetId=self.b), 'POST', session=self.alice)[0], 404)
        self.assertEqual(self.api.call('/v1/auth/session', method='POST', who='bob')[0], 403)
        self.assertEqual(self.api.call('/v1/social/overview', session=self.bob, who='bob')[0], 401)

    def test_search_limits_account_and_connection_ip(self):
        from team_auth import hashed
        with patch('team_auth.time.time', return_value=int(time.time())):
            for _ in range(20):
                self.assertEqual(self.search('unknown_user')[0], 200)
            limited = self.search('unknown_user')
            self.assertEqual(limited[0], 429)
            self.assertEqual(limited[1].get('retry-after'), '60')
            self.assertEqual(self.search('unknown_user', session=self.bob, who='bob')[0], 200)
            with psycopg.connect(self.dsn) as conn:
                conn.execute('UPDATE team_rate_limits SET hits=60 WHERE scope_hash=%s', (hashed('friend-search-ip:127.0.0.1'),))
            self.assertEqual(self.search('unknown_user', session=self.bob, who='bob')[0], 429)

    def test_seed_account_without_allowlist_and_state_based_availability(self):
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(seed_module.seed(conn), 3)
            self.assertEqual(seed_module.seed(conn), 0)
        person = self.search('dev_sky')[2]['person']
        self.assertEqual(person['name'], '개발 하늘')
        self.assertEqual(self.api.call('/v1/social/friends/requests', dict(targetId=person['id']), 'POST', session=self.alice)[0], 201)
        self.assertEqual(self.api.call('/v1/social/overview', session=self.alice)[2]['requests'][0]['id'], person['id'])
        self.api.write_members([r for r in self.api.members_rows if r['name'] != 'bob'])
        self.assertEqual(self.api.call('/v1/social/overview', session=self.bob, who='bob')[0], 403)
        self.assertEqual(self.search(self.bob['user']['handle'])[2]['person']['id'], self.b)

    def test_additive_migration_preserves_ciphertext_and_handles(self):
        schema = (Path(__file__).parent/'schema.sql').read_text()
        with psycopg.connect(self.dsn) as conn:
            with conn.transaction(force_rollback=True):
                conn.execute('CREATE SCHEMA handle_migration_test')
                conn.execute('SET LOCAL search_path TO handle_migration_test')
                conn.execute('CREATE TABLE team_accounts(account_id text PRIMARY KEY,protected bytea NOT NULL,created_at timestamptz NOT NULL DEFAULT now())')
                for n in range(20):
                    conn.execute('INSERT INTO team_accounts(account_id,protected) VALUES(%s,%s)', ('team-'+format(n, '040x'), b'preserved-'+bytes([n])))
                before = conn.execute('SELECT account_id,protected,created_at FROM team_accounts ORDER BY account_id').fetchall()
                conn.execute(schema)
                after = conn.execute('SELECT account_id,protected,created_at FROM team_accounts ORDER BY account_id').fetchall()
                self.assertEqual(before, after)
                handles = conn.execute('SELECT handle FROM team_accounts ORDER BY account_id').fetchall()
                self.assertEqual(len(set(handles)), 20)
                for (handle,) in handles:
                    self.assertEqual(normalize_handle(handle), handle)
                conn.execute(schema)
                self.assertEqual(handles, conn.execute('SELECT handle FROM team_accounts ORDER BY account_id').fetchall())

    def test_openapi_covers_browser_only_handle_contracts(self):
        __import__('api_application')
        status, _, schema = self.api.call('/openapi.json')
        self.assertEqual(status, 200)
        operation = schema['paths']['/v1/social/friends/search']['get']
        self.assertEqual(operation['parameters'][0]['name'], 'handle')
        self.assertEqual(operation['x-wegoh-surface'], 'browser')
        self.assertIn('expectedHandle', schema['paths']['/v1/profile/handle']['put']['requestBody']['content']['application/json']['schema']['required'])


if __name__ == '__main__':
    unittest.main()
