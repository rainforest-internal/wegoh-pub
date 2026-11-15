import asyncio
import struct
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import psycopg
from fastapi import HTTPException

from private_records import PrivateRecordError
from team_voice import Peer, TeamVoice, VoicePhase, VoiceReason, VoiceRejection, FRAME_RATE_WINDOW_LIMIT


class VoiceDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = TeamVoice(SimpleNamespace(dsn='', enabled=True, rate=Mock()), Mock())
        self.socket = SimpleNamespace(close=AsyncMock())
        self.peer = Peer(self.socket, 'private-account', 'private-room', {'token': 'private-token'})

    def assert_safe(self, records):
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIsNone(record.exc_info)
        output = record.getMessage()
        for secret in ('private-account', 'private-room', 'private-token', 'private-exception', 'private-audio'):
            self.assertNotIn(secret, output)
        return output

    async def terminated(self, error, phase=VoicePhase.FRAME):
        with self.assertLogs('wegoh.voice', level='WARNING') as logs:
            await self.service.terminate(self.peer, phase=phase, error=error)
            await self.service.terminate(self.peer, phase=phase, error=error)
        self.socket.close.assert_awaited_once_with(code=1008)
        return self.assert_safe(logs.records)

    async def test_rate_rejection_distinguishes_burst_and_window_without_policy_change(self):
        for reason in (VoiceReason.RATE_BURST, VoiceReason.RATE_WINDOW):
            with self.subTest(reason=reason):
                self.setUp()
                self.peer.rate_updated = 0
                if reason == VoiceReason.RATE_BURST:
                    self.peer.rate_credit = 0
                else:
                    self.peer.frames = deque([0] * FRAME_RATE_WINDOW_LIMIT)
                with self.assertRaises(VoiceRejection) as raised:
                    self.service.frame_rate(self.peer, 0)
                self.assertEqual(raised.exception.status_code, 429)
                output = await self.terminated(raised.exception)
                self.assertIn('reason=' + reason.value, output)
                self.assertIn('phase=frame', output)
                self.assertIn('status=429', output)
                self.assertIn('window=' + (str(FRAME_RATE_WINDOW_LIMIT) if reason == VoiceReason.RATE_WINDOW else '0'), output)

    async def test_sequence_rejection_logs_only_numeric_sequence_before_floor_cleanup(self):
        self.peer.floor = SimpleNamespace(close=Mock())
        self.peer.lease = 'private-token'
        self.peer.until = time.monotonic() + 15
        self.peer.sequence = 3
        with self.assertRaises(VoiceRejection) as raised:
            await self.service.relay(self.peer, struct.pack('<I', 8) + bytes(640))
        output = await self.terminated(raised.exception)
        self.assertIn('reason=sequence_mismatch status=400', output)
        self.assertIn('last_seq=3 received_seq=8', output)
        self.assertEqual(self.peer.sequence, -1)

    async def test_exception_details_and_tracebacks_are_never_logged(self):
        cases = ((HTTPException(403, 'private-exception private-token'), 'authorization_denied', 403),
                 (PrivateRecordError('private-exception'), 'integrity_failure', 503),
                 (TimeoutError('private-exception'), 'send_timeout', 503),
                 (OSError('private-exception'), 'transport_failure', 503))
        for error, reason, status in cases:
            with self.subTest(reason=reason):
                self.setUp()
                output = await self.terminated(error, VoicePhase.AUTH)
                self.assertIn(f'reason={reason} status={status}', output)

    async def test_database_failure_logs_validated_sqlstate_only(self):
        class UnsafeState(psycopg.Error):
            sqlstate = 'private-exception\n40P01'
        for error, expected in ((psycopg.errors.DeadlockDetected('private-exception'), '40P01'),
                                (UnsafeState('private-exception'), 'None')):
            with self.subTest(sqlstate=expected):
                self.setUp()
                output = await self.terminated(error, VoicePhase.AUTH)
                self.assertIn('reason=database_failure status=503', output)
                self.assertIn('sqlstate=' + expected, output)

    async def test_context_invalidation_logs_once_even_if_authorization_also_fails(self):
        self.peer.loop = asyncio.get_running_loop()
        self.service.peers.add(self.peer)
        with self.assertLogs('wegoh.voice', level='WARNING') as logs:
            self.service.invalidate_context('private-room')
            await asyncio.sleep(0)
            await self.service.terminate(self.peer, error=HTTPException(403, 'private-token'))
            await asyncio.sleep(0)
        output = self.assert_safe(logs.records)
        self.assertIn('phase=invalidation reason=context_invalidated status=403', output)

    async def test_queue_overflow_keeps_original_close_code_and_logs_once(self):
        for _ in range(self.peer.queue.maxsize):
            self.peer.queue.put_nowait('private-audio')
        with self.assertLogs('wegoh.voice', level='WARNING') as logs:
            await self.service.put(self.peer, 'private-audio')
            await self.service.put(self.peer, 'private-audio')
        output = self.assert_safe(logs.records)
        self.assertIn('phase=sender reason=queue_full status=429 close_code=1013', output)
        self.socket.close.assert_awaited_once_with(code=1013)

    async def test_normal_stop_does_not_emit_rejection(self):
        with self.assertNoLogs('wegoh.voice', level='WARNING'):
            await self.service.control(self.peer, {'type': 'stop'})
        self.socket.close.assert_awaited_once_with(code=1000)

    async def test_sender_task_http_failure_reaches_route_diagnostics(self):
        self.service.enabled = True
        self.service.authorize = Mock(return_value={
            'id': 'private-account', 'voiceTransport': 'iphone', 'voiceStamp': 'private-token',
            'voiceMuted': set(), 'voiceCanTransmit': True, 'voiceSuspended': False})
        self.service.sender = AsyncMock(side_effect=HTTPException(403, 'private-exception'))
        socket = SimpleNamespace(accept=AsyncMock(), close=AsyncMock(), state=SimpleNamespace())
        async def receive():
            await asyncio.sleep(.01)
            return {'type': 'websocket.receive', 'text': '{"type":"ping"}'}
        socket.receive = receive
        route = next(route for route in self.service.router(trip_context=True).routes
                     if getattr(route, 'path', None) == '/v1/iphone/trips/{trip}/voice')
        with patch('voice_authorization.close_voice_database'), self.assertLogs('wegoh.voice', level='WARNING') as logs:
            await route.endpoint(socket, 'private-room')
        output = self.assert_safe(logs.records)
        self.assertIn('phase=sender reason=authorization_denied status=403', output)
        self.assertFalse(self.service.peers)
