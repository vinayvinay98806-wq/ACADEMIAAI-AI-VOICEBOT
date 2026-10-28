# Pull Request: [W1-Week1] Audio Input Contracts, Deterministic Chunker & Mock Sources

## Summary

This PR delivers **Week 1** of the Worker 1 (W1) assignment for the **Academiaai AI Voice Co-Pilot** pipeline, establishing robust, deterministic audio data contracts, a fake microphone source, a streaming chunker, and comprehensive unit tests with a CLI demonstration.

All implementation is strictly contained within `src/academiaai/audio/` and its unit tests under `tests/test_audio/`. No external dependencies or real microphone drivers are introduced.

---

## Deliverables by Assignment Days

### 1. Days 1–2: Audio Schemas & Validation (`src/academiaai/audio/schemas.py`)
- **`AudioFormat`**:
  - Sample rate validation supporting standard speech rates (`8000`, `11025`, `12000`, `16000`, `22050`, `24000`, `32000`, `44100`, `48000` Hz).
  - Channel validation (`1` for Mono, `2` for Stereo).
  - Sample width validation (`1`, `2`, `4` bytes per sample).
  - Accurate frame and duration calculation utilities (`bytes_per_frame`, `bytes_per_second`, `calculate_duration_ms`, `calculate_byte_count`).
- **`AudioChunk`**:
  - Immutable raw PCM data carrier.
  - Strict sequence tracking: non-negative `sequence_id` with monotonic validation.
  - Timestamp tracking: non-negative stream offset in milliseconds `timestamp_ms`.
  - Frame alignment enforcement: validates that `len(data)` is an exact multiple of `bytes_per_frame`.
- **Exception Hierarchy**:
  - Base `AudioError` -> `AudioFormatError`, `AudioChunkError`.
  - Subclasses: `EmptyChunkError` and `CorruptChunkError`.

### 2. Days 3–4: Mock Audio Source & Chunker (`src/academiaai/audio/sources.py`)
- **`DeterministicChunker`**:
  - Slices incoming continuous or fragmented byte streams into fixed-duration `AudioChunk` packets.
  - Automatically manages continuous monotonic `sequence_id` (starting at 0) and cumulative `timestamp_ms`.
  - Supports stream buffering, packet ingestion, and frame-aligned remainder flushing.
- **`FakeMicrophoneSource`**:
  - Synthetic, deterministic audio generator without physical hardware dependencies.
  - Supported signal modes:
    - `SINE_WAVE`: Pure tone at configurable frequency (e.g., 440 Hz).
    - `SILENCE`: Zeroed PCM stream.
    - `WHITE_NOISE`: Deterministic pseudo-random noise with fixed seed reproducibility.
    - `SPEECH_LIKE`: Modulated voiced bursts and silence pauses to emulate speech rhythm.
  - Produces valid, aligned `AudioChunk` instances ready for downstream VAD/STT consumers.

### 3. Days 5–6: CLI Demo & Unit Tests
- **CLI Demo (`src/academiaai/audio/cli.py`)**:
  - Command-line tool showcasing streaming chunk generation with summary statistics.
  - Includes `--test-invalid` flag demonstrating structured handling of invalid sample rates, invalid channels, empty chunks, corrupt unaligned payloads, negative sequence IDs, and duration discrepancies.
- **Unit Test Suite**:
  - `tests/test_audio/test_schemas.py`: Verifies format configurations, invalid rates, channels, widths, and duration calculations.
  - `tests/test_audio/test_sources.py`: Verifies chunker buffering, streaming, reset behavior, and deterministic reproducibility across all signal types.
  - `tests/test_audio/test_edge_cases.py`: Rigorous coverage of empty, non-bytes, corrupt/unaligned, and inconsistent chunks.

### 4. Day 7: PR Preparation & Test Verification
- All 28 tests pass deterministically.
- Actual test execution log included below.

---

## Actual Test Execution Output

