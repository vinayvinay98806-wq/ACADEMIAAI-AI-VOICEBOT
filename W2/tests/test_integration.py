"""End-to-End Integration and Contract Tests for Week 2 Speech-to-Text Pipeline.

Covers the entire chain:
AudioChunk (W1 Schema)
  -> Audio Preprocessor (Resampling, Downmixing, Peak Normalization)
  -> STT Orchestrator (Reliability, Bounded Retries, Timeout Handling)
  -> Transcription Adapter (Fake/Simulated Provider)
  -> Transcript Events (Interim & Final Reconciliation)
  -> Ordered Transcript Accumulator (Chronological Ordering, Deduplication)
  -> Continuous Consolidated Transcript Output
"""

import math
import struct
import time
import unittest
from typing import Any, Dict, List, Optional

from academiaai.audio.schemas import AudioChunk, AudioFormat
from w2_stt.accumulator import OrderedTranscriptAccumulator
from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.exceptions import (
    STTPermanentError,
    STTTimeoutError,
    STTTransientError,
)
from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.orchestrator import OrchestratorConfig, STTOrchestrator
from w2_stt.preprocessing import AudioPreprocessingConfig, AudioPreprocessor
from w2_stt.reliability import RetryConfig
from w2_stt.schemas import (
    TranscriptEvent,
    TranscriptEventType,
    TranscriptSegment,
)


class FlakyTranscriptionAdapter(BaseTranscriptionAdapter):
    """Test fixture adapter simulating transient network failures before recovering."""

    def __init__(self, fail_first_n_times: int = 2) -> None:
        self.fail_count = fail_first_n_times
        self.call_count = 0
        self.chunks_received: List[bytes] = []

    @property
    def provider_name(self) -> str:
        return "FlakyTranscriptionAdapter"

    def process_audio_chunk(
        self,
        chunk: bytes,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TranscriptEvent]:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise ConnectionResetError(f"Simulated network reset on attempt {self.call_count}")

        self.chunks_received.append(chunk)
        return [
            TranscriptEvent(
                session_id=context.get("session_id", "test-flaky-session") if context else "test-flaky-session",
                event_type=TranscriptEventType.FINAL,
                timestamp=0.5,
                segment=TranscriptSegment(
                    segment_id=f"flaky-seg-{len(self.chunks_received)}",
                    start_time=0.0,
                    end_time=0.5,
                    text="Recovered from network drop",
                    confidence=0.99,
                    is_final=True,
                ),
            )
        ]

    def flush(self) -> List[TranscriptEvent]:
        return []

    def reset(self) -> None:
        self.call_count = 0
        self.chunks_received.clear()


