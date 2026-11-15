import asyncio
import json
import os
import socket
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
from fastapi import HTTPException
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from team_voice import TeamVoice, Peer
from team_rooms import CONSENTS
from team_trip_context import resolve_trip_context
from voice_authorization import voice_context


class TripVoicePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.voice=TeamVoice(SimpleNamespace(dsn='',enabled=True),MagicMock())

    def peer(self,actor,room='room',native=False):
        identity=dict(id=actor,role='creator',voiceTransport='native' if native else 'browser',voiceStamp=('joined',),deviceId=actor)
        peer=Peer(SimpleNamespace(close=AsyncMock(),send_bytes=AsyncMock()),actor,room,identity)
        peer.loop=asyncio.get_running_loop();self.voice.peers.add(peer)
        return peer

    async def test_block_barrier_only_stops_both_parties_and_purges_their_audio(self):
        a,b,other,outside=self.peer('a'),self.peer('b',native=True),self.peer('other'),self.peer('a','elsewhere')
        for peer in (a,b,other,outside):
            peer.queue.put_nowait(('lease','a',b'old audio'))
        self.voice.on_trip_block(None,'trip','room','a','b')
        self.assertTrue(a.invalidated);self.assertTrue(b.invalidated)
        self.assertTrue(a.queue.empty());self.assertTrue(b.queue.empty())
        self.assertFalse(other.invalidated);self.assertFalse(outside.invalidated)
        self.assertFalse(other.queue.empty());self.assertFalse(outside.queue.empty())
        await asyncio.sleep(0)
        self.assertTrue(a.closed);self.assertTrue(b.closed)
        self.assertFalse(other.closed);self.assertFalse(outside.closed)

    async def test_withdraw_after_membership_or_trip_closes_needs_no_database(self):
        a,b=self.peer('a'),self.peer('b')
        self.voice.withdraw_trip_context(None,'trip','room',account='a')
        self.assertTrue(a.invalidated);self.assertFalse(b.invalidated)
        self.voice.withdraw_trip_context(None,'trip','room')
        self.assertTrue(b.invalidated)
        await asyncio.sleep(0)

    async def test_rejoin_or_consent_generation_never_matches_old_peer(self):
        peer=self.peer('a')
        self.assertTrue(self.voice.current_peer(peer,peer.identity))
        fresh=dict(peer.identity,voiceStamp=('new-joined',))
        self.assertFalse(self.voice.current_peer(peer,fresh))
        peer.invalidated=True
        self.assertFalse(self.voice.current_peer(peer,peer.identity))

    async def test_trip_voice_resolves_active_trip_and_legacy_never_uses_trip_flag(self):
        auth=self.voice.auth;conn=MagicMock()
        with patch('voice_authorization.resolve_trip_context',return_value=dict(roomId='room')) as resolve:
            result=voice_context(self.voice,conn,SimpleNamespace(state=SimpleNamespace(voice_trip='trip')),'ignored','a')
            self.assertEqual(result,('room','trip'))
            resolve.assert_called_once_with(auth,conn,'trip','a',states=('active',))
        conn.execute.return_value.fetchone.return_value=None
        self.assertEqual(voice_context(self.voice,conn,SimpleNamespace(state=SimpleNamespace()),'legacy','a'),('legacy',None))
        self.voice.rooms.access.assert_not_called()
        conn.execute.return_value.fetchone.return_value=('trip',)
        voice_context(self.voice,conn,SimpleNamespace(state=SimpleNamespace()),'linked','a')
        self.voice.rooms.access.assert_called_once_with(conn,'linked','a')

    async def test_invalidated_source_never_delivers_even_with_old_floor_and_epochs(self):
        source,target=self.peer('source'),self.peer('target')
        source.lease='lease';source.until=1e20;self.voice.active_floors['room']=source
        self.voice.on_trip_block(None,'trip','room','source','absent')
        await self.voice.deliver(target,source,'lease','source',b'old audio',source.epoch,target.epoch)
        target.socket.send_bytes.assert_not_awaited()
        await asyncio.sleep(0)


class TripVoiceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_team_trips import TripTests
        cls.previous=os.environ.get('WEGOH_VOICE_ENABLED')
        os.environ['WEGOH_VOICE_ENABLED']='1'
        cls.fixture=TripTests;cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.tearDownClass)
        cls.addClassCleanup(cls.restore_environment)

    @classmethod
    def restore_environment(cls):
        if cls.previous is None:os.environ.pop('WEGOH_VOICE_ENABLED',None)
        else:os.environ['WEGOH_VOICE_ENABLED']=cls.previous

    def setUp(self):
        self.h=self.fixture('test_v6_creation_privacy_permissions_and_invitation_lifecycle')
        self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.auth=self.h.module.TEAM_AUTH
        self.a,self.b,self.e=self.h.sessions();self.trip=self.h.new_trip(self.a)
        self.h.join(self.trip,self.a,self.b);self.h.join(self.trip,self.a,self.e)
        with psycopg.connect(self.h.dsn) as conn:
            self.room=resolve_trip_context(self.auth,conn,self.trip,self.a['user']['id'])['roomId']
            for session in (self.a,self.b,self.e):
                self.auth.trip_service.set_sharing(conn,self.trip,session['user']['id'],{key:key=='voice' for key in CONSENTS})

    def ws(self,session,path=None):
        raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=3)
        try:
            return connect('ws://web.wegoh.invalid'+(path or '/v1/social/trips/'+self.trip+'/voice'),sock=raw,
                additional_headers={'Cf-Access-Jwt-Assertion':self.h.assertion(session['user']['displayName']),'Cookie':session['cookie']},origin='https://web.wegoh.invalid',open_timeout=3,close_timeout=1)
        except BaseException:
            raw.close();raise

    def control(self,stream,kind):
        for _ in range(12):
            value=stream.recv(timeout=2)
            if isinstance(value,str) and json.loads(value)['type']==kind:return json.loads(value)
        self.fail('Expected '+kind)

    def start_trip(self):
        return self.h.close_trip(self.trip,self.a,action='start')

    def test_planned_and_legacy_denial_active_audio_and_end_closure(self):
        with self.assertRaises(InvalidStatus):self.ws(self.a)
        self.start_trip()
        with self.assertRaises(InvalidStatus):self.ws(self.a,'/v1/social/rooms/'+self.room+'/voice')
        with self.ws(self.a) as a,self.ws(self.b) as b:
            self.control(a,'ready');self.control(b,'ready')
            a.send(json.dumps(dict(type='floor-request')));self.control(a,'floor-granted');self.control(b,'floor-started')
            frame=struct.pack('<I',0)+b'\x00'*640;a.send(frame);self.assertEqual(b.recv(timeout=2),frame)
            self.h.close_trip(self.trip,self.a,action='finish')
            for stream in (a,b):
                with self.assertRaises(ConnectionClosed):
                    while True:stream.recv(timeout=2)
        with self.assertRaises(InvalidStatus):self.ws(self.a)

    def test_member_block_closes_only_two_parties_and_owner_can_continue(self):
        self.start_trip()
        with self.ws(self.a) as a,self.ws(self.b) as b,self.ws(self.e) as e:
            for stream in (a,b,e):self.control(stream,'ready')
            self.assertEqual(self.h.social('/blocks',self.b,dict(targetId=self.e['user']['id']),'POST')[0],201)
            for stream in (b,e):
                with self.assertRaises(ConnectionClosed):
                    while True:stream.recv(timeout=2)
            a.send(json.dumps(dict(type='ping')));self.control(a,'pong')
            a.send(json.dumps(dict(type='floor-request')));self.control(a,'floor-granted')
        with self.assertRaises(InvalidStatus):self.ws(self.b)
        with self.assertRaises(InvalidStatus):self.ws(self.e)

    def test_voice_consent_off_then_on_closes_existing_connection(self):
        self.start_trip()
        with self.ws(self.b) as b:
            self.control(b,'ready')
            with psycopg.connect(self.h.dsn) as conn:
                current=resolve_trip_context(self.auth,conn,self.trip,self.a['user']['id'])
                self.auth.trip_service.set_role(conn,self.trip,self.a['user']['id'],self.b['user']['id'],'dj',current['revision'])
            b.send(json.dumps({'type':'ping'}))
            self.control(b,'pong')
            with psycopg.connect(self.h.dsn) as conn:
                self.auth.trip_service.set_sharing(conn,self.trip,self.b['user']['id'],{key:False for key in CONSENTS})
                self.auth.trip_service.set_sharing(conn,self.trip,self.b['user']['id'],{key:key=='voice' for key in CONSENTS})
            with self.assertRaises(ConnectionClosed):
                while True:b.recv(timeout=2)
        with self.ws(self.b) as b:self.control(b,'ready')


if __name__=='__main__':unittest.main()
