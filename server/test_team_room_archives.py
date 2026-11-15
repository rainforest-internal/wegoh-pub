"""Archive contracts on the existing isolated PostgreSQL/HTTP fixture."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi import HTTPException
from starlette.responses import Response
from websockets.exceptions import InvalidStatus, ConnectionClosed
import test_team_auth as fixture
import test_team_rooms as rooms
from team_rooms import TeamRooms


_archive_fixture_started = False


def start_archive_fixture():
    global _archive_fixture_started
    if _archive_fixture_started:
        return
    old_voice = os.environ.get('WEGOH_VOICE_ENABLED')
    os.environ['WEGOH_VOICE_ENABLED'] = '1'
    fixture.TeamTests.setUpClass()
    _archive_fixture_started = True

    def cleanup():
        global _archive_fixture_started
        try:
            fixture.TeamTests.tearDownClass()
        finally:
            _archive_fixture_started = False
            if old_voice is None:
                os.environ.pop('WEGOH_VOICE_ENABLED', None)
            else:
                os.environ['WEGOH_VOICE_ENABLED'] = old_voice

    unittest.addModuleCleanup(cleanup)


class ArchiveBoundaryTests(unittest.TestCase):
    def test_native_archive_save_is_denied_before_storage(self):
        from team_history import TeamHistory
        service=TeamHistory(SimpleNamespace(dsn='unused',enabled=True),rooms=None)
        route=next(r for r in service.router().routes if r.path=='/v1/social/history/from-archive')
        request=SimpleNamespace(state=SimpleNamespace(device_identity={'id':'native'}))
        import asyncio
        with patch('team_history.psycopg.connect',side_effect=AssertionError('Native save reached storage')):
            with self.assertRaises(HTTPException)as error:
                asyncio.run(route.endpoint(request=request,response=Response()))
        self.assertEqual(error.exception.status_code,404)

    def test_native_policies_do_not_admit_archive_routes(self):
        from native_access_policy import required_scope, RouteDenied
        from native_functional_policy import is_functional_route
        for path in ('/v1/social/room-archives', '/v1/social/room-archives/'+'a'*32):
            for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                with self.subTest(method=method, path=path):
                    with self.assertRaises(RouteDenied):
                        required_scope(method, path)
                    self.assertFalse(is_functional_route(method, path))

    def test_archive_handlers_reject_native_identity_before_storage(self):
        service = TeamRooms(SimpleNamespace(dsn='unused', enabled=True))
        request = SimpleNamespace(state=SimpleNamespace(device_identity={'id':'native'}))
        endpoints = [route for route in service.router().routes if '/room-archives' in route.path]
        self.assertEqual(len(endpoints), 2)
        for route in endpoints:
            with self.subTest(path=route.path):
                self.assertEqual(route.methods, {'GET'})
                args = dict(request=request, response=Response())
                if '{room}' in route.path:
                    args['room'] = 'a'*32
                with patch('team_rooms.psycopg.connect', side_effect=AssertionError('Native archive request reached storage')):
                    with self.assertRaises(HTTPException) as error:
                        route.endpoint(**args)
                self.assertEqual(error.exception.status_code, 404)


class RoomArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_archive_fixture()

    def setUp(self):
        self.h = rooms.RoomTests(methodName='test_18_room_owner_member_roles_and_explicit_close')
        self.h.setUp()
        self.a, self.b, self.e = self.h.sessions()
        self.room = self.h.new_room(self.a)
        self.rid = self.room['id']
        self.base = '/rooms/' + self.rid
        self.archive = '/room-archives/' + self.rid
        self.assertEqual(self.h.join(self.b, self.room['code'], status=True, location=True, music=True, voice=True)[0], 200)
        self.assertEqual(self.h.share(self.rid, self.a, status=True, location=True, music=True, voice=True)[0], 200)
        self.assertEqual(self.h.room(self.base+'/role', dict(accountId=self.a['user']['id'], role='dj'), 'PATCH', session=self.a)[0], 200)
        status, _, self.playlist = self.h.call('/v1/playlists', dict(name='Archive playlist', tracks=[
            dict(title='Archive song', url='https://www.melon.com/song/detail.htm?songId=10000001')]), 'POST', session=self.a)
        self.assertEqual(status, 201)
        self.selection = dict(revision=0, playlistId=self.playlist['id'], playlistRevision=self.playlist['revision'],
            trackId=self.playlist['tracks'][0]['id'], rightsConfirmed=True)
        status, _, self.music = self.h.room(self.base+'/music', self.selection, 'PUT', session=self.a)
        self.assertEqual(status, 200, self.music)
        status, _, shared = self.h.room(self.base+'/music/playlist', dict(title='Shared archive song',
            artist='Shared artist', url='https://music.example/archive-song', rightsConfirmed=True), 'POST', who='bob', session=self.b)
        self.assertEqual(status, 201, shared)
        self.shared_track = shared['playlist']['tracks'][0]['id']
        status, _, self.signal = self.h.room(self.base+'/signals', dict(kind='rest', destination=dict(
            name='Planned stop', latitude=37.5, longitude=127.0)), 'POST', session=self.a)
        self.assertEqual(status, 201)
        self.vote = self.base+'/signals/'+self.signal['id']+'/vote'
        self.assertEqual(self.h.room(self.vote, dict(choice='agree'), 'POST', who='bob', session=self.b)[0], 200)

    def expire(self):
        with psycopg.connect(self.h.dsn) as conn:
            conn.execute("UPDATE team_rooms SET expires_at=clock_timestamp()-interval '1 second' WHERE room_id=%s", (self.rid,))

    def close(self):
        status, _, value = self.h.room(self.base+'/leave', method='POST', session=self.a)
        self.assertEqual((status, value), (200, dict(status='closed')))

    def save_archive(self,session=None,who='alice',title='My archived trip',**kw):
        return self.h.room('/history/from-archive',dict(roomId=self.rid,title=title),
            'POST',session=session or self.a,who=who,**kw)

    def test_archive_save_is_private_and_retries_preserve_current_edits(self):
        self.assertEqual(self.save_archive()[0],404)
        self.close()
        status,headers,saved=self.save_archive()
        self.assertEqual(status,201,saved)
        self.assertEqual(headers['cache-control'],'private, no-store')
        path='/history/'+saved['id']
        detail=self.h.room(path,session=self.a)[2]
        self.assertEqual(detail['title'],'My archived trip')
        self.assertEqual(detail['source']['roomId'],self.rid)
        self.assertEqual(detail['source']['kind'],'room-confirmed')
        self.assertEqual(detail['visits'],[])
        self.assertEqual(detail['traceBatches'],[])
        self.assertEqual(detail['grants'],[])
        self.assertFalse(detail['permissions']['collectTrace'])
        self.assertLessEqual(detail['startedAt'],detail['endedAt'])
        self.assertEqual(self.h.room(path,who='bob',session=self.b)[0],404)
        edit={key:detail[key]for key in ('startedAt','endedAt','courseId','courseVersion','revision')}
        edit['title']='Edited after saving'
        self.assertEqual(self.h.room(path,edit,'PUT',session=self.a)[0],200)
        retried=self.save_archive(title='Must not overwrite')
        self.assertEqual(retried[0],200)
        self.assertEqual(retried[2]['id'],saved['id'])
        self.assertEqual(retried[2]['revision'],2)
        self.assertEqual(self.h.room(path,session=self.a)[2]['title'],'Edited after saving')
        self.assertEqual(self.h.room(path,method='DELETE',session=self.a)[0],200)
        recreated=self.save_archive()
        self.assertEqual(recreated[0],201)
        self.assertNotEqual(recreated[2]['id'],saved['id'])

    def test_archive_save_current_authority_and_exact_body(self):
        self.close()
        self.assertEqual(self.save_archive(session=self.e,who='eve')[0],404)
        self.assertEqual(self.save_archive(csrf=False)[0],403)
        for value in ({'roomId':self.rid},{'roomId':self.rid,'title':'','consent':True},
                      {'roomId':'invalid','title':'Trip'}):
            self.assertEqual(self.h.room('/history/from-archive',value,'POST',session=self.a)[0],400 if value['roomId']==self.rid else 404)
        self.assertEqual(self.h.room('/blocks',dict(targetId=self.b['user']['id']),'POST',session=self.a)[0],201)
        self.assertEqual(self.save_archive()[0],404)
        self.assertEqual(self.save_archive(session=self.b,who='bob')[0],404)
        with psycopg.connect(self.h.dsn)as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_histories').fetchone()[0],0)

    def test_concurrent_archive_saves_and_former_member_period(self):
        self.assertEqual(self.h.room(self.base+'/leave',method='POST',who='bob',session=self.b)[0],200)
        self.close()
        with ThreadPoolExecutor(max_workers=2)as pool:
            results=list(pool.map(lambda _:self.save_archive(),range(2)))
        self.assertEqual(sorted(r[0]for r in results),[200,201])
        self.assertEqual(results[0][2]['id'],results[1][2]['id'])
        status,_,saved=self.save_archive(session=self.b,who='bob')
        self.assertEqual(status,201,saved)
        detail=self.h.room('/history/'+saved['id'],who='bob',session=self.b)[2]
        with psycopg.connect(self.h.dsn)as conn:
            left=conn.execute('SELECT left_at FROM team_room_members WHERE room_id=%s AND account_id=%s',
                (self.rid,self.b['user']['id'])).fetchone()[0]
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_history_saves').fetchone()[0],2)
        from datetime import datetime
        self.assertEqual(datetime.fromisoformat(detail['endedAt']),left)

    def saved(self, conn):
        result = {}
        for table in ('team_room_members', 'team_room_signals', 'team_room_votes', 'team_room_music', 'team_room_playlist_tracks', 'team_playlists'):
            result[table] = conn.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
        result['metadata'] = conn.execute('SELECT room_id,owner_id,code_hash,protected,created_at FROM team_rooms ORDER BY room_id').fetchall()
        return result

    def test_expiry_archives_once_preserves_records_and_invalidates(self):
        with psycopg.connect(self.h.dsn) as conn:
            before = self.saved(conn)
            music = conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s', (self.rid,)).fetchone()[0]
        with self.h.websocket(self.b, who='bob') as socket:
            self.assertEqual(json.loads(socket.recv(timeout=2))['type'], 'snapshot')
            self.expire()
            event = json.loads(socket.recv(timeout=3))
            self.assertEqual(event['type'], 'invalidate')
            self.assertIn('rooms', event['resources'])
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(self.saved(conn), before)
            row = conn.execute('SELECT archived_at,closed_at,expiry_notified_at,archived_music FROM team_rooms WHERE room_id=%s', (self.rid,)).fetchone()
            self.assertTrue(all(row[:3]))
            self.assertEqual(row[3], music)
            revision = conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='rooms'", (self.a['user']['id'],)).fetchone()[0]
            self.h.module.TEAM_ROOMS.notify_expired(conn)
            self.assertEqual(conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='rooms'", (self.a['user']['id'],)).fetchone()[0], revision)
        status, headers, archive = self.h.room(self.archive, session=self.a)
        self.assertEqual(status, 200)
        self.assertIn('no-store', next(v for k,v in headers.items() if k.lower() == 'cache-control'))
        self.assertEqual((archive['state'], archive['readOnly']), ('archived', True))
        self.assertEqual(archive['signals'][0]['destination']['name'], 'Planned stop')
        self.assertEqual(archive['signals'][0]['votes'], dict(agree=1, **{'pass':0}))
        self.assertEqual(archive['musicSelection']['trackId'], self.selection['trackId'])
        self.assertFalse({'code', 'inviteUri', 'consents', 'availableConsentKeys'} & set(archive))
        self.assertEqual(self.h.room('/overview', session=self.a)[2]['rooms'], [])

    def test_archive_acl_prior_members_current_blocks_and_browser_only(self):
        self.assertEqual(self.h.room(self.archive, session=self.a)[0], 404)
        self.assertEqual(self.h.room(self.base+'/leave', method='POST', who='bob', session=self.b)[0], 200)
        self.close()
        status, _, detail = self.h.room(self.archive, who='bob', session=self.b)
        self.assertEqual(status, 200)
        self.assertEqual(detail['signals'], [])
        self.assertTrue(next(m for m in detail['members'] if m['id'] == self.b['user']['id'])['leftAt'])
        self.assertEqual(self.h.room('/room-archives', who='bob', session=self.b)[2]['rooms'][0]['id'], self.rid)
        self.assertEqual(self.h.room(self.archive, who='eve', session=self.e)[0], 404)
        self.assertEqual(self.h.room('/room-archives', who='eve', session=self.e)[2]['rooms'], [])
        self.assertEqual(self.h.room(self.archive)[0], 401)
        self.assertEqual(self.h.room('/room-archives')[0], 401)
        self.assertEqual(self.h.room('/blocks', dict(targetId=self.b['user']['id']), 'POST', session=self.a)[0], 201)
        for who, session in (('alice', self.a), ('bob', self.b)):
            self.assertEqual(self.h.room(self.archive, who=who, session=session)[0], 404)
            self.assertEqual(self.h.room('/room-archives', who=who, session=session)[2]['rooms'], [])
        self.assertEqual(self.h.room('/blocks/'+self.b['user']['id'], method='DELETE', session=self.a)[0], 200)
        self.assertEqual(self.h.room(self.archive, who='bob', session=self.b)[0], 200)
        _, _, native = self.h.pair(self.a)
        for path in ('/v1/social/room-archives', '/v1/social'+self.archive):
            self.assertIn(self.h.native(path, token=native['accessToken'])[0], (403, 404))
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            self.assertEqual(self.h.room(self.archive, {}, method, session=self.a)[0], 405)

    def assert_closed_paths(self):
        signal = self.base+'/signals/'+self.signal['id']
        member = self.b['user']['id']
        reads = (self.base, '/invites/'+self.room['code'], self.base+'/music',
            self.base+'/voice/filters', self.base+'/device-reports', self.base+'/report-receiving',
            self.base+'/device-command-access', self.base+'/device-requests', self.base+'/missions', self.base+'/driving-data')
        writes = (
            ('POST', '/rooms/join', dict(code=self.room['code'], consents=rooms.choices())),
            ('PATCH', self.base+'/consents', dict(consents=rooms.choices(status=True))),
            ('PATCH', self.base+'/role', dict(accountId=member, role='dj')),
            ('POST', self.base+'/leave', None),
            ('PATCH', self.base+'/review-request', dict(consent=True)),
            ('POST', self.base+'/reports', dict(reason='privacy', code=self.room['code'])),
            ('POST', self.base+'/signals', dict(kind='rest')),
            ('PATCH', signal+'/review-request', dict(consent=True)),
            ('POST', signal+'/reports', dict(reason='privacy')),
            ('POST', self.vote, dict(choice='pass')), ('DELETE', self.vote, None),
            ('PUT', self.base+'/music', dict(self.selection, revision=1)),
            ('DELETE', self.base+'/music', dict(revision=1)),
            ('PATCH', self.base+'/music/review-request', dict(revision=1, consent=True)),
            ('POST', self.base+'/music/reports', dict(selectionId=self.music['selection']['id'], reason='privacy')),
            ('POST', self.base+'/music/playlist', dict(title='Closed room song', artist='Artist', url='https://music.example/closed', rightsConfirmed=True)),
            ('DELETE', self.base+'/music/playlist/'+self.shared_track, None),
            ('PATCH', self.base+'/music/playlist/'+self.shared_track+'/review-request', dict(consent=True)),
            ('POST', self.base+'/music/playlist/'+self.shared_track+'/reports', dict(reason='privacy')),
            ('PUT', self.base+'/voice/filters/'+member, dict(muted=True)),
            ('POST', self.base+'/voice/reports', dict(speakerId=member, leaseId='a'*32, reason='privacy')),
            ('PUT', self.base+'/device-reporting', dict(deviceId='d'*32, revision=0, joinedAt='2026-01-01T00:00:00Z',
                devicePermissionRevision=0, shareLocation=True, shareVisits=True, receiveLocation=True, receiveVisits=True, expiresInHours=1)),
            ('DELETE', self.base+'/device-reporting', None),
            ('PUT', self.base+'/report-receiving', dict(revision=0, joinedAt='2026-01-01T00:00:00Z', receiveLocation=True, receiveVisits=True, expiresInHours=1)),
            ('DELETE', self.base+'/report-receiving', None),
            ('POST', self.base+'/missions', dict(preference='balanced')),
        )
        for method, path, data in [('GET', path, None) for path in reads] + list(writes):
            with self.subTest(method=method, path=path):
                result = self.h.room(path, data, method, session=self.a)
                self.assertEqual(result[0], 404, result[2])
        with self.assertRaises(InvalidStatus):
            self.h.websocket(self.a, path='/v1/social'+self.base+'/voice')
        vehicle = self.h.module.TEAM_VEHICLE
        with psycopg.connect(self.h.dsn) as conn:
            with patch.object(vehicle, 'purposes', return_value=(None, dict(location=True, visits=True), 1, None)):
                for kind in ('location', 'visits'):
                    with self.assertRaises(HTTPException) as error:
                        vehicle.ingest(conn, self.rid, dict(id=self.a['user']['id'], deviceId='d'*32), None, kind, {})
                    self.assertEqual(error.exception.status_code, 404)

    def test_all_live_paths_reject_expired_and_archived_rooms_without_changes(self):
        with psycopg.connect(self.h.dsn) as conn:
            before = self.saved(conn)
        self.expire()
        self.assert_closed_paths()
        self.assertEqual(self.h.room(self.archive, session=self.a)[0], 200)
        self.assert_closed_paths()
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(self.saved(conn), before)

    def test_owner_close_preserves_records_and_terminates_live_voice(self):
        with psycopg.connect(self.h.dsn) as conn:
            before = self.saved(conn)
        with self.h.websocket(self.a, path='/v1/social'+self.base+'/voice') as socket:
            self.assertEqual(json.loads(socket.recv(timeout=2))['type'], 'ready')
            self.close()
            with self.assertRaises(ConnectionClosed):
                while True:
                    socket.recv(timeout=3)
        self.assert_closed_paths()
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(self.saved(conn), before)

    def test_location_reports_are_deleted_but_archive_sources_are_not(self):
        vehicle = self.h.module.TEAM_VEHICLE
        with psycopg.connect(self.h.dsn) as conn:
            before = self.saved(conn)
            conn.execute('INSERT INTO native_device_refs(device_id,kind) VALUES(%s,%s)', ('d'*32, 'retired'))
            for kind in ('location', 'visits'):
                raw = vehicle.protect(kind, self.a['user']['id'], self.rid+':'+'d'*32, dict(synthetic=True))
                conn.execute('INSERT INTO team_vehicle_latest_reports(room_id,device_id,kind,account_id,protected) VALUES(%s,%s,%s,%s,%s)',
                    (self.rid, 'd'*32, kind, self.a['user']['id'], raw))
        self.close()
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_vehicle_latest_reports WHERE room_id=%s', (self.rid,)).fetchone()[0], 0)
            self.assertEqual(self.saved(conn), before)
        archive = self.h.room(self.archive, session=self.a)[2]
        self.assertNotIn('synthetic', json.dumps(archive))

    def test_archive_music_survives_later_personal_playlist_changes(self):
        self.close()
        original = self.h.room(self.archive, session=self.a)[2]['musicSelection']
        self.assertEqual(self.h.call('/v1/playlists/'+self.playlist['id'], method='DELETE', session=self.a)[0], 200)
        self.assertEqual(self.h.room(self.archive, session=self.a)[2]['musicSelection'], original)

    def test_expired_music_is_preserved_before_late_playlist_invalidation(self):
        with psycopg.connect(self.h.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s', (self.rid,)).fetchone()[0]
        self.expire()
        self.assertEqual(self.h.call('/v1/playlists/'+self.playlist['id'], method='DELETE', session=self.a)[0], 200)
        with psycopg.connect(self.h.dsn) as conn:
            archived = conn.execute('SELECT archived_at,archived_music FROM team_rooms WHERE room_id=%s', (self.rid,)).fetchone()
            self.assertIsNotNone(archived[0])
            self.assertEqual(archived[1], raw)
            self.assertEqual(conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s', (self.rid,)).fetchone()[0], raw)
        archive = self.h.room(self.archive, session=self.a)[2]
        self.assertIsNotNone(archive['musicSelection'])
        self.assertEqual(archive['musicSelection']['trackId'], self.selection['trackId'])
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(conn.execute('SELECT archived_music FROM team_rooms WHERE room_id=%s', (self.rid,)).fetchone()[0], raw)

    def test_shared_selection_and_playlist_survive_archive_and_repeated_clear(self):
        status, _, review = self.h.room(self.base+'/music/playlist/'+self.shared_track+'/review-request',
            dict(consent=True), 'PATCH', who='bob', session=self.b)
        self.assertEqual(status, 200, review)
        status, _, decision = self.h.call('/v1/moderation/content/room-music/'+self.rid+':'+self.shared_track,
            dict(checksum=review['checksum'], decision='approved', reviewer='Synthetic admin',
                reviewNote='Synthetic shared archive track reviewed'), 'POST', session=self.a)
        self.assertEqual(status, 200, decision)
        status, _, selected = self.h.room(self.base+'/music', dict(self.selection, revision=1,
            playlistId=self.rid, playlistRevision=1, trackId=self.shared_track), 'PUT', session=self.a)
        self.assertEqual(status, 200, selected)
        with psycopg.connect(self.h.dsn) as conn:
            before = self.saved(conn)
        self.expire()
        service = self.h.module.TEAM_ROOM_MUSIC
        with psycopg.connect(self.h.dsn) as conn:
            service.clear(conn, self.rid)
            archived = conn.execute('SELECT archived_at,archived_music FROM team_rooms WHERE room_id=%s', (self.rid,)).fetchone()
            self.assertIsNotNone(archived[0])
            self.assertEqual(service.restore(self.rid, archived[1])['sharedTrackId'], self.shared_track)
            service.clear(conn, self.rid)
            self.assertEqual(conn.execute('SELECT archived_at,archived_music FROM team_rooms WHERE room_id=%s', (self.rid,)).fetchone(), archived)
            self.assertEqual(self.saved(conn), before)
        status, _, archive = self.h.room(self.archive, session=self.a)
        self.assertEqual(status, 200, archive)
        self.assertEqual(archive['musicSelection']['playlistId'], self.rid)
        self.assertEqual(archive['musicSelection']['trackId'], self.shared_track)
        self.assert_closed_paths()
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(self.saved(conn), before)

    def test_old_notified_and_owner_closed_rooms_are_lazily_archived(self):
        closed = self.h.new_room(self.a)['id']
        with psycopg.connect(self.h.dsn) as conn:
            conn.execute("UPDATE team_rooms SET expires_at=clock_timestamp()-interval '1 second',expiry_notified_at=now() WHERE room_id=%s", (self.rid,))
            conn.execute('UPDATE team_rooms SET closed_at=clock_timestamp() WHERE room_id=%s', (closed,))
            before = self.saved(conn)
        status, _, listing = self.h.room('/room-archives', session=self.a)
        self.assertEqual(status, 200)
        self.assertEqual({item['id'] for item in listing['rooms']}, {self.rid, closed})
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_rooms WHERE archived_at IS NOT NULL').fetchone()[0], 2)
            self.assertEqual(self.saved(conn), before)

    def test_additive_migration_keeps_populated_legacy_rows_and_repeats(self):
        schema = (Path(__file__).parent/'schema.sql').read_text()
        original, migration = schema.split('-- E1 room archive', 1)
        tables = ('team_accounts', 'team_rooms', 'team_room_members', 'team_room_signals', 'team_room_votes', 'team_room_music', 'team_room_playlist_tracks')
        with psycopg.connect(self.h.dsn) as conn:
            conn.execute('CREATE SCHEMA e1_archive_migration')
            conn.execute('SET LOCAL search_path TO e1_archive_migration')
            conn.execute(original)
            for table in tables:
                columns = [row[0] for row in conn.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position', ('e1_archive_migration', table))]
                fields = ','.join(columns)
                conn.execute('INSERT INTO '+table+'('+fields+') SELECT '+fields+' FROM public.'+table)
            conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 hour',expiry_notified_at=now()")
            columns = {table:[row[0] for row in conn.execute('SELECT column_name FROM information_schema.columns '
                'WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position', ('e1_archive_migration', table))] for table in tables}
            before = {table:conn.execute('SELECT '+','.join(columns[table])+' FROM '+table+' ORDER BY 1,2').fetchall() for table in tables}
            conn.execute(migration)
            conn.execute(migration)
            for table in tables:
                after = conn.execute('SELECT '+','.join(columns[table])+' FROM '+table+' ORDER BY 1,2').fetchall()
                self.assertEqual(after, before[table])
            self.assertEqual(conn.execute('SELECT archived_at,archived_music,trip_id FROM team_rooms').fetchone(), (None, None, None))
            conn.execute('SET LOCAL search_path TO public')
            conn.execute('DROP SCHEMA e1_archive_migration CASCADE')


class TripResultBoundaryTests(unittest.TestCase):
    def test_archive_classes_share_one_fixture_until_module_cleanup(self):
        with patch(__name__ + '._archive_fixture_started', False), patch.dict(os.environ), \
                patch.object(fixture.TeamTests, 'setUpClass') as start, \
                patch.object(fixture.TeamTests, 'tearDownClass') as stop, \
                patch.object(unittest, 'addModuleCleanup') as register:
            start_archive_fixture()
            start_archive_fixture()
            start.assert_called_once_with()
            stop.assert_not_called()
            register.assert_called_once()
            register.call_args.args[0]()
            stop.assert_called_once_with()

    def test_personal_period_never_extends_past_finish_or_uses_future_start(self):
        from datetime import datetime, timezone, timedelta
        from team_history import TeamHistory
        joined = datetime(2026, 1, 1, tzinfo=timezone.utc)
        started, ended = joined + timedelta(hours=1), joined + timedelta(hours=2)
        context = dict(startedAt=started, endedAt=ended)
        self.assertEqual(TeamHistory.trip_period(context, joined, ended + timedelta(hours=1)), (started, ended))
        left = joined + timedelta(minutes=10)
        self.assertEqual(TeamHistory.trip_period(context, joined, left), (joined, left))

    def test_trip_routes_deny_native_before_storage(self):
        import asyncio
        from team_trip_results import TeamTripResults
        service = TeamTripResults(SimpleNamespace(dsn='unused', enabled=True))
        request = SimpleNamespace(state=SimpleNamespace(device_identity={'id':'native'}))
        routes = [route for route in service.trip_router().routes if route.path.startswith('/v1/social/')]
        self.assertEqual(len(routes), 4)
        for route in routes:
            args = dict(request=request, response=Response())
            if '{trip}' in route.path:
                args['trip'] = 'a'*32
            with self.subTest(path=route.path), patch('team_trip_results.psycopg.connect', side_effect=AssertionError('Reached storage')):
                with self.assertRaises(HTTPException) as error:
                    if 'POST' in route.methods:
                        asyncio.run(route.endpoint(**args))
                    else:
                        route.endpoint(**args)
                self.assertEqual(error.exception.status_code, 404)

    def test_archive_listing_does_not_collide_with_trip_detail(self):
        from starlette.routing import Match
        from team_trips import TeamTrips
        from team_trip_results import TeamTripResults
        auth = SimpleNamespace(dsn='unused', enabled=True)
        routes = TeamTrips(auth).router().routes + TeamTripResults(auth).trip_router().routes
        matches = [route for route in routes if route.matches(dict(type='http', method='GET', path='/v1/social/trip-archives'))[0] == Match.FULL]
        self.assertEqual([route.path for route in matches], ['/v1/social/trip-archives'])


class TripResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_team_trips
        cls.fixture = test_team_trips.TripTests
        start_archive_fixture()

    def setUp(self):
        from team_trip_results import TeamTripResults
        self.h = self.fixture(methodName='test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.auth = self.h.module.TEAM_AUTH
        self.service = TeamTripResults(self.auth, self.h.module.TEAM_ROOMS, self.h.module.TEAM_HISTORY)
        self.previous = getattr(self.auth, 'trip_results_service', None)
        self.auth.trip_results_service = self.service
        self.addCleanup(setattr, self.auth, 'trip_results_service', self.previous)
        self.a, self.b, self.e = self.h.sessions()
        self.trip = self.h.new_trip(self.a)
        self.h.join(self.trip, self.a, self.b)
        self.owner, self.member = self.a['user']['id'], self.b['user']['id']

    def transition(self, action):
        with psycopg.connect(self.h.dsn) as conn:
            revision = conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s', (self.trip,)).fetchone()[0]
            return self.h.module.TEAM_TRIPS.transition(conn, self.trip, self.owner, action, revision)

    def detail(self, account=None):
        with psycopg.connect(self.h.dsn) as conn:
            return self.service.archive_detail(conn, self.trip, account or self.owner)

    def finish(self):
        self.transition('start')
        return self.transition('finish')

    def test_finish_writes_one_encrypted_summary_without_personal_records_or_live_access(self):
        with patch.object(self.service.rooms, 'access', side_effect=AssertionError('Live room access')):
            finished = self.finish()
            result = self.detail()
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(result['summaryState'], 'available')
            self.assertEqual(result['summary']['safety']['state'], 'unavailable')
        with psycopg.connect(self.h.dsn) as conn:
            self.h.module.TEAM_TRIPS.transition(conn, self.trip, self.owner, 'finish', finished['revision'])
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results WHERE trip_id=%s', (self.trip,)).fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_histories').fetchone()[0], 0)
            raw = conn.execute('SELECT protected FROM team_trip_results WHERE trip_id=%s', (self.trip,)).fetchone()[0]
            self.assertNotIn(self.owner.encode(), bytes(raw))
            self.assertEqual(len(self.service.restore(self.trip, raw)['members']), 2)

    def test_summary_is_filtered_after_sharing_revocation_and_block(self):
        from team_rooms import CONSENTS
        available = self.service.rooms.available_consents()
        with psycopg.connect(self.h.dsn) as conn:
            self.h.module.TEAM_TRIPS.set_sharing(conn, self.trip, self.member, {key:key in available for key in CONSENTS})
        self.finish()
        self.assertEqual({member['accountId'] for member in self.detail()['summary']['members']}, {self.owner, self.member})
        with psycopg.connect(self.h.dsn) as conn:
            self.h.module.TEAM_TRIPS.set_sharing(conn, self.trip, self.member, {key:False for key in CONSENTS})
        self.assertEqual([member['accountId'] for member in self.detail()['summary']['members']], [self.owner])
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.owner), 'POST')[0], 201)
        self.assertIsNone(self.detail(self.member)['summary'])
        self.assertEqual(self.detail(self.member)['state'], 'left')
        self.assertEqual(self.detail()['summary']['members'][0]['accountId'], self.owner)

    def test_former_member_keeps_only_own_period_and_personal_record(self):
        self.transition('start')
        self.assertEqual(self.h.trip('/'+self.trip+'/members/'+self.member, method='DELETE', session=self.b)[0], 200)
        before = self.detail(self.member)
        self.assertEqual(before['state'], 'left')
        self.assertIsNone(before['summary'])
        self.transition('finish')
        after = self.detail(self.member)
        self.assertEqual(after, before)
        with psycopg.connect(self.h.dsn) as conn:
            saved, created = self.service.save_history(conn, self.trip, self.member, 'Only my time')
            self.assertTrue(created)
            record = self.service.history.detail(conn, saved['id'], self.member)
            self.assertEqual(record['source']['tripId'], self.trip)
            self.assertEqual(record['endedAt'], before['ownPeriod']['endedAt'].isoformat())
            self.assertEqual((record['visits'], record['traceBatches'], record['grants']), ([], [], []))
        self.assertEqual(self.h.social('/blocks', self.b, dict(targetId=self.owner), 'POST')[0], 201)
        self.assertEqual(self.h.social('/history/'+saved['id'], self.b)[0], 200)

    def test_pending_and_outsider_and_legacy_cross_member_blocks_are_denied(self):
        self.h.befriend(self.a, self.e, who=self.e['user']['displayName'])
        self.h.invite(self.trip, self.a, self.e)
        self.finish()
        with self.assertRaises(HTTPException) as error:
            self.detail(self.e['user']['id'])
        self.assertEqual(error.exception.status_code, 404)
        with psycopg.connect(self.h.dsn) as conn:
            conn.execute("UPDATE team_trips SET source_kind='legacy_room' WHERE trip_id=%s", (self.trip,))
        with patch('team_trip_results.blocked', return_value=True):
            with self.assertRaises(HTTPException) as error:
                self.detail()
            self.assertEqual(error.exception.status_code, 404)

    def test_end_failure_rolls_back_lifecycle_and_retry_can_finish(self):
        self.transition('start')
        with patch.object(self.service, 'protect', side_effect=RuntimeError('Synthetic result failure')):
            with self.assertRaises(RuntimeError):
                self.transition('finish')
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(conn.execute('SELECT state FROM team_trips WHERE trip_id=%s', (self.trip,)).fetchone()[0], 'active')
            self.assertIsNone(conn.execute('SELECT closed_at FROM team_rooms WHERE trip_id=%s', (self.trip,)).fetchone()[0])
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results').fetchone()[0], 0)
        self.assertEqual(self.transition('finish')['state'], 'completed')

    def test_current_feature_readers_cannot_inject_other_trip_or_new_ids(self):
        self.finish()
        with psycopg.connect(self.h.dsn) as conn:
            context, _, _ = self.service.access(conn, self.trip, self.owner)
            reader = SimpleNamespace(trip_result_reader=lambda *args: dict(missions=[
                dict(id='a'*32, state='result-withdrawn', roomId=context['roomId']), dict(id='b'*32, state='completed')]))
            with patch.object(self.auth, 'mission_service', reader, create=True):
                result = self.service.current_results(conn, context, self.owner, dict(missions=['a'*32]),
                    'missions', 'mission_service', 'trip_result_reader')
            self.assertEqual(result, [dict(id='a'*32, state='result-withdrawn')])

    def test_finish_freezes_selected_and_agreed_place_ids_and_rechecks_current_sharing(self):
        selected = dict(id='a'*32, kind='selected', place=dict(name='Selected place'))
        agreed = dict(id='b'*32, kind='agreed', place=dict(name='Agreed place'))
        from unittest.mock import Mock
        reader = Mock(return_value=dict(places=[selected, agreed, selected]))
        service = SimpleNamespace(result_reader=reader)
        with patch.object(self.auth, 'trip_places_service', service, create=True):
            self.finish()
            with psycopg.connect(self.h.dsn) as conn:
                raw = conn.execute('SELECT protected FROM team_trip_results WHERE trip_id=%s', (self.trip,)).fetchone()[0]
                self.assertEqual(self.service.restore(self.trip, raw)['places'], [selected['id'], agreed['id']])
            self.assertEqual(self.detail()['summary']['places'], [selected, agreed])
            reader.return_value = dict(places=[selected, dict(id='c'*32, kind='agreed', place=dict(name='Later place'))])
            self.assertEqual(self.detail()['summary']['places'], [selected, dict(id=agreed['id'], state='unavailable')])

    def test_cancelled_and_soft_deleted_trips_preserve_personal_records(self):
        self.transition('cancel')
        self.assertIsNone(self.detail()['summary'])
        with psycopg.connect(self.h.dsn) as conn:
            saved, _ = self.service.save_history(conn, self.trip, self.owner, 'Cancelled trip')
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_results').fetchone()[0], 0)
        self.assertEqual(self.h.trip('/'+self.trip, method='DELETE', session=self.a)[0], 200)
        self.assertEqual(self.h.social('/history/'+saved['id'], self.a)[0], 200)
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(self.service.list_archives(conn, self.owner)['archives'], [])

    def test_concurrent_personal_saves_reuse_current_record_and_keep_edits(self):
        self.finish()

        def save(title):
            with psycopg.connect(self.h.dsn) as conn:
                return self.service.save_history(conn, self.trip, self.owner, title)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(save, ['First save', 'Second save']))
        self.assertEqual(first[0]['id'], second[0]['id'])
        self.assertEqual(sorted([first[1], second[1]]), [False, True])
        item = first[0]['id']
        with psycopg.connect(self.h.dsn) as conn:
            row, record, _, _ = self.service.history.row(conn, item, self.owner, True)
            record['title'] = 'Edited later'
            self.service.history.save(conn, row, record, data=True, permission=True)
        result, created = save('Must not overwrite')
        self.assertFalse(created)
        self.assertEqual(result, dict(id=item, revision=2, permissionRevision=2))
        with psycopg.connect(self.h.dsn) as conn:
            self.assertEqual(self.service.history.detail(conn, item, self.owner)['title'], 'Edited later')
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_history_saves').fetchone()[0], 1)

    def test_existing_legacy_archive_save_is_reused_after_promotion(self):
        self.finish()
        with psycopg.connect(self.h.dsn) as conn:
            context, joined, _ = self.service.access(conn, self.trip, self.owner)
            item = self.service.history.add(conn, self.owner,
                dict(title='Existing archived record', startedAt=joined.isoformat(), endedAt=joined.isoformat(),
                    courseId=None, courseVersion=None),
                dict(kind='room-confirmed', actorId=self.owner, receivedAt=joined.isoformat(), roomId=context['roomId']))
            conn.execute('INSERT INTO team_room_history_saves(room_id,account_id,history_id) VALUES(%s,%s,%s)',
                (context['roomId'], self.owner, item))
            result, created = self.service.save_history(conn, self.trip, self.owner, 'New title')
            self.assertFalse(created)
            self.assertEqual(result['id'], item)
            detail = self.service.history.detail(conn, item, self.owner)
            self.assertEqual(detail['source']['roomId'], context['roomId'])
            self.assertEqual(detail['title'], 'Existing archived record')


if __name__ == '__main__':
    unittest.main(verbosity=2)
