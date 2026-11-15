import json
import os
import socket
import unittest

import psycopg
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect
from team_rooms import CONSENTS
from team_trip_context import resolve_trip_context


class TripMediaAuthorityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_team_trips import TripTests
        previous = os.environ.get('WEGOH_VOICE_ENABLED')
        def restore_voice():
            if previous is None:
                os.environ.pop('WEGOH_VOICE_ENABLED', None)
            else:
                os.environ['WEGOH_VOICE_ENABLED'] = previous
        cls.addClassCleanup(restore_voice)
        os.environ['WEGOH_VOICE_ENABLED'] = '1'
        cls.fixture=TripTests;cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)

    def setUp(self):
        from test_native_functional_business import FunctionalBusinessTests
        self.h=self.fixture('test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.auth=self.h.module.TEAM_AUTH
        self.a,self.b,self.e=self.h.sessions();self.trip=self.h.new_trip(self.a)
        self.h.join(self.trip,self.a,self.b)
        factory=FunctionalBusinessTests('test_native_friend_request_respond_scope_withdrawal_and_original_authority')
        factory.h=self.h;factory.certificates={}
        self.factory=factory
        self.c=factory.connect(self.b,'bob')
        factory.approve(self.b,self.c,['rooms:read','room-music:read','room-music:control','room-voice:receive','room-voice:transmit'],'bob')
        with psycopg.connect(self.h.dsn) as conn:
            context=resolve_trip_context(self.auth,conn,self.trip,self.a['user']['id'])
            self.room=context['roomId']
            self.auth.trip_service.set_role(conn,self.trip,self.a['user']['id'],self.b['user']['id'],'dj',context['revision'])
            self.auth.trip_service.set_sharing(conn,self.trip,self.b['user']['id'],{key:key in ('music','voice') for key in CONSENTS})
        self.h.close_trip(self.trip,self.a,action='start')

    def path(self,kind,legacy=False):
        return '/v1/devices/'+self.c['deviceId']+('/rooms/'+self.room if legacy else '/trips/'+self.trip)+'/'+kind+'-permissions'

    def get(self,kind,session=None):
        result=self.h.call(self.path(kind),session=session or self.b,who=(session or self.b)['user']['displayName'])
        self.assertEqual(result[0],200,result[2]);self.assertNotIn('roomId',result[2])
        self.assertEqual(result[2]['tripId'],self.trip);self.assertEqual(result[2]['contractVersion'],1)
        return result[2]

    def put(self,kind,value,**flags):
        body={key:item for key,item in value.items() if key not in ('deviceId','expiresAt')}
        body['permissions']=flags
        return self.h.call(self.path(kind),body,'PUT',session=self.b,who='bob')

    def test_native_trip_detail_with_music_purpose_before_and_after_music_consent(self):
        planned = self.h.new_trip(self.a)
        self.h.join(planned,self.a,self.b)
        for trip,state in ((planned,'planned'),(self.trip,'active')):
            status,_,detail = self.factory.native(self.c,'/v1/native/trips/'+trip)
            self.assertEqual(status,200,detail)
            self.assertEqual((detail['id'],detail['state']),(trip,state))
            self.assertIsNone(detail['display']['music'])
        value = self.get('music')
        response = self.put('music',value,receiveMusic=True,shareMusic=False)
        self.assertEqual(response[0],200,response[2])
        status,_,detail = self.factory.native(self.c,'/v1/native/trips/'+self.trip)
        self.assertEqual(status,200,detail)
        self.assertEqual(detail['display']['music']['trackCount'],0)

    def test_expiry_preserved_revoke_after_finish_and_foreign_access_denied(self):
        for kind,flags in (('music',dict(receiveMusic=True,shareMusic=True)),('voice',dict(receiveVoice=True,transmitVoice=True))):
            value=self.get(kind);self.assertEqual(all(value['permissions'].values()),kind=='voice')
            self.assertEqual(any(value['permissions'].values()),kind=='voice')
            self.assertEqual(self.h.call(self.path(kind),session=self.e,who='eve')[0],404)
            self.assertEqual(self.h.call(self.path(kind,legacy=True),session=self.b,who='bob')[0],409)
            first=self.put(kind,value,**flags);self.assertEqual(first[0],200,first[2])
            with psycopg.connect(self.h.dsn) as conn:
                conn.execute('UPDATE native_room_'+kind+'_authorizations SET expires_at=expires_at-60 WHERE grant_id=%s AND room_id=%s',(self.c['grantId'],self.room))
            current=self.get(kind)
            again=self.put(kind,current,**flags);self.assertEqual(again[0],200,again[2])
            self.assertEqual(again[2]['expiresAt'],current['expiresAt'])
        self.h.close_trip(self.trip,self.a,action='finish')
        for kind in ('music','voice'):
            value=self.get(kind);self.assertFalse(any(value['permissions'].values()))
            response=self.h.call(self.path(kind),method='DELETE',session=self.b,who='bob')
            self.assertEqual(response[0],200,response[2]);self.assertFalse(any(response[2]['permissions'].values()))
            flags={key:False for key in value['permissions']}
            value=self.get(kind);self.assertEqual(self.put(kind,value,**flags)[0],200)
            value=self.get(kind);flags={key:True for key in flags}
            self.assertEqual(self.put(kind,value,**flags)[0],409)

    def test_leave_rejoin_rejects_stale_join_and_only_voice_restarts_on(self):
        initial={}
        for kind,flags in (('music',dict(receiveMusic=True,shareMusic=True)),('voice',dict(receiveVoice=True,transmitVoice=True))):
            value=self.get(kind);result=self.put(kind,value,**flags)
            self.assertEqual(result[0],200,result[2]);initial[kind]=result[2]
        with psycopg.connect(self.h.dsn) as conn:
            self.auth.trip_service.remove_member(conn,self.trip,self.b['user']['id'])
        for kind in ('music','voice'):
            self.assertFalse(any(self.get(kind)['permissions'].values()))
            self.assertEqual(self.h.call(self.path(kind),method='DELETE',session=self.b,who='bob')[0],200)
        self.h.join(self.trip,self.a,self.b)
        for kind in ('music','voice'):
            value=self.get(kind);self.assertEqual(all(value['permissions'].values()),kind=='voice')
            self.assertEqual(any(value['permissions'].values()),kind=='voice')
            self.assertNotEqual(value['memberJoinedAt'],initial[kind]['memberJoinedAt'])
            self.assertEqual(self.put(kind,initial[kind],**initial[kind]['permissions'])[0],409)


    def own(self,credential):
        result=self.factory.native(credential,'/v1/native/trips/'+self.trip+'/voice-permissions')
        self.assertEqual(result[0],200,result[2]);self.assertNotIn('roomId',result[2])
        return result[2]

    def stream(self,credential,snapshot):
        raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=3)
        headers={'Authorization':'Bearer '+credential['accessToken'],'cf-cert-sha256':self.factory.certificates[credential['grantId']],
            'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false',
            'X-WegoH-Functional-Revision':str(snapshot['functionalRevision']),'X-WegoH-Room-Voice-Revision':str(snapshot['revision'])}
        try:
            return connect('ws://api.wegoh.invalid/v1/social/trips/'+self.trip+'/voice',sock=raw,additional_headers=headers,origin=None,open_timeout=3,close_timeout=1)
        except BaseException:
            raw.close();raise

    def ready(self,stream):
        for _ in range(12):
            value=stream.recv(timeout=2)
            if isinstance(value,str) and json.loads(value)['type']=='ready':return
        self.fail('Expected ready')

    def test_trip_socket_follows_account_participation_and_ignores_legacy_device_choices(self):
        on=dict(receiveVoice=True,transmitVoice=True);off=dict(receiveVoice=False,transmitVoice=False)
        car=self.factory.connect(self.a)
        value=self.own(car)
        self.assertEqual((value['permissions'],value['tripId']),(on,self.trip))
        self.assertGreaterEqual(value['revision'],1)
        with self.stream(car,value) as live:
            self.ready(live)
            path='/v1/devices/'+car['deviceId']+'/trips/'+self.trip+'/voice-permissions'
            stopped=self.h.call(path,method='DELETE',session=self.a,who='alice')
            self.assertEqual(stopped[0],200,stopped[2]);self.assertEqual(stopped[2]['permissions'],off)
            self.assertEqual(self.own(car),value)
            live.send(json.dumps({'type':'ping'}))
            self.assertEqual(json.loads(live.recv(timeout=2))['type'],'pong')
            with psycopg.connect(self.h.dsn) as conn:
                self.auth.trip_service.set_sharing(conn,self.trip,self.a['user']['id'],{key:False for key in CONSENTS})
            with self.assertRaises(ConnectionClosed):
                while True:live.recv(timeout=2)
        disabled=self.own(car)
        self.assertEqual(disabled['permissions'],off);self.assertGreater(disabled['revision'],value['revision'])
        with self.assertRaises(InvalidStatus) as denied:self.stream(car,value)
        self.assertEqual(denied.exception.response.status_code,403)

        self.factory.approve(self.b,self.c,['rooms:read'],'bob')
        other=self.own(self.c);self.assertEqual(other['permissions'],on)
        with self.stream(self.c,other) as live:
            self.ready(live)


if __name__=='__main__':unittest.main()
