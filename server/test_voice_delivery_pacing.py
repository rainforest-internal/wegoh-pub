import asyncio
import struct
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from team_voice import Peer, TeamVoice


class VoiceDeliveryPacingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = TeamVoice(SimpleNamespace(dsn='', enabled=True), None)
        self.source = Peer(None, 'speaker', 'room', {})
        self.source.lease = 'lease'
        self.source.until = time.monotonic() + 15
        self.service.active_floors['room'] = self.source
        self.sent = []

        async def send(raw):
            self.sent.append((time.monotonic(), raw))

        self.target = Peer(SimpleNamespace(send_bytes=send), 'listener', 'room', {})

    async def deliver(self, sequence):
        raw = struct.pack('<I', sequence) + bytes(640)
        await self.service.deliver(self.target, self.source, 'lease', 'speaker', raw,
                                   self.source.epoch, self.target.epoch)

    async def test_coalesced_batch_is_paced_for_existing_eight_frame_players(self):
        for sequence in range(25):
            await self.deliver(sequence)
        self.assertEqual([struct.unpack_from('<I', raw)[0] for _, raw in self.sent], list(range(25)))
        self.assertTrue(all(right[0] - left[0] >= .017 for left, right in zip(self.sent, self.sent[1:])))

    async def test_slow_authorization_consumes_interval_instead_of_adding_to_it(self):
        await self.deliver(0)
        self.target.next_delivery = time.monotonic() - 1
        started = time.monotonic()
        await self.deliver(1)
        self.assertLess(self.sent[-1][0] - started, .01)

    async def test_scheduler_stall_never_causes_catch_up_burst(self):
        await self.deliver(0)
        await asyncio.sleep(.08)
        await self.deliver(1)
        await self.deliver(2)
        self.assertGreaterEqual(self.sent[-1][0] - self.sent[-2][0], .017)

    async def test_revocation_during_pacing_discards_frame_before_transport(self):
        await self.deliver(0)
        task = asyncio.create_task(self.deliver(1))
        await asyncio.sleep(0)
        self.target.epoch += 1
        await task
        self.assertEqual(len(self.sent), 1)

    async def test_release_during_pacing_discards_frame_before_transport(self):
        await self.deliver(0)
        task = asyncio.create_task(self.deliver(1))
        await asyncio.sleep(0)
        self.source.lease = None
        self.source.epoch += 1
        await task
        self.assertEqual(len(self.sent), 1)

    async def test_full_sender_checks_authority_for_each_paced_frame(self):
        self.source.identity = dict(voiceTransport='iphone', voiceStamp='source')
        self.target.identity = dict(voiceTransport='iphone', voiceStamp='target')
        def authorize(socket, room):
            peer = self.source if socket is None else self.target
            return dict(peer.identity, id=peer.actor, voiceCanReceive=True,
                        voiceCanTransmit=True, voiceMuted=set(), voiceSuspended=False)
        self.service.authorize = Mock(side_effect=authorize)
        delivery = patch('voice_authorization.authorize_delivery_source',
                         side_effect=lambda service, target, source: authorize(source.socket, source.room))
        source_authorize = delivery.start()
        self.addCleanup(delivery.stop)
        for sequence in range(25):
            await self.service.put(self.target, ('lease', 'speaker', struct.pack('<I', sequence) + bytes(640)))
        writer = asyncio.create_task(self.service.sender(self.target))
        try:
            async with asyncio.timeout(2):
                while len(self.sent) < 25:
                    await asyncio.sleep(.005)
        finally:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        self.assertEqual(self.service.authorize.call_count, 25)
        self.assertEqual(source_authorize.call_count, 25)
        self.assertFalse(self.target.closed)
