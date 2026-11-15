import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import psycopg
from fastapi import HTTPException
from team_room_music import TeamRoomMusic
from team_rooms import CONSENTS
from team_trip_context import resolve_trip_context
from native_room_music_authority import NativeRoomMusicAuthority
from native_room_voice_authority import NativeRoomVoiceAuthority


class TripMusicPolicyTests(unittest.TestCase):
    def test_trip_dto_hides_internal_room_references(self):
        room, trip = 'a'*32, 'b'*32
        source = dict(revision=2, selection=dict(playlistId=room, review=dict(key=room+':'+('c'*32))), playlist=dict(tracks=[]))
        value = TeamRoomMusic.trip_dto(source, trip, room)
        self.assertEqual(value['tripId'], trip)
        self.assertEqual(value['contractVersion'], 1)
        self.assertNotIn(room, json.dumps(value))
        self.assertEqual(source['selection']['playlistId'], room)

    def test_finite_expiry_and_membership_generation_apply_to_both_authorities(self):
        joined = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for authority, flags in ((NativeRoomMusicAuthority, dict(receiveMusic=True,shareMusic=True)),
                                  (NativeRoomVoiceAuthority, dict(receiveVoice=True,transmitVoice=True))):
            with self.subTest(authority=authority.__name__):
                functional = SimpleNamespace(base=SimpleNamespace(now=lambda:100),auth=SimpleNamespace())
                service = authority(functional, MagicMock())
                row = dict(device_id='d'*32,state='ACTIVE',member_joined_at=joined,expires_at=150,revision=3)
                service.row = MagicMock(return_value=row)
                service.payload = MagicMock(return_value=dict(permissions=flags))
                if hasattr(service, 'trip_default'):
                    service.trip_default = MagicMock(return_value=False)
                grant = dict(device_id='d'*32,grant_id='e'*32)
                consent = dict(revision=1,approvedPurposes=['rooms:read','room-music:read','room-music:control','room-voice:receive','room-voice:transmit'])
                value = service.snapshot(None,grant,consent,'a'*32,joined,200)
                self.assertEqual(value['expiresAt'],150)
                self.assertTrue(all(value['permissions'].values()))
                for member, expiry in ((joined.replace(day=2),200),(joined,99)):
                    self.assertFalse(any(service.snapshot(None,grant,consent,'a'*32,member,expiry)['permissions'].values()))
                trip_value = service.trip_snapshot(value,'b'*32)
                self.assertNotIn('roomId',trip_value)
                self.assertEqual(trip_value['contractVersion'],1)

    def test_trip_context_has_no_fake_room_expiry_and_legacy_context_remains_bounded(self):
        for authority in (NativeRoomMusicAuthority,NativeRoomVoiceAuthority):
            db = MagicMock();db.connection=db;db.autocommit=False
            cursor = db.cursor.return_value.__enter__.return_value
            joined = datetime(2026,1,1,tzinfo=timezone.utc)
            cursor.execute.return_value.fetchone.return_value=(joined,)
            functional = MagicMock()
            functional.owner_grant.return_value=(dict(grant_id='c'*32,expires_at=250),None)
            functional.snapshot.return_value=dict(expiresAt=200)
            rooms = MagicMock()
            rooms.access.return_value=dict(expiresAt=None,state='active')
            service = authority(functional,rooms)
            self.assertEqual(service.context(db,'owner','d'*32,'a'*32,trip_context=True)[-1],200)
            rooms.access.assert_called_with(cursor,'a'*32,'owner',trip_context=True)
            rooms.access.return_value=dict(expiresAt=datetime.fromtimestamp(175,timezone.utc),state='active')
            self.assertEqual(service.context(db,'owner','d'*32,'a'*32)[-1],175)

    def test_trip_withdraw_hooks_do_not_require_live_membership(self):
        music=TeamRoomMusic(SimpleNamespace(dsn='',enabled=True),MagicMock())
        music.clear=MagicMock()
        music.withdraw_trip_context(None,'trip','room','former')
        music.clear.assert_called_once_with(None,'room','former')
        for authority in (NativeRoomMusicAuthority,NativeRoomVoiceAuthority):
            service=authority(SimpleNamespace(base=None,auth=None),None)
            service.withdraw_room_context=MagicMock()
            service.withdraw_trip_context(None,'trip','room')
            service.withdraw_room_context.assert_called_once_with(None,'room',None)

    def test_unsafe_or_foreign_playlist_links_fail_before_storage_or_playback(self):
        music=TeamRoomMusic(SimpleNamespace(dsn='',enabled=True),MagicMock())
        data=dict(kind='playlist-link',provider='melon',title='여행 음악',revision=0,rightsConfirmed=True)
        for url in ('http://www.melon.com/list','https://www.melon.com.evil.invalid/list',
                    'https://user@www.melon.com/list','https://www.melon.com:444/list','https://www.melon.com/ bad'):
            with self.subTest(url=url), self.assertRaises(HTTPException) as error:
                music.select_link(None,'a'*32,'owner',dict(data,url=url),trip_context=True)
            self.assertEqual(error.exception.status_code,400)
        music.rooms.access.assert_not_called()


class TripMusicIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_team_trips import TripTests
        cls.fixture=TripTests
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)

    def setUp(self):
        self.h=self.fixture('test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.auth=self.h.module.TEAM_AUTH;self.music=self.auth.room_music_service
        self.a,self.b,self.e=self.h.sessions()
        self.trip=self.h.new_trip(self.a)
        self.h.join(self.trip,self.a,self.b);self.h.join(self.trip,self.a,self.e)
        with psycopg.connect(self.h.dsn) as conn:
            context=resolve_trip_context(self.auth,conn,self.trip,self.a['user']['id'])
            self.room=context['roomId']
            self.auth.trip_service.set_role(conn,self.trip,self.a['user']['id'],self.b['user']['id'],'dj',context['revision'])
            for session in (self.a,self.b,self.e):
                self.auth.trip_service.set_sharing(conn,self.trip,session['user']['id'],{key:key=='music' for key in CONSENTS})

    def api(self, session, path, data=None, method='GET', *, expected=200, **kwargs):
        status, _, value = self.h.call(path, data, method, session=session, who=session['user']['displayName'], **kwargs)
        self.assertEqual(status, expected, value)
        return value

    def personal_music(self, session):
        return self.api(session, '/v1/playlists', dict(name='내 음악', tracks=[
            dict(title='여행 음악 모음', url='https://www.melon.com/mymusic/dj/mymusicdjplaylistview_inform.htm?plylstSeq=5001'),
            dict(title='공유하지 않은 음악', url='https://www.melon.com/playlist/detail.htm?plylstSeq=5002'),
        ]), 'POST', expected=201)

    def import_choice(self, source, index=0):
        return dict(playlistId=source['id'], playlistRevision=source['revision'], trackId=source['tracks'][index]['id'],
                    rightsConfirmed=True, reviewConsent=True)

    def publish_track(self, identifier):
        path = '/v1/moderation/content/room-music/' + self.room + ':' + identifier
        detail = self.api(self.a, path)
        self.api(self.a, path, dict(checksum=detail['review']['checksum'], decision='approved', reviewer='검수자',
                                    reviewNote='여행 음악 제목과 링크 확인'), 'POST')

    def test_regular_member_adds_one_saved_link_and_review_controls_visibility(self):
        endpoint = '/v1/social/trips/' + self.trip + '/music/saved-playlists'
        with psycopg.connect(self.h.dsn) as conn:
            self.auth.trip_service.set_sharing(conn,self.trip,self.e['user']['id'],{key:False for key in CONSENTS})
        empty = self.api(self.e, endpoint)
        self.assertEqual(empty, dict(tripId=self.trip, items=[], limit=200, canAdd=True, canReorder=False, nowPlaying=[]))
        source = self.personal_music(self.e)
        choice = self.import_choice(source)
        with ThreadPoolExecutor(max_workers=2) as workers:
            copies = list(workers.map(lambda _: self.api(self.e, endpoint, choice, 'POST'), range(2)))
        self.assertEqual(copies[0], copies[1])
        added, = copies[0]['items']
        self.assertEqual(set(added), {'id','title','url','addedBy','reviewState'})
        self.assertEqual((added['title'],added['url']), (source['tracks'][0]['title'],source['tracks'][0]['url']))
        self.assertEqual(added['addedBy'], dict(id=self.e['user']['id'], name=self.e['user']['displayName']))
        self.assertEqual(self.api(self.a, endpoint)['items'], [])
        self.assertNotIn(source['id'], json.dumps(added))
        self.publish_track(added['id'])
        released, = self.api(self.a, endpoint)['items']
        self.assertEqual(released, dict(added,reviewState='approved'))
        self.assertEqual(self.api(self.b, endpoint)['items'], [released])
        self.assertEqual(self.api(self.e, '/v1/social/trips/'+self.trip+'/workspace')['mySharing']['music'], False)
        self.h.close_trip(self.trip,self.a,action='start')
        self.assertEqual(self.api(self.a, endpoint)['items'], [released])
        self.assertIsNone(self.api(self.b, endpoint.removesuffix('/saved-playlists'))['selection'])
        self.assertEqual(self.api(self.e, '/v1/playlists/'+source['id']), source)
        contributed = endpoint.removesuffix('/saved-playlists') + '/playlist/' + added['id']
        self.api(self.e, contributed+'/review-request', dict(consent=False), 'PATCH')
        self.assertEqual(self.api(self.a, endpoint)['items'], [])
        requested, = self.api(self.e, endpoint, choice, 'POST')['items']
        self.assertEqual(requested, dict(released, reviewState='quarantined'))
        self.assertEqual(self.api(self.a, endpoint)['items'], [])
        self.publish_track(requested['id'])
        self.assertEqual(self.api(self.a, endpoint)['items'], [released])
        self.api(self.e, contributed, method='DELETE')
        self.assertEqual(self.api(self.e, endpoint)['items'], [])
        self.assertEqual(self.api(self.a, endpoint)['items'], [])

    def test_source_membership_ownership_and_review_are_checked_on_every_read(self):
        endpoint = '/v1/social/trips/' + self.trip + '/music/saved-playlists'
        source = self.personal_music(self.e)
        choice = self.import_choice(source)
        for changes in ({'rightsConfirmed':False},{'reviewConsent':False},{'url':source['tracks'][0]['url']}):
            self.api(self.e, endpoint, dict(choice,**changes), 'POST', expected=400)
        self.api(self.e, endpoint, choice, 'POST', csrf=False, expected=403)
        self.api(self.e, endpoint, dict(choice,playlistRevision=source['revision']+1), 'POST', expected=409)
        self.assertIn(self.h.call(endpoint,choice,'POST',session=self.a)[0], (404,409))
        entry, = self.api(self.e, endpoint, choice, 'POST')['items']
        self.publish_track(entry['id'])
        changed = self.api(self.e, '/v1/playlists/'+source['id'], dict(name=source['name'], revision=source['revision'],
            tracks=source['tracks'] + [dict(title='추가 곡',url='https://music.youtube.com/playlist?list=PL2000')]), 'PUT')
        self.assertEqual([item['id'] for item in self.api(self.b,endpoint)['items']], [entry['id']])
        block = self.h.social('/blocks',self.b,dict(targetId=self.e['user']['id']),'POST')
        self.assertEqual(block[0],201,block[2])
        self.assertEqual(self.api(self.b,endpoint)['items'],[])
        self.assertEqual(len(self.api(self.a,endpoint)['items']),1)
        replacement = dict(changed['tracks'][0], url='https://music.youtube.com/playlist?list=PL3000')
        self.api(self.e, '/v1/playlists/'+source['id'], dict(name=changed['name'], revision=changed['revision'],
            tracks=[replacement,*changed['tracks'][1:]]), 'PUT')
        self.assertEqual(self.api(self.a,endpoint)['items'],[])
        other = self.h.new_trip(self.a)
        foreign = '/v1/social/trips/'+other+'/music/saved-playlists'
        self.api(self.e, foreign, expected=404)
        self.api(self.e, foreign, choice, 'POST', expected=404)

    def test_native_participant_can_add_only_a_current_owned_saved_choice(self):
        endpoint = '/v1/social/trips/' + self.trip + '/music/saved-playlists'
        source = self.personal_music(self.e)
        _,_,device = self.h.pair(self.e,'eve')
        auth = dict(token=device['accessToken'], certificate=self.h._native_fingerprint)
        status, _, consent = self.h.native('/v1/device/functional-permissions', **auth)
        self.assertEqual(status,200,consent)
        status, _, value = self.h.native(endpoint, **auth)
        self.assertEqual((status,value), (200,self.api(self.e,endpoint)))
        choice = self.import_choice(source)
        self.assertEqual(self.h.native(endpoint, choice,'POST',**auth)[0],400)
        revision = consent['revision']
        self.assertEqual(self.h.native(endpoint,dict(choice,functionalRevision=revision+1),'POST',**auth)[0],409)
        status, _, value = self.h.native(endpoint,dict(choice,functionalRevision=revision),'POST',**auth)
        self.assertEqual(status,200,value)
        self.assertEqual(value,self.api(self.e,endpoint))
        entry, = value['items']
        self.publish_track(entry['id'])
        browser_call = self.h.call
        def approve_without_library(path, data=None, method='GET', **kwargs):
            if method=='POST' and path.startswith('/v1/connections/'):
                data=dict(data, approvedScopes=[scope for scope in data['approvedScopes'] if scope!='playlists:read'])
            return browser_call(path,data,method,**kwargs)
        self.assertEqual(self.h.native('/v1/device',method='DELETE',**auth)[0],200)
        with patch.object(self.h,'call',side_effect=approve_without_library):
            _,_,restricted = self.h.pair(self.e,'eve')
        limited = dict(token=restricted['accessToken'],certificate=self.h._native_fingerprint)
        self.assertEqual(self.h.native(endpoint,**limited)[0],200)
        self.assertEqual(self.h.native('/v1/playlists',**limited)[0],403)
        functional = self.h.native('/v1/device/functional-permissions',**limited)[2]['revision']
        self.assertEqual(self.h.native(endpoint,dict(choice,functionalRevision=functional),'POST',**limited)[0],403)
        self.api(self.a, '/v1/social/trips/'+self.trip+'/members/'+self.e['user']['id'], method='DELETE')
        self.assertEqual(self.h.native(endpoint, **auth)[0],401)
        self.assertEqual(self.h.native(endpoint, **limited)[0],404)
        self.assertEqual(self.api(self.a,endpoint)['items'],[])
        self.h.join(self.trip,self.a,self.e)
        self.assertEqual(self.api(self.a,endpoint)['items'],[])
        self.h.close_trip(self.trip,self.a,action='cancel')
        self.api(self.e, endpoint, choice, 'POST', expected=409)

    def test_vehicle_playback_is_shared_and_only_dj_or_owner_reorders(self):
        base = '/v1/social/trips/' + self.trip + '/music'
        endpoint, playing = base + '/saved-playlists', base + '/now-playing'
        source = self.personal_music(self.e)
        first, = self.api(self.e, endpoint, self.import_choice(source, 0), 'POST')['items']
        second = self.api(self.e, endpoint, self.import_choice(source, 1), 'POST')['items'][1]
        for item in (first, second):
            self.publish_track(item['id'])
        _,_,device = self.h.pair(self.e,'eve')
        auth = dict(token=device['accessToken'], certificate=self.h._native_fingerprint)
        revision = self.h.native('/v1/device/functional-permissions', **auth)[2]['revision']
        self.api(self.e, playing, dict(itemId=first['id']), 'PUT', expected=403)
        self.assertEqual(self.h.native(playing, dict(itemId=first['id']), 'PUT', **auth)[0], 400)
        status, _, value = self.h.native(playing, dict(itemId=second['id'], functionalRevision=revision), 'PUT', **auth)
        self.assertEqual(status, 200, value)
        now, = value['nowPlaying']
        self.assertEqual((now['itemId'], now['startedBy']), (second['id'], dict(id=self.e['user']['id'], name=self.e['user']['displayName'])))
        self.assertEqual(self.api(self.a, endpoint)['nowPlaying'], [now])
        self.assertEqual(self.h.native(playing, dict(itemId='f'*32, functionalRevision=revision), 'PUT', **auth)[0], 409)
        self.assertFalse(self.api(self.e, endpoint)['canReorder'])
        self.assertTrue(self.api(self.b, endpoint)['canReorder'] and self.api(self.a, endpoint)['canReorder'])
        position = endpoint + '/' + second['id'] + '/position'
        self.assertEqual(self.h.native(position, dict(afterId=None, functionalRevision=revision), 'PATCH', **auth)[0], 403)
        moved = self.api(self.b, position, dict(afterId=None), 'PATCH')
        self.assertEqual([item['id'] for item in moved['items']], [second['id'], first['id']])
        self.assertEqual([item['id'] for item in self.api(self.e, endpoint)['items']], [second['id'], first['id']])
        block = self.h.social('/blocks', self.b, dict(targetId=self.e['user']['id']), 'POST')
        self.assertEqual(block[0], 201, block[2])
        self.assertEqual(self.api(self.b, endpoint)['nowPlaying'], [])
        self.api(self.e, base + '/playlist/' + second['id'], method='DELETE')
        self.assertEqual(self.api(self.a, endpoint)['nowPlaying'], [])
        self.api(self.a, '/v1/social/trips/' + self.trip + '/members/' + self.e['user']['id'], method='DELETE')
        self.assertEqual(self.api(self.a, endpoint)['nowPlaying'], [])

    def test_saved_and_manually_added_links_share_review_and_keep_their_order(self):
        base = '/v1/social/trips/' + self.trip + '/music'
        endpoint = base + '/saved-playlists'
        track = dict(title='이전 여행 링크', artist='음악', url='https://www.melon.com/playlist/detail.htm?plylstSeq=5100',
                     rightsConfirmed=True)
        old = self.api(self.b, base+'/playlist', track, 'POST', expected=201)['playlist']['tracks'][0]
        self.assertEqual(self.api(self.a,endpoint)['items'],[])
        self.api(self.b, base+'/playlist/'+old['id']+'/review-request', dict(consent=True), 'PATCH')
        self.publish_track(old['id'])
        source = self.personal_music(self.e)
        items = self.api(self.e,endpoint,self.import_choice(source),'POST')['items']
        self.assertEqual([item['title'] for item in items], [track['title'],source['tracks'][0]['title']])
        self.publish_track(items[1]['id'])
        self.assertEqual([item['id'] for item in self.api(self.a,endpoint)['items']], [old['id'],items[1]['id']])
        self.api(self.b, base+'/playlist/'+old['id']+'/review-request', dict(consent=False), 'PATCH')
        self.assertEqual([item['id'] for item in self.api(self.a,endpoint)['items']], [items[1]['id']])
        self.api(self.e,'/v1/playlists/'+source['id'],method='DELETE')
        self.assertEqual(self.api(self.a,endpoint)['items'],[])

    def test_vehicle_reads_the_same_trip_playlist_as_the_phone(self):
        base = '/v1/social/trips/' + self.trip + '/music'
        endpoint = base + '/saved-playlists'
        source = self.personal_music(self.a)
        saved, = self.api(self.a, endpoint, self.import_choice(source), 'POST')['items']
        self.publish_track(saved['id'])
        typed = self.api(self.e, base+'/playlist', dict(title='Zoo', artist='음악', url='https://youtu.be/jNQXAC9IVRw',
                                                         rightsConfirmed=True), 'POST', expected=201)['playlist']['tracks'][-1]
        self.api(self.e, base+'/playlist/'+typed['id']+'/review-request', dict(consent=True), 'PATCH')
        self.publish_track(typed['id'])
        _,_,car = self.h.pair(self.a)
        auth = dict(token=car['accessToken'], certificate=self.h._native_fingerprint)
        def vehicle():
            status, _, value = self.h.native(endpoint, **auth)
            self.assertEqual(status, 200, value)
            return value
        phone = self.api(self.a, endpoint)
        self.assertEqual([item['id'] for item in phone['items']], [saved['id'], typed['id']])
        self.assertEqual(vehicle(), phone)
        self.api(self.b, endpoint+'/'+typed['id']+'/position', dict(afterId=None), 'PATCH')
        self.assertEqual([item['id'] for item in vehicle()['items']], [typed['id'], saved['id']])
        self.api(self.e, base+'/playlist/'+typed['id']+'/review-request', dict(consent=False), 'PATCH')
        self.assertEqual(vehicle(), self.api(self.a, endpoint))
        self.assertEqual([item['id'] for item in vehicle()['items']], [saved['id']])
        self.api(self.e, base+'/playlist/'+typed['id']+'/review-request', dict(consent=True), 'PATCH')
        self.publish_track(typed['id'])
        self.assertEqual(len(vehicle()['items']), 2)
        with psycopg.connect(self.h.dsn) as conn:
            self.auth.trip_service.set_sharing(conn, self.trip, self.a['user']['id'], {key: False for key in CONSENTS})
        self.assertEqual(vehicle(), self.api(self.a, endpoint))
        self.assertNotIn(typed['id'], [item['id'] for item in vehicle()['items']])
        with psycopg.connect(self.h.dsn) as conn:
            self.auth.trip_service.set_sharing(conn, self.trip, self.a['user']['id'], {key: key == 'music' for key in CONSENTS})
        self.assertIn(typed['id'], [item['id'] for item in vehicle()['items']])
        self.assertEqual(self.h.social('/blocks', self.a, dict(targetId=self.e['user']['id']), 'POST')[0], 201)
        self.assertEqual(vehicle(), self.api(self.a, endpoint))
        self.assertNotIn(typed['id'], [item['id'] for item in vehicle()['items']])

    def select(self,session=None):
        session=session or self.b
        with psycopg.connect(self.h.dsn) as conn:
            revision=self.music.saved(conn,self.room)[0]
            return self.music.select_link(conn,self.room,session['user']['id'],dict(revision=revision,kind='playlist-link',provider='melon',title='함께 가는 길',url='https://www.melon.com/mymusic/playlist/mymusicplaylistview_inform.htm?plylstSeq=1234',rightsConfirmed=True),trip_context=True)

    def test_dj_handoff_consent_rejoin_and_end_never_restore_a_selection(self):
        for boundary in ('dj','consent','rejoin','end'):
            with self.subTest(boundary=boundary):
                selected=self.select();self.assertEqual(selected['selection']['kind'],'playlist-link')
                with psycopg.connect(self.h.dsn) as conn:
                    if boundary=='dj':
                        context=resolve_trip_context(self.auth,conn,self.trip,self.a['user']['id'])
                        update=self.auth.trip_service.set_role(conn,self.trip,self.a['user']['id'],self.e['user']['id'],'dj',context['revision'])
                        self.auth.trip_service.set_role(conn,self.trip,self.a['user']['id'],self.b['user']['id'],'dj',update['revision'])
                    elif boundary=='consent':
                        self.auth.trip_service.set_sharing(conn,self.trip,self.b['user']['id'],{key:False for key in CONSENTS})
                        self.auth.trip_service.set_sharing(conn,self.trip,self.b['user']['id'],{key:key=='music' for key in CONSENTS})
                    elif boundary=='rejoin':
                        self.auth.trip_service.remove_member(conn,self.trip,self.b['user']['id'])
                    else:
                        context=resolve_trip_context(self.auth,conn,self.trip,self.a['user']['id'])
                        self.auth.trip_service.transition(conn,self.trip,self.a['user']['id'],'cancel',context['revision'])
                    self.assertIsNone(self.music.saved(conn,self.room)[1])
                if boundary=='rejoin':
                    self.h.join(self.trip,self.a,self.b)
                    with psycopg.connect(self.h.dsn) as conn:
                        self.auth.trip_service.set_sharing(conn,self.trip,self.b['user']['id'],{key:key=='music' for key in CONSENTS})
                        context=resolve_trip_context(self.auth,conn,self.trip,self.a['user']['id'])
                        self.auth.trip_service.set_role(conn,self.trip,self.a['user']['id'],self.b['user']['id'],'dj',context['revision'])
        with psycopg.connect(self.h.dsn) as conn, self.assertRaises(HTTPException):
            self.music.snapshot(conn,self.room,self.b['user']['id'],trip_context=True)

    def test_block_hides_only_the_parties_music_and_legacy_route_denies(self):
        selected=self.select()
        with psycopg.connect(self.h.dsn) as conn:
            projection=self.music.current(conn,self.room,self.music.saved(conn,self.room)[1],trip_context=True)
            review=self.music.content.request(conn,'room-music',self.room+':'+selected['selection']['id'],self.b['user']['id'],projection,True,expires_at=None)
        result=self.h.call('/v1/moderation/content/room-music/'+self.room+':'+selected['selection']['id'],dict(checksum=review['checksum'],decision='approved',reviewer='Synthetic admin',reviewNote='Synthetic metadata reviewed'),'POST',session=self.a)
        self.assertEqual(result[0],200,result[2])
        self.assertEqual(self.h.social('/blocks',self.b,dict(targetId=self.e['user']['id']),'POST')[0],201)
        with psycopg.connect(self.h.dsn) as conn:
            self.assertIsNone(self.music.snapshot(conn,self.room,self.e['user']['id'],trip_context=True)['selection'])
            self.assertIsNotNone(self.music.snapshot(conn,self.room,self.a['user']['id'],trip_context=True)['selection'])
        self.assertEqual(self.h.social('/rooms/'+self.room+'/music',self.b)[0],409)
        other=self.h.new_trip(self.a)
        with psycopg.connect(self.h.dsn) as conn:
            room=resolve_trip_context(self.auth,conn,other,self.a['user']['id'])['roomId']
            with self.assertRaises(HTTPException):
                self.music.shared_entry(conn,room,'f'*32,trip_context=True)


if __name__=='__main__':
    unittest.main()
