"""Unit tests for AudioFormat and AudioChunk schemas (Days 1–2)."""

import unittest

from academiaai.audio.schemas import (
    AudioChunk,
    AudioChunkError,
    AudioError,
    AudioFormat,
    AudioFormatError,
    CorruptChunkError,
    EmptyChunkError,
    STANDARD_SAMPLE_RATES,
    SUPPORTED_CHANNELS,
    SUPPORTED_SAMPLE_WIDTHS,
)


class TestAudioFormat(unittest.TestCase):
    """Test suite for AudioFormat validation and calculations."""

    def test_default_format_creation(self) -> None:
        """Test default AudioFormat values (16kHz, mono, 16-bit PCM)."""
        fmt = AudioFormat()
        self.assertEqual(fmt.sample_rate, 16000)
        self.assertEqual(fmt.channels, 1)
        self.assertEqual(fmt.sample_width, 2)
        self.assertEqual(fmt.encoding, "pcm_s16le")
        self.assertEqual(fmt.bytes_per_frame, 2)
        self.assertEqual(fmt.bytes_per_second, 32000)

    def test_supported_sample_rates(self) -> None:
        """Test that all defined standard sample rates are accepted."""
        for rate in STANDARD_SAMPLE_RATES:
            fmt = AudioFormat(sample_rate=rate)
            self.assertEqual(fmt.sample_rate, rate)

    def test_invalid_sample_rates(self) -> None:
        """Test that non-standard, negative, zero, and non-integer sample rates raise AudioFormatError."""
        invalid_rates = [0, -16000, 12345, 99999, 16000.5, "16000", None, True]
        for rate in invalid_rates:
            with self.subTest(rate=rate):
                with self.assertRaises(AudioFormatError):
                    AudioFormat(sample_rate=rate)  # type: ignore

    def test_channel_validation(self) -> None:
        """Test mono and stereo channel acceptance and rejection of invalid channel counts."""
        # Valid channels
        for ch in SUPPORTED_CHANNELS:
            fmt = AudioFormat(channels=ch)
            self.assertEqual(fmt.channels, ch)

        # Invalid channels
        invalid_channels = [0, 3, 4, 6, 8, -1, 1.0, "1", None, False]
        for ch in invalid_channels:
            with self.subTest(ch=ch):
                with self.assertRaises(AudioFormatError):
                    AudioFormat(channels=ch)  # type: ignore

    def test_sample_width_validation(self) -> None:
        """Test supported sample widths and rejection of invalid widths."""
        for width in SUPPORTED_SAMPLE_WIDTHS:
            fmt = AudioFormat(sample_width=width)
            self.assertEqual(fmt.sample_width, width)

        invalid_widths = [0, 3, 5, 8, -2, 2.0, "2", None]
        for width in invalid_widths:
            with self.subTest(width=width):
                with self.assertRaises(AudioFormatError):
                    AudioFormat(sample_width=width)  # type: ignore

    def test_encoding_validation(self) -> None:
        """Test encoding string validation."""
        fmt = AudioFormat(encoding="pcm_s24le")
        self.assertEqual(fmt.encoding, "pcm_s24le")

        with self.assertRaises(AudioFormatError):
            AudioFormat(encoding="")
        with self.assertRaises(AudioFormatError):
            AudioFormat(encoding="   ")
        with self.assertRaises(AudioFormatError):
            AudioFormat(encoding=123)  # type: ignore

    def test_duration_and_byte_calculations(self) -> None:
        """Test bidirectional duration <-> byte count conversions."""
        fmt = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        # 20ms at 16kHz 16-bit mono = 320 samples = 640 bytes
        self.assertEqual(fmt.calculate_byte_count(20.0), 640)
        self.assertAlmostEqual(fmt.calculate_duration_ms(640), 20.0)

        # Stereo: 20ms at 16kHz 16-bit stereo = 320 frames * 4 bytes/frame = 1280 bytes
        stereo_fmt = AudioFormat(sample_rate=16000, channels=2, sample_width=2)
        self.assertEqual(stereo_fmt.calculate_byte_count(20.0), 1280)
        self.assertAlmostEqual(stereo_fmt.calculate_duration_ms(1280), 20.0)

        # Negative inputs
        with self.assertRaises(AudioFormatError):
            fmt.calculate_duration_ms(-10)
        with self.assertRaises(AudioFormatError):
            fmt.calculate_byte_count(-20.0)


class TestAudioChunkSchema(unittest.TestCase):
    """Test suite for AudioChunk data contract and attributes."""

    def setUp(self) -> None:
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.valid_data = b"\x00\x00" * 320  # 20ms worth of silence

    def test_valid_audio_chunk(self) -> None:
        """Test valid AudioChunk instantiation and derived properties."""
        chunk = AudioChunk(
            data=self.valid_data,
            format=self.format,
            sequence_id=0,
            timestamp_ms=0.0,
        )
        self.assertEqual(chunk.data, self.valid_data)
        self.assertEqual(chunk.format, self.format)
        self.assertEqual(chunk.sequence_id, 0)
        self.assertEqual(chunk.timestamp_ms, 0.0)
        self.assertAlmostEqual(chunk.duration_ms, 20.0)
        self.assertEqual(chunk.frame_count, 320)
        self.assertEqual(chunk.sample_count, 320)
        self.assertFalse(chunk.is_empty)

    def test_bytearray_input_conversion(self) -> None:
        """Test that bytearray input is accepted and converted to bytes."""
        mutable_data = bytearray(self.valid_data)
        chunk = AudioChunk(
            data=mutable_data,
            format=self.format,
            sequence_id=5,
            timestamp_ms=100.0,
        )
        self.assertIsInstance(chunk.data, bytes)
        self.assertEqual(chunk.data, self.valid_data)


if __name__ == "__main__":
    unittest.main()
