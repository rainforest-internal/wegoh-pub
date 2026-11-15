"""iPhone courses share immutable owned versions with the web over real HTTP/DB."""
import copy
import unittest
from unittest.mock import patch

import psycopg

from place_search import MockPlaceSearch, PlaceSearch
import test_iphone_session as account


class IPhoneCourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(account.IphoneSessionTests.doClassCleanups)
        with patch('studio.PlaceSearch.from_environment', return_value=PlaceSearch(MockPlaceSearch())):
            account.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.session = account.IphoneSessionTests('test_login_bootstraps_same_account_and_restores_then_logs_out')
        self.session.setUp()
        self.token = self.session.login()['accessToken']
        self.pack = self.session.api.pack()

    def save(self, pack=None, token=None, rights=True):
        return self.session.iphone('/v1/iphone/courses',
            {'pack': pack or self.pack, 'rightsConfirmed': rights}, 'POST', token=token or self.token)

    def detail(self, pack=None, token=None):
        pack = pack or self.pack
        return self.session.iphone(f"/v1/iphone/courses/{pack['id']}/versions/{pack['version']}", token=token or self.token)

    def test_create_read_edit_and_web_see_the_same_versions(self):
        status, headers, saved = self.save()
        self.assertEqual((status, saved['state']), (201, 'approved'))
        self.assertIn('no-store', self.session.header(headers, 'cache-control'))
        status, _, detail = self.detail()
        self.assertEqual(status, 200)
        self.assertEqual(detail['pack']['author'], 'alice')
        self.assertEqual(detail['pack']['stops'], self.pack['stops'])
        self.assertIsNone(detail['remixDraftId'])
        updated = copy.deepcopy(self.pack)
        updated.update(version=2, title='Edited from iPhone')
        updated['stops'][0]['name'] = 'Updated place'
        self.assertEqual(self.save(updated)[0], 201)
        catalogue = self.session.iphone('/v1/iphone/courses', token=self.token)[2]['packs']
        self.assertEqual([(p['id'], p['version']) for p in catalogue], [(self.pack['id'], 2)])
        self.assertEqual(catalogue[0]['stops'], [dict(id=stop['id'], name=stop['name'], lat=stop['latitude'], lng=stop['longitude'])
                                                 for stop in updated['stops']])
        self.assertEqual(catalogue[0]['stopNames'], ['Updated place'])
        self.assertEqual(len(catalogue[0]['stopNames']), catalogue[0]['stopCount'])
        self.assertEqual(self.detail()[2]['pack']['title'], self.pack['title'])
        web = self.session.api.login()
        web_courses = self.session.api.call('/v1/studio/packs', session=web)[2]['packs']
        self.assertEqual({p['version'] for p in web_courses if p['id'] == self.pack['id']}, {1, 2})
        public = self.session.api.call(f"/v1/packs/{self.pack['id']}/versions/2", session=web)[2]
        self.assertEqual(public['title'], updated['title'])

    def test_legacy_without_review_is_immediately_readable_discoverable_and_copyable(self):
        status, _, saved = self.save()
        self.assertEqual(status, 201)
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute('DELETE FROM pack_reviews WHERE checksum=%s', (saved['checksum'],))
            conn.execute('DELETE FROM pack_review_events WHERE checksum=%s', (saved['checksum'],))
        catalogue = self.session.iphone('/v1/iphone/courses', token=self.token)
        self.assertEqual(catalogue[0], 200, catalogue[2])
        self.assertEqual(catalogue[2]['packs'][0]['state'], 'approved')
        self.assertEqual(self.detail()[0], 200)
        library = self.session.iphone('/v1/iphone/courses/library', token=self.token)
        self.assertEqual(library[0], 200, library[2])
        self.assertIn(self.pack['id'], [item['id'] for item in library[2]['public']])
        public = f"/v1/iphone/courses/public/{self.pack['id']}/versions/1"
        self.assertEqual(self.session.iphone(public, token=self.token)[0], 200)
        copy = self.session.iphone(public + '/copy', {}, 'POST', token=self.token)
        self.assertEqual(copy[0], 201, copy[2])
        self.assertNotEqual(copy[2]['pack']['id'], self.pack['id'])
        with psycopg.connect(self.session.api.dsn) as conn:
            self.assertIsNone(conn.execute('SELECT state FROM pack_reviews WHERE checksum=%s', (saved['checksum'],)).fetchone())

    def test_public_cover_uses_current_iphone_authority_and_post_publication_restrictions(self):
        self.assertEqual(self.save()[0], 201)
        public = f"/v1/iphone/courses/public/{self.pack['id']}/versions/1"
        path = public + '/cover'
        self.assertEqual(self.session.iphone(path, token=self.token)[0], 404)
        image = b'\xff\xd8\xffsynthetic-stored-jpeg'
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute('INSERT INTO pack_course_covers(pack_id,version,image) VALUES(%s,1,%s)',
                         (self.pack['id'], image))
            conn.execute('DELETE FROM pack_reviews WHERE checksum=(SELECT checksum FROM pack_versions WHERE pack_id=%s)',
                         (self.pack['id'],))
        with patch('team_course_discovery.CourseDiscovery.courses',
                   side_effect=AssertionError('A version lookup must not load the full course catalog')):
            detail = self.session.iphone(public, token=self.token)
            response = self.session.iphone(path, token=self.token)
        self.assertEqual(detail[0], 200, detail[2])
        self.assertEqual(detail[2]['pack']['id'], self.pack['id'])
        self.assertEqual(response[0], 200, response[2])
        self.assertEqual(response[2], image)
        self.assertEqual(self.session.header(response[1], 'content-type'), 'image/jpeg')
        self.assertEqual(self.session.header(response[1], 'cache-control'), 'private, no-store, no-transform')
        self.assertEqual(self.session.header(response[1], 'x-content-type-options'), 'nosniff')
        self.assertEqual(self.session.iphone(path)[0], 401)
        self.assertEqual(self.session.iphone(path + '?all=1', token=self.token)[0], 400)
        self.assertEqual(self.session.iphone(path, {}, 'PUT', token=self.token)[0], 405)
        self.assertEqual(self.session.iphone(public + '/reports', dict(reason='privacy'), 'POST', token=self.token)[0], 202)
        self.assertEqual(self.session.iphone(path, token=self.token)[0], 404)

    def test_edit_preserves_existing_tags_and_cover_and_returns_confirmed_author(self):
        web = self.session.api.login()
        payload = dict(pack=self.pack, rightsConfirmed=True, tags=['바다', '드라이브'])
        self.assertEqual(self.session.api.call('/v1/packs', payload, 'POST', session=web)[0], 201)
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute('INSERT INTO pack_course_covers(pack_id,version,image) VALUES(%s,1,%s)',
                         (self.pack['id'], b'fixture-existing-cover'))
        detail = self.detail()[2]
        self.assertEqual(detail['tags'], ['바다', '드라이브'])
        self.assertTrue(detail['hasCover'])
        updated = copy.deepcopy(self.pack)
        updated.update(version=2, title='Edited without losing metadata', author='Old client name')
        payload = dict(pack=updated, rightsConfirmed=True, tags=detail['tags'], copyCoverFromVersion=1)
        status, _, receipt = self.session.iphone('/v1/iphone/courses', payload, 'POST', token=self.token)
        self.assertEqual(status, 201)
        self.assertEqual(receipt['pack']['author'], 'alice')
        with psycopg.connect(self.session.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT tags FROM pack_versions WHERE pack_id=%s AND version=2', (self.pack['id'],)).fetchone()[0], detail['tags'])
            self.assertEqual(bytes(conn.execute('SELECT image FROM pack_course_covers WHERE pack_id=%s AND version=2', (self.pack['id'],)).fetchone()[0]), b'fixture-existing-cover')

    def test_ownership_roles_host_and_revoked_sessions_are_enforced(self):
        self.assertEqual(self.save()[0], 201)
        other = self.session.login(who='bob')['accessToken']
        self.assertEqual(self.session.iphone('/v1/iphone/courses', token=other)[2]['packs'], [])
        self.assertEqual(self.detail(token=other)[0], 404)
        self.assertEqual(self.save(token=other)[0], 409)
        viewer = self.session.login(who='eve')['accessToken']
        self.assertEqual(self.save(token=viewer)[0], 403)
        web = self.session.api.login()
        self.assertEqual(self.session.api.call('/v1/iphone/courses', session=web, bearer=self.token)[0], 404)
        self.assertEqual(self.session.api.native('/v1/iphone/courses', token=self.token)[0], 404)
        self.assertEqual(self.session.iphone(account.SESSION, method='DELETE', token=self.token)[0], 204)
        self.session.assert_error(self.save(), 401, 'IPHONE_SESSION_REVOKED')

    def test_old_sessions_keep_their_scope_and_writes_require_publication_rights(self):
        with psycopg.connect(self.session.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET scopes=%s', (['account:read', 'maps:read', 'vehicles:manage'],))
        self.session.assert_error(self.session.iphone('/v1/iphone/courses', token=self.token), 403, 'IPHONE_SCOPE_DENIED')
        self.session.assert_error(self.save(), 403, 'IPHONE_SCOPE_DENIED')
        self.assertEqual(self.session.iphone(account.SESSION, token=self.token)[0], 200)
        self.token = self.session.login()['accessToken']
        self.assertEqual(self.save(rights=False)[0], 400)
        invalid = copy.deepcopy(self.pack)
        invalid['stops'][0]['latitude'] = 100
        self.assertEqual(self.save(invalid)[0], 400)
        self.assertEqual(self.session.iphone('/v1/iphone/courses', token=self.token)[2]['packs'], [])

    def test_retry_is_idempotent_and_stale_edit_does_not_replace_a_version(self):
        self.assertEqual(self.save()[0], 201)
        self.assertEqual(self.save()[0], 200)
        conflicting = dict(self.pack, title='Changed at the same version')
        self.assertEqual(self.save(conflicting)[0], 409)
        skipped = dict(self.pack, version=3)
        self.assertEqual(self.save(skipped)[0], 409)
        self.assertEqual(self.detail()[2]['pack']['title'], self.pack['title'])
