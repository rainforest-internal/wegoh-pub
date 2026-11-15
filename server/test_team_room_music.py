"""Room music metadata on owned temporary PG; no provider fetch/audio/vehicle."""
import json
import os
from pathlib import Path
import unittest
from concurrent.futures import ThreadPoolExecutor

import psycopg
import test_team_auth as fixture
import test_team_rooms as rooms


class RoomMusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        __import__('api_application')
    @classmethod
    def tearDownClass(cls):
        fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=rooms.RoomTests(methodName='test_18_room_owner_member_roles_and_explicit_close')
        self.h.setUp()
    def setup(self):
        a,b,_=self.h.sessions()
        room=self.h.new_room(a);rid=room['id']
        self.assertEqual(self.h.join(b,room['code'],music=True)[0],200)
        self.assertEqual(self.h.share(rid,a,music=True)[0],200)
        self.assertEqual(self.h.room('/rooms/'+rid+'/role',dict(accountId=a['user']['id'],role='dj'),'PATCH',session=a)[0],200)
        return a,b,rid
    def list(self,session,who='alice'):
        status,_,data=self.h.call('/v1/playlists',dict(name='Synthetic road music',tracks=[
            dict(title='Synthetic first song',url='https://www.melon.com/song/detail.htm?songId=10000001'),
            dict(title='Synthetic second song',url='https://www.melon.com/song/detail.htm?songId=10000002')]),'POST',session=session,who=who)
        self.assertEqual(status,201,data);return data
    def music(self,rid,session,who='alice',data=None,method='GET'):
        return self.h.room('/rooms/'+rid+'/music',data,method,session=session,who=who)
    def select(self,rid,session,playlist,revision=0,index=0,who='alice',**extra):
        value=dict(revision=revision,playlistId=playlist['id'],playlistRevision=playlist['revision'],
                   trackId=playlist['tracks'][index]['id'],rightsConfirmed=True);value.update(extra)
        return self.music(rid,session,who,value,'PUT')
    def approve(self,rid,a):
        own=self.music(rid,a)[2]
        status,_,review=self.h.room('/rooms/'+rid+'/music/review-request',
            dict(revision=own['revision'],consent=True),'PATCH',session=a)
        self.assertEqual(status,200,review)
        key=rid+':'+own['selection']['id']
        status,_,decision=self.h.call('/v1/moderation/content/room-music/'+key,
            dict(checksum=review['checksum'],decision='approved',reviewer='Synthetic admin',reviewNote='Synthetic metadata and source links reviewed'),
            'POST',session=a)
        self.assertEqual(status,200,decision)
        return own

    def test_01_explicit_consent_dj_ownership_rights_and_current_track(self):
        a,b,rid=self.setup();playlist=self.list(a)
        self.assertEqual(self.select(rid,b,playlist,who='bob')[0],403)
        self.assertEqual(self.select(rid,a,playlist,rightsConfirmed=False)[0],400)
        self.assertEqual(self.select(rid,a,{**playlist,'id':'f'*32})[0],409)
        first=self.select(rid,a,playlist)
        self.assertEqual(first[0],200,first[2]);self.assertEqual(first[2]['revision'],1)
        self.assertIsNone(self.music(rid,b,'bob')[2]['selection'])
        self.approve(rid,a)
        received=self.music(rid,b,'bob')[2]['selection']
        self.assertEqual(received['name'],playlist['name']);self.assertEqual(received['tracks'],playlist['tracks'])
        second=self.select(rid,a,playlist,1,1)
        self.assertEqual(second[0],200,second[2])
        self.assertEqual(self.music(rid,b,'bob')[2]['selection']['currentTrackId'],playlist['tracks'][1]['id'])
        self.assertEqual(self.select(rid,a,playlist,1)[0],409)

    def test_02_review_withdraw_and_report_requarantine(self):
        a,b,rid=self.setup();playlist=self.list(a);self.select(rid,a,playlist);self.approve(rid,a)
        value=self.music(rid,b,'bob')[2]
        self.assertEqual(self.h.room('/rooms/'+rid+'/music/reports',
            dict(selectionId=value['selection']['id'],reason='rights'),'POST',session=b,who='bob')[0],202)
        self.assertIsNone(self.music(rid,b,'bob')[2]['selection'])
        self.assertEqual(self.music(rid,a)[2]['selection']['review']['state'],'quarantined')
        own=self.music(rid,a)[2]
        self.assertEqual(self.h.room('/rooms/'+rid+'/music/review-request',dict(revision=own['revision'],consent=False),'PATCH',session=a)[0],200)
        queue=self.h.call('/v1/moderation/content',session=a)[2]
        self.assertNotIn(rid+':'+own['selection']['id'],[item['key']for item in queue['items']])

    def test_03_scope_withdraw_dj_handoff_and_playlist_edit_clear(self):
        a,b,rid=self.setup();playlist=self.list(a);self.select(rid,a,playlist);self.approve(rid,a)
        self.assertEqual(self.h.share(rid,a,music=True,status=True)[0],200)
        self.assertIsNotNone(self.music(rid,b,'bob')[2]['selection'])
        self.assertEqual(self.h.share(rid,a,music=True)[0],200) # unrelated status/location off keeps music
        self.assertIsNotNone(self.music(rid,b,'bob')[2]['selection'])
        self.assertEqual(self.h.call('/v1/playlists/'+playlist['id'],
            dict(name=playlist['name'],tracks=playlist['tracks'],revision=playlist['revision']),'PUT',session=a)[0],200)
        self.assertIsNone(self.music(rid,b,'bob')[2]['selection'])
        changed=self.h.call('/v1/playlists/'+playlist['id'],session=a)[2]
        selected=self.select(rid,a,changed,revision=self.music(rid,a)[2]['revision'])
        self.assertEqual(selected[0],200,selected[2]);self.approve(rid,a)
        self.h.room('/rooms/'+rid+'/role',dict(accountId=b['user']['id'],role='dj'),'PATCH',session=a)
        self.assertIsNone(self.music(rid,b,'bob')[2]['selection'])
        members=self.h.detail(rid,a)[2]['members']
        self.assertEqual([item['id']for item in members if item['role']=='dj'],[b['user']['id']])

    def test_04_leave_block_expiry_and_receiver_revocation(self):
        for boundary in ('receiver','sender','leave','block','expiry'):
            with self.subTest(boundary=boundary):
                self.setUp();a,b,rid=self.setup();playlist=self.list(a);self.select(rid,a,playlist);self.approve(rid,a)
                if boundary=='receiver':
                    self.h.share(rid,b,who='bob');self.assertEqual(self.music(rid,b,'bob')[0],403)
                    continue
                if boundary=='sender':self.h.share(rid,a)
                elif boundary=='leave':self.h.room('/rooms/'+rid+'/leave',method='POST',session=a)
                elif boundary=='block':self.h.friend('/blocks',dict(targetId=b['user']['id']),'POST',session=a)
                else:
                    with psycopg.connect(fixture.TeamTests.dsn)as conn:conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 second'WHERE room_id=%s",(rid,))
                status,_,value=self.music(rid,b,'bob')
                if boundary=='sender':self.assertIsNone(value['selection'])
                else:self.assertEqual(status,404,value)

    def test_05_parallel_revision_and_native_no_implicit_music_purpose(self):
        a,b,rid=self.setup();playlist=self.list(a)
        with ThreadPoolExecutor(max_workers=2)as pool:
            statuses=list(pool.map(lambda index:self.select(rid,a,playlist,index=index)[0],[0,1]))
        self.assertEqual(sorted(statuses),[200,409])
        # Use the current proof-checked public-v1 connection fixture. Global
        # functional purpose and this device's room consent are separate gates.
        from test_native_functional_music import NativeMusicTests
        native=NativeMusicTests('test_native_dj_current_purpose_room_consent_rights_review_and_withdrawal')
        native.h=self.h;native.certs={}
        credential=native.connect(a);device=credential['deviceId'];key=credential['accessToken']
        native.approve(a,credential,['rooms:read'])
        path='/v1/social/rooms/'+rid+'/music'
        self.assertEqual(native.native(credential,path)[0],403)
        permission='/v1/devices/'+device+'/music-permission'
        current=self.h.call(permission,session=a)[2]
        self.assertEqual(current['authority'],'native-functional');self.assertFalse(current['enabled'])
        self.assertEqual(self.h.call(permission,dict(revision=current['revision'],enabled=True),
            'PUT',session=b,who='bob')[0],404)
        self.assertEqual(self.h.call(permission,dict(revision=current['revision'],enabled=True),
            'PUT',session=a)[0],409)
        self.assertFalse(self.h.call(permission,session=a)[2]['enabled'])
        native.approve(a,credential,['rooms:read'])
        self.assertEqual(native.native(credential,path)[0],403)
        native.approve(a,credential,['rooms:read','room-music:read'])
        self.assertTrue(self.h.call(permission,session=a)[2]['enabled'])
        self.assertEqual(native.native(credential,path)[0],403)
        native.room_approve(a,credential,rid)
        self.assertEqual(native.native(credential,path)[0],200)
        other=native.connect(b,'bob')
        self.assertEqual(native.native(credential,path,certificate=native.certs[other['grantId']])[0],401)
        fingerprint=native.certs[credential['grantId']]
        self.assertEqual(self.h.native(path,certificate=fingerprint)[0],401)
        # The shared synthetic HTTP fixture supplies trusted-edge certificate
        # headers; actual TLS transport is covered by its dedicated suites.
        import socket
        from websockets.sync.client import connect
        raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=5)
        with connect('ws://api.wegoh.invalid/v1/events',sock=raw,origin=None,open_timeout=3,close_timeout=1,
            additional_headers={'Authorization':'Bearer '+key,'cf-cert-sha256':fingerprint,
                'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'})as channel:
            initial=json.loads(channel.recv(timeout=3));self.assertEqual(initial['type'],'snapshot')
            self.assertEqual(initial['resources'],['courses','devices','playlists'])
            with self.h.websocket(a)as browser:
                snapshot=json.loads(browser.recv(timeout=3));self.assertIn('rooms',snapshot['resources'])
                current=self.music(rid,a)[2]
                self.assertEqual(self.select(rid,a,playlist,current['revision'],1)[0],200)
                event=json.loads(browser.recv(timeout=3));self.assertEqual(event['type'],'invalidate');self.assertIn('rooms',event['resources'])
                self.assertNotIn('Synthetic',json.dumps(event))
            event=json.loads(channel.recv(timeout=3));self.assertEqual(event['type'],'invalidate')
            self.assertEqual(event['resources'],['devices']);self.assertNotIn('Synthetic',json.dumps(event))
            self.assertEqual(self.h.call(permission,method='DELETE',session=a)[0],409)
            self.assertTrue(self.h.call(permission,session=a)[2]['enabled'])
            revoke='/v1/devices/'+device+'/functional-permissions/room-music:read'
            self.assertEqual(self.h.call(revoke,method='DELETE',session=a)[0],200)
            event=json.loads(channel.recv(timeout=3));self.assertEqual(event['type'],'invalidate')
            self.assertEqual(event['resources'],['devices']);self.assertNotIn('Synthetic',json.dumps(event))
        self.assertFalse(self.h.call(permission,session=a)[2]['enabled'])
        self.assertEqual(native.native(credential,path)[0],403)
        native.approve(a,credential,['rooms:read','room-music:read'])
        self.assertEqual(native.native(credential,path)[0],403) # Reapproval never revives room consent.

    def test_06_encrypted_selection_and_no_metadata_in_events(self):
        a,b,rid=self.setup();playlist=self.list(a);self.select(rid,a,playlist)
        with psycopg.connect(fixture.TeamTests.dsn)as conn:
            raw=conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0]
            self.assertNotIn(playlist['id'].encode(),bytes(raw))
            versions=conn.execute("SELECT resource,revision FROM team_resource_versions WHERE account_id=%s AND resource='rooms'",(b['user']['id'],)).fetchall()
            self.assertTrue(versions);self.assertGreater(versions[0][1],1)
        self.assertEqual(self.h.room('/rooms/'+rid+'/music',dict(revision=1),'DELETE',session=a,csrf=False)[0],403)

    def test_07_current_openapi_documents_separate_device_and_room_purposes(self):
        a,b,rid=self.setup();playlist=self.list(a)
        selected=self.select(rid,a,playlist)[2]
        request=self.h.room('/rooms/'+rid+'/music/review-request',dict(revision=selected['revision'],consent=True),'PATCH',session=a)
        self.assertEqual(request[0],200,request[2])
        status,_,inspected=self.h.call('/v1/moderation/content/room-music/'+rid+':'+selected['selection']['id'],session=a)
        self.assertEqual(status,200,inspected)
        status,_,schema=self.h.call('/developer/openapi.json',session=a)
        self.assertEqual(status,200,schema)
        get=schema['paths']['/v1/social/rooms/{room}/music']['get']
        self.assertIn({'NativeMTLS':[],'DeviceBearer':[]},get['security'])
        self.assertIn('rooms:read',get['description']);self.assertIn('room-music:read',get['description'])
        native=schema['paths']['/v1/device/music-permission']['get']
        self.assertFalse(native['x-wegoh-executable'])
        self.assertEqual(native['security'],[{'NativeMTLS':[],'DeviceBearer':[]}])
        put=schema['paths']['/v1/social/rooms/{room}/music']['put']['requestBody']['content']['application/json']['schema']
        browser,native_put=put['oneOf']
        self.assertFalse(browser['additionalProperties']);self.assertFalse(native_put['additionalProperties'])
        self.assertEqual(set(browser['required']),{'revision','playlistId','playlistRevision','trackId','rightsConfirmed'})
        self.assertEqual(set(native_put['required'])-set(browser['required']),{'functionalRevision','roomMusicRevision'})
        for method in ('put','delete'):
            retired=schema['paths']['/v1/devices/{device}/music-permission'][method]
            self.assertFalse(retired['x-wegoh-executable']);self.assertIn('409',retired['responses']);self.assertNotIn('200',retired['responses'])
        documented=sum(method in ('get','post','put','patch','delete')for methods in schema['paths'].values()for method in methods)
        self.assertEqual(schema['x-wegoh-documentation-coverage']['operations'],documented)
        for path,methods in {
            '/v1/social/rooms/{room}/music':('get','put','delete'),
            '/v1/social/rooms/{room}/music/review-request':('patch',),
            '/v1/social/rooms/{room}/music/reports':('post',),
            '/v1/devices/{device}/music-permission':('get','put','delete'),
            '/v1/device/music-permission':('get',)}.items():
            self.assertTrue(set(methods)<=set(schema['paths'][path]))
        export=os.environ.get('WEGOH_ROOM_MUSIC_SCHEMA_EXPORT')
        if export:
            root=Path(__file__).resolve().parents[1]
            target=Path(export)
            if target.parent.resolve()!=root/'docs/evidence/room-music-unit'or target.exists()or target.is_symlink():
                raise RuntimeError('Explicit fresh public synthetic schema evidence path required')
            target.write_text(json.dumps(dict(openapi=schema,projection=inspected['projection']),ensure_ascii=False,indent=2)+chr(10))

if __name__=='__main__':unittest.main(verbosity=2)
