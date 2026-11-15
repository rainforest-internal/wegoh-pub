"""The browser library uses real account sessions and an isolated PostgreSQL DB."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from urllib.parse import urlencode

import test_team_auth as fixture


class CourseLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    def setUp(self):
        self.http = fixture.TeamTests(methodName='test_01_jwt_verification_and_exact_hosts')
        self.http.setUp()
        self.alice = self.http.login()
        self.bob = self.http.login('bob')
        self.eve = self.http.login('eve')
        self.pack = self.http.pack()
        self.assertEqual(self.http.publish(self.pack, self.alice)[0], 201)
        self.library = '/v1/studio/course-library'
        self.star = f"/v1/studio/course-stars/{self.pack['id']}/versions/1"

    def read(self, session, who='alice'):
        status, headers, library = self.http.call(self.library, session=session, who=who)
        self.assertEqual(status, 200, library)
        self.assertEqual(headers['cache-control'], 'private, no-store')
        return library

    def test_latest_public_and_saved_version_have_independent_lifetimes(self):
        self.assertEqual(self.read(self.eve, 'eve')['public'][0]['id'], self.pack['id'])
        self.assertEqual(self.read(self.eve, 'eve')['saved'], [])
        self.assertEqual(self.http.approve(self.pack, self.alice)[0], 200)

        def save(_):
            return self.http.call(self.star, method='PUT', session=self.eve, who='eve')[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(save, range(2))), [200, 200])
        viewer = self.read(self.eve, 'eve')
        self.assertEqual(viewer['saved'], viewer['public'])
        self.assertEqual(viewer['saved'][0]['starCount'], 1)
        self.assertTrue(viewer['saved'][0]['starred'])
        bob = self.read(self.bob, 'bob')
        self.assertEqual(bob['saved'], [])
        self.assertEqual(bob['public'][0]['starCount'], 1)
        self.assertFalse(bob['public'][0]['starred'])

        newer = dict(self.pack, version=2, title='New course version')
        self.assertEqual(self.http.publish(newer, self.alice)[0], 201)
        self.assertEqual(self.http.approve(newer, self.alice)[0], 200)
        viewer = self.read(self.eve, 'eve')
        self.assertEqual([item['version'] for item in viewer['public']], [2])
        self.assertEqual([item['version'] for item in viewer['saved']], [1])
        room_body = dict(name='Saved trip', courseId=self.pack['id'], courseVersion=1, expiresInHours=6)
        status, _, room = self.http.call('/v1/social/rooms', room_body, 'POST', session=self.eve, who='eve')
        self.assertEqual(status, 201, room)
        detail = self.http.call('/v1/social/rooms/'+room['id'], session=self.eve, who='eve')[2]
        self.assertEqual(detail['courseVersion'], 1)

        report = f"/v1/packs/{self.pack['id']}/versions/1/reports"
        self.assertEqual(self.http.call(report, dict(reason='privacy'), 'POST', session=self.bob, who='bob')[0], 202)
        viewer = self.read(self.eve, 'eve')
        self.assertEqual(viewer['saved'], [])
        self.assertEqual([item['version'] for item in viewer['public']], [2])
        self.assertEqual(self.http.call('/v1/social/rooms', room_body, 'POST', session=self.eve, who='eve')[0], 409)
        self.assertEqual(self.http.call(self.star, method='DELETE', session=self.eve, who='eve')[0], 200)
        self.assertEqual(self.http.approve(self.pack, self.alice)[0], 200)
        self.assertEqual(self.read(self.eve, 'eve')['saved'], [])

    def test_only_current_browser_account_can_change_its_star(self):
        self.assertEqual(self.http.approve(self.pack, self.alice)[0], 200)
        self.assertEqual(self.http.call(self.library)[0], 401)
        self.assertEqual(self.http.call(self.star, method='PUT', session=self.bob, who='bob', csrf=False)[0], 403)
        self.assertEqual(self.http.call(self.star, method='PUT', session=self.bob, who='bob', origin='https://other.invalid')[0], 403)
        self.assertEqual(self.http.call(self.star, method='PUT', session=self.bob, who='bob')[2], {'starred': True})
        for _ in range(2):
            self.assertEqual(self.http.call(self.star, method='DELETE', session=self.alice)[2], {'starred': False})
        self.assertEqual(len(self.read(self.bob, 'bob')['saved']), 1)
        self.assertEqual(self.http.call(self.star, method='DELETE', session=self.bob, who='bob')[2], {'starred': False})
        self.assertEqual(self.read(self.alice)['public'][0]['starCount'], 0)

    def test_tags_follow_the_immutable_version_and_public_visibility(self):
        self.assertEqual(self.read(self.eve, 'eve')['public'][0]['tags'], [])
        tagged = dict(self.pack, version=2)
        payload = dict(rightsConfirmed=True, pack=tagged, tags=[' #해안도로 ', 'DRIVE', 'drive'])
        self.assertEqual(self.http.call('/v1/packs', payload, 'POST', session=self.eve, who='eve')[0], 403)
        self.assertEqual(self.http.call('/v1/packs', payload, 'POST', session=self.alice, csrf=False)[0], 403)
        self.assertEqual(self.http.call('/v1/packs', payload, 'POST', session=self.alice)[0], 201)
        self.assertEqual(self.http.call('/v1/packs', payload, 'POST', session=self.alice)[0], 200)
        self.assertEqual(self.http.call('/v1/packs', dict(payload, tags=['other']), 'POST', session=self.alice)[0], 409)
        self.assertEqual(self.http.call('/v1/packs', dict(payload, pack=dict(tagged, version=3)),
                                       'POST', session=self.bob, who='bob')[0], 409)
        owner = self.http.call('/v1/studio/packs', session=self.alice)[2]
        self.assertEqual({item['version']: item['tags'] for item in owner['packs']},
                         {1: [], 2: ['해안도로', 'DRIVE']})
        self.assertEqual(self.http.call('/v1/studio/packs', session=self.bob, who='bob')[2]['packs'], [])
        original = f"/v1/packs/{tagged['id']}/versions/2"
        downloaded = self.http.call(original, session=self.eve, who='eve')[2]
        self.assertEqual(downloaded, dict(tagged, author=owner['packs'][0]['author']))

        coast = '?' + urlencode({'tag': '#해안도로'})
        self.assertEqual(self.http.call(self.library + coast)[0], 401)
        for tag in ('#해안도로', 'drive'):
            status, headers, results = self.http.call(self.library + '?' + urlencode({'tag': tag}),
                                                       session=self.eve, who='eve')
            self.assertEqual(status, 200)
            self.assertEqual(headers['cache-control'], 'private, no-store')
            self.assertEqual([(item['version'], item['tags']) for item in results['public']],
                             [(2, ['해안도로', 'DRIVE'])])
        self.assertEqual(self.http.call(self.library + '?tag=other', session=self.eve, who='eve')[2]['public'], [])

        edited = dict(payload, pack=dict(tagged, version=3), tags=['#산책'])
        self.assertEqual(self.http.call('/v1/packs', edited, 'POST', session=self.alice)[0], 201)
        self.assertEqual(self.http.call(self.library + coast, session=self.eve, who='eve')[2]['public'], [])
        self.assertEqual(self.read(self.eve, 'eve')['public'][0]['tags'], ['산책'])
        report = f"/v1/packs/{tagged['id']}/versions/3/reports"
        self.assertEqual(self.http.call(report, dict(reason='privacy'), 'POST', session=self.eve, who='eve')[0], 202)
        walk = '?' + urlencode({'tag': '산책'})
        self.assertEqual(self.http.call(self.library + walk, session=self.eve, who='eve')[2]['public'], [])
        self.assertEqual(self.read(self.eve, 'eve')['public'][0]['tags'], ['해안도로', 'DRIVE'])
        self.assertEqual(self.http.call('/v1/moderation/packs', session=self.eve, who='eve')[0], 403)
        queue = self.http.call('/v1/moderation/packs', session=self.alice)[2]['packs']
        quarantined = next(item for item in queue if item['version'] == 3)
        self.assertEqual((quarantined['state'], quarantined['tags']), ('quarantined', ['산책']))

    def test_invalid_course_tags_are_rejected(self):
        pack = dict(self.pack, version=2)
        for tags in (None, 'coast', ['two words'], ['<script>'], ['a' * 25], ['tag'] * 9):
            with self.subTest(tags=tags):
                status, _, _ = self.http.call('/v1/packs', dict(rightsConfirmed=True, pack=pack, tags=tags),
                                               'POST', session=self.alice)
                self.assertEqual(status, 400)
        self.assertEqual(self.http.call(self.library + '?tag=two%20words', session=self.eve, who='eve')[0], 400)
        self.assertEqual(self.read(self.eve, 'eve')['public'][0]['version'], 1)

    def test_follow_receives_first_approval_and_respects_current_visibility(self):
        self.assertEqual(self.http.approve(self.pack, self.alice)[0], 200)
        follow = f"/v1/studio/course-follows/{self.pack['id']}/versions/1"
        self.assertEqual(self.http.call(follow, method='PUT', session=self.alice)[0], 404)
        self.assertEqual(self.http.call(follow, method='PUT', session=self.bob, who='bob', csrf=False)[0], 403)
        status, _, receipt = self.http.call(follow, method='PUT', session=self.bob, who='bob')
        self.assertEqual(status, 200, receipt)
        self.assertEqual(self.http.call(follow, method='PUT', session=self.bob, who='bob')[2], receipt)
        self.assertEqual(self.read(self.bob, 'bob')['news'], [])
        self.assertEqual(self.http.call(self.star, method='PUT', session=self.bob, who='bob')[0], 200)
        self.assertEqual(self.read(self.eve, 'eve')['public'][0]['creatorRank'], 1)

        new_course = dict(self.http.pack(), title='Synthetic new trip')
        self.assertEqual(self.http.publish(new_course, self.alice)[0], 201)
        self.assertEqual(self.read(self.bob, 'bob')['news'][0]['id'], new_course['id'])
        for _ in range(2):
            self.assertEqual(self.http.approve(new_course, self.alice)[0], 200)
        news = self.read(self.bob, 'bob')['news']
        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]['id'], new_course['id'])
        self.assertFalse(news[0]['read'])
        self.assertEqual(self.read(self.eve, 'eve')['news'], [])
        read = f"/v1/studio/course-news/{news[0]['eventId']}/read"
        self.assertEqual(self.http.call(read, method='PUT', session=self.eve, who='eve')[0], 404)
        self.assertEqual(self.http.call(read, method='PUT', session=self.bob, who='bob')[2], {'read': True})
        self.assertTrue(self.read(self.bob, 'bob')['news'][0]['read'])

        report = f"/v1/packs/{new_course['id']}/versions/1/reports"
        self.assertEqual(self.http.call(report, dict(reason='privacy'), 'POST', session=self.eve, who='eve')[0], 202)
        self.assertEqual(self.read(self.bob, 'bob')['news'], [])
        self.assertEqual(self.http.call(read, method='PUT', session=self.bob, who='bob')[0], 404)
        self.assertEqual(self.http.approve(new_course, self.alice)[0], 200)
        self.assertTrue(self.read(self.bob, 'bob')['news'][0]['read'])
        block = dict(targetId=self.bob['user']['id'])
        self.assertEqual(self.http.call('/v1/social/blocks', block, 'POST', session=self.alice)[0], 201)
        library = self.read(self.bob, 'bob')
        self.assertEqual(library['news'], [])
        self.assertFalse(library['public'][0]['canFollow'])
        self.assertEqual(library['following'], [dict(id=receipt['followId'], name=None)])
        cancel = '/v1/studio/course-follows/'+receipt['followId']
        self.assertEqual(self.http.call(cancel, method='DELETE', session=self.eve, who='eve')[0], 200)
        self.assertEqual(len(self.read(self.bob, 'bob')['following']), 1)
        self.assertEqual(self.http.call(cancel, method='DELETE', session=self.bob, who='bob')[2], {'following': False})
        self.assertEqual(self.read(self.bob, 'bob')['following'], [])
