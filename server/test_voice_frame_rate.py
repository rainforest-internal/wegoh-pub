import unittest
from fastapi import HTTPException
from team_voice import Peer, TeamVoice


class VoiceFrameRateTests(unittest.TestCase):
    def peer(self):
        value = Peer(None, 'synthetic', 'synthetic', {})
        value.rate_updated = 0
        return value

    def stream(self, *, hold=0, repeated=False, processing=.001, count=750):
        peer = self.peer()
        processed = -1
        for sequence in range(count):
            captured = sequence * .02
            if repeated:
                block = sequence // 20 * .4
                arrived = max(captured, block + hold)
            else:
                arrived = max(captured, 2 + hold) if 2 <= captured <= 2 + hold else captured
            processed = max(arrived, processed + processing)
            TeamVoice.frame_rate(peer, processed)
        return peer

    def test_full_fifteen_second_floor_accepts_fifty_frames_per_second(self):
        self.stream()

    def test_fifty_fps_survives_short_delivery_coalescing(self):
        for hold in (.1, .12, .16):
            with self.subTest(hold_ms=round(hold*1000)):
                self.stream(hold=hold)

    def test_repeated_coalescing_still_accepts_normal_fifty_fps(self):
        for hold in (.1, .12, .16):
            with self.subTest(hold_ms=round(hold*1000)):
                self.stream(hold=hold, repeated=True)

    def test_coalescing_and_authorization_processing_can_overlap(self):
        self.stream(hold=.16, repeated=True, processing=.005)

    def test_half_second_audio_batch_does_not_disconnect_normal_speech(self):
        for hold in (.2, .3, .48):
            with self.subTest(hold_ms=round(hold * 1000)):
                self.stream(hold=hold)

    def test_repeated_half_second_batches_preserve_normal_average(self):
        peer = self.peer()
        for sequence in range(750):
            captured = sequence * .02
            arrived = max(captured, sequence // 50 + .48)
            TeamVoice.frame_rate(peer, arrived)

    def test_releasing_and_restarting_floor_does_not_refill_budget(self):
        peer = self.peer()
        for _ in range(25):
            TeamVoice.frame_rate(peer, 0)
        peer.lease = None
        peer.sequence = -1
        peer.lease = 'next-synthetic-lease'
        with self.assertRaises(HTTPException) as exceeded:
            TeamVoice.frame_rate(peer, 0)
        self.assertEqual(exceeded.exception.status_code, 429)

    def test_instantaneous_flood_exhausts_bounded_audio_budget(self):
        peer = self.peer()
        for _ in range(25):
            TeamVoice.frame_rate(peer, 0)
        with self.assertRaises(HTTPException) as exceeded:
            TeamVoice.frame_rate(peer, 0)
        self.assertEqual(exceeded.exception.status_code, 429)

    def test_sustained_excess_over_fifty_five_fps_is_rejected(self):
        for fps in (60, 100):
            with self.subTest(fps=fps):
                peer = self.peer()
                rejected_at = None
                for sequence in range(fps * 6):
                    try:
                        TeamVoice.frame_rate(peer, sequence / fps)
                    except HTTPException as error:
                        self.assertEqual(error.status_code, 429)
                        rejected_at = sequence / fps
                        break
                self.assertIsNotNone(rejected_at)
                self.assertLess(rejected_at, 6)

    def test_rolling_window_cannot_accumulate_unbounded_frames(self):
        peer = self.peer()
        accepted = 0
        with self.assertRaises(HTTPException) as exceeded:
            for sequence in range(100):
                TeamVoice.frame_rate(peer, sequence / 100)
                accepted += 1
        self.assertEqual(exceeded.exception.status_code, 429)
        self.assertLessEqual(accepted, 80)
