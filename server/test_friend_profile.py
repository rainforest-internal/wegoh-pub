import unittest

import psycopg
import test_team_friends as fixture


class FriendProfileTests(fixture.FriendTests):
    def accept(self, sender, recipient):
        self.assertEqual(self.friend('/friends/requests/' + sender['user']['id'] + '/respond',
            {'accept': True}, 'POST', session=recipient, who='bob')[0], 200)

    def test_current_display_name_and_only_registered_plates(self):
        alice, bob, _ = self.sessions()
        self.assertEqual(self.request_friend(alice, bob)[0], 201)
        self.accept(alice, bob)
        path = '/friends/' + bob['user']['id'] + '/profile'
        self.assertEqual(self.call('/v1/profile', {'displayName': '새 이름', 'expectedDisplayName': 'bob'},
            'PUT', who='bob', session=bob)[0], 200)

        def expect(*plates):
            status, headers, profile = self.friend(path, session=alice)
            self.assertEqual(status, 200, profile)
            self.assertEqual(headers['cache-control'], 'private, no-store')
            self.assertEqual(profile, {'name': '새 이름', 'plateNumbers': list(plates)})

        def set_plate(device, plate, revision, *, session=bob, who='bob'):
            status, _, result = self.call('/v1/devices/' + device + '/vehicle-profile',
                {'plateNumber': plate, 'name': '', 'expectedRevision': revision}, 'PUT', session=session, who=who)
            self.assertEqual(status, 200, result)

        alice_device = self.pair(alice)[2]['deviceId']
        set_plate(alice_device, '111가1111', 0, session=alice, who='alice')
        first = self.pair(bob, 'bob')[2]['deviceId']
        expect()
        set_plate(first, '456나7890', 0)
        expect('456나7890')
        set_plate(first, '123가4567', 1)
        expect('123가4567')
        self.assertEqual(self.friend('/overview', session=alice)[2]['friends'],
            [{'id': bob['user']['id'], 'name': '새 이름', 'hasVehicle': True}])
        set_plate(first, '', 2)
        expect()
        set_plate(first, '456나7890', 3)
        self.assertEqual(self.call('/v1/devices/' + first, method='DELETE', session=bob, who='bob')[0], 200)
        expect()
        second = self.pair(bob, 'bob')[2]['deviceId']
        expect()
        set_plate(second, '123가4567', 0)
        expect('123가4567')
        self.assertEqual(self.call('/v1/devices/' + second, method='DELETE', session=bob, who='bob')[0], 200)
        expect()

    def test_only_current_unblocked_friends_can_read_browser_detail(self):
        alice, bob, eve = self.sessions()
        alice_id, bob_id = alice['user']['id'], bob['user']['id']
        path = '/friends/' + bob_id + '/profile'
        self.assertEqual(self.friend(path)[0], 401)
        for peer in (alice_id, bob_id, 'invalid', 'team-' + '0' * 40):
            with self.subTest(peer=peer):
                self.assertEqual(self.friend('/friends/' + peer + '/profile', session=alice)[0], 404)
        self.assertEqual(self.request_friend(alice, bob)[0], 201)
        self.assertEqual(self.friend(path, session=alice)[0], 404)
        self.accept(alice, bob)
        self.assertEqual(self.friend(path, session=eve, who='eve')[0], 404)
        token = self.pair(alice)[2]['accessToken']
        self.assertEqual(self.native('/v1/social' + path, token=token)[0], 404)
        self.assertEqual(self.friend('/friends/' + bob_id, method='DELETE', session=alice)[0], 200)
        self.assertEqual(self.friend(path, session=alice)[0], 404)
        self.assertEqual(self.request_friend(alice, bob)[0], 201)
        self.accept(alice, bob)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE team_accounts SET account_status='suspended' WHERE account_id=%s", (bob_id,))
        self.assertEqual(self.friend(path, session=alice)[0], 404)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE team_accounts SET account_status='active' WHERE account_id=%s", (bob_id,))
        self.assertEqual(self.friend('/blocks', {'targetId': alice_id}, 'POST', session=bob, who='bob')[0], 201)
        self.assertEqual(self.friend(path, session=alice)[0], 404)
        self.assertEqual(self.friend('/friends/' + alice_id + '/profile', session=bob, who='bob')[0], 404)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(FriendProfileTests(name) for name in vars(FriendProfileTests) if name.startswith('test_'))
