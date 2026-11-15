"""HTTP copy/publish and revocation checks against a fresh PostgreSQL cluster."""
import unittest

import psycopg

import test_iphone_session as account


class IPhoneCourseCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(account.IphoneSessionTests.doClassCleanups)
        account.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.mobile = account.IphoneSessionTests('test_login_bootstraps_same_account_and_restores_then_logs_out')
        self.mobile.setUp()
        self.api = self.mobile.api
        self.alice = self.mobile.login()['accessToken']
        self.bob = self.mobile.login(who='bob')['accessToken']
        self.web = self.api.login()
        self.pack = self.api.pack()
        self.tags = ['바다', '산책']
        status, _, saved = self.api.call('/v1/packs', dict(pack=self.pack, rightsConfirmed=True, tags=self.tags),
                                          'POST', session=self.web)
        self.assertEqual(status, 201, saved)
        self.checksum = saved['checksum']
        self.version = f"{self.pack['id']}/versions/1"
        self.path = '/v1/iphone/courses/public/' + self.version + '/copy'

    def copy(self, token, data=None):
        return self.mobile.iphone(self.path, {} if data is None else data, 'POST', token=token)

    def allow(self, consent):
        path = '/v1/studio/packs/' + self.version + '/reuse-permission'
        status, _, current = self.api.call(path, session=self.web)
        self.assertEqual(status, 200, current)
        status, _, result = self.api.call(path, dict(revision=current['revision'], checksum=self.checksum,
                                                  consent=consent, rightsConfirmed=consent), 'PUT', session=self.web)
        self.assertEqual(status, 200, result)

    def publish(self, receipt, token=None, **overrides):
        payload = dict(pack=receipt['pack'], rightsConfirmed=True, tags=receipt['tags'], remixDraftId=receipt['remixDraftId'])
        payload.update(overrides)
        return self.mobile.iphone('/v1/iphone/courses', payload, 'POST', token=token or self.bob)

    def test_copy_preserves_source_rights_tags_and_cover_and_creates_a_new_immutable_pack(self):
        self.assertEqual(self.copy(self.bob)[0], 403)
        self.allow(True)
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute('INSERT INTO pack_course_covers(pack_id,version,image) VALUES(%s,1,%s)',
                         (self.pack['id'], b'fixture-course-cover'))
        status, headers, receipt = self.copy(self.bob)
        self.assertEqual(status, 201, receipt)
        self.assertIn('no-store', self.mobile.header(headers, 'cache-control'))
        self.assertEqual(set(receipt), {'pack','tags','hasCover','remixDraftId'})
        self.assertEqual(receipt['tags'], self.tags)
        self.assertTrue(receipt['hasCover'])
        draft = receipt['pack']
        self.assertNotEqual(draft['id'], self.pack['id'])
        self.assertEqual((draft['author'], draft['version'], draft['stops']), ('bob', 1, self.pack['stops']))
        self.assertEqual(self.mobile.iphone('/v1/iphone/courses', token=self.bob)[2]['packs'], [])
        draft['title'] = 'My edited coast itinerary'
        self.assertEqual(self.publish(receipt, rightsConfirmed=False)[0], 400)
        status, _, saved = self.publish(receipt)
        self.assertEqual(status, 201, saved)
        self.assertEqual(saved['source'], dict(kind='course', courseId=self.pack['id'], version=1, checksum=self.checksum))
        self.assertEqual(self.publish(receipt)[0], 200)
        with psycopg.connect(self.api.dsn) as conn:
            rows = conn.execute('SELECT p.pack_id,p.title,p.tags,c.image FROM pack_versions p '
                                'JOIN pack_course_covers c USING(pack_id,version)').fetchall()
        self.assertEqual({(r[0],r[1],tuple(r[2]),bytes(r[3])) for r in rows},
                         {(draft['id'],draft['title'],tuple(self.tags),b'fixture-course-cover'),
                          (self.pack['id'],self.pack['title'],tuple(self.tags),b'fixture-course-cover')})
        own = self.mobile.iphone(f"/v1/iphone/courses/{draft['id']}/versions/1", token=self.bob)[2]
        self.assertEqual(own['remixDraftId'], receipt['remixDraftId'])
        self.assertTrue(own['hasCover'])

    def test_receipt_binds_owner_pack_and_rechecks_source_at_publication(self):
        self.allow(True)
        status, _, draft = self.copy(self.bob)
        self.assertEqual(status, 201, draft)
        self.assertEqual(self.publish(draft, token=self.alice)[0], 404)
        without_receipt = dict(pack=draft['pack'], rightsConfirmed=True)
        self.assertEqual(self.mobile.iphone('/v1/iphone/courses', without_receipt, 'POST', token=self.bob)[0], 403)
        changed = dict(draft['pack'], id='other-course')
        self.assertEqual(self.publish(draft, pack=changed)[0], 409)
        self.allow(False)
        self.assertEqual(self.publish(draft)[0], 403)
        self.allow(True)
        self.assertEqual(self.publish(draft)[0], 409)
        status, _, draft = self.copy(self.bob)
        self.assertEqual(status, 201, draft)
        with psycopg.connect(self.api.dsn) as conn:
            conn.execute("UPDATE pack_reviews SET state='rejected' WHERE checksum=%s", (self.checksum,))
            conn.execute("INSERT INTO pack_review_events(checksum,state,reviewer,review_note) VALUES(%s,'rejected','operator','Explicit post-publication restriction')", (self.checksum,))
        self.assertEqual(self.copy(self.bob)[0], 404)
        self.assertEqual(self.publish(draft)[0], 404)

    def test_owner_can_copy_without_external_reuse_grant_and_sessions_and_input_are_checked(self):
        self.assertEqual(self.copy(self.alice)[0], 201)
        self.assertEqual(self.copy(self.alice, {'packId':'other'})[0], 400)
        self.assertEqual(self.copy(self.mobile.login(who='eve')['accessToken'])[0], 403)
        self.assertEqual(self.api.call(self.path, {}, 'POST', session=self.web)[0], 404)
        self.assertEqual(self.mobile.iphone('/v1/iphone/session', method='DELETE', token=self.alice)[0], 204)
        self.mobile.assert_error(self.copy(self.alice), 401, 'IPHONE_SESSION_REVOKED')

    def test_null_history_without_public_copy_marker_stays_inaccessible(self):
        status, _, draft = self.copy(self.alice)
        self.assertEqual(status, 201, draft)
        remix = self.api.module.TEAM_AUTH.history_remix_service
        identifier = draft['remixDraftId']
        owner = self.web['user']['id']
        with psycopg.connect(self.api.dsn) as conn:
            row = conn.execute('SELECT protected FROM team_remix_drafts WHERE draft_id=%s',(identifier,)).fetchone()
            value = remix.restore('draft', owner, identifier, row[0])
            del value['publicCopy']
            value['source']['historyId'] = '0' * 32
            conn.execute('UPDATE team_remix_drafts SET protected=%s WHERE draft_id=%s',
                         (remix.protect('draft', owner, identifier, value), identifier))
        self.assertEqual(self.publish(draft, token=self.alice)[0], 404)
        self.assertEqual(self.api.call('/v1/social/remix-drafts/' + identifier, session=self.web)[0], 404)
