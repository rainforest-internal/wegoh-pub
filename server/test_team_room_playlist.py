"""Shared room playlist permissions, reviewed metadata and current-song regression."""
import secrets
import json
import unittest
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg
import test_team_auth as fixture
import test_team_room_music as music_fixture
from private_records import VisitCipher


class RoomPlaylistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')

    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()

    setUp = music_fixture.RoomMusicTests.setUp
    setup = music_fixture.RoomMusicTests.setup
    music = music_fixture.RoomMusicTests.music
    select = music_fixture.RoomMusicTests.select
    approve = music_fixture.RoomMusicTests.approve

    def add(self, room, session, who='alice', **changes):
        value = dict(title='Road song', artist='Road artist', url='https://music.example/song', rightsConfirmed=True)
        value.update(changes)
        return self.h.room('/rooms/' + room + '/music/playlist', value, 'POST', session=session, who=who)

    def entry(self, room, session, who='alice'):
        return self.music(room, session, who)[2]['playlist']['tracks'][-1]

    def remove(self, room, track, session, who='alice'):
        return self.h.room('/rooms/' + room + '/music/playlist/' + track, method='DELETE', session=session, who=who)

    def review(self, room, track, session, who='alice', consent=True):
        return self.h.room('/rooms/' + room + '/music/playlist/' + track + '/review-request',
                           dict(consent=consent), 'PATCH', session=session, who=who)

    def approve_entry(self, room, track, session, admin, who='alice'):
        status, _, review = self.review(room, track, session, who)
        self.assertEqual(status, 200, review)
        status, _, value = self.h.call('/v1/moderation/content/room-music/' + room + ':' + track,
            dict(checksum=review['checksum'], decision='approved', reviewer='Synthetic admin',
                 reviewNote='Synthetic track metadata reviewed'), 'POST', session=admin)
        self.assertEqual(status, 200, value)

    def test_member_add_order_author_and_review_visibility(self):
        a, b, room = self.setup()
        self.assertEqual(self.add(room, b, 'bob')[0], 201)
        first = self.entry(room, b, 'bob')
        self.assertEqual(first['addedBy']['id'], b['user']['id'])
        self.assertEqual(first['artist'], 'Road artist')
        self.assertTrue(first['canDelete'])
        self.assertIsNone(self.entry(room, a)['track'])
        self.approve_entry(room, first['id'], b, a, 'bob')
        self.assertEqual(self.entry(room, a)['track']['title'], 'Road song')
        self.assertEqual(self.add(room, a, title='Second song')[0], 201)
        second = self.entry(room, a)
        self.approve_entry(room, second['id'], a, a)
        tracks = self.music(room, b, 'bob')[2]['playlist']['tracks']
        self.assertEqual([item['id'] for item in tracks], [first['id'], second['id']])
        self.assertFalse(tracks[1]['canDelete'])
        with psycopg.connect(fixture.TeamTests.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_room_playlist_tracks WHERE room_id=%s', (room,)).fetchone()[0]
            self.assertNotIn(b'Road song', bytes(raw))

    def test_nonmember_consent_leave_block_closed_expired_deny(self):
        for boundary in ('nonmember', 'consent', 'leave', 'block', 'closed', 'expiry'):
            with self.subTest(boundary=boundary):
                self.setUp()
                a, b, room = self.setup()
                if boundary == 'nonmember':
                    outsider = self.h.login('eve')
                    self.assertEqual(self.add(room, outsider, 'eve')[0], 404)
                    continue
                self.assertEqual(self.add(room, b, 'bob')[0], 201)
                track = self.entry(room, b, 'bob')['id']
                self.approve_entry(room, track, b, a, 'bob')
                if boundary == 'consent':
                    self.h.share(room, b, 'bob')
                elif boundary == 'leave':
                    self.h.room('/rooms/' + room + '/leave', method='POST', session=b, who='bob')
                elif boundary == 'block':
                    self.h.friend('/blocks', dict(targetId=b['user']['id']), 'POST', session=a)
                elif boundary == 'closed':
                    self.h.room('/rooms/' + room + '/leave', method='POST', session=a)
                else:
                    with psycopg.connect(fixture.TeamTests.dsn) as conn:
                        conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 second' WHERE room_id=%s", (room,))
                expected = 403 if boundary == 'consent' else 404
                self.assertEqual(self.add(room, b, 'bob')[0], expected)
                self.assertEqual(self.remove(room, track, b, 'bob')[0], expected)
                if boundary in ('consent', 'leave', 'block'):
                    self.assertIsNone(self.entry(room, a)['track'])

    def test_delete_own_track_and_owner_all_tracks(self):
        a, b, room = self.setup()
        self.assertEqual(self.add(room, a)[0], 201)
        own = self.entry(room, a)['id']
        self.assertEqual(self.remove(room, own, b, 'bob')[0], 403)
        self.assertEqual(self.add(room, b, 'bob')[0], 201)
        added = self.entry(room, b, 'bob')['id']
        self.assertEqual(self.remove(room, added, b, 'bob')[0], 200)
        self.assertEqual(self.remove(room, added, b, 'bob')[0], 404)
        self.assertEqual(self.add(room, b, 'bob')[0], 201)
        self.assertEqual(self.remove(room, self.entry(room, b, 'bob')['id'], a)[0], 200)
        self.assertEqual(self.remove(room, own, a)[0], 200)

    def test_url_text_rights_and_body_validation(self):
        a, _, room = self.setup()
        for url in ('http://music.example/song', 'javascript:alert(1)', 'https:///song',
                    'https://user:pass@music.example/song', 'https://music.example:444/song',
                    'https://music.example:bad/song', 'https://music.example/a b',
                    'https://music.example\\@evil.example/song', 'https://%65vil.example/song'):
            with self.subTest(url=url):
                self.assertEqual(self.add(room, a, url=url)[0], 400)
        for changes in (dict(title=' '), dict(artist=''), dict(title='x' * 121),
                        dict(artist='x' * 81), dict(title='song\n'), dict(rightsConfirmed=False),
                        dict(extra=True), dict(title=4)):
            with self.subTest(changes=changes):
                self.assertEqual(self.add(room, a, **changes)[0], 400)
        self.assertEqual(self.add(room, a, title='x' * 5000)[0], 413)
        self.assertEqual(self.add(room, a, url='https://music.example:443/song')[0], 201)

    def test_capacity_serializes_and_account_rate_survives_deletion(self):
        a, b, room = self.setup()
        with psycopg.connect(fixture.TeamTests.dsn) as conn:
            joined = conn.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s',
                                  (room, a['user']['id'])).fetchone()[0]
            for _ in range(199):
                identifier = secrets.token_hex(16)
                projection = dict(name='Seed artist', tracks=[dict(id=identifier, title='Seed song', url='https://music.example/song')])
                raw = VisitCipher().protect('team-room-playlist:' + room + ':' + a['user']['id'], identifier, projection)
                conn.execute('INSERT INTO team_room_playlist_tracks(room_id,track_id,account_id,member_joined_at,protected) VALUES(%s,%s,%s,%s,%s)',
                             (room, identifier, a['user']['id'], joined, raw))
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda actor: self.add(room, actor[0], actor[1])[0], [(a, 'alice'), (b, 'bob')]))
        self.assertEqual(sorted(statuses), [201, 409])
        self.assertFalse(self.music(room, a)[2]['playlist']['canAdd'])
        self.setUp()
        a, _, room = self.setup()
        with patch('team_auth.time', SimpleNamespace(time=lambda: 1800000000)):
            for _ in range(10):
                self.assertEqual(self.add(room, a)[0], 201)
                self.assertEqual(self.remove(room, self.entry(room, a)['id'], a)[0], 200)
            self.assertEqual(self.add(room, a)[0], 429)

    def test_current_song_selection_and_source_withdrawal(self):
        for boundary in ('delete', 'consent', 'review', 'report'):
            with self.subTest(boundary=boundary):
                self.setUp()
                a, b, room = self.setup()
                self.assertEqual(self.add(room, b, 'bob')[0], 201)
                entry = self.entry(room, b, 'bob')
                playlist = dict(id=room, revision=1, tracks=[entry['track']])
                self.assertEqual(self.select(room, a, playlist)[0], 409)
                self.approve_entry(room, entry['id'], b, a, 'bob')
                self.assertEqual(self.select(room, b, playlist, who='bob')[0], 403)
                self.assertEqual(self.select(room, a, playlist)[0], 200)
                self.approve(room, a)
                self.assertEqual(self.music(room, b, 'bob')[2]['selection']['currentTrackId'], entry['id'])
                if boundary == 'delete':
                    self.remove(room, entry['id'], b, 'bob')
                elif boundary == 'consent':
                    self.h.share(room, b, 'bob')
                elif boundary == 'review':
                    self.review(room, entry['id'], b, 'bob', False)
                else:
                    result = self.h.room('/rooms/' + room + '/music/playlist/' + entry['id'] + '/reports',
                        dict(reason='rights'), 'POST', session=a)
                    self.assertEqual(result[0], 202, result[2])
                self.assertIsNone(self.music(room, a)[2]['selection'])

    def test_room_invalidation_and_rejoin_does_not_restore_old_entries(self):
        a, b, room = self.setup()
        def versions():
            with psycopg.connect(fixture.TeamTests.dsn) as conn:
                return dict(conn.execute("SELECT account_id,revision FROM team_resource_versions WHERE resource='rooms'"))
        before = versions()
        self.assertEqual(self.add(room, b, 'bob')[0], 201)
        track = self.entry(room, b, 'bob')['id']
        after = versions()
        for account in (a, b):
            self.assertGreater(after[account['user']['id']], before[account['user']['id']])
        self.approve_entry(room, track, b, a, 'bob')
        code = self.h.detail(room, a)[2]['code']
        self.h.room('/rooms/' + room + '/leave', method='POST', session=b, who='bob')
        self.assertEqual(self.h.join(b, code, music=True)[0], 200)
        self.assertIsNone(self.entry(room, a)['track'])
        before = versions()
        self.assertEqual(self.remove(room, track, a)[0], 200)
        after = versions()
        for account in (a, b):
            self.assertGreater(after[account['user']['id']], before[account['user']['id']])

    def test_ended_room_clear_preserves_selection_for_archive(self):
        a, _, room = self.setup()
        playlist = music_fixture.RoomMusicTests.list(self, a)
        self.assertEqual(self.select(room, a, playlist)[0], 200)
        service = fixture.TeamTests.module.TEAM_AUTH.room_music_service
        with psycopg.connect(fixture.TeamTests.dsn) as conn:
            before = service.saved(conn, room)
            conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 second' WHERE room_id=%s", (room,))
            service.clear(conn, room)
            self.assertEqual(service.saved(conn, room), before)

    def test_websocket_uses_existing_rooms_invalidation(self):
        a, b, room = self.setup()
        with self.h.websocket(b, who='bob') as receiver:
            self.assertEqual(json.loads(receiver.recv(timeout=2))['type'], 'snapshot')
            self.assertEqual(self.add(room, a)[0], 201)
            frame = json.loads(receiver.recv(timeout=3))
            self.assertEqual(frame['type'], 'invalidate')
            self.assertEqual(frame['resources'], ['rooms'])
            self.assertNotIn('Road song', json.dumps(frame))
            self.assertNotIn(room, json.dumps(frame))

    def test_native_read_shape_stays_strict_and_writes_are_phone_only(self):
        from test_native_functional_music import NativeMusicTests
        a, b, room = self.setup()
        self.assertEqual(self.add(room, b, 'bob')[0], 201)
        entry = self.entry(room, b, 'bob')
        self.approve_entry(room, entry['id'], b, a, 'bob')
        self.assertEqual(self.select(room, a, dict(id=room, revision=1, tracks=[entry['track']]))[0], 200)
        self.approve(room, a)
        native = NativeMusicTests('test_native_dj_current_purpose_room_consent_rights_review_and_withdrawal')
        native.h, native.certs = self.h, {}
        credential = native.connect(b, 'bob')
        native.approve(b, credential, ['rooms:read', 'room-music:read'], who='bob')
        native.room_approve(b, credential, room, who='bob')
        path = '/v1/social/rooms/' + room + '/music'
        status, _, snapshot = native.native(credential, path)
        self.assertEqual(status, 200, snapshot)
        self.assertEqual(set(snapshot), {'revision', 'canEdit', 'selection', 'nativeReadOnly'})
        self.assertEqual(len(snapshot['selection']['tracks']), 1)
        self.assertEqual(set(snapshot['selection']['tracks'][0]), {'id', 'title', 'url'})
        self.assertEqual(snapshot['selection']['currentTrackId'], entry['id'])
        self.assertIn(native.native(credential, path + '/playlist', dict(title='Song', artist='Artist',
            url='https://music.example/song', rightsConfirmed=True), 'POST')[0], (403, 404))


if __name__ == '__main__':
    unittest.main(verbosity=2)
