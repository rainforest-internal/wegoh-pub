import copy
import unittest
from unittest.mock import patch

import psycopg

import test_iphone_trips as fixture


class IPhoneTripHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.IPhoneTripTests.setUpClass.__func__(cls)

    def setUp(self):
        self.h = fixture.IPhoneTripTests()
        self.h.setUp()
        self.addCleanup(self.h.phone.doCleanups)
        h = self.h
        h.befriend(h.bob)
        self.trip = h.create()
        h.join(self.trip, h.bob)
        h.vehicle()
        self.base = '/' + self.trip
        self.car = h.checked(h.call(self.base + '/cars', dict(name='현재 차', seats=2), 'POST'), 201)['id']
        self.packs = []
        for number in range(2):
            pack = h.phone.api.pack()
            pack['id'] += '-' + str(number)
            pack['stops'] = [dict(copy.deepcopy(pack['stops'][0]), id='s' + str(index), name=f'공유 장소 {number}-{index}') for index in range(2)]
            h.checked(h.phone.iphone('/v1/iphone/courses', dict(pack=pack, rightsConfirmed=True), 'POST', token=h.alice['accessToken']), 201)
            h.checked(h.call(self.base + '/courses', dict(packId=pack['id']), 'POST'), 201)
            self.packs.append(pack)
        for kind in ('pickup', 'drop'):
            h.checked(h.call(self.base + '/cars/' + self.car + '/places',
                dict(kind=kind, name='개인 ' + kind, lat=37.6, lng=127.1), 'POST'), 201)

    def complete(self):
        h = self.h
        h.checked(h.call(self.base + '/start', dict(revision=h.detail(self.trip)['revision'], routeContractVersion=2), 'POST'))
        h.checked(h.call(self.base + '/finish', dict(revision=h.detail(self.trip)['revision']), 'POST'))

    def options(self, session=None):
        return self.h.checked(self.h.call(self.base + '/course-draft-options', session=session))

    def draft(self, options, selection=None, session=None, **changes):
        data = dict(selectionFingerprint=options['selectionFingerprint'],
            selectionIds=selection if selection is not None else [place['id'] for place in options['places'][:3]])
        data.update(changes)
        return self.h.call(self.base + '/course-drafts', data, 'POST', session=session)

    def publish(self, draft, **changes):
        data = dict(pack=draft['pack'], tags=draft['tags'], remixDraftId=draft['remixDraftId'], rightsConfirmed=True)
        data.update(changes)
        return self.h.phone.iphone('/v1/iphone/courses', data, 'POST', token=self.h.alice['accessToken'])

    def test_actual_iphone_v2_finish_records_and_shared_only_selection_publish(self):
        h = self.h
        self.assertEqual(h.call(self.base + '/course-draft-options')[0], 409)
        self.complete()
        result = h.checked(h.call(self.base + '/results'))
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(len(result['summary']['courses']), 2)
        self.assertEqual(h.call(self.base + '/history')[0], 404)
        saved = h.checked(h.call(self.base + '/history', dict(title='함께한 기록'), 'POST'), 201)
        self.assertEqual(h.checked(h.call(self.base + '/history', dict(title='중복 요청'), 'POST')), saved)
        record = h.checked(h.call(self.base + '/history'))
        self.assertEqual(record['id'], saved['id'])
        self.assertEqual(record['title'], '함께한 기록')
        self.assertEqual(record['source']['tripId'], self.trip)
        self.assertEqual(h.call(self.base + '/history', session=h.bob)[0], 404)
        options = self.options()
        self.assertEqual(len(options['places']), 4)
        self.assertTrue(all(place['name'].startswith('공유 장소') for place in options['places']))
        self.assertNotIn('개인 pickup', str(options))
        self.assertNotIn('개인 drop', str(options))
        self.assertTrue(all(place['canReuse'] for place in options['places']))
        draft = h.checked(self.draft(options), 201)
        self.assertEqual(set(draft), {'pack', 'tags', 'hasCover', 'remixDraftId'})
        self.assertEqual(len(draft['pack']['stops']), 3)
        self.assertEqual(draft['pack']['version'], 1)
        self.assertEqual(draft['pack']['author'], 'alice')
        self.assertNotIn('rightsConfirmed', draft['pack'])
        self.assertEqual(self.publish(draft, rightsConfirmed=False)[0], 400)
        result = h.checked(self.publish(draft), 201)
        self.assertEqual(result['source']['kind'], 'trip')
        self.assertNotIn('tripId', result['source'])
        self.assertEqual([source['courseId'] for source in result['source']['courses']], [pack['id'] for pack in self.packs])
        with psycopg.connect(h.phone.api.dsn) as conn:
            protected = bytes(conn.execute('SELECT protected FROM team_remix_drafts WHERE draft_id=%s', (draft['remixDraftId'],)).fetchone()[0])
            self.assertNotIn('공유 장소'.encode(), protected)
            self.assertNotIn(self.trip.encode(), protected)

    def test_selection_currentness_input_scope_and_account_boundaries(self):
        h = self.h
        self.complete()
        options = self.options()
        ids = [place['id'] for place in options['places']]
        for selection in ([], ids, [ids[0], ids[0]], [ids[0], 1]):
            self.assertEqual(self.draft(options, selection)[0], 400)
        self.assertEqual(self.draft(options, list(reversed(ids[:2])))[0], 409)
        self.assertEqual(self.draft(options, ['f' * 32])[0], 409)
        self.assertEqual(self.draft(options, selectionFingerprint='f' * 64)[0], 409)
        self.assertEqual(h.call(self.base + '/course-draft-options?trip=other')[0], 400)
        self.assertEqual(h.call(self.base + '/results', session=h.eve)[0], 404)
        self.assertEqual(self.draft(options, session=h.bob)[0], 409)
        web = h.phone.api.login()
        self.assertEqual(h.phone.api.call('/v1/iphone/trips' + self.base + '/results', session=web)[0], 404)
        for suffix, data, method in [('/results', None, 'GET'), ('/history', None, 'GET'),
                ('/history', dict(title='잘못된 호스트'), 'POST'), ('/course-draft-options', None, 'GET'),
                ('/course-drafts', dict(selectionIds=ids[:1], selectionFingerprint=options['selectionFingerprint']), 'POST')]:
            self.assertEqual(h.phone.api.native('/v1/iphone/trips' + self.base + suffix, data, method)[0], 404)
        with psycopg.connect(h.phone.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['trips:read'] WHERE account_id=%s", (h.a,))
        self.assertEqual(h.call(self.base + '/history', dict(title='금지'), 'POST')[0], 403)
        self.assertEqual(self.draft(options)[0], 403)
        h.checked(h.call(self.base + '/results'))

    def test_source_reuse_withdrawal_and_membership_change_revoke_draft(self):
        h = self.h
        self.complete()
        options = self.options()
        draft = h.checked(self.draft(options), 201)
        with psycopg.connect(h.phone.api.dsn) as conn:
            conn.execute('DELETE FROM team_trip_members WHERE trip_id=%s AND account_id=%s', (self.trip, h.a))
        self.assertEqual(self.publish(draft)[0], 404)

    def test_other_author_reuse_is_required_and_withdrawal_invalidates_receipt(self):
        h = self.h
        pack = h.phone.api.pack()
        pack['id'] += '-bob'
        pack['author'] = 'bob'
        h.checked(h.phone.iphone('/v1/iphone/courses', dict(pack=pack, rightsConfirmed=True), 'POST', token=h.bob['accessToken']), 201)
        h.checked(h.call(self.base + '/courses', dict(packId=pack['id']), 'POST'), 201)
        self.complete()
        options = self.options()
        candidate = next(place for place in options['places'] if place['courseId'] == pack['id'])
        self.assertFalse(candidate['canReuse'])
        self.assertEqual(self.draft(options, [candidate['id']])[0], 403)
        web = h.phone.api.login('bob')
        path = '/v1/studio/packs/' + pack['id'] + '/versions/1/reuse-permission'
        def permission(enabled):
            current = h.checked(h.phone.api.call(path, session=web, who='bob'))
            return h.checked(h.phone.api.call(path, dict(revision=current['revision'], checksum=current['checksum'],
                consent=enabled, rightsConfirmed=enabled), 'PUT', session=web, who='bob'))
        permission(True)
        options = self.options()
        candidate = next(place for place in options['places'] if place['courseId'] == pack['id'])
        self.assertTrue(candidate['canReuse'])
        draft = h.checked(self.draft(options, [candidate['id']]), 201)
        permission(False)
        self.assertEqual(self.publish(draft)[0], 409)
        permission(True)
        self.assertEqual(self.publish(draft)[0], 409)

    def test_revoke_between_initial_auth_and_write_does_not_save(self):
        h = self.h
        self.complete()
        service = h.phone.api.module.TEAM_AUTH.iphone_sessions
        original = service.authenticate
        def revoked(request, scope, **kwargs):
            if kwargs.get('connection') is not None:
                with psycopg.connect(h.phone.api.dsn) as conn:
                    conn.execute('UPDATE iphone_sessions SET revoked_at=0 WHERE account_id=%s', (h.a,))
            return original(request, scope, **kwargs)
        with patch.object(service, 'authenticate', side_effect=revoked):
            self.assertEqual(h.call(self.base + '/history', dict(title='작성 금지'), 'POST')[0], 401)
        with psycopg.connect(h.phone.api.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_histories WHERE owner_id=%s', (h.a,)).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
