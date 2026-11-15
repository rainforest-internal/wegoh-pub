"""Authenticated installation and transactional outbox over disposable HTTP/PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest
from unittest.mock import Mock
from uuid import uuid4

import psycopg

from iphone_push import PushWorker
import test_iphone_session as fixture


class IPhonePushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.IphoneSessionTests.setUpClass()
        cls.addClassCleanup(fixture.IphoneSessionTests.doClassCleanups)

    def setUp(self):
        self.phone = fixture.IphoneSessionTests()
        self.phone.setUp()
        self.alice = self.phone.login()
        self.bob = self.phone.login(who='bob')
        self.auth = self.phone.api.module.TEAM_AUTH
        self.installation = dict(installationId=str(uuid4()), deviceToken='16' * 32, environment='sandbox')
        self.provider = Mock()
        self.provider.send.return_value = 200, '', None, None
        self.worker = PushWorker(self.auth, self.provider)

    def register(self, *, session=None, **overrides):
        return self.phone.iphone('/v1/iphone/push/installation', dict(self.installation, **overrides), 'PUT',
                                 token=(session or self.bob)['accessToken'])

    def delete(self, *, session):
        return self.phone.iphone('/v1/iphone/push/installation', {'installationId': self.installation['installationId']},
                                 'DELETE', token=session['accessToken'])

    def sql(self, stmt, args=()):
        with psycopg.connect(self.auth.dsn) as conn:
            return conn.execute(stmt, args).fetchall()

    def friend_request(self):
        return self.phone.iphone('/v1/iphone/friends/requests', {'targetId': self.bob['user']['id']},
                                 'POST', token=self.alice['accessToken'])[0]

    def test_auth_schema_repeat_token_and_idempotent_sender(self):
        path = '/v1/iphone/push/installation'
        self.assertEqual(self.phone.iphone(path, self.installation, 'PUT')[0], 401)
        for update in ({'installationId': 'invalid'}, {'deviceToken': 'A' * 64}, {'deviceToken':'a' * 65},
                       {'deviceToken': 'a' * 514}, {'environment':'proxy'}, {'extra':'not-accepted'}):
            self.assertEqual(self.register(**update)[0], 400)
        self.assertEqual(self.register()[0], 200)
        binding, protected = self.sql('SELECT binding,protected FROM iphone_push_installations')[0]
        self.assertNotIn(self.installation['deviceToken'].encode(), bytes(protected))
        self.assertEqual(self.register()[0], 200)
        self.assertEqual(self.sql('SELECT binding FROM iphone_push_installations'), [(binding,)])
        self.assertEqual(self.friend_request(), 201)
        self.assertEqual(self.friend_request(), 200)
        self.assertEqual(len(self.sql('SELECT 1 FROM iphone_push_outbox')), 1)
        self.assertTrue(self.worker.deliver_one())
        self.assertFalse(self.worker.deliver_one())
        args, kwargs = self.provider.send.call_args
        self.assertEqual(args, (self.installation['deviceToken'], 'sandbox'))
        self.assertEqual((kwargs['kind'], kwargs['recipient_id'], kwargs['trip_id']),
                         ('friend_request', self.bob['user']['id'], None))
        self.assertRegex(kwargs['event_id'], r'^[a-f0-9]{32}$')

    def test_outbox_protects_event_meaning_and_rejects_swapped_installation_ciphertext(self):
        from iphone_push import event_context
        from private_records import VisitCipher
        self.register()
        self.register(installationId=str(uuid4()), deviceToken='af' * 32)
        self.assertEqual(self.friend_request(), 201)
        fields = {r[0] for r in self.sql("SELECT column_name FROM information_schema.columns "
                                          "WHERE table_schema='public' AND table_name='iphone_push_outbox'")}
        self.assertTrue({'kind', 'actor_id', 'resource_id', 'trip_id'}.isdisjoint(fields))
        rows = self.sql('SELECT installation_id,binding,event_id,protected,recipient_id FROM iphone_push_outbox')
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0][3], rows[1][3])
        a, b = self.alice['user']['id'], self.bob['user']['id']
        for installation, binding, event, protected, recipient in rows:
            self.assertEqual(recipient, b)
            self.assertNotIn(b'friend_request', bytes(protected))
            self.assertNotIn(a.encode(), bytes(protected))
            value = VisitCipher().restore('iphone-push-event:'+b, event_context(installation, binding, event), protected)
            self.assertEqual((value['kind'], value['actor_id'], value['recipient_id'], value['trip_id']),
                             ('friend_request', a, b, None))
        with psycopg.connect(self.auth.dsn) as conn:
            for current, other in (rows, rows[::-1]):
                conn.execute('UPDATE iphone_push_outbox SET protected=%s WHERE installation_id=%s',
                             (other[3], current[0]))
        self.assertTrue(self.worker.deliver_one())
        self.assertTrue(self.worker.deliver_one())
        self.assertFalse(self.worker.deliver_one())
        self.provider.send.assert_not_called()

    def test_account_rebind_and_previous_session_unregistration(self):
        self.register()
        self.friend_request()
        self.register(session=self.alice)
        self.assertEqual(self.delete(session=self.bob)[2], {'registered': False})
        self.assertEqual(self.sql('SELECT account_id FROM iphone_push_installations'), [(self.alice['user']['id'],)])
        self.assertFalse(self.worker.deliver_one())
        self.provider.send.assert_not_called()
        self.assertEqual(self.delete(session=self.alice)[2], {'registered': False})
        self.assertFalse(self.sql('SELECT 1 FROM iphone_push_installations'))

    def test_self_logout_suppresses_an_already_committed_event(self):
        self.register()
        self.friend_request()
        self.assertEqual(self.phone.iphone('/v1/iphone/session', method='DELETE', token=self.bob['accessToken'])[0], 204)
        self.assertTrue(self.worker.deliver_one())
        self.provider.send.assert_not_called()

    def test_old_scope_and_expiry_never_deliver(self):
        from iphone_sessions import digest
        self.register()
        session_hash = digest('session', self.bob['accessToken'])
        with psycopg.connect(self.auth.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read'] WHERE token_hash=%s", (session_hash,))
        self.assertEqual(self.friend_request(), 201)
        self.assertFalse(self.worker.deliver_one())
        self.assertEqual(self.phone.iphone('/v1/iphone/friends/'+self.bob['user']['id'], {}, 'DELETE',
                                          token=self.alice['accessToken'])[0], 200)
        with psycopg.connect(self.auth.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read','friends:read'] WHERE token_hash=%s", (session_hash,))
        self.assertEqual(self.friend_request(), 201)
        with psycopg.connect(self.auth.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET expires_at=1 WHERE token_hash=%s', (session_hash,))
        self.assertTrue(self.worker.deliver_one())
        self.provider.send.assert_not_called()

    def test_token_rotation_removes_pending_events_from_the_old_binding(self):
        self.register()
        self.friend_request()
        replacement = 'ac' * 32
        self.assertEqual(self.register(deviceToken=replacement)[0], 200)
        self.assertFalse(self.worker.deliver_one())
        self.provider.send.assert_not_called()
        self.assertEqual(len(self.sql('SELECT 1 FROM iphone_push_installations')), 1)

    def test_410_from_before_registration_is_ignored_and_current_one_invalidates(self):
        self.register()
        self.friend_request()
        registered = self.sql('SELECT registered_ms FROM iphone_push_installations')[0][0]
        self.provider.send.return_value = 410, 'Unregistered', registered-1000, None
        self.assertTrue(self.worker.deliver_one())
        self.assertTrue(self.sql('SELECT 1 FROM iphone_push_installations'))
        alice_install = dict(installationId=str(uuid4()), deviceToken='2a' * 32)
        self.register(session=self.alice, **alice_install)
        self.phone.iphone('/v1/iphone/friends/requests/'+self.alice['user']['id']+'/respond',
                          {'accept': True}, 'POST', token=self.bob['accessToken'])
        self.provider.send.return_value = 410, 'Unregistered', int(time.time()*1000)+20, None
        self.assertTrue(self.worker.deliver_one())
        self.assertEqual(self.sql('SELECT account_id FROM iphone_push_installations'), [(self.bob['user']['id'],)])

    def test_429_waits_then_retries_same_event_and_does_not_race_workers(self):
        self.register()
        self.friend_request()
        clock = int(time.time())
        self.worker.clock = lambda: clock
        self.provider.send.return_value = 429, 'TooManyRequests', None, 12
        self.assertTrue(self.worker.deliver_one())
        first = self.provider.send.call_args.kwargs['event_id']
        self.assertFalse(self.worker.deliver_one())
        clock += 12
        sending, release = threading.Event(), threading.Event()
        def slow_send(*args, **kwargs):
            sending.set()
            self.assertTrue(release.wait(3))
            return 200, '', None, None
        self.provider.send.side_effect = slow_send
        with ThreadPoolExecutor(max_workers=2) as executor:
            send = executor.submit(self.worker.deliver_one)
            self.assertTrue(sending.wait(3))
            try:
                self.assertFalse(self.worker.deliver_one())
            finally:
                release.set()
            self.assertTrue(send.result(timeout=3))
        self.assertEqual(self.provider.send.call_args.kwargs['event_id'], first)


if __name__ == '__main__':
    unittest.main()