```text
$env:PYTHONPATH="src"; python -m unittest discover -s tests -v

test_chunker_flush_corrupt_remainder (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_chunker_flush_corrupt_remainder)
Verify that flushing an unaligned remainder from chunker raises CorruptChunkError. ... ok
test_corrupt_chunk_unaligned_mono (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_corrupt_chunk_unaligned_mono)
Verify that odd/unaligned byte counts raise CorruptChunkError in mono 16-bit. ... ok
test_corrupt_chunk_unaligned_stereo (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_corrupt_chunk_unaligned_stereo)
Verify that byte counts not divisible by 4 raise CorruptChunkError in stereo 16-bit. ... ok
test_empty_chunk_rejection (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_empty_chunk_rejection)
Verify that an empty byte payload raises EmptyChunkError. ... ok
test_exception_hierarchy (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_exception_hierarchy)
Verify that all audio exceptions correctly inherit from AudioError. ... ok
test_inconsistent_duration_rejection (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_inconsistent_duration_rejection)
Verify that explicit duration_ms conflicting with payload raises CorruptChunkError. ... ok
test_negative_sequence_id_rejection (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_negative_sequence_id_rejection)
Verify that negative or non-integer sequence IDs raise AudioChunkError. ... ok
test_negative_timestamp_rejection (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_negative_timestamp_rejection)
Verify that negative or non-numeric timestamps raise AudioChunkError. ... ok
test_non_bytes_payload_rejection (test_audio.test_edge_cases.TestAudioChunkIntegrityAndErrors.test_non_bytes_payload_rejection)
Verify that non-bytes/non-bytearray objects raise AudioChunkError. ... ok
test_bytearray_input_conversion (test_audio.test_schemas.TestAudioChunkSchema.test_bytearray_input_conversion)
Test that bytearray input is accepted and converted to bytes. ... ok
test_valid_audio_chunk (test_audio.test_schemas.TestAudioChunkSchema.test_valid_audio_chunk)
Test valid AudioChunk instantiation and derived properties. ... ok
test_channel_validation (test_audio.test_schemas.TestAudioFormat.test_channel_validation)
Test mono and stereo channel acceptance and rejection of invalid channel counts. ... ok
test_default_format_creation (test_audio.test_schemas.TestAudioFormat.test_default_format_creation)
Test default AudioFormat values (16kHz, mono, 16-bit PCM). ... ok
test_duration_and_byte_calculations (test_audio.test_schemas.TestAudioFormat.test_duration_and_byte_calculations)
Test bidirectional duration <-> byte count conversions. ... ok
test_encoding_validation (test_audio.test_schemas.TestAudioFormat.test_encoding_validation)
Test encoding string validation. ... ok
test_invalid_sample_rates (test_audio.test_schemas.TestAudioFormat.test_invalid_sample_rates)
Test that non-standard, negative, zero, and non-integer sample rates raise AudioFormatError. ... ok
test_sample_width_validation (test_audio.test_schemas.TestAudioFormat.test_sample_width_validation)
Test supported sample widths and rejection of invalid widths. ... ok
test_supported_sample_rates (test_audio.test_schemas.TestAudioFormat.test_supported_sample_rates)
Test that all defined standard sample rates are accepted. ... ok
test_chunk_stream (test_audio.test_sources.TestDeterministicChunker.test_chunk_stream)
Test processing stream generator via chunk_stream. ... ok
test_chunker_initial_state (test_audio.test_sources.TestDeterministicChunker.test_chunker_initial_state)
Verify initial state of chunker. ... ok
test_chunking_exact_multiple (test_audio.test_sources.TestDeterministicChunker.test_chunking_exact_multiple)
Test feeding exact multiple of chunk size (2 chunks = 1280 bytes). ... ok
test_chunking_with_arbitrary_packet_sizes (test_audio.test_sources.TestDeterministicChunker.test_chunking_with_arbitrary_packet_sizes)
Test feeding irregular packet sizes (e.g. network/ring-buffer fragments). ... ok
test_reset (test_audio.test_sources.TestDeterministicChunker.test_reset)
Test that reset clears buffer and sequence counter. ... ok
test_silence_signal (test_audio.test_sources.TestFakeMicrophoneSource.test_silence_signal)
Test generating silence produces zeroed byte chunks. ... ok
test_sine_wave_determinism (test_audio.test_sources.TestFakeMicrophoneSource.test_sine_wave_determinism)
Test sine wave generation produces non-zero, mathematically deterministic samples. ... ok
test_speech_like_pattern (test_audio.test_sources.TestFakeMicrophoneSource.test_speech_like_pattern)
Test speech-like pattern produces chunks with voiced and unvoiced intervals. ... ok
test_total_duration_limit (test_audio.test_sources.TestFakeMicrophoneSource.test_total_duration_limit)
Test total_duration_ms stopping condition. ... ok
test_white_noise_reproducibility (test_audio.test_sources.TestFakeMicrophoneSource.test_white_noise_reproducibility)
Test that identical seeds generate bit-for-bit identical white noise. ... ok

----------------------------------------------------------------------
Ran 28 tests in 0.024s

OK
```

