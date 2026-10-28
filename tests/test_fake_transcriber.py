"""Tests for DeterministicFakeTranscriber."""

import unittest

from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.schemas import TranscriptEventType
from tests.fixtures.sample_events import (
    make_interim_segment,
    make_final_segment,
)
from w2_stt.schemas import TranscriptEvent


class TestDeterministicFakeTranscriber(unittest.TestCase):
    """Test suite for deterministic fake transcriber behavior."""

    def test_provider_name(self) -> None:
        """Verify provider metadata."""
        transcriber = DeterministicFakeTranscriber()
        self.assertEqual(transcriber.provider_name, "DeterministicFakeTranscriber")

    def test_deterministic_repeatability_across_instances(self) -> None:
        """Verify identical inputs across independent instances produce identical outputs."""
        transcriber_a = DeterministicFakeTranscriber()
        transcriber_b = DeterministicFakeTranscriber()

        mock_audio_chunks = [b"chunk_alpha_001", b"chunk_beta_002", b"chunk_gamma_003"]

        events_a = []
        for ch in mock_audio_chunks:
            events_a.extend(transcriber_a.process_audio_chunk(ch))

        events_b = []
        for ch in mock_audio_chunks:
            events_b.extend(transcriber_b.process_audio_chunk(ch))

        self.assertEqual(len(events_a), len(events_b))
        for ea, eb in zip(events_a, events_b):
            self.assertEqual(ea.event_type, eb.event_type)
            self.assertEqual(ea.segment.segment_id, eb.segment.segment_id)
            self.assertEqual(ea.segment.text, eb.segment.text)
            self.assertEqual(ea.segment.start_time, eb.segment.start_time)
            self.assertEqual(ea.segment.end_time, eb.segment.end_time)
            self.assertEqual(ea.segment.confidence, eb.segment.confidence)
            self.assertEqual(ea.segment.is_final, eb.segment.is_final)

    def test_reset_restores_identical_stream_reproduction(self) -> None:
        """Verify calling reset() produces identical outputs on a second run."""
        transcriber = DeterministicFakeTranscriber()
        test_chunk = b"consistent_audio_payload"

        run_1_events = transcriber.process_audio_chunk(test_chunk)
        run_1_events.extend(transcriber.process_audio_chunk(test_chunk))

        transcriber.reset()

        run_2_events = transcriber.process_audio_chunk(test_chunk)
        run_2_events.extend(transcriber.process_audio_chunk(test_chunk))

        self.assertEqual(len(run_1_events), len(run_2_events))
        for r1, r2 in zip(run_1_events, run_2_events):
            self.assertEqual(r1.event_type, r2.event_type)
            self.assertEqual(r1.segment.text, r2.segment.text)

    def test_interim_followed_by_final(self) -> None:
        """Verify the alternating cadence of interim then final segment."""
        transcriber = DeterministicFakeTranscriber()

        # Chunk 0 -> Interim
        chunk_0_events = transcriber.process_audio_chunk(b"chunk_0")
        self.assertEqual(len(chunk_0_events), 1)
        self.assertEqual(chunk_0_events[0].event_type, TranscriptEventType.INTERIM)
        self.assertFalse(chunk_0_events[0].segment.is_final)
        seg_id = chunk_0_events[0].segment.segment_id

        # Chunk 1 -> Final (same segment_id finalized)
        chunk_1_events = transcriber.process_audio_chunk(b"chunk_1")
        self.assertEqual(len(chunk_1_events), 1)
        self.assertEqual(chunk_1_events[0].event_type, TranscriptEventType.FINAL)
        self.assertTrue(chunk_1_events[0].segment.is_final)
        self.assertEqual(chunk_1_events[0].segment.segment_id, seg_id)

    def test_flush_finalizes_pending_interim(self) -> None:
        """Verify flush() emits a final event if an interim was left pending."""
        transcriber = DeterministicFakeTranscriber()
        # Process single chunk leaving interim pending
        evts = transcriber.process_audio_chunk(b"single_chunk")
        self.assertEqual(evts[0].event_type, TranscriptEventType.INTERIM)

        flushed = transcriber.flush()
        self.assertEqual(len(flushed), 1)
        self.assertEqual(flushed[0].event_type, TranscriptEventType.FINAL)
        self.assertTrue(flushed[0].segment.is_final)
        self.assertEqual(flushed[0].segment.segment_id, evts[0].segment.segment_id)

        # Subsequent flush should return empty
        self.assertEqual(transcriber.flush(), [])

    def test_simulated_error_injection(self) -> None:
        """Verify error is injected at the specified chunk index."""
        transcriber = DeterministicFakeTranscriber(error_on_chunk_index=1)

        normal_evts = transcriber.process_audio_chunk(b"chunk_0")
        self.assertEqual(normal_evts[0].event_type, TranscriptEventType.INTERIM)

        error_evts = transcriber.process_audio_chunk(b"chunk_1")
        self.assertEqual(len(error_evts), 1)
        self.assertEqual(error_evts[0].event_type, TranscriptEventType.ERROR)
        self.assertEqual(error_evts[0].error.code, "SIMULATED_TRANSCRIBER_ERROR")
        self.assertIsNone(error_evts[0].segment)

    def test_scripted_events_replay_mode(self) -> None:
        """Verify scripted mode yields pre-configured events exactly."""
        scripted_batch_1 = [
            TranscriptEvent(
                event_type=TranscriptEventType.INTERIM,
                segment=make_interim_segment(text="Scripted interim"),
            )
        ]
        scripted_batch_2 = [
            TranscriptEvent(
                event_type=TranscriptEventType.FINAL,
                segment=make_final_segment(text="Scripted final"),
            )
        ]

        transcriber = DeterministicFakeTranscriber(
            scripted_events=[scripted_batch_1, scripted_batch_2]
        )

        res1 = transcriber.process_audio_chunk(b"any")
        self.assertEqual(res1[0].segment.text, "Scripted interim")

        res2 = transcriber.process_audio_chunk(b"any")
        self.assertEqual(res2[0].segment.text, "Scripted final")


if __name__ == "__main__":
    unittest.main()