class TestSTTEndToEndIntegration(unittest.TestCase):
    """Comprehensive integration test suite for the complete W2 workflow."""

    def _generate_audio_chunk(
        self,
        seq: int,
        sample_rate: int = 48000,
        channels: int = 2,
        duration_ms: float = 100.0,
        amplitude: float = 0.2,
    ) -> AudioChunk:
        """Create a synthetic AudioChunk with specified format and audio waveform."""
        fmt = AudioFormat(sample_rate=sample_rate, channels=channels, sample_width=2)
        total_samples = int(round((duration_ms / 1000.0) * sample_rate))
        raw_samples = []
        for i in range(total_samples):
            val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * 440.0 * (i / sample_rate)))
            clamped = max(-32768, min(32767, val))
            if channels == 1:
                raw_samples.append(clamped)
            else:
                raw_samples.extend([clamped, clamped])

        data = struct.pack(f"<{len(raw_samples)}h", *raw_samples)
        return AudioChunk(
            data=data,
            format=fmt,
            sequence_id=seq,
            timestamp_ms=seq * duration_ms,
        )

    # -------------------------------------------------------------------------
    # Full End-to-End Streaming Workflow Tests
    # -------------------------------------------------------------------------

    def test_complete_pipeline_flow(self) -> None:
        """Test full audio chunk -> preprocessing -> orchestration -> transcription -> accumulation."""
        pre_cfg = AudioPreprocessingConfig(
            target_sample_rate=16000,
            target_channels=1,
            normalize_audio=True,
            target_peak_level=0.95,
        )
        orch_cfg = OrchestratorConfig(
            session_id="integration-session-001",
            default_language="en-US",
            preprocessing_config=pre_cfg,
            retry_config=RetryConfig(max_retries=2, initial_backoff_seconds=0.01),
        )
        adapter = DeterministicFakeTranscriber()
        orchestrator = STTOrchestrator(
            adapter=adapter,
            config=orch_cfg,
            sleep_func=lambda d: None,
        )

        # Feed 4 synthetic 48kHz stereo chunks
        for seq in range(4):
            chunk = self._generate_audio_chunk(seq=seq, sample_rate=48000, channels=2)
            events = orchestrator.process_chunk(chunk)
            self.assertGreater(len(events), 0)

        # Flush trailing interim segments
        flushed = orchestrator.flush()
        self.assertGreaterEqual(len(flushed), 0)

        # Verify accumulated state
        self.assertEqual(orchestrator.chunk_counter, 4)
        self.assertFalse(orchestrator.accumulator.has_pending_interim)
        transcript = orchestrator.get_transcript()
        self.assertTrue(len(transcript) > 0)
        self.assertGreater(orchestrator.accumulator.final_count, 0)

    # -------------------------------------------------------------------------
    # Deduplication and Reconciliation Tests
    # -------------------------------------------------------------------------

    def test_event_deduplication_in_pipeline(self) -> None:
        """Verify that duplicate events injected into the accumulator are suppressed."""
        accumulator = OrderedTranscriptAccumulator(session_id="dedup-session")
        seg = TranscriptSegment(
            segment_id="seg-100",
            start_time=0.0,
            end_time=1.0,
            text="Unique lecture utterance.",
            confidence=0.97,
            is_final=True,
        )
        event = TranscriptEvent(
            event_id="evt-fixed-uuid-1",
            session_id="dedup-session",
            event_type=TranscriptEventType.FINAL,
            segment=seg,
        )

        # Ingest first time: processed
        res1 = accumulator.add_event(event)
        self.assertTrue(res1)
        self.assertEqual(accumulator.final_count, 1)

        # Ingest second time: suppressed
        res2 = accumulator.add_event(event)
        self.assertFalse(res2)
        self.assertEqual(accumulator.final_count, 1)
        self.assertEqual(accumulator.duplicate_events_count, 1)
        self.assertEqual(accumulator.get_full_transcript(), "Unique lecture utterance.")

    def test_out_of_order_events_sorted_chronologically(self) -> None:
        """Verify segments arriving out of order are assembled chronologically."""
        accumulator = OrderedTranscriptAccumulator()

        seg_part2 = TranscriptSegment(
            segment_id="seg-002",
            start_time=1.0,
            end_time=2.0,
            text="world",
            confidence=0.95,
            is_final=True,
        )
        seg_part1 = TranscriptSegment(
            segment_id="seg-001",
            start_time=0.0,
            end_time=1.0,
            text="Hello",
            confidence=0.95,
            is_final=True,
        )

        # Ingest part 2 first, then part 1
        accumulator.add_segment(seg_part2)
        accumulator.add_segment(seg_part1)

        # Verify sorted sequence
        segments = accumulator.get_segments()
        self.assertEqual([s.segment_id for s in segments], ["seg-001", "seg-002"])
        self.assertEqual(accumulator.get_full_transcript(), "Hello world")

    # -------------------------------------------------------------------------
    # Reliability and Flaky Provider Recovery Tests
    # -------------------------------------------------------------------------

    def test_flaky_provider_automatic_recovery(self) -> None:
        """Verify orchestrator survives 2 transient network failures and recovers on 3rd attempt."""
        flaky_adapter = FlakyTranscriptionAdapter(fail_first_n_times=2)
        retry_cfg = RetryConfig(
            max_retries=3,
            initial_backoff_seconds=0.01,
            backoff_multiplier=1.5,
        )
        orchestrator = STTOrchestrator(
            adapter=flaky_adapter,
            config=OrchestratorConfig(retry_config=retry_cfg),
            sleep_func=lambda d: None,
        )

        chunk = self._generate_audio_chunk(seq=0, sample_rate=16000, channels=1)
        events = orchestrator.process_chunk(chunk)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, TranscriptEventType.FINAL)
        self.assertEqual(orchestrator.get_transcript(), "Recovered from network drop")
        self.assertEqual(flaky_adapter.call_count, 3)

    def test_timeout_and_retry_limit_enforcement(self) -> None:
        """Verify orchestrator enforces timeout and bounded retries on slow provider."""
        class StallingAdapter(BaseTranscriptionAdapter):
            @property
            def provider_name(self) -> str:
                return "StallingAdapter"

            def process_audio_chunk(self, chunk: bytes, context=None):
                time.sleep(0.2)
                return []

            def flush(self):
                return []

            def reset(self):
                pass

        stalling_adapter = StallingAdapter()
        retry_cfg = RetryConfig(
            max_retries=2,
            timeout_seconds=0.03,
            initial_backoff_seconds=0.005,
        )
        orchestrator = STTOrchestrator(
            adapter=stalling_adapter,
            config=OrchestratorConfig(retry_config=retry_cfg, raise_on_error=False),
            sleep_func=lambda d: None,
        )

        chunk = self._generate_audio_chunk(seq=0, sample_rate=16000, channels=1)
        events = orchestrator.process_chunk(chunk)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, TranscriptEventType.ERROR)
        self.assertEqual(events[0].error.code, "STT_TIMEOUT")
        self.assertEqual(len(orchestrator.errors), 1)

    # -------------------------------------------------------------------------
    # Session Reset & Multi-Session Tests
    # -------------------------------------------------------------------------

    def test_multi_session_clean_reset(self) -> None:
        """Verify orchestrator cleanly separates consecutive sessions after reset()."""
        adapter = DeterministicFakeTranscriber()
        orchestrator = STTOrchestrator(adapter=adapter)

        # Session 1
        orchestrator.process_chunk(self._generate_audio_chunk(seq=0, sample_rate=16000, channels=1))
        orchestrator.flush()
        transcript_session_1 = orchestrator.get_transcript()
        self.assertTrue(len(transcript_session_1) > 0)

        # Reset for Session 2
        orchestrator.reset()
        self.assertEqual(orchestrator.get_transcript(), "")
        self.assertEqual(orchestrator.chunk_counter, 0)

        # Session 2
        orchestrator.process_chunk(self._generate_audio_chunk(seq=0, sample_rate=16000, channels=1))
        orchestrator.flush()
        transcript_session_2 = orchestrator.get_transcript()
        # Since DeterministicFakeTranscriber was reset, identical input produces identical transcript
        self.assertEqual(transcript_session_1, transcript_session_2)


if __name__ == "__main__":
    unittest.main()