---

## Actual CLI Demo Output

```text
$env:PYTHONPATH="src"; python -m academiaai.audio.cli --signal sine_wave --chunks 5 --test-invalid

======================================================================
Academiaai AI Voice Co-Pilot - Worker 1: Audio Input & Chunker (Week 1)
======================================================================
Audio Format  : 16000 Hz, 1 channel(s), pcm_s16le
Chunk Duration: 20.0 ms (640 bytes/chunk)
Signal Type   : sine_wave (freq: 440.0 Hz, amp: 0.50)
Target Chunks : 5
----------------------------------------------------------------------
 Seq |    Timestamp |   Duration |   Bytes |  Frames | Preview (Hex)
----------------------------------------------------------------------
   0 |       0.00ms |    20.00ms |   640 B |     320 | 0000010bae15b51f...
   1 |      20.00ms |    20.00ms |   640 B |     320 | 22c371c76ecdeed4...
   2 |      40.00ms |    20.00ms |   640 B |     320 | 62da0bd212cbacc5...
   3 |      60.00ms |    20.00ms |   640 B |     320 | 9e25281cdb110607...
   4 |      80.00ms |    20.00ms |   640 B |     320 | de3c5c3ff73fab3e...
----------------------------------------------------------------------
SUMMARY:
  Total Chunks Generated : 5
  Sequence IDs Validated : 0 .. 4 (strictly monotonic)
  Total Audio Time       : 100.00 ms
  Total Audio Bytes      : 3200 bytes
  Integrity Check        : ALL CHUNKS PASSED FRAME ALIGNMENT AND VALIDATION
======================================================================

======================================================================
DEMO: Audio Validation & Error Handling (Invalid / Empty / Corrupt)
======================================================================

[Case 1] Attempting to construct AudioFormat with invalid sample rate (12345 Hz)...
  --> Caught expected AudioFormatError: Unsupported sample rate: 12345 Hz. Supported standard rates are: [8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000]

[Case 2] Attempting to construct AudioFormat with invalid channel count (5 channels)...
  --> Caught expected AudioFormatError: Invalid channel count: 5. Supported channels: [1, 2] (1=mono, 2=stereo)

[Case 3] Attempting to create AudioChunk with empty byte payload (b'')...
  --> Caught expected EmptyChunkError: AudioChunk data is empty (0 bytes)

[Case 4] Attempting to create AudioChunk with unaligned corrupt byte payload (3 bytes for 16-bit mono)...
  --> Caught expected CorruptChunkError: Corrupt chunk: data length (3 bytes) is not aligned to frame size (2 bytes = 2 bytes/sample * 1 channels). Remainder: 1 byte(s)

[Case 5] Attempting to create AudioChunk with negative sequence ID (-1)...
  --> Caught expected AudioChunkError: sequence_id must be non-negative (>= 0), got -1

[Case 6] Attempting to create AudioChunk with mismatched duration (claimed 100ms, actual 20ms)...
  --> Caught expected CorruptChunkError: Chunk duration_ms (100.00 ms) is inconsistent with payload length (640 bytes = 20.00 ms)

----------------------------------------------------------------------
All error cases successfully caught and verified against schemas.
----------------------------------------------------------------------
```

---

## Scope Compliance Checklist

- [x] Implemented W1 Week 1 scope only (Days 1–7).
- [x] Defined `AudioChunk`, `AudioFormat`, and `AudioError` schemas with sample-rate and channel validation.
- [x] Implemented `FakeMicrophoneSource` and `DeterministicChunker` with timestamps and sequence IDs.
- [x] Implemented CLI demo and unit tests covering invalid, empty, and corrupt chunks.
- [x] Prepared work for PR review and documented actual test output.
- [x] All implementation isolated inside W1 module (`src/academiaai/audio/`) and its tests (`tests/test_audio/`).
- [x] Zero real microphone hardware or third-party paid API dependencies used.
- [x] Week 2+ scope excluded (no real device enumeration, no OS permissions, no VAD energy/silence classifier logic).
- [x] No modifications to other workers' modules or Git configuration.
- [x] No automatic git commit or push performed.
