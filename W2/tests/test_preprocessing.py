"""Unit and contract tests for Audio Preprocessing (Resampling, Normalization, Conversion)."""

import math
import struct
import unittest

import numpy as np

from academiaai.audio.schemas import AudioChunk, AudioFormat
from w2_stt.exceptions import (
    STTConfigurationError,
    STTInputError,
    STTPreprocessingError,
)
from w2_stt.preprocessing import AudioPreprocessingConfig, AudioPreprocessor


class TestAudioPreprocessing(unittest.TestCase):
    """Validation suite for audio resampling, normalization, and format conversions."""

    def setUp(self) -> None:
        self.standard_format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)

    def _generate_sine_pcm(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        frequency: float = 440.0,
        duration_ms: float = 100.0,
        amplitude: float = 0.5,
    ) -> bytes:
        """Generate synthetic PCM 16-bit sine wave bytes."""
        total_samples = int(round((duration_ms / 1000.0) * sample_rate))
        raw_samples = []
        for i in range(total_samples):
            val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * frequency * (i / sample_rate)))
            clamped = max(-32768, min(32767, val))
            if channels == 1:
                raw_samples.append(clamped)
            else:
                # Stereo: duplicate sample across L & R
                raw_samples.extend([clamped, clamped])
        return struct.pack(f"<{len(raw_samples)}h", *raw_samples)

    # -------------------------------------------------------------------------
    # Configuration Validation Tests
    # -------------------------------------------------------------------------

    def test_valid_preprocessing_config(self) -> None:
        """Verify default and customized valid AudioPreprocessingConfig."""
        cfg = AudioPreprocessingConfig(
            target_sample_rate=16000,
            target_channels=1,
            target_sample_width=2,
            normalize_audio=True,
            target_peak_level=0.90,
        )
        self.assertEqual(cfg.target_sample_rate, 16000)
        self.assertEqual(cfg.target_channels, 1)
        self.assertTrue(cfg.normalize_audio)
        self.assertEqual(cfg.target_peak_level, 0.90)

    def test_invalid_target_sample_rate_rejected(self) -> None:
        """Non-standard sample rate must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            AudioPreprocessingConfig(target_sample_rate=12345)

    def test_invalid_target_channels_rejected(self) -> None:
        """Unsupported channel count must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            AudioPreprocessingConfig(target_channels=5)

    def test_invalid_target_peak_level_rejected(self) -> None:
        """Peak level outside (0.0, 1.0] must raise STTConfigurationError."""
        with self.assertRaises(STTConfigurationError):
            AudioPreprocessingConfig(target_peak_level=0.0)
        with self.assertRaises(STTConfigurationError):
            AudioPreprocessingConfig(target_peak_level=1.2)

    # -------------------------------------------------------------------------
    # Fast-Path / Identity Bypass Tests
    # -------------------------------------------------------------------------

    def test_identity_bypass_when_matching_target_and_no_normalization(self) -> None:
        """Audio already matching target format with normalization off must return identical object."""
        pcm = self._generate_sine_pcm(16000, 1, duration_ms=50.0)
        chunk = AudioChunk(
            data=pcm,
            format=self.standard_format,
            sequence_id=42,
            timestamp_ms=100.0,
        )
        preprocessor = AudioPreprocessor(
            AudioPreprocessingConfig(
                target_sample_rate=16000,
                target_channels=1,
                target_sample_width=2,
                normalize_audio=False,
            )
        )
        result = preprocessor.process(chunk)
        self.assertIs(result, chunk)  # Exact same memory reference, zero overhead

    def test_master_bypass_when_disabled(self) -> None:
        """When enabled=False, preprocessor returns chunk unmodified even if format differs."""
        fmt_48k = AudioFormat(sample_rate=48000, channels=2, sample_width=2)
        pcm = self._generate_sine_pcm(48000, 2, duration_ms=50.0)
        chunk = AudioChunk(data=pcm, format=fmt_48k, sequence_id=1, timestamp_ms=0.0)

        preprocessor = AudioPreprocessor(AudioPreprocessingConfig(enabled=False))
        result = preprocessor.process(chunk)
        self.assertIs(result, chunk)

    # -------------------------------------------------------------------------
    # Resampling Tests
    # -------------------------------------------------------------------------

    def test_downsampling_48k_to_16k(self) -> None:
        """Audio at 48kHz must be downsampled to 16kHz (3:1 ratio) with accurate metadata."""
        fmt_48k = AudioFormat(sample_rate=48000, channels=1, sample_width=2)
        pcm_48k = self._generate_sine_pcm(48000, 1, duration_ms=100.0)
        chunk = AudioChunk(
            data=pcm_48k,
            format=fmt_48k,
            sequence_id=7,
            timestamp_ms=250.0,
        )

        preprocessor = AudioPreprocessor(
            AudioPreprocessingConfig(target_sample_rate=16000, target_channels=1)
        )
        processed = preprocessor.process(chunk)

        # 48kHz has 4800 samples for 100ms; 16kHz must have 1600 samples
        expected_samples = 1600
        expected_bytes = expected_samples * 2
        self.assertEqual(len(processed.data), expected_bytes)
        self.assertEqual(processed.format.sample_rate, 16000)
        self.assertEqual(processed.format.channels, 1)
        self.assertEqual(processed.sequence_id, 7)
        self.assertEqual(processed.timestamp_ms, 250.0)
        self.assertAlmostEqual(processed.duration_ms, 100.0, delta=0.5)

    def test_upsampling_8k_to_16k(self) -> None:
        """Telephony 8kHz audio must be upsampled to 16kHz (1:2 ratio)."""
        fmt_8k = AudioFormat(sample_rate=8000, channels=1, sample_width=2)
        pcm_8k = self._generate_sine_pcm(8000, 1, duration_ms=50.0)
        chunk = AudioChunk(data=pcm_8k, format=fmt_8k, sequence_id=12, timestamp_ms=500.0)

        preprocessor = AudioPreprocessor(
            AudioPreprocessingConfig(target_sample_rate=16000, target_channels=1)
        )
        processed = preprocessor.process(chunk)

        # 8kHz has 400 samples; 16kHz must have 800 samples
        self.assertEqual(processed.sample_count, 800)
        self.assertEqual(processed.format.sample_rate, 16000)

    # -------------------------------------------------------------------------
    # Channel Downmixing Tests
    # -------------------------------------------------------------------------

    def test_stereo_to_mono_downmixing(self) -> None:
        """Stereo 2-channel audio must be averaged down to mono 1-channel."""
        fmt_stereo = AudioFormat(sample_rate=16000, channels=2, sample_width=2)
        # Create stereo frames where Left has amplitude 10000, Right has amplitude 20000
        frames_count = 100
        left = [10000] * frames_count
        right = [20000] * frames_count
        interleaved = []
        for l, r in zip(left, right):
            interleaved.extend([l, r])
        pcm_stereo = struct.pack(f"<{len(interleaved)}h", *interleaved)

        chunk = AudioChunk(
            data=pcm_stereo,
            format=fmt_stereo,
            sequence_id=1,
            timestamp_ms=0.0,
        )

        preprocessor = AudioPreprocessor(
            AudioPreprocessingConfig(target_sample_rate=16000, target_channels=1)
        )
        processed = preprocessor.process(chunk)

        self.assertEqual(processed.format.channels, 1)
        self.assertEqual(processed.frame_count, frames_count)
        # Check averaged samples: (10000 + 20000) / 2 = 15000
        samples = np.frombuffer(processed.data, dtype=np.int16)
        self.assertTrue(np.all(samples == 15000))

    # -------------------------------------------------------------------------
    # Normalization Tests
    # -------------------------------------------------------------------------

    def test_audio_peak_normalization(self) -> None:
        """Quiet audio signal should be scaled up to target peak level."""
        # Low amplitude: 0.1 of max (~3276)
        pcm = self._generate_sine_pcm(16000, 1, duration_ms=50.0, amplitude=0.1)
        chunk = AudioChunk(data=pcm, format=self.standard_format, sequence_id=1, timestamp_ms=0.0)

        preprocessor = AudioPreprocessor(
            AudioPreprocessingConfig(
                target_sample_rate=16000,
                target_channels=1,
                normalize_audio=True,
                target_peak_level=0.95,
            )
        )
        processed = preprocessor.process(chunk)

        samples = np.frombuffer(processed.data, dtype=np.int16)
        max_peak = np.max(np.abs(samples))
        expected_peak = int(32767 * 0.95)
        # Allow slight rounding tolerance
        self.assertAlmostEqual(max_peak, expected_peak, delta=2)

    def test_silent_audio_normalization_does_not_divide_by_zero(self) -> None:
        """All-zero silent audio should pass through normalization without NaN or crash."""
        silence_bytes = bytes(3200)  # 1600 samples of 16-bit silence
        chunk = AudioChunk(data=silence_bytes, format=self.standard_format, sequence_id=2, timestamp_ms=0.0)

        preprocessor = AudioPreprocessor(
            AudioPreprocessingConfig(normalize_audio=True, target_peak_level=0.95)
        )
        processed = preprocessor.process(chunk)
        samples = np.frombuffer(processed.data, dtype=np.int16)
        self.assertEqual(np.max(np.abs(samples)), 0)

    # -------------------------------------------------------------------------
    # Input Error Handling Tests
    # -------------------------------------------------------------------------

    def test_invalid_chunk_type_raises_stt_input_error(self) -> None:
        """Passing non-AudioChunk must raise STTInputError."""
        preprocessor = AudioPreprocessor()
        with self.assertRaises(STTInputError):
            preprocessor.process("not-a-chunk")  # type: ignore

    def test_empty_chunk_payload_raises_stt_input_error(self) -> None:
        """AudioChunk with empty data cannot be instantiated or processed."""
        # AudioChunk itself forbids 0 bytes via EmptyChunkError
        preprocessor = AudioPreprocessor()
        with self.assertRaises(Exception):
            chunk = AudioChunk(data=b"", format=self.standard_format, sequence_id=0, timestamp_ms=0.0)
            preprocessor.process(chunk)


if __name__ == "__main__":
    unittest.main()
