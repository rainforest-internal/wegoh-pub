"""Synthetic subscriptions on a disposable loopback API and PostgreSQL cluster.

The data comes from course_subscription_seed.py, the same command operators run
against a shared service, so this fixture also tests that command end to end.
"""
import io
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import psycopg

import course_subscription_seed as seed
import test_iphone_session as iphone
import test_team_friends as friends


SUBSCRIBER, EMPTY_VIEWER = 'bob', 'dave'
RECENT = [seed.PACK_PREFIX + course[1] for course in seed.COURSES if course[6]]


def owned(helper):
    fixture = friends.auth_fixture.TeamTests
    if (helper.state != fixture.state or helper.dsn != fixture.dsn
            or not helper.state.name.startswith('wegoh-team-contract-')
            or not (helper.state / 'postgres' / 'postmaster.pid').is_file()):
        raise RuntimeError('A running owned disposable subscription fixture is required')


def seed_subscriptions(helper):
    owned(helper)
    sessions = {who: helper.login(who) for who in (SUBSCRIBER, EMPTY_VIEWER)}
    result = seed.apply(helper.dsn, helper.state / 'content', accounts=[sessions[SUBSCRIBER]['user']['id']])
    phone = iphone.IphoneSessionTests('test_login_bootstraps_same_account_and_restores_then_logs_out')
    phone.api = helper
    tokens = {who: phone.login(who=who)['accessToken'] for who in (SUBSCRIBER, EMPTY_VIEWER)}
    return sessions, result, tokens


def subscriptions_fixture():
    class SubscriptionsFixture(friends.FriendTests):
        browser_fixture_accounts = ('alice', SUBSCRIBER, EMPTY_VIEWER)

        @classmethod
        def setUpClass(cls):
            cls.iphone_origin = patch.dict(os.environ, {'WEGOH_IPHONE_API_ORIGIN': 'https://' + iphone.IPHONE})
            cls.iphone_origin.start()
            try:
                super().setUpClass()
                names = dict(alice='데모 관리자', bob='구독 방문자 (데모)', dave='빈 구독 방문자 (데모)')
                roles = dict(alice='admin', bob='viewer', dave='viewer')
                cls.members_rows = [dict(email=who + '@example.invalid', name=name, role=roles[who])
                    for who, name in names.items()]
                cls.write_members(cls.members_rows)
            except BaseException:
                cls.iphone_origin.stop()
                raise

        @classmethod
        def tearDownClass(cls):
            try:
                super().tearDownClass()
            finally:
                cls.iphone_origin.stop()

        @classmethod
        def prepare_browser_fixture(cls, helper):
            sessions, _, tokens = seed_subscriptions(helper)
            cls.browser_fixture_metadata = dict(subscriberId=sessions[SUBSCRIBER]['user']['id'],
                emptyViewerId=sessions[EMPTY_VIEWER]['user']['id'],
                iphoneSessions=[dict(name=who, accessToken=tokens[who]) for who in (SUBSCRIBER, EMPTY_VIEWER)])

    return SubscriptionsFixture


class SubscriptionSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = subscriptions_fixture()
        cls.fixture.setUpClass()
        cls.state = cls.fixture.state

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()
        if cls.state.exists():
            raise AssertionError('Disposable subscription fixture state was not removed')

    def setUp(self):
        self.helper = self.fixture()
        self.helper.setUp()

    def read_library(self, token):
        status, _, value = self.helper.call('/v1/iphone/courses/library', who=None,
            host=iphone.IPHONE, origin=None, bearer=token)
        self.assertEqual(status, 200, value)
        return value

    def synthetic_rows(self):
        with psycopg.connect(self.helper.dsn) as conn:
            return (conn.execute('SELECT count(*) FROM team_accounts WHERE account_id=ANY(%s)',
                        (list(seed.CREATOR_IDS.values()),)).fetchone()[0],
                    conn.execute('SELECT count(*) FROM pack_versions WHERE pack_id LIKE %s',
                        (seed.PACK_PREFIX + '%',)).fetchone()[0],
                    conn.execute('SELECT count(*) FROM team_course_tag_follows WHERE tag LIKE %s',
                        (seed.TAG_PREFIX + '%',)).fetchone()[0])

    def test_apply_is_idempotent_with_three_creators_many_tags_recent_news_and_covers(self):
        _, first, tokens = seed_subscriptions(self.helper)
        before = self.read_library(tokens[SUBSCRIBER])
        _, second, tokens = seed_subscriptions(self.helper)
        after = self.read_library(tokens[SUBSCRIBER])
        self.assertEqual((first['createdCourses'], first['newCreatorFollows'], first['newTagFollows']),
                         (len(seed.COURSES), 3, len(seed.TAGS)))
        self.assertEqual((second['createdCourses'], second['newCreatorFollows'], second['newTagFollows']), (0, 0, 0))
        self.assertEqual(before, after)
        self.assertGreater(len(seed.TAGS), 8)
        self.assertCountEqual([item['name'] for item in after['following']], seed.NAMES.values())
        self.assertCountEqual(after['followedTags'], seed.TAGS)
        self.assertEqual(len(after['public']), len(seed.COURSES))
        # Only courses published after the subscription started are news, newest first.
        self.assertEqual([item['id'] for item in after['news']], list(reversed(RECENT)))
        self.assertEqual(after['unreadCount'], len(RECENT))
        for item in after['public']:
            self.assertTrue(item['id'].startswith(seed.PACK_PREFIX))
            self.assertTrue(item['author'].endswith('(데모)'))
            self.assertTrue(all(tag.startswith(seed.TAG_PREFIX) for tag in item['tags']))
            self.assertTrue(item['hasCover'])
            path = f"/v1/iphone/courses/public/{item['id']}/versions/1"
            status, _, detail = self.helper.call(path, who=None, host=iphone.IPHONE, origin=None, bearer=tokens[SUBSCRIBER])
            self.assertEqual(status, 200, detail)
            self.assertGreater(len(detail['pack']['stops']), 0)
            status, headers, raw = self.helper.call(path + '/cover', who=None,
                host=iphone.IPHONE, origin=None, bearer=tokens[SUBSCRIBER])
            self.assertEqual(status, 200)
            self.assertIn('image/jpeg', headers.get('content-type', ''))
            self.assertEqual(Image.open(io.BytesIO(raw)).size, (640, 360))
        empty = self.read_library(tokens[EMPTY_VIEWER])
        self.assertEqual((empty['following'], empty['followedTags'], empty['news']), ([], [], []))

    def test_command_targets_a_handle_and_restores_an_unfollowed_creator(self):
        sessions, _, tokens = seed_subscriptions(self.helper)
        library = self.read_library(tokens[SUBSCRIBER])
        follow = library['following'][0]['id']
        status, _, result = self.helper.call('/v1/studio/course-follows/' + follow, method='DELETE',
            who=SUBSCRIBER, session=sessions[SUBSCRIBER])
        self.assertEqual(status, 200, result)
        self.assertEqual(len(self.read_library(tokens[SUBSCRIBER])['following']), 2)
        self.assertEqual(seed.main(['apply', '--handle', '@' + sessions[SUBSCRIBER]['user']['handle'].upper()])['newCreatorFollows'], 1)
        after = self.read_library(tokens[SUBSCRIBER])
        self.assertEqual(len(after['following']), 3)
        self.assertEqual([item['id'] for item in after['news']], list(reversed(RECENT)))
        with self.assertRaisesRegex(seed.SeedError, 'No active account'):
            seed.main(['apply', '--handle', 'missing_handle'])

    def test_remove_deletes_only_synthetic_rows_and_can_be_reapplied(self):
        owner = self.helper.login('alice')
        unrelated = self.helper.pack()
        self.assertEqual(self.helper.publish(unrelated, owner)[0], 201)
        sessions, _, tokens = seed_subscriptions(self.helper)
        status, _, result = self.helper.call(f"/v1/studio/course-stars/{unrelated['id']}/versions/1", method='PUT',
            who=SUBSCRIBER, session=sessions[SUBSCRIBER])
        self.assertEqual(status, 200, result)
        with psycopg.connect(self.helper.dsn) as conn:
            checksums = [row[0] for row in conn.execute('SELECT checksum FROM pack_versions WHERE pack_id LIKE %s',
                                                        (seed.PACK_PREFIX + '%',))]
        self.assertEqual(seed.main(['remove']), dict(creators=3, courses=len(seed.COURSES), tagFollows=len(seed.TAGS)))
        self.assertEqual(self.synthetic_rows(), (0, 0, 0))
        self.assertFalse(any((self.helper.state / 'content' / checksum).exists() for checksum in checksums))
        library = self.read_library(tokens[SUBSCRIBER])
        self.assertEqual((library['following'], library['followedTags'], library['news']), ([], [], []))
        self.assertEqual([item['id'] for item in library['public']], [unrelated['id']])
        self.assertEqual([item['id'] for item in library['saved']], [unrelated['id']])
        self.assertEqual(seed.main(['remove']), dict(creators=0, courses=0, tagFollows=0))
        _, again, _ = seed_subscriptions(self.helper)
        self.assertEqual(again['createdCourses'], len(seed.COURSES))
        self.assertEqual(self.synthetic_rows(), (3, len(seed.COURSES), len(seed.TAGS)))

    def test_apply_preserves_a_course_id_owned_by_someone_else(self):
        owner = self.helper.login('alice')
        taken = dict(self.helper.pack(), id=seed.PACK_PREFIX + seed.COURSES[-1][1])
        self.assertEqual(self.helper.publish(taken, owner)[0], 201)
        subscriber = self.helper.login(SUBSCRIBER)['user']['id']
        with self.assertRaisesRegex(seed.SeedError, 'belongs to another creator'):
            seed.apply(self.helper.dsn, self.helper.state / 'content', accounts=[subscriber])
        self.assertEqual(self.synthetic_rows(), (0, 1, 0))

    def test_remove_keeps_everything_while_a_trip_uses_a_synthetic_course(self):
        sessions, _, _ = seed_subscriptions(self.helper)
        with psycopg.connect(self.helper.dsn) as conn:
            subscriber = sessions[SUBSCRIBER]['user']['id']
            conn.execute("INSERT INTO team_trips(trip_id,owner_id,protected) VALUES(repeat('a',32),%s,'\\x00')", (subscriber,))
            conn.execute("INSERT INTO team_trip_courses(trip_id,pack_id,added_by,protected) VALUES(repeat('a',32),%s,%s,'\\x00')",
                         (RECENT[0], subscriber))
        with self.assertRaisesRegex(seed.SeedError, 'trip course'):
            seed.main(['remove'])
        self.assertEqual(self.synthetic_rows(), (3, len(seed.COURSES), len(seed.TAGS)))

    def test_command_requires_shared_accounts_and_an_owned_fixture(self):
        with patch.dict(os.environ, WEGOH_AUTH_MODE='local'):
            with self.assertRaisesRegex(seed.SeedError, 'shared accounts'):
                seed.main(['remove'])
        with self.assertRaisesRegex(seed.SeedError, 'target account'):
            seed.apply(self.helper.dsn, self.helper.state / 'content')
        foreign = SimpleNamespace(state=self.helper.state.parent, dsn='host=not-a-fixture.invalid')
        with patch.object(psycopg, 'connect', side_effect=AssertionError('Unexpected database access')):
            with self.assertRaisesRegex(RuntimeError, 'owned disposable'):
                seed_subscriptions(foreign)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve-fixture':
        friends.serve_fixture(sys.argv[2], fixture_class=subscriptions_fixture())
    elif sys.argv[1:] == ['--check']:
        unittest.main(argv=[sys.argv[0]], verbosity=2)
    else:
        raise SystemExit('Usage: test_course_subscriptions_fixture.py --serve-fixture CONFIG.json | --check')
