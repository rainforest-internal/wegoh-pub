"""Personal phone sessions use the existing encrypted friendship graph over HTTP."""
import hashlib
import hmac
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import psycopg
import test_iphone_session as fixture


class IPhoneFriendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(fixture.IphoneSessionTests.doClassCleanups)
        fixture.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.phone = fixture.IphoneSessionTests()
        self.phone.setUp()
        self.alice = self.phone.login()
        self.bob = self.phone.login(who='bob')
        self.eve = self.phone.login(who='eve')
        self.a, self.b = self.alice['user']['id'], self.bob['user']['id']

    def call(self, suffix='', body=None, method='GET', *, session=None):
        return self.phone.iphone('/v1/iphone/' + suffix, body, method,
                                 token=(session or self.alice)['accessToken'])

    def search(self, handle, **kwargs):
        return self.call('friends/search?handle=' + handle, **kwargs)

    def test_search_request_accept_profile_and_same_web_graph(self):
        handle = self.call('profile', session=self.bob)[2]['user']['handle']
        status, headers, result = self.search(handle.upper())
        self.assertEqual(status, 200, result)
        self.assertIn('no-store', self.phone.header(headers, 'cache-control'))
        self.assertEqual(result['person'], dict(id=self.b, name='bob', handle=handle, relationship='none'))
        payload = dict(targetId=self.b)
        self.assertEqual(self.call('friends/requests', payload, 'POST')[0], 201)
        self.assertEqual(self.call('friends/requests', payload, 'POST')[0], 200)
        self.assertEqual(self.search(handle)[2]['person']['relationship'], 'outgoing')
        incoming = self.call('friends', session=self.bob)[2]['requests']
        self.assertEqual([(p['id'], p['direction']) for p in incoming], [(self.a, 'incoming')])
        self.assertEqual(self.call('friends', session=self.eve)[2], dict(friends=[], requests=[], blocks=[]))
        path = 'friends/requests/' + self.a + '/respond'
        self.assertEqual(self.call(path, dict(accept=True), 'POST', session=self.eve)[0], 404)
        self.assertEqual(self.call(path, dict(accept=True), 'POST', session=self.bob)[0], 200)
        self.assertEqual(self.search(handle)[2]['person']['relationship'], 'friend')
        self.assertEqual(self.call('friends/' + self.b + '/profile')[2], dict(name='bob', plateNumbers=[]))
        self.assertEqual(self.call('friends/' + self.b + '/profile', session=self.eve)[0], 404)
        web = self.phone.api.login()
        friends = self.phone.api.call('/v1/social/overview', session=web)[2]['friends']
        self.assertEqual([p['id'] for p in friends], [self.b])
        self.assertEqual(self.call('friends/' + self.b, {}, 'DELETE')[0], 200)
        self.assertEqual(self.call('friends/' + self.b + '/profile')[0], 404)

    def test_push_tracks_only_current_friend_transition_and_intended_recipient(self):
        from iphone_push_events import push_event_visible

        def visible(call):
            data = call.kwargs
            self.assertEqual(len(data['recipients']), 1)
            event = dict(kind=data['kind'], actor_id=data['actor'], recipient_id=data['recipients'][0],
                         resource_id=data['resource_id'], trip_id=None)
            with psycopg.connect(self.phone.api.dsn) as conn:
                return push_event_visible(conn, event, self.phone.api.module.TEAM_AUTH, 0)

        with patch('iphone_push.enqueue_push') as enqueue:
            self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 201)
            first = enqueue.call_args
            self.assertEqual((first.kwargs['kind'], first.kwargs['actor'], first.kwargs['recipients']),
                             ('friend_request', self.a, [self.b]))
            self.assertTrue(visible(first))
            self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 200)
            self.assertEqual(enqueue.call_count, 1)
            self.assertEqual(self.call('friends/requests/' + self.a + '/respond', dict(accept=False),
                                       'POST', session=self.bob)[0], 200)
            self.assertEqual(enqueue.call_count, 1)
            self.assertFalse(visible(first))
            self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 201)
            second = enqueue.call_args
            self.assertFalse(visible(first))
            self.assertTrue(visible(second))
            self.assertEqual(self.call('friends/requests/' + self.a + '/respond', dict(accept=True),
                                       'POST', session=self.bob)[0], 200)
            accepted = enqueue.call_args
            self.assertEqual((accepted.kwargs['kind'], accepted.kwargs['actor'], accepted.kwargs['recipients']),
                             ('friend_accepted', self.b, [self.a]))
            self.assertFalse(visible(second))
            self.assertTrue(visible(accepted))
            self.assertEqual(self.call('blocks', dict(targetId=self.b), 'POST')[0], 201)
            self.assertFalse(visible(accepted))
            self.assertEqual(enqueue.call_count, 3)

    def test_push_follows_public_friend_link_once_and_rolls_back_with_write(self):
        from fastapi import HTTPException
        owner = self.phone.api.login()
        guest = self.phone.api.login('bob')

        def link_call(suffix, data, session, who):
            return self.phone.api.call('/v1/social/' + suffix, data, 'POST', session=session, who=who)

        with patch('iphone_push.enqueue_push', side_effect=HTTPException(503, 'Synthetic queue failure')):
            self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 503)
        self.assertEqual(self.call('friends', session=self.bob)[2]['requests'], [])
        _, _, value = link_call('friend-link', {}, owner, 'alice')
        with patch('iphone_push.enqueue_push') as enqueue:
            for _ in range(2):
                self.assertEqual(link_call('friend-links/accept', dict(token=value['token']), guest, 'bob')[0], 200)
            self.assertEqual(enqueue.call_count, 1)
            self.assertEqual(enqueue.call_args.kwargs['kind'], 'friend_accepted')
            self.assertEqual(enqueue.call_args.kwargs['actor'], self.b)
            self.assertEqual(enqueue.call_args.kwargs['recipients'], [self.a])

    def test_decline_cancel_block_and_search_do_not_disclose_hidden_accounts(self):
        handle = self.call('profile', session=self.bob)[2]['user']['handle']
        self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 201)
        self.assertEqual(self.call('friends/' + self.a, {}, 'DELETE', session=self.bob)[0], 403)
        self.assertEqual(self.call('friends/requests/' + self.a + '/respond', dict(accept=False), 'POST', session=self.bob)[0], 200)
        self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 201)
        self.assertEqual(self.call('friends/' + self.b, {}, 'DELETE')[0], 200)
        self.assertEqual(self.call('blocks', dict(targetId=self.b), 'POST')[0], 201)
        self.assertEqual(self.search(handle)[2], dict(person=None))
        self.assertEqual(self.call('friends', session=self.bob)[2]['requests'], [])
        self.assertEqual(self.call('friends/requests', dict(targetId=self.a), 'POST', session=self.bob)[0], 404)
        self.assertEqual(self.call('blocks/' + self.b, {}, 'DELETE')[0], 200)
        self.assertEqual(self.search(handle)[2]['person']['relationship'], 'none')
        self.assertEqual(self.search('unknown_code')[2], dict(person=None))
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s", (self.b,))
        self.assertEqual(self.search(handle)[2], dict(person=None))

    def test_boundaries_scopes_strict_inputs_and_revocation(self):
        for query in ('friends/search', 'friends/search?handle=abc&handle=def', 'friends/search?handle=abc&owner=x',
                      'friends/search?handle=ab', 'friends?ignored=1'):
            self.assertEqual(self.call(query)[0], 400, query)
        self.assertEqual(self.call('friends/requests', dict(targetId=self.a), 'POST')[0], 400)
        self.assertEqual(self.call('friends/requests', dict(targetId=self.b, owner=self.a), 'POST')[0], 400)
        self.assertEqual(self.call('friends/requests/' + self.b + '/respond', dict(accept='true'), 'POST')[0], 400)
        web = self.phone.api.login()
        self.assertEqual(self.phone.api.call('/v1/iphone/friends', session=web, bearer=self.alice['accessToken'])[0], 404)
        self.assertEqual(self.phone.api.native('/v1/iphone/friends', token=self.alice['accessToken'])[0], 404)
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s', (['account:read'],))
        self.assertEqual(self.call('friends')[0], 403)
        self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 403)
        self.alice = self.phone.login()
        service = self.phone.api.module.TEAM_AUTH.iphone_sessions
        original = service.authenticate
        def revoked(request, scope, **options):
            if options.get('lock'):
                from iphone_sessions import fail
                fail(401, 'SESSION_REVOKED')
            return original(request, scope, **options)
        with patch.object(service, 'authenticate', side_effect=revoked):
            self.assertEqual(self.call('friends/requests', dict(targetId=self.b), 'POST')[0], 401)
        self.assertEqual(self.call('friends')[2]['requests'], [])
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s", (self.a,))
        self.assertEqual(self.call('friends/' + self.b + '/profile')[0], 401)

    def test_already_open_v2_login_never_acquires_friend_scopes(self):
        request, verifier, state = self.phone.start()
        actor = self.phone.api.login()['user']['id']
        message = f"wegoh-iphone-login-v2:{request['requestId']}:{actor}".encode('ascii')
        fields = dict(request_id=request['requestId'], csrf=hmac.new(self.phone.api.module.TEAM_AUTH.secret, message, hashlib.sha256).hexdigest())
        status, headers, _ = self.phone.submit(fields, 'approve')
        self.assertEqual(status, 303)
        callback = parse_qs(urlsplit(self.phone.header(headers, 'location')).query, strict_parsing=True)
        self.assertEqual(callback['state'], [state])
        status, _, legacy = self.phone.exchange(request, verifier, callback['code'][0])
        self.assertEqual(status, 200)
        self.assertNotIn('friends:read', legacy['scopes'])
        self.assertNotIn('friends:manage', legacy['scopes'])
        self.assertEqual(self.call('friends', session=legacy)[0], 403)
        self.assertEqual(self.call('profile', session=legacy)[0], 200)
