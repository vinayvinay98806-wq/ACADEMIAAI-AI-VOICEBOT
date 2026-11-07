"""Audio Preprocessing Module for Workstream W2: Speech-to-Text.

This module provides `AudioPreprocessor` and `AudioPreprocessingConfig` to prepare raw audio
chunks for downstream speech recognition engines:
- Format verification and contract enforcement.
- Safe audio resampling (e.g. 48kHz / 44.1kHz -> 16kHz speech recognition standard).
- Multi-channel downmixing (stereo -> mono).
- Peak amplitude normalization.
- Metadata preservation (sequence_id, timestamp_ms, updated duration_ms).
- Avoidance of unnecessary conversions when input already matches target parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Union

import numpy as np

from academiaai.audio.schemas import (
    STANDARD_SAMPLE_RATES,
    SUPPORTED_CHANNELS,
    SUPPORTED_SAMPLE_WIDTHS,
    AudioChunk,
    AudioFormat,
    AudioFormatError,
)
from w2_stt.exceptions import (
    STTConfigurationError,
    STTInputError,
    STTPreprocessingError,
)


@dataclass(frozen=True)
class AudioPreprocessingConfig:
    """Configuration for audio preprocessing operations.

    Attributes:
        target_sample_rate: Desired sample rate in Hz (default 16000 for speech recognition).
        target_channels: Target channel count (1 for mono, 2 for stereo).
        target_sample_width: Bytes per sample (default 2 for 16-bit PCM).
        normalize_audio: If True, scales audio peak amplitude to target_peak_level.
        target_peak_level: Peak amplitude scaling fraction (0.0 < target_peak_level <= 1.0).
        enabled: Master toggle to enable or bypass all preprocessing.
    """

    target_sample_rate: int = 16000
    target_channels: int = 1
    target_sample_width: int = 2
    normalize_audio: bool = False
    target_peak_level: float = 0.95
    enabled: bool = True

    def __post_init__(self) -> None:
        """Validate preprocessing configuration options."""
        if self.target_sample_rate not in STANDARD_SAMPLE_RATES:
            raise STTConfigurationError(
                f"Unsupported target_sample_rate: {self.target_sample_rate}. "
                f"Supported standard rates: {sorted(STANDARD_SAMPLE_RATES)}"
            )
        if self.target_channels not in SUPPORTED_CHANNELS:
            raise STTConfigurationError(
                f"Unsupported target_channels: {self.target_channels}. Supported: {sorted(SUPPORTED_CHANNELS)}"
            )
        if self.target_sample_width not in SUPPORTED_SAMPLE_WIDTHS:
            raise STTConfigurationError(
                f"Unsupported target_sample_width: {self.target_sample_width}. Supported: {sorted(SUPPORTED_SAMPLE_WIDTHS)}"
            )
        if not (0.0 < self.target_peak_level <= 1.0):
            raise STTConfigurationError(
                f"target_peak_level must be in (0.0, 1.0], got {self.target_peak_level!r}"
            )


class AudioPreprocessor:
    """Prepares and standardizes raw audio chunks for transcription consumption.

    Guarantees:
    - Input validity: Ensures non-empty, frame-aligned audio inputs.
    - Identity bypass: If input chunk already matches target format and normalization is off,
      the original chunk is returned unmodified without memory duplication.
    - Resampling: Deterministic linear interpolation resampling.
    - Normalization: Safe bounded scaling without clipping or NaN generation.
    - Metadata fidelity: Preserves sequence ID and starting timestamp, re-calculating duration.
    """

    def __init__(self, config: Optional[AudioPreprocessingConfig] = None) -> None:
        self._config = config or AudioPreprocessingConfig()

    @property
    def config(self) -> AudioPreprocessingConfig:
        return self._config

    def process(self, chunk: AudioChunk) -> AudioChunk:
        """Apply preprocessing transformations to an AudioChunk.

        Args:
            chunk: Input AudioChunk to preprocess.

        Returns:
            Preprocessed AudioChunk conforming to target configuration.

        Raises:
            STTInputError: If chunk is invalid, empty, or unaligned.
            STTPreprocessingError: If conversion fails during numeric processing.
        """
        # 1. Input validation
        if not isinstance(chunk, AudioChunk):
            raise STTInputError(
                f"Expected AudioChunk instance, got {type(chunk).__name__}"
            )
        if len(chunk.data) == 0:
            raise STTInputError("AudioChunk payload is empty (0 bytes)")

        # 2. Check if preprocessing is completely bypassed
        if not self._config.enabled:
            return chunk

        src_fmt = chunk.format
        target_sr = self._config.target_sample_rate
        target_ch = self._config.target_channels
        target_sw = self._config.target_sample_width
        do_norm = self._config.normalize_audio

        # 3. Fast path: If already conforming and no normalization requested, return as-is
        if (
            src_fmt.sample_rate == target_sr
            and src_fmt.channels == target_ch
            and src_fmt.sample_width == target_sw
            and not do_norm
        ):
            return chunk

        try:
            # 4. Decode raw bytes to numpy array based on input sample width
            if src_fmt.sample_width == 1:
                # 8-bit PCM (unsigned)
                raw = np.frombuffer(chunk.data, dtype=np.uint8).astype(np.float32)
                samples = (raw - 128.0) * 256.0
            elif src_fmt.sample_width == 2:
                # 16-bit PCM (signed int16)
                samples = np.frombuffer(chunk.data, dtype=np.int16).astype(np.float32)
            elif src_fmt.sample_width == 4:
                # 32-bit float or int32
                samples = np.frombuffer(chunk.data, dtype=np.float32)
                # If normalized float [-1.0, 1.0], scale to 16-bit range
                if np.max(np.abs(samples)) <= 1.0:
                    samples = samples * 32767.0
            else:
                raise STTPreprocessingError(
                    f"Unsupported source sample_width: {src_fmt.sample_width}"
                )

            # 5. Channel conversion (downmix stereo to mono, or upmix mono to stereo)
            if src_fmt.channels == 2 and target_ch == 1:
                # Stereo to mono: average channels
                samples = samples.reshape(-1, 2)
                samples = np.mean(samples, axis=1)
            elif src_fmt.channels == 1 and target_ch == 2:
                # Mono to stereo: duplicate channel
                samples = np.repeat(samples[:, np.newaxis], 2, axis=1).reshape(-1)
            elif src_fmt.channels != target_ch:
                raise STTPreprocessingError(
                    f"Cannot convert from {src_fmt.channels} to {target_ch} channels"
                )

            # 6. Resampling via linear interpolation
            if src_fmt.sample_rate != target_sr:
                in_length = len(samples)
                out_length = int(round(in_length * (target_sr / src_fmt.sample_rate)))
                if out_length <= 0:
                    raise STTPreprocessingError(
                        f"Resampling produced 0 output samples for input length {in_length}"
                    )

                if in_length == 1:
                    samples = np.repeat(samples, out_length)
                else:
                    x_in = np.linspace(0.0, 1.0, in_length)
                    x_out = np.linspace(0.0, 1.0, out_length)
                    samples = np.interp(x_out, x_in, samples)

            # 7. Audio amplitude normalization
            if do_norm:
                peak = float(np.max(np.abs(samples)))
                if peak > 0.0:
                    max_allowed = 32767.0 * self._config.target_peak_level
                    scale_factor = max_allowed / peak
                    samples = samples * scale_factor

            # 8. Quantize back to 16-bit PCM target
            samples = np.clip(np.round(samples), -32768.0, 32767.0).astype(np.int16)
            out_bytes = samples.tobytes()

            # 9. Build preprocessed AudioFormat & AudioChunk preserving sequence/timestamp
            out_format = AudioFormat(
                sample_rate=target_sr,
                channels=target_ch,
                sample_width=target_sw,
                encoding="pcm_s16le",
            )
            new_duration_ms = out_format.calculate_duration_ms(len(out_bytes))

            return AudioChunk(
                data=out_bytes,
                format=out_format,
                sequence_id=chunk.sequence_id,
                timestamp_ms=chunk.timestamp_ms,
                duration_ms=new_duration_ms,
            )

        except Exception as exc:
            if isinstance(exc, (STTInputError, STTPreprocessingError)):
                raise
            raise STTPreprocessingError(
                f"Audio preprocessing transformation failed: {exc}"
            ) from exc
