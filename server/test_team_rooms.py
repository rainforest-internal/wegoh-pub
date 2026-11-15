"""Isolated room contracts: no production account, DB, GPS, voice or vehicle."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
import unittest
import psycopg
import uvicorn
import test_team_auth as auth_fixture
import test_team_friends as friend_fixture

KEYS=('status','location','visits','music','voice','control')
def choices(**values):return {key:values.get(key,False) for key in KEYS}

class RoomTests(friend_fixture.FriendTests):
    def test_linked_room_legacy_routes_and_expiry_are_closed(self):
        from team_trip_context import resolve_trip_context
        a, b, e = self.sessions()
        status, _, created = self.friend('/trips', dict(title='통합 여행',description='',memberIds=[]), 'POST', session=a)
        self.assertEqual(status, 201)
        trip = created['id']
        with psycopg.connect(self.dsn) as conn:
            context = resolve_trip_context(self.module.TEAM_AUTH, conn, trip, a['user']['id'])
            room = context['roomId']
            before = conn.execute('SELECT protected,closed_at,archived_at,expiry_notified_at FROM team_rooms WHERE room_id=%s', (room,)).fetchone()
            self.module.TEAM_ROOMS.notify_expired(conn)
            self.assertEqual(conn.execute('SELECT protected,closed_at,archived_at,expiry_notified_at FROM team_rooms WHERE room_id=%s', (room,)).fetchone(), before)
            self.assertIsNone(self.module.TEAM_ROOMS.access(conn, room, a['user']['id'], trip_context=True)['expiresAt'])
        for path, data, method in (
                ('', None, 'GET'), ('/leave', None, 'POST'),
                ('/consents', dict(consents=choices()), 'PATCH'),
                ('/role', dict(accountId=a['user']['id'],role='dj'), 'PATCH'),
                ('/signals', dict(kind='rest'), 'POST')):
            result = self.room('/rooms/'+room+path, data, method, session=a)
            self.assertEqual((result[0],result[2]), (409,dict(detail='TRIP_CLIENT_UPDATE_REQUIRED')))
        self.assertEqual(self.detail(room,b,'bob')[0], 404)
        self.assertEqual(self.room('/overview', session=a)[2]['rooms'], [])

    def room(self,path,data=None,method='GET',who='alice',session=None,**kw):
        return self.friend(path,data,method,who=who,session=session,**kw)
    def new_room(self,session,**kw):
        value=dict(name='Shared road',courseId=None,courseVersion=None,expiresInHours=6)
        value.update(kw);status,_,data=self.room('/rooms',value,'POST',session=session)
        self.assertEqual(status,201,data);return data
    def join(self,session,code,who='bob',**values):
        return self.room('/rooms/join',dict(code=code,consents=choices(**values)),'POST',who,session)
    def share(self,room,session,who='alice',**values):
        return self.room('/rooms/'+room+'/consents',dict(consents=choices(**values)),'PATCH',who,session)
    def detail(self,room,session,who='alice'):
        return self.room('/rooms/'+room,session=session,who=who)

    def test_agreed_stop_uses_other_members_votes_and_current_consent(self):
        alice, bob, eve = self.sessions()
        room = self.new_room(alice)
        rid, code = room['id'], room['code']
        self.assertEqual(self.share(rid, alice, status=True, location=True)[0], 200)
        self.assertEqual(self.join(bob, code, status=True, location=True)[0], 200)
        destination = dict(name='Synthetic stop', latitude=37.5, longitude=127.0)
        status, _, proposal = self.room('/rooms/'+rid+'/signals', dict(kind='restroom', destination=destination),
                                       'POST', 'bob', bob)
        self.assertEqual(status, 201, proposal)
        vote = '/rooms/'+rid+'/signals/'+proposal['id']+'/vote'
        self.assertEqual(self.room(vote, dict(choice='agree'), 'POST', 'bob', bob)[0], 200)
        self.assertIsNone(self.detail(rid, alice)[2]['agreedStop'])
        self.assertEqual(self.room(vote, dict(choice='agree'), 'POST', session=alice)[0], 200)
        own = self.detail(rid, bob, 'bob')[2]['agreedStop']
        peer = self.detail(rid, alice)[2]['agreedStop']
        self.assertEqual(own, dict(signalId=proposal['id'], destination=destination))
        self.assertEqual(peer['signalId'], own['signalId'])
        self.assertEqual(peer['destination']['name'], '선택한 장소')
        self.assertEqual(self.detail(rid, eve, 'eve')[0], 404)
        self.assertEqual(self.join(eve, code, who='eve', status=True)[0], 200)
        self.assertIsNone(self.detail(rid, alice)[2]['agreedStop'])
        self.assertEqual(self.room(vote, dict(choice='agree'), 'POST', 'eve', eve)[0], 200)
        self.assertEqual(self.detail(rid, alice)[2]['agreedStop']['signalId'], proposal['id'])
        self.assertEqual(self.room(vote, method='DELETE', who='eve', session=eve)[0], 200)
        self.assertIsNone(self.detail(rid, alice)[2]['agreedStop'])
        self.assertEqual(self.room(vote, dict(choice='agree'), 'POST', 'eve', eve)[0], 200)
        self.assertEqual(self.share(rid, bob, who='bob', status=True, location=False)[0], 200)
        self.assertIsNone(self.detail(rid, alice)[2]['agreedStop'])

    def test_18_room_owner_member_roles_and_explicit_close(self):
        a,b,e=self.sessions();room=self.new_room(a);rid=room['id'];path='/rooms/'+rid
        self.assertEqual(self.detail(rid,b,'bob')[0],404)
        invited=self.room('/invites/'+room['code'],session=b,who='bob')[2]
        self.assertEqual(invited['availableConsentKeys'],['status','location','music']);self.assertNotIn('members',invited)
        self.assertEqual(self.join(b,room['code'])[0],200)
        own=self.detail(rid,b,'bob')[2]
        self.assertEqual(own['consents'],choices());self.assertEqual(own['role'],'member')
        self.assertEqual(self.room(path+'/role',dict(accountId=b['user']['id'],role='dj'),'PATCH',session=a)[0],200)
        self.assertEqual(self.room(path+'/role',dict(accountId=a['user']['id'],role='food'),'PATCH','bob',b)[0],403)
        self.assertEqual(self.room(path+'/role',dict(accountId=b['user']['id'],role='dj'),'PATCH','eve',e)[0],404)
        self.assertEqual(self.room(path+'/leave',method='POST',who='bob',session=b)[2]['status'],'left')
        self.assertEqual(self.detail(rid,a)[0],200);self.assertEqual(self.detail(rid,b,'bob')[0],404)
        self.assertEqual(self.room(path+'/leave',method='POST',session=a)[2]['status'],'closed')
        self.assertEqual(self.detail(rid,a)[0],404)
        self.assertEqual(self.room('/overview',session=a)[2]['rooms'],[])
        with psycopg.connect(self.dsn) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_rooms').fetchone()[0],1)

    def test_19_exact_consents_unsupported_capabilities_and_idempotent_join(self):
        a,b,_=self.sessions();room=self.new_room(a);rid=room['id']
        for unsupported in ('visits','voice','control'):
            self.assertEqual(self.join(b,room['code'],**{unsupported:True})[0],400)
        self.assertEqual(self.room('/rooms/join',dict(code=room['code'],consents={'status':True}),'POST','bob',b)[0],400)
        self.assertEqual(self.join(b,room['code'],status=True)[0],200)
        self.assertEqual(self.room('/rooms/'+rid+'/role',dict(accountId=b['user']['id'],role='dj'),'PATCH',session=a)[0],200)
        repeated=self.join(b,room['code'])[2]
        self.assertTrue(repeated['consents']['status'])
        self.assertEqual(self.detail(rid,b,'bob')[2]['role'],'dj')
        self.assertEqual(self.room('/rooms/'+rid+'/consents',dict(consents=choices()),'PATCH',session=b,who='bob',csrf=False)[0],403)
        self.assertEqual(self.room('/rooms/'+rid+'/role',dict(accountId=[],role='dj'),'PATCH',session=a)[0],400)
        self.assertEqual(self.detail(rid+'%20',a)[0],404)

    def test_20_past_place_and_status_disclosure_rechecked_on_every_read(self):
        a,b,_=self.sessions();room=self.new_room(a);rid=room['id'];self.join(b,room['code'],status=True)
        self.share(rid,a,status=True,location=True)
        place=dict(name='Chosen meeting place',latitude=37.654321,longitude=127.123456)
        signal=self.room('/rooms/'+rid+'/signals',dict(kind='restroom',destination=place),'POST',session=a)
        self.assertEqual(signal[0],201)
        # Location consent permits coordinates; unreviewed user text remains masked.
        self.assertEqual(self.detail(rid,a)[2]['signals'][0]['destination'],place)
        self.assertEqual(self.detail(rid,b,'bob')[2]['signals'][0]['destination'],dict(place,name='선택한 장소'))
        self.share(rid,a,status=True)
        redacted=self.detail(rid,b,'bob')[2]
        self.assertIsNone(redacted['signals'][0]['destination']);self.assertNotIn('127.123456',json.dumps(redacted))
        self.share(rid,a)
        self.assertEqual(self.detail(rid,b,'bob')[2]['signals'],[])
        self.assertEqual(self.room('/rooms/'+rid+'/signals',dict(kind='rest'),'POST',session=a)[0],403)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_signals').fetchone()[0],1)
            raw=conn.execute('SELECT protected FROM team_room_signals').fetchone()[0]
        self.assertNotIn(b'127.123456',bytes(raw))

    def test_21_votes_are_individual_and_withdrawal_hides_old_votes(self):
        a,b,e=self.sessions();room=self.new_room(a);rid=room['id'];self.join(b,room['code'],status=True);self.share(rid,a,status=True,location=True)
        _,_,status=self.room('/rooms/'+rid+'/signals',dict(kind='drowsy'),'POST',session=a)
        self.assertEqual(self.room('/rooms/'+rid+'/signals/'+status['id']+'/vote',dict(choice='agree'),'POST','bob',b)[0],409)
        _,_,signal=self.room('/rooms/'+rid+'/signals',dict(kind='rest',destination=dict(name='Chosen rest place',latitude=37.4,longitude=127.0)),'POST',session=a)
        path='/rooms/'+rid+'/signals/'+signal['id']+'/vote'
        self.assertEqual(self.room(path,dict(choice='agree'),'POST','eve',e)[0],404)
        self.assertEqual(self.room(path,dict(choice='agree',accountId=a['user']['id']),'POST','bob',b)[0],400)
        self.assertEqual(self.room(path,dict(choice='agree'),'POST','bob',b)[0],200)
        item=self.detail(rid,b,'bob')[2]['signals'][0]
        self.assertEqual(item['votes'],dict(agree=1,**{'pass':0}));self.assertEqual(item['myVote'],'agree')
        self.assertEqual(self.room(path,dict(choice='pass'),'POST','bob',b)[0],200)
        self.assertEqual(self.detail(rid,a)[2]['signals'][0]['votes'],dict(agree=0,**{'pass':1}))
        self.share(rid,a,status=True)
        self.assertEqual(self.room(path,dict(choice='agree'),'POST','bob',b)[0],409)
        self.share(rid,b,'bob')
        self.assertEqual(self.detail(rid,a)[2]['signals'][0]['votes'],dict(agree=0,**{'pass':0}))
        self.assertEqual(self.room(path,method='DELETE',who='bob',session=b)[0],200)
        with psycopg.connect(self.dsn) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_room_votes').fetchone()[0],0)

    def test_22_block_revokes_room_access_without_deleting_records(self):
        a,b,e=self.sessions();room=self.new_room(a);rid=room['id'];self.join(b,room['code'],status=True);self.join(e,room['code'],'eve',status=True)
        self.share(rid,a,status=True,location=True)
        self.room('/rooms/'+rid+'/signals',dict(kind='rest',destination=dict(name='Private place',latitude=37.5,longitude=127.0)),'POST',session=a)
        self.assertEqual(self.room('/blocks',dict(targetId=b['user']['id']),'POST',session=a)[0],201)
        self.assertEqual(self.detail(rid,b,'bob')[0],404);self.assertEqual(self.detail(rid,a)[0],200)
        self.assertEqual(self.join(b,room['code'])[0],404)
        self.room('/blocks/'+b['user']['id'],method='DELETE',session=a)
        self.assertEqual(self.join(b,room['code'])[0],200)
        # Non-owner blocker exits a third-party room; cannot evict its owner.
        self.assertEqual(self.room('/blocks',dict(targetId=e['user']['id']),'POST','bob',b)[0],201)
        self.assertEqual(self.detail(rid,b,'bob')[0],404);self.assertEqual(self.detail(rid,e,'eve')[0],200)
        with psycopg.connect(self.dsn) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_rooms').fetchone()[0],1)

    def test_23_expiry_emits_real_wss_invalidation_and_retains_ciphertext(self):
        a,b,_=self.sessions();room=self.new_room(a);rid=room['id'];self.join(b,room['code'])
        with self.websocket(b,who='bob') as connection:
            self.assertEqual(json.loads(connection.recv(timeout=2))['type'],'snapshot')
            with psycopg.connect(self.dsn) as conn:conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 second' WHERE room_id=%s",(rid,))
            event=json.loads(connection.recv(timeout=3));self.assertEqual(event['type'],'invalidate');self.assertIn('rooms',event['resources'])
        self.assertEqual(self.detail(rid,b,'bob')[0],404)
        self.assertEqual(self.room('/invites/'+room['code'],session=a)[0],404)
        self.assertEqual(self.join(b,room['code'])[0],404)
        self.assertEqual(self.room('/overview',session=a)[2]['rooms'],[])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_room_members').fetchone()[0],2)
            self.assertIsNotNone(conn.execute('SELECT expiry_notified_at FROM team_rooms').fetchone()[0])

    def test_24_parallel_join_vs_block_on_independent_http_workers(self):
        a,b,_=self.sessions();room=self.new_room(a);rid=room['id']
        port=auth_fixture.free_port();server=uvicorn.Server(uvicorn.Config(self.module.app,host='127.0.0.1',port=port,proxy_headers=False,access_log=False,log_level='warning',ws='websockets-sansio'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        helper=type(self)(methodName='test_24_parallel_join_vs_block_on_independent_http_workers');helper.port=port
        try:
            limit=time.monotonic()+5
            while not server.started and time.monotonic()<limit:time.sleep(.01)
            self.assertTrue(server.started)
            with ThreadPoolExecutor(max_workers=2) as pool:
                calls=[pool.submit(self.join,b,room['code']),pool.submit(helper.room,'/blocks',dict(targetId=b['user']['id']),'POST',session=a)]
                values=[f.result(timeout=5) for f in calls]
            self.assertIn(values[0][0],(200,404));self.assertEqual(values[1][0],201)
            self.assertEqual(self.detail(rid,b,'bob')[0],404);self.assertEqual(self.detail(rid,a)[0],200)
            self.assertEqual(self.join(b,room['code'])[0],404)
        finally:server.should_exit=True;thread.join(5)

    def test_25_published_course_room_omits_removed_web_invite(self):
        a,b,_=self.sessions();pack=self.pack();self.publish(pack,a)
        value=dict(name='With course',courseId=pack['id'],courseVersion=1,expiresInHours=6)
        status,_,room=self.room('/rooms',value,'POST',session=a);self.assertEqual(status,201,room);rid=room['id']
        detail=self.detail(rid,a)[2]
        self.assertEqual(detail['course'],dict(id=pack['id'],version=1,title=pack['title']))
        self.assertNotIn('inviteUri',detail)
        self.assertEqual(self.room('/rooms/'+rid+'/invite-qr.svg',session=a)[0],404)
        _,_,credential=self.pair(a)
        status,_,native=self.native('/v1/social/rooms/'+rid,token=credential['accessToken']);self.assertEqual(status,200,native)
        self.assertTrue({'code','inviteUri','consents','availableConsentKeys'}.isdisjoint(native))

    @classmethod
    def prepare_browser_fixture(cls,helper):
        session=helper.login();pack=helper.pack();pack['title']='우리의 주말 코스'
        helper.publish(pack,session);helper.approve(pack,session)

    @classmethod
    def fixture_tick(cls,helper,config):
        control=config.with_suffix('.control.json')
        if not control.exists():return
        import os,stat,datetime
        info=control.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise RuntimeError('Unsafe isolated fixture control')
        value=json.loads(control.read_bytes());assert set(value)=={'action','roomId'} and value['action']=='expire-room' and re.fullmatch('[a-f0-9]{32}',value['roomId'])
        assert cls.state.name.startswith('wegoh-team-contract-') and cls.state.parent==Path('/tmp')
        with psycopg.connect(cls.dsn) as conn:
            row=conn.execute("UPDATE team_rooms SET expires_at=now()-interval '1 second' WHERE room_id=%s RETURNING room_id",(value['roomId'],)).fetchone()
        result=dict(action=value['action'],roomId=value['roomId'],updated=bool(row),performedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
        config.with_suffix('.control-result.json').write_text(json.dumps(result));config.with_suffix('.control-result.json').chmod(0o600)
        control.unlink()

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--serve-fixture':friend_fixture.serve_fixture(sys.argv[2],fixture_class=RoomTests)
    else:unittest.main(verbosity=2)
