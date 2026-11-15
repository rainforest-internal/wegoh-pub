import unittest
from unittest.mock import patch
import psycopg
from fastapi import HTTPException
import test_iphone_trips as fixture


class IPhoneTripMusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.IPhoneTripTests.setUpClass.__func__(cls)

    def setUp(self):
        self.h = fixture.IPhoneTripTests()
        self.h.setUp()
        self.addCleanup(self.h.phone.doCleanups)
        self.h.befriend(self.h.bob)
        self.trip = self.h.create()
        self.h.join(self.trip, self.h.bob)
        self.path = '/' + self.trip + '/music'
        self.auth = self.h.phone.api.module.TEAM_AUTH
        self.music = self.auth.room_music_service

    def call(self, suffix='', data=None, method='GET', **kwargs):
        return self.h.call(self.path + suffix, data, method, **kwargs)

    def enable(self, session=None):
        return self.h.checked(self.call('/sharing', dict(enabled=True), 'PATCH', session=session))

    def add(self, review=False):
        return dict(title='합성 여행 음악', url='https://music.youtube.com/playlist?list=synthetic',
                    rightsConfirmed=True, reviewConsent=review)

    def context(self, conn):
        from team_trip_context import resolve_trip_context
        room = resolve_trip_context(self.auth, conn, self.trip, self.h.a)['roomId']
        return room, self.music.rooms.access(conn, room, self.h.a, trip_context=True)['consents']

    def test_default_off_consent_and_revocation_preserve_other_choices(self):
        self.assertEqual(self.h.checked(self.call()), dict(tripId=self.trip, musicSharing=False, items=[], limit=200, canAdd=True,
                                                               canReorder=True, nowPlaying=[]))
        self.assertEqual(self.h.phone.header(self.call()[1], 'cache-control'), 'private, no-store')
        with psycopg.connect(self.h.phone.api.dsn) as conn: room, before = self.context(conn)
        self.assertEqual(self.call('/playlist', self.add(), 'POST')[0], 403)
        self.assertTrue(self.enable()['musicSharing'])
        self.h.checked(self.call('/playlist', self.add(), 'POST'), 201)
        value = self.h.checked(self.call('/sharing', dict(enabled=False), 'PATCH'))
        self.assertFalse(value['musicSharing']); self.assertEqual(value['items'], [])
        with psycopg.connect(self.h.phone.api.dsn) as conn: _, after = self.context(conn)
        self.assertEqual({k:v for k,v in before.items() if k!='music'}, {k:v for k,v in after.items() if k!='music'})

    def test_explicit_review_controls_foreign_visibility_and_encrypted_storage(self):
        self.enable(); self.enable(self.h.bob)
        item, = self.h.checked(self.call('/playlist', self.add(True), 'POST'), 201)['items']
        self.assertEqual((item['addedBy']['id'], item['reviewState']), (self.h.a, 'quarantined'))
        self.assertEqual(self.h.checked(self.call(session=self.h.bob))['items'], [])
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            room, _ = self.context(conn)
            raw = conn.execute('SELECT protected FROM team_room_playlist_tracks WHERE room_id=%s AND track_id=%s', (room,item['id'])).fetchone()[0]
            self.assertNotIn('합성 여행 음악'.encode(), bytes(raw))
        web = self.h.phone.api.login(); path = '/v1/moderation/content/room-music/' + room + ':' + item['id']
        detail = self.h.checked(self.h.phone.api.call(path, session=web))
        self.h.checked(self.h.phone.api.call(path, dict(checksum=detail['review']['checksum'],decision='approved',reviewer='합성 검수자',reviewNote='합성 링크 확인'),'POST',session=web))
        self.assertEqual(self.h.checked(self.call(session=self.h.bob))['items'][0]['id'], item['id'])
        private = self.h.checked(self.call('/playlist', self.add(False), 'POST'),201)['items'][-1]
        self.assertEqual(private['reviewState'], 'private')
        self.assertEqual(len(self.h.checked(self.call(session=self.h.bob))['items']), 1)

    def test_closed_fields_invalid_links_and_review_failure_never_store(self):
        for data in [dict(enabled=1),dict(enabled=True,voice=True),{}]: self.assertEqual(self.call('/sharing',data,'PATCH')[0],400)
        self.enable()
        for change in [dict(url='http://example.invalid/song'),dict(rightsConfirmed=False),dict(reviewConsent='true'),dict(artist='pretend'),dict(title='')]:
            self.assertEqual(self.call('/playlist',dict(self.add(),**change),'POST')[0],400)
        self.assertEqual(self.h.checked(self.call())['items'],[])
        self.assertEqual(self.call('?deviceId=private')[0],400)
        with patch.object(self.music,'review_track',side_effect=HTTPException(503,'Synthetic review unavailable')):
            self.assertEqual(self.call('/playlist',self.add(True),'POST')[0],503)
        self.assertEqual(self.h.checked(self.call())['items'],[])

    def test_owner_reorders_visible_items_and_other_members_cannot(self):
        self.enable(); self.enable(self.h.bob)
        for index in range(3):
            self.h.checked(self.call('/playlist', dict(self.add(), title='합성 곡 %d' % index), 'POST'), 201)
        first, second, third = [item['id'] for item in self.h.checked(self.call())['items']]
        moved = self.h.checked(self.call('/playlist/' + third + '/position', dict(afterId=None), 'PATCH'))
        self.assertEqual([item['id'] for item in moved['items']], [third, first, second])
        moved = self.h.checked(self.call('/playlist/' + third + '/position', dict(afterId=second), 'PATCH'))
        self.assertEqual([item['id'] for item in moved['items']], [first, second, third])
        again = self.h.checked(self.call('/playlist/' + third + '/position', dict(afterId=second), 'PATCH'))
        self.assertEqual(again['items'], moved['items'])
        added = self.h.checked(self.call('/playlist', dict(self.add(), title='합성 곡 끝'), 'POST'), 201)['items']
        self.assertEqual([item['id'] for item in added[:3]], [first, second, third])
        bob = self.h.checked(self.call(session=self.h.bob))
        self.assertFalse(bob['canReorder'])
        self.assertEqual(self.call('/playlist/' + first + '/position', dict(afterId=None), 'PATCH', session=self.h.bob)[0], 403)
        private = self.h.checked(self.call('/playlist', dict(self.add(), title='합성 비공개'), 'POST', session=self.h.bob), 201)['items'][-1]
        self.assertEqual(self.call('/playlist/' + first + '/position', dict(afterId=private['id']), 'PATCH')[0], 409)
        for data in [dict(afterId=first), dict(afterId='x'), dict(), dict(afterId=None, extra=True)]:
            self.assertEqual(self.call('/playlist/' + first + '/position', data, 'PATCH')[0], 400)
        self.assertEqual(self.call('/playlist/' + 'f' * 32 + '/position', dict(afterId=None), 'PATCH')[0], 409)

    def test_departed_member_cannot_read_or_write_music(self):
        self.enable(self.h.bob)
        self.h.checked(self.h.call('/' + self.trip + '/members/' + self.h.b, {}, method='DELETE'))
        self.assertEqual(self.call(session=self.h.bob)[0], 404)
        self.assertEqual(self.call('/sharing', dict(enabled=True), 'PATCH', session=self.h.bob)[0], 404)
        self.assertEqual(self.call('/playlist', self.add(), 'POST', session=self.h.bob)[0], 404)

    def test_existing_scopes_membership_and_phone_host_are_required(self):
        self.assertEqual(self.call(session=self.h.eve)[0],404)
        self.assertEqual(self.call('/sharing',dict(enabled=True),'PATCH',session=self.h.eve)[0],404)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read','trips:read'] WHERE account_id=%s",(self.h.a,))
        self.h.checked(self.call())
        self.assertEqual(self.call('/sharing',dict(enabled=True),'PATCH')[0],403)
        self.assertEqual(self.call('/playlist',self.add(),'POST')[0],403)
        web=self.h.phone.api.login()
        self.assertEqual(self.h.phone.api.call('/v1/iphone/trips'+self.path,session=web)[0],404)

    def library(self, session=None, title='내 플레이리스트 곡'):
        token = (session or self.h.alice)['accessToken']
        data = dict(name=title, tracks=[dict(title=title, url='https://open.spotify.com/track/synthetic')])
        return self.h.checked(self.h.phone.iphone('/v1/iphone/playlists', data, 'POST', token=token), 201)

    def pick(self, playlist, **change):
        return dict(dict(playlistId=playlist['id'], playlistRevision=playlist['revision'],
                         trackId=playlist['tracks'][0]['id'], rightsConfirmed=True, reviewConsent=True), **change)

    def test_saved_library_track_is_added_without_retyping_and_is_idempotent(self):
        playlist = self.library()
        first = self.h.checked(self.call('/saved-playlists', self.pick(playlist), 'POST'))
        item, = first['items']
        self.assertEqual((item['title'], item['url'], item['addedBy']['id'], item['reviewState']),
                         ('내 플레이리스트 곡', 'https://open.spotify.com/track/synthetic', self.h.a, 'quarantined'))
        self.assertEqual(set(first), {'tripId', 'musicSharing', 'items', 'limit', 'canAdd', 'canReorder', 'nowPlaying'})
        self.assertEqual(self.h.phone.header(self.call('/saved-playlists', self.pick(playlist), 'POST')[1],
                                             'cache-control'), 'private, no-store')
        self.assertEqual([row['id'] for row in self.h.checked(self.call())['items']], [item['id']])
        self.assertEqual(self.h.checked(self.call(session=self.h.bob))['items'], [])

    def test_saved_library_selection_is_closed_owned_and_current(self):
        playlist = self.library()
        for change in [dict(rightsConfirmed=False), dict(reviewConsent=False), dict(playlistRevision=True),
                       dict(trackId='not-an-id'), dict(extra=True)]:
            self.assertEqual(self.call('/saved-playlists', self.pick(playlist, **change), 'POST')[0], 400, change)
        self.assertEqual(self.call('/saved-playlists', self.pick(playlist, playlistRevision=2), 'POST')[0], 409)
        foreign = self.library(self.h.bob)
        self.assertEqual(self.call('/saved-playlists', self.pick(foreign), 'POST')[0], 409)
        self.assertEqual(self.call('/saved-playlists', self.pick(foreign), 'POST', session=self.h.eve)[0], 404)
        self.assertEqual(self.h.checked(self.call())['items'], [])
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['trips:read','trips:manage'] WHERE account_id=%s", (self.h.a,))
        self.assertEqual(self.call('/saved-playlists', self.pick(playlist), 'POST')[0], 403)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read','trips:read'] WHERE account_id=%s", (self.h.a,))
        self.assertEqual(self.call('/saved-playlists', self.pick(playlist), 'POST')[0], 403)


    def test_vehicle_matches_phone_and_follows_its_room_music_purpose(self):
        self.enable(); self.enable(self.h.bob)
        typed = self.h.checked(self.call('/playlist', dict(self.add(True), title='Zoo'), 'POST', session=self.h.bob), 201)['items'][-1]
        with psycopg.connect(self.h.phone.api.dsn) as conn: room, _ = self.context(conn)
        web = self.h.phone.api.login(); path = '/v1/moderation/content/room-music/' + room + ':' + typed['id']
        detail = self.h.checked(self.h.phone.api.call(path, session=web))
        self.h.checked(self.h.phone.api.call(path, dict(checksum=detail['review']['checksum'], decision='approved',
            reviewer='합성 검수자', reviewNote='합성 링크 확인'), 'POST', session=web))
        _, _, car = self.h.phone.api.pair(web)
        settings = '/v1/iphone/vehicles/' + car['deviceId'] + '/functional-permissions'
        def vehicle():
            return self.h.checked(self.h.phone.api.native('/v1/social/trips/' + self.trip + '/music/saved-playlists',
                                                          token=car['accessToken']))
        def phone():
            value = self.h.checked(self.call())
            self.assertEqual([item['title'] for item in value['items']], ['Zoo'])
            return {k: v for k, v in value.items() if k != 'musicSharing'}
        def purpose(enabled):
            current = self.h.checked(self.h.phone.iphone(settings, token=self.h.alice['accessToken']))['authorization']
            body = {k: v for k, v in current.items() if k not in ('deviceId', 'expiresAt')}
            body['approvedPurposes'] = sorted(set(body['approvedPurposes']) - {'room-music:read'} | ({'room-music:read'} if enabled else set()))
            self.h.checked(self.h.phone.iphone(settings, body, 'PUT', token=self.h.alice['accessToken']))
        self.assertEqual(vehicle(), phone())
        purpose(False)
        self.assertEqual(vehicle()['items'], [])
        phone()
        purpose(True)
        self.assertEqual(vehicle(), phone())

if __name__=='__main__': unittest.main()
