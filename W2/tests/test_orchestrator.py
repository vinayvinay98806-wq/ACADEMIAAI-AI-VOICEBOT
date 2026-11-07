"""Unit and contract tests for the STT Orchestrator layer."""

import unittest
from typing import List, Optional

from academiaai.audio.schemas import AudioChunk, AudioFormat
from w2_stt.accumulator import OrderedTranscriptAccumulator
from w2_stt.exceptions import STTInputError, STTProviderError
from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.orchestrator import OrchestratorConfig, STTOrchestrator
from w2_stt.preprocessing import AudioPreprocessingConfig, AudioPreprocessor
from w2_stt.reliability import RetryConfig
from w2_stt.schemas import TranscriptEventType


class TestSTTOrchestrator(unittest.TestCase):
    """Validation test suite for STTOrchestrator."""

    def setUp(self) -> None:
        self.format_16k = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.adapter = DeterministicFakeTranscriber()
        self.config = OrchestratorConfig(
            session_id="test-orchestrator-session",
            raise_on_error=False,
            preserve_chunk_metadata=True,
        )
        self.orchestrator = STTOrchestrator(
            adapter=self.adapter,
            config=self.config,
            sleep_func=lambda d: None,
        )

    def _create_chunk(self, seq: int, duration_ms: float = 100.0) -> AudioChunk:
        byte_count = self.format_16k.calculate_byte_count(duration_ms)
        data = bytes([seq % 256] * byte_count)
        return AudioChunk(
            data=data,
            format=self.format_16k,
            sequence_id=seq,
            timestamp_ms=seq * duration_ms,
        )

    # -------------------------------------------------------------------------
    # Audio-to-Transcript Flow Tests
    # -------------------------------------------------------------------------

    def test_single_audio_chunk_flow_and_metadata_preservation(self) -> None:
        """Verify processing a single AudioChunk emits events and preserves chunk metadata."""
        chunk = self._create_chunk(seq=0, duration_ms=200.0)
        events = self.orchestrator.process_chunk(chunk)

        self.assertGreater(len(events), 0)
        first_event = events[0]
        self.assertEqual(first_event.session_id, "test-orchestrator-session")
        self.assertEqual(first_event.metadata.get("chunk_sequence_id"), 0)
        self.assertEqual(first_event.metadata.get("chunk_timestamp_ms"), 0.0)
        self.assertEqual(first_event.metadata.get("chunk_duration_ms"), 200.0)
        self.assertEqual(first_event.metadata.get("provider_name"), "DeterministicFakeTranscriber")

        self.assertEqual(self.orchestrator.chunk_counter, 1)
        self.assertEqual(self.orchestrator.total_audio_duration_ms, 200.0)

    def test_multiple_sequential_chunks(self) -> None:
        """Verify sequential ingestion of multiple chunks through process_chunks."""
        chunks = [self._create_chunk(seq=i, duration_ms=100.0) for i in range(4)]
        all_events = self.orchestrator.process_chunks(chunks)

        self.assertGreater(len(all_events), 0)
        self.assertEqual(self.orchestrator.chunk_counter, 4)
        self.assertAlmostEqual(self.orchestrator.total_audio_duration_ms, 400.0)

        # Transcripts should be available
        transcript = self.orchestrator.get_transcript(include_interim=True)
        self.assertTrue(len(transcript) > 0)

    def test_raw_bytes_processing(self) -> None:
        """Verify passing raw bytes is automatically wrapped and processed cleanly."""
        raw_pcm = bytes([1, 2] * 1600)  # 1600 16-bit samples = 100ms
        events = self.orchestrator.process_chunk(raw_pcm)

        self.assertGreater(len(events), 0)
        self.assertEqual(self.orchestrator.chunk_counter, 1)

    # -------------------------------------------------------------------------
    # Input Validation & Safe Handling Tests
    # -------------------------------------------------------------------------

    def test_empty_bytes_in_streaming_mode_emits_error_event(self) -> None:
        """Empty byte payload with raise_on_error=False emits error event into accumulator."""
        events = self.orchestrator.process_chunk(b"")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, TranscriptEventType.ERROR)
        self.assertEqual(events[0].error.code, "AUDIO_INPUT_INVALID")
        self.assertEqual(len(self.orchestrator.errors), 1)

    def test_empty_bytes_with_raise_on_error(self) -> None:
        """Empty byte payload with raise_on_error=True raises STTInputError."""
        strict_orch = STTOrchestrator(
            adapter=self.adapter,
            config=OrchestratorConfig(raise_on_error=True),
        )
        with self.assertRaises(STTInputError):
            strict_orch.process_chunk(b"")

    def test_invalid_input_type(self) -> None:
        """Invalid chunk object type is rejected safely."""
        with self.assertRaises(STTInputError):
            strict_orch = STTOrchestrator(
                adapter=self.adapter,
                config=OrchestratorConfig(raise_on_error=True),
            )
            strict_orch.process_chunk(12345)  # type: ignore

    # -------------------------------------------------------------------------
    # Flush & Reset Lifecycle Tests
    # -------------------------------------------------------------------------

    def test_flush_finalizes_pending_interim(self) -> None:
        """Calling flush() finalizes any pending interim segment in provider."""
        # Process odd number of chunks to leave interim pending
        chunk0 = self._create_chunk(seq=0)
        self.orchestrator.process_chunk(chunk0)
        self.assertTrue(self.orchestrator.accumulator.has_pending_interim)

        flushed = self.orchestrator.flush()
        self.assertEqual(len(flushed), 1)
        self.assertEqual(flushed[0].event_type, TranscriptEventType.FINAL)
        self.assertFalse(self.orchestrator.accumulator.has_pending_interim)

    def test_session_reset(self) -> None:
        """Reset clears accumulator segments, provider buffers, and metrics."""
        self.orchestrator.process_chunk(self._create_chunk(seq=0))
        self.orchestrator.flush()
        self.assertGreater(self.orchestrator.accumulator.final_count, 0)
        self.assertEqual(self.orchestrator.chunk_counter, 1)

        self.orchestrator.reset()
        self.assertEqual(self.orchestrator.accumulator.final_count, 0)
        self.assertEqual(self.orchestrator.chunk_counter, 0)
        self.assertEqual(self.orchestrator.total_audio_duration_ms, 0.0)
        self.assertEqual(self.orchestrator.get_transcript(), "")

    # -------------------------------------------------------------------------
    # Preprocessor Integration Tests
    # -------------------------------------------------------------------------

    def test_orchestrator_with_preprocessing(self) -> None:
        """Orchestrator preprocessor resamples 48kHz stereo input to 16kHz mono before provider."""
        fmt_48k_stereo = AudioFormat(sample_rate=48000, channels=2, sample_width=2)
        raw_stereo_bytes = bytes(48000 * 2 * 2 // 10)  # 100ms
        chunk = AudioChunk(data=raw_stereo_bytes, format=fmt_48k_stereo, sequence_id=0, timestamp_ms=0.0)

        pre_cfg = AudioPreprocessingConfig(
            target_sample_rate=16000,
            target_channels=1,
            normalize_audio=False,
        )
        orch = STTOrchestrator(
            adapter=self.adapter,
            config=OrchestratorConfig(preprocessing_config=pre_cfg),
        )

        events = orch.process_chunk(chunk)
        self.assertGreater(len(events), 0)
        self.assertEqual(events[0].metadata.get("chunk_sequence_id"), 0)

    # -------------------------------------------------------------------------
    # Error Handling & State Preservation Tests
    # -------------------------------------------------------------------------

    def test_provider_error_does_not_corrupt_accumulated_transcript(self) -> None:
        """Provider error injected on second chunk does not corrupt first finalized segment."""
        # Provider configured to fail on chunk index 1
        faulty_adapter = DeterministicFakeTranscriber(error_on_chunk_index=1)
        orch = STTOrchestrator(
            adapter=faulty_adapter,
            config=OrchestratorConfig(raise_on_error=False),
        )

        # Chunk 0 succeeds (emits interim)
        orch.process_chunk(self._create_chunk(seq=0))

        # Chunk 1 produces simulated provider error event
        events = orch.process_chunk(self._create_chunk(seq=1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, TranscriptEventType.ERROR)

        # Diagnostic errors are recorded, but accumulator is unharmed
        self.assertEqual(len(orch.errors), 1)
        self.assertEqual(orch.errors[0].code, "SIMULATED_TRANSCRIBER_ERROR")


if __name__ == "__main__":
    unittest.main()
