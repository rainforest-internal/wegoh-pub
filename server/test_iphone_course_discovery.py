import unittest
from unittest.mock import patch
from urllib.parse import quote, urlencode

import psycopg

import test_iphone_courses as fixture


class CourseDiscoveryTests(fixture.IPhoneCourseTests):
    def setUp(self):
        super().setUp()
        self.alice = self.session.api.login()
        self.bob = self.session.api.login('bob')
        self.other = self.session.login(who='bob')['accessToken']
        self.source = self.session.api.pack()
        self.source.update(title='바다 드라이브', description='서쪽 해안 코스')
        self.publish(self.source, ['바다', 'Cafe'])

    def checked(self, response, status=200):
        self.assertEqual(response[0], status, response[2])
        return response[2]

    def publish(self, pack, tags):
        return self.checked(self.session.api.call('/v1/packs', dict(pack=pack, tags=tags, rightsConfirmed=True),
            'POST', session=self.bob, who='bob'), 201)

    def call(self, path='/library', body=None, method='GET', token=None):
        return self.session.iphone('/v1/iphone/courses' + path, body, method, token=token or self.token)

    def library(self, query=''):
        return self.checked(self.call('/library' + query))

    def reference(self, prefix, pack=None):
        pack = pack or self.source
        return '/' + prefix + '/' + pack['id'] + '/versions/' + str(pack['version'])

    def test_real_catalogue_checksum_search_and_multiple_tags_are_intersected(self):
        response = self.call()
        self.checked(response)
        self.assertEqual(self.session.header(response[1], 'cache-control'), 'private, no-store')
        value = response[2]
        self.assertEqual(set(value), {'public', 'saved', 'news', 'following', 'popularTags', 'followedTags', 'unreadCount'})
        item = value['public'][0]
        self.assertEqual(set(item), {'id', 'version', 'title', 'author', 'description', 'stopCount', 'stopNames', 'tags', 'checksum',
            'creatorId', 'hasCover', 'starred', 'starCount', 'canFollow', 'followId', 'creatorRank', 'stops'})
        self.assertEqual(item['stopNames'], [stop['name'] for stop in self.source['stops']])
        self.assertEqual(item['stops'], [dict(id=stop['id'], name=stop['name'], lat=stop['latitude'], lng=stop['longitude'])
                                         for stop in self.source['stops']])
        raw = self.session.api.call('/v1/packs/' + self.source['id'] + '/versions/1', session=self.alice)[2]
        self.assertEqual(raw['title'], item['title'])
        with psycopg.connect(self.session.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT checksum FROM pack_versions WHERE pack_id=%s', (self.source['id'],)).fetchone()[0], item['checksum'])
        query = '?' + urlencode([('q', '해안'), ('tag', '#바다'), ('tag', 'cafe')])
        self.assertEqual([row['id'] for row in self.library(query)['public']], [self.source['id']])
        self.assertEqual([row['id'] for row in self.library('?' + urlencode({'q': '#cafe'}))['public']], [self.source['id']])
        self.assertEqual(self.library('?' + urlencode([('tag', '바다'), ('tag', '없는태그')]))['public'], [])
        for query in ('?extra=x', '?q=a&q=b', '?q=' + 'x' * 101, '?' + urlencode([('tag', '바다')] * 9), '?tag='):
            self.assertEqual(self.call('/library' + query)[0], 400)

    def test_stars_saved_versions_and_latest_public_version_are_independent(self):
        path = self.reference('stars')
        self.assertEqual(self.checked(self.call(path, {}, 'PUT')), dict(starred=True))
        self.assertEqual(self.checked(self.call(path, {}, 'PUT')), dict(starred=True))
        newer = dict(self.source, version=2, title='새 바다 코스',
                     stops=[dict(self.source['stops'][0], name='새 바다 전망대')] + self.source['stops'][1:])
        self.publish(newer, ['바다'])
        value = self.library()
        self.assertEqual([(item['id'], item['version']) for item in value['public']], [(self.source['id'], 2)])
        self.assertEqual([(item['id'], item['version']) for item in value['saved']], [(self.source['id'], 1)])
        self.assertEqual(value['public'][0]['stopNames'][0], '새 바다 전망대')
        self.assertEqual(value['saved'][0]['stopNames'], [stop['name'] for stop in self.source['stops']])
        self.assertEqual(self.checked(self.call(path, {}, 'DELETE')), dict(starred=False))
        self.assertEqual(self.library()['saved'], [])

    def test_creator_and_tag_subscriptions_deduplicate_feed_and_share_read_markers_with_web(self):
        follow = self.checked(self.call(self.reference('follows'), {}, 'PUT'))
        self.assertEqual(self.checked(self.call(self.reference('follows'), {}, 'PUT')), follow)
        self.assertEqual(self.checked(self.call('/tag-follows/cafe', {}, 'PUT')), dict(following=True, tag='Cafe'))
        self.assertEqual(self.library()['news'], [])
        self.publish(dict(self.source, version=2), ['Cafe', '바다'])
        value = self.library()
        self.assertEqual((len(value['news']), value['unreadCount']), (1, 1))
        self.assertEqual(value['followedTags'], ['Cafe'])
        self.assertEqual(value['following'][0]['creatorId'], self.bob['user']['id'])
        event = value['news'][0]['eventId']
        self.assertEqual(self.checked(self.call('/news/' + event + '/read', {}, 'PUT')), dict(read=True))
        self.assertEqual(self.library()['unreadCount'], 0)
        web = self.checked(self.session.api.call('/v1/studio/course-library', session=self.alice))
        self.assertTrue(web['news'][0]['read'])
        self.checked(self.call('/follows/' + follow['followId'], {}, 'DELETE'))
        self.assertEqual(self.library()['following'], [])
        self.assertEqual(len(self.library()['news']), 1)
        self.checked(self.call('/tag-follows/CAFE', {}, 'DELETE'))
        self.assertEqual(self.library()['news'], [])

    def test_popular_tags_are_casefold_unique_and_hidden_is_personal_without_learning_consent(self):
        other = self.session.api.pack()
        self.publish(other, ['cafe'])
        value = self.library()
        self.assertEqual(len([tag for tag in value['popularTags'] if tag.casefold() == 'cafe']), 1)
        self.checked(self.call(self.reference('hidden'), {}, 'PUT'))
        self.assertNotIn(self.source['id'], [item['id'] for item in self.library()['public']])
        other_view = self.checked(self.call(token=self.other))
        self.assertIn(self.source['id'], [item['id'] for item in other_view['public']])
        with psycopg.connect(self.session.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_recommendations').fetchone()[0], 0)
        self.checked(self.call(self.reference('hidden'), {}, 'DELETE'))
        self.assertIn(self.source['id'], [item['id'] for item in self.library()['public']])

    def test_public_detail_and_creator_statistics_are_actual_and_currently_filtered(self):
        detail = self.checked(self.call(self.reference('public')))
        self.assertEqual(detail['pack']['id'], self.source['id'])
        self.assertEqual(detail['creatorId'], self.bob['user']['id'])
        self.checked(self.call(self.reference('stars'), {}, 'PUT'))
        self.checked(self.call(self.reference('follows'), {}, 'PUT'))
        path = '/creators/' + detail['creatorId']
        profile = self.checked(self.call(path))
        self.assertEqual([len(item['stops']) for item in profile['courses']], [len(self.source['stops'])])
        self.assertEqual(profile['creator']['courseCount'], 1)
        self.assertEqual(profile['creator']['starCount'], 1)
        self.assertEqual(profile['creator']['followerCount'], 1)
        self.assertTrue(profile['creator']['following'])
        self.checked(self.session.api.call('/v1/social/blocks', dict(targetId=detail['creatorId']), 'POST', session=self.alice), 201)
        self.assertEqual(self.library()['public'], [])
        self.assertEqual(self.call(path)[0], 404)
        self.assertEqual(self.call(self.reference('public'))[0], 404)
        self.assertIsNone(self.library()['following'][0]['name'])
        self.assertEqual(self.call(self.reference('stars'), {}, 'PUT')[0], 404)
        self.checked(self.call(self.reference('stars'), {}, 'DELETE'))

    def test_report_uses_existing_quarantine_and_same_request_retry(self):
        path = self.reference('public') + '/reports'
        first = self.checked(self.call(path, dict(reason='privacy'), 'POST'), 202)
        self.assertEqual(self.checked(self.call(path, dict(reason='privacy'), 'POST'), 202), first)
        self.assertEqual(self.library()['public'], [])
        self.assertEqual(self.call(self.reference('public'))[0], 404)
        self.assertEqual(self.call(path, dict(reason='custom'), 'POST')[0], 400)
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute("UPDATE pack_reviews SET state='rejected' WHERE checksum IN (SELECT checksum FROM pack_versions WHERE pack_id=%s)",
                (self.source['id'],))
            before = conn.execute('SELECT count(*) FROM pack_review_events').fetchone()[0]
        self.assertEqual(self.checked(self.call(path, dict(reason='privacy'), 'POST'), 202), first)
        with psycopg.connect(self.session.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM pack_review_events').fetchone()[0], before)
            self.assertEqual(conn.execute('SELECT state FROM pack_reviews WHERE checksum IN (SELECT checksum FROM pack_versions WHERE pack_id=%s)',
                (self.source['id'],)).fetchone()[0], 'rejected')

    def test_legacy_public_creator_does_not_break_library_or_expose_profile_authority(self):
        legacy = self.session.api.pack()
        self.publish(legacy, ['옛날'])
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute("UPDATE pack_versions SET creator_id='local-creator' WHERE pack_id=%s", (legacy['id'],))
        self.assertEqual([item['id'] for item in self.library()['public']], [self.source['id']])
        self.assertEqual(self.call(self.reference('stars', legacy), {}, 'PUT')[0], 404)
        web = self.checked(self.session.api.call('/v1/studio/course-library', session=self.alice))
        row = next(item for item in web['public'] if item['id'] == legacy['id'])
        self.assertFalse(row['canFollow'])
        self.assertIsNone(row['followId'])

    def test_write_locks_the_shared_graph_before_current_phone_token(self):
        from team_rooms import TeamRooms
        auth = self.session.api.module.TEAM_AUTH
        authenticate, graph = auth.iphone_sessions.authenticate, TeamRooms.graph_lock
        observed = []
        def token(*args, **kwargs):
            result = authenticate(*args, **kwargs)
            if kwargs.get('lock'):
                observed.append('token-locked')
            return result
        def shared(conn):
            observed.append('graph')
            return graph(conn)
        with patch.object(auth.iphone_sessions, 'authenticate', side_effect=token), patch.object(TeamRooms, 'graph_lock', side_effect=shared):
            self.checked(self.call(self.reference('stars'), {}, 'PUT'))
        self.assertEqual(observed[:2], ['graph', 'token-locked'])

    def test_unread_count_is_bounded_to_the_visible_feed_window(self):
        self.checked(self.call(self.reference('follows'), {}, 'PUT'))
        for version in range(2, 33):
            self.publish(dict(self.source, version=version), ['바다'])
        feed = self.library()
        self.assertEqual((len(feed['news']), feed['unreadCount']), (30, 30))
        for item in feed['news']:
            self.checked(self.call('/news/' + item['eventId'] + '/read', {}, 'PUT'))
        self.assertEqual(self.library()['unreadCount'], 0)

    def test_scopes_empty_write_body_and_ownership_are_not_inferred(self):
        self.assertEqual(self.call(self.reference('stars'), {'extra': True}, 'PUT')[0], 400)
        self.assertEqual(self.call('/tag-follows/not-published', {}, 'PUT')[0], 404)
        self.assertEqual(self.call('/news/999999/read', {}, 'PUT')[0], 404)
        self.assertEqual(self.checked(self.call(self.reference('follows'), {}, 'PUT'))['followId'], self.library()['following'][0]['id'])
        self.assertEqual(self.call(self.reference('follows'), {}, 'PUT', token=self.other)[0], 404)
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['courses:read']")
        self.checked(self.call())
        self.assertEqual(self.call(self.reference('stars'), {}, 'PUT')[0], 403)
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read']")
        self.assertEqual(self.call()[0], 403)

    def test_native_read_only_library_requires_current_courses_scope_and_exact_query(self):
        _, _, device = self.session.api.pair(self.alice)
        path = '/v1/native/courses/library'
        native = lambda suffix='': self.session.api.native(path + suffix, token=device['accessToken'])
        result = self.checked(native('?' + urlencode([('tag', '바다'), ('tag', 'cafe')])))
        self.assertEqual(result['public'][0]['id'], self.source['id'])
        self.assertNotIn('stops', result['public'][0])
        self.assertEqual(self.session.api.native('/v1/native/courses/public/' + self.source['id'] + '/versions/1', token=device['accessToken'])[0], 200)
        self.assertEqual(native('?q=a&q=b')[0], 400)
        self.assertEqual(self.session.api.native('/v1/native/courses/stars/' + self.source['id'] + '/versions/1', {}, 'PUT', device['accessToken'])[0], 404)
        self.assertEqual(self.session.api.call('/v1/native/courses/library', session=self.alice)[0], 404)
        from native_authorization import protect, restore
        service = self.session.api.module.TEAM_NATIVE_AUTHORIZATION
        original = service.lock
        def remove_scope_after_middleware(conn, key):
            original(conn, key)
            row = conn.execute('SELECT protected_consent FROM native_v2_grants WHERE grant_id=%s', (device['grantId'],)).fetchone()
            raw = row['protected_consent'] if isinstance(row, dict) else row[0]
            consent = restore('consent', device['grantId'], raw)
            consent['scopes'].remove('courses:read')
            conn.execute('UPDATE native_v2_grants SET protected_consent=%s WHERE grant_id=%s',
                (protect('consent', device['grantId'], consent), device['grantId']))
        with patch.object(service, 'lock', side_effect=remove_scope_after_middleware):
            self.assertEqual(native()[0], 403)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(CourseDiscoveryTests(name) for name in CourseDiscoveryTests.__dict__ if name.startswith('test_'))
