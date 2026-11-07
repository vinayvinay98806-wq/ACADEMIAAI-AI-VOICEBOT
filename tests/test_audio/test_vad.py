"""Unit tests for Voice Activity Detection (VAD) (Week 2)."""

import unittest

from academiaai.audio.schemas import AudioChunk, AudioFormat
from academiaai.audio.sources import FakeMicrophoneSource, SignalType
from academiaai.audio.vad import (
    SpeechSegment,
    ThresholdVAD,
    VADConfigurationError,
    VADError,
    VADResult,
    calculate_chunk_rms,
)


class TestVoiceActivityDetection(unittest.TestCase):
    """Test suite for ThresholdVAD and RMS energy calculation."""

    def setUp(self) -> None:
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.vad = ThresholdVAD(energy_threshold=0.05, min_speech_duration_ms=0.0)

    def _generate_chunk(self, signal_type: SignalType, amplitude: float = 0.5) -> AudioChunk:
        """Helper to generate a single synthetic AudioChunk."""
        source = FakeMicrophoneSource(
            audio_format=self.format,
            chunk_duration_ms=20.0,
            signal_type=signal_type,
            amplitude=amplitude,
            total_chunks=1,
        )
        chunks = source.generate_chunks(1)
        self.assertEqual(len(chunks), 1)
        return chunks[0]

    def test_silence_below_threshold(self) -> None:
        """Test that synthetic silence yields 0 energy and is classified as non-speech."""
        chunk = self._generate_chunk(SignalType.SILENCE)
        result = self.vad.process_chunk(chunk)

        self.assertAlmostEqual(result.energy, 0.0, places=5)
        self.assertFalse(result.is_speech)
        self.assertFalse(result.raw_is_speech)
        self.assertEqual(result.threshold, 0.05)
        self.assertIs(result.chunk, chunk)

    def test_sine_wave_above_threshold(self) -> None:
        """Test that synthetic sine wave (amplitude=0.5) produces ~0.354 RMS and is classified as speech."""
        chunk = self._generate_chunk(SignalType.SINE_WAVE, amplitude=0.5)
        result = self.vad.process_chunk(chunk)

        # Theoretical RMS of sine wave with amp A is A / sqrt(2) = 0.5 / 1.4142 ~ 0.3535
        self.assertAlmostEqual(result.energy, 0.3535, places=2)
        self.assertGreater(result.energy, self.vad.energy_threshold)
        self.assertTrue(result.is_speech)
        self.assertTrue(result.raw_is_speech)

    def test_low_level_noise_below_threshold(self) -> None:
        """Test that low-level noise (amplitude=0.02) remains below threshold (0.05)."""
        # Noise at 0.02 amplitude has RMS ~ 0.02 / sqrt(3) ~ 0.0115
        chunk = self._generate_chunk(SignalType.WHITE_NOISE, amplitude=0.02)
        result = self.vad.process_chunk(chunk)

        self.assertLess(result.energy, 0.05)
        self.assertFalse(result.is_speech)
        self.assertFalse(result.raw_is_speech)

    def test_high_level_noise_above_threshold(self) -> None:
        """Test that loud noise (amplitude=0.8) exceeds threshold."""
        chunk = self._generate_chunk(SignalType.WHITE_NOISE, amplitude=0.8)
        result = self.vad.process_chunk(chunk)

        self.assertGreater(result.energy, 0.05)
        self.assertTrue(result.is_speech)

    def test_configurable_threshold(self) -> None:
        """Test adjusting the energy threshold changes speech classification deterministically."""
        chunk = self._generate_chunk(SignalType.SINE_WAVE, amplitude=0.2)
        # 0.2 sine wave RMS ~ 0.1414
        rms = calculate_chunk_rms(chunk)
        self.assertAlmostEqual(rms, 0.1414, places=2)

        # Low threshold (0.05): classified as speech
        vad_sensitive = ThresholdVAD(energy_threshold=0.05)
        self.assertTrue(vad_sensitive.process_chunk(chunk).is_speech)

        # High threshold (0.25): classified as non-speech
        vad_strict = ThresholdVAD(energy_threshold=0.25)
        self.assertFalse(vad_strict.process_chunk(chunk).is_speech)

    def test_minimum_speech_duration(self) -> None:
        """Test that transient noise shorter than min_speech_duration_ms is filtered out."""
        # 20ms chunks, require 60ms min speech duration (at least 3 consecutive chunks)
        vad = ThresholdVAD(energy_threshold=0.05, min_speech_duration_ms=60.0)

        source = FakeMicrophoneSource(
            audio_format=self.format,
            chunk_duration_ms=20.0,
            signal_type=SignalType.SINE_WAVE,
            amplitude=0.5,
        )

        chunk1 = source.read_chunk()
        chunk2 = source.read_chunk()
        chunk3 = source.read_chunk()

        # Chunk 1 (20ms): raw is speech, but accumulated 20ms < 60ms -> is_speech = False
        res1 = vad.process_chunk(chunk1)
        self.assertTrue(res1.raw_is_speech)
        self.assertFalse(res1.is_speech)
        self.assertAlmostEqual(res1.consecutive_speech_ms, 20.0)

        # Chunk 2 (40ms): raw is speech, accumulated 40ms < 60ms -> is_speech = False
        res2 = vad.process_chunk(chunk2)
        self.assertTrue(res2.raw_is_speech)
        self.assertFalse(res2.is_speech)
        self.assertAlmostEqual(res2.consecutive_speech_ms, 40.0)

        # Chunk 3 (60ms): raw is speech, accumulated 60ms >= 60ms -> is_speech = True!
        res3 = vad.process_chunk(chunk3)
        self.assertTrue(res3.raw_is_speech)
        self.assertTrue(res3.is_speech)
        self.assertAlmostEqual(res3.consecutive_speech_ms, 60.0)

    def test_speech_spanning_multiple_chunks_and_silence_reset(self) -> None:
        """Test consecutive speech chunks followed by silence reset consecutive speech duration."""
        vad = ThresholdVAD(energy_threshold=0.05, min_speech_duration_ms=40.0)

        sine_chunk = self._generate_chunk(SignalType.SINE_WAVE, amplitude=0.5)
        silence_chunk = self._generate_chunk(SignalType.SILENCE)

        # 2 speech chunks: meets 40ms requirement
        vad.process_chunk(sine_chunk)
        res2 = vad.process_chunk(sine_chunk)
        self.assertTrue(res2.is_speech)

        # Silence chunk arrives: resets consecutive speech
        res_silence = vad.process_chunk(silence_chunk)
        self.assertFalse(res_silence.is_speech)
        self.assertEqual(res_silence.consecutive_speech_ms, 0.0)

        # Completed speech segment recorded
        segments = vad.completed_segments
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0].duration_ms, 40.0)
        self.assertEqual(len(segments[0].chunks), 2)

    def test_stream_ending_during_speech(self) -> None:
        """Test finalizing an active speech stream cleanly captures pending speech segment."""
        vad = ThresholdVAD(energy_threshold=0.05, min_speech_duration_ms=40.0)

        sine_chunk = self._generate_chunk(SignalType.SINE_WAVE, amplitude=0.5)
        vad.process_chunk(sine_chunk)
        vad.process_chunk(sine_chunk)
        vad.process_chunk(sine_chunk)  # 60ms of speech, stream stops before silence

        # Before finalize: segments is empty because speech was still active
        self.assertEqual(len(vad.completed_segments), 0)

        # Call finalize()
        segments = vad.finalize()
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0].duration_ms, 60.0)
        self.assertEqual(len(segments[0].chunks), 3)

    def test_deterministic_repeated_results(self) -> None:
        """Test running VAD twice on identical input produces bit-for-bit identical results."""
        vad1 = ThresholdVAD(energy_threshold=0.05, min_speech_duration_ms=40.0)
        vad2 = ThresholdVAD(energy_threshold=0.05, min_speech_duration_ms=40.0)

        source = FakeMicrophoneSource(
            audio_format=self.format,
            chunk_duration_ms=20.0,
            signal_type=SignalType.SPEECH_LIKE,
            amplitude=0.5,
            seed=123,
            total_chunks=10,
        )
        chunks = source.generate_chunks(10)

        results1 = [vad1.process_chunk(c) for c in chunks]
        results2 = [vad2.process_chunk(c) for c in chunks]

        for r1, r2 in zip(results1, results2):
            self.assertEqual(r1.is_speech, r2.is_speech)
            self.assertEqual(r1.raw_is_speech, r2.raw_is_speech)
            self.assertAlmostEqual(r1.energy, r2.energy, places=7)

    def test_invalid_parameters_raise(self) -> None:
        """Test invalid threshold or duration raises VADConfigurationError."""
        with self.assertRaises(VADConfigurationError):
            ThresholdVAD(energy_threshold=-0.1)

        with self.assertRaises(VADConfigurationError):
            ThresholdVAD(min_speech_duration_ms=-10.0)

        with self.assertRaises(VADConfigurationError):
            ThresholdVAD(energy_threshold="invalid")  # type: ignore

    def test_reset(self) -> None:
        """Test resetting VAD clears counters and completed segments."""
        vad = ThresholdVAD(energy_threshold=0.05)
        chunk = self._generate_chunk(SignalType.SINE_WAVE)
        vad.process_chunk(chunk)
        self.assertGreater(vad.consecutive_speech_ms, 0.0)

        vad.reset()
        self.assertEqual(vad.consecutive_speech_ms, 0.0)
        self.assertEqual(len(vad.completed_segments), 0)


if __name__ == "__main__":
    unittest.main()
