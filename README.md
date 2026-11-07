# Academiaai AI Voice Co-Pilot

## Worker 1 (W1): Audio Input & Voice Activity Detection (VAD)

This directory contains the production-grade audio ingestion and Voice Activity Detection (VAD) pipeline for **Worker 1 (W1)** of the Academiaai AI Voice Co-Pilot project. It is entirely self-contained, reproducible, hardware-independent, and deterministic.

---

## Architecture Overview

Worker 1 implements an end-to-end audio ingestion stream designed to deliver validated, continuous audio frames and speech activity decisions to downstream speech recognition and AI dialogue components:

```text
[ MockAudioDeviceAdapter ]
          │ (Enumeration & Permission Checks: UNKNOWN -> GRANTED)
          ▼
[ AudioLifecycleController ] ── (IDLE -> RUNNING -> PAUSED -> STOPPED)
          │
          ▼
[ FakeMicrophoneSource / DeterministicChunker ]
          │ (Atomic, frame-aligned AudioChunks)
          ▼
[ ThresholdVAD ] ── (Normalized RMS energy & min speech duration)
          │
          ▼
[ BoundedAudioBuffer ] ── (FIFO bounded memory & backpressure: DROP_NEWEST)
```

---

## Module Breakdown & Responsibilities

| Module | Responsibilities | Key Classes & Contracts |
| --- | --- | --- |
| `schemas.py` | Audio contracts, sample rates, chunk integrity, and exception hierarchy | `AudioFormat`, `AudioChunk`, `AudioError`, `AudioFormatError`, `AudioChunkError`, `EmptyChunkError`, `CorruptChunkError` |
| `sources.py` | Deterministic synthetic audio generator and stream chunker | `FakeMicrophoneSource`, `DeterministicChunker`, `SignalType` (`SINE_WAVE`, `SILENCE`, `WHITE_NOISE`, `SPEECH_LIKE`) |
| `devices.py` | Audio input device model, permission states, and mock adapter | `AudioDevice`, `AudioDeviceAdapter`, `MockAudioDeviceAdapter`, `PermissionState` (`UNKNOWN`, `REQUESTED`, `GRANTED`, `DENIED`), `DeviceError` hierarchy |
| `lifecycle.py` | Audio capture session state machine and chunk ingestion gates | `AudioLifecycleController`, `LifecycleState` (`IDLE`, `RUNNING`, `PAUSED`, `STOPPED`), `InvalidStateTransitionError`, `SessionNotRunningError` |
| `vad.py` | Baseline Voice Activity Detection using RMS energy and duration filtering | `VADInterface`, `ThresholdVAD`, `VADResult`, `SpeechSegment`, `calculate_chunk_rms`, `VADError`, `VADConfigurationError` |
| `buffer.py` | Bounded FIFO audio buffer with backpressure and sequence tracking | `BoundedAudioBuffer`, `BackpressurePolicy` (`DROP_NEWEST`, `DROP_OLDEST`), `BufferStats`, `AudioBufferError`, `BufferCapacityError` |
| `pipeline.py` | Coordinated integration harness wiring devices, lifecycle, source, VAD, and buffer | `AudioPipeline`, `PipelineStepResult`, `PipelineSummary` |
| `cli.py` | Interactive command-line interface for Week 1 & Week 2 demonstrations | `main()`, `run_pipeline_demo()`, `run_week2_demo()`, `run_invalid_chunk_demonstration()` |

---

## Detailed Component Specifications

### 1. Audio Device & Permission Workflow (`devices.py`)

The audio device layer abstracts hardware microphones without requiring OS audio drivers, native audio bindings, or paid cloud APIs:

- **Permission States**:
  - `UNKNOWN`: Initial unprompted state. Capture is disallowed.
  - `REQUESTED`: Permission request currently pending.
  - `GRANTED`: Capture is permitted.
  - `DENIED`: Capture is explicitly blocked.
- **Access Guard**: `validate_capture_allowed()` ensures that both a device is explicitly selected and permission is `GRANTED`. If no device is selected, `DeviceNotSelectedError` is raised; if permission is not granted, `DevicePermissionError` is raised.

### 2. Audio Lifecycle Controller (`lifecycle.py`)

Enforces a deterministic finite-state machine (FSM) over the capture session:

- **Valid Transitions**:
  - `IDLE -> RUNNING`: Triggered via `start()`. Validates device selection and permission state.
  - `RUNNING -> PAUSED`: Triggered via `pause()`. Suspends chunk ingestion while preserving sequence tracking.
  - `PAUSED -> RUNNING`: Triggered via `resume()`. Re-enables chunk ingestion seamlessly.
  - `RUNNING -> STOPPED` or `PAUSED -> STOPPED`: Triggered via `stop()`. Cleanly terminates session.
  - `STOPPED -> IDLE`: Triggered via `reset()`. Clears counters to permit a new session.
- **Chunk Gate**: `accept_chunk(chunk)` strictly requires `LifecycleState.RUNNING`. Attempting to ingest audio during `IDLE`, `PAUSED`, or `STOPPED` states raises `SessionNotRunningError` and increments rejection diagnostics.

### 3. Voice Activity Detection (`vad.py`)

A deterministic baseline energy/amplitude Voice Activity Detector:

- **Energy Metric**: Normalized Root-Mean-Square (RMS) amplitude:
  $$\text{RMS} = \sqrt{\frac{1}{N} \sum_{i=1}^{N} \left(\frac{s_i}{32768}\right)^2}$$
- **Units**: Dimensionless normalized amplitude in $[0.0, 1.0]$.
  - `0.000`: Digital silence (`SignalType.SILENCE`).
  - `~0.012`: Low-level background noise (`SignalType.WHITE_NOISE`, amplitude=0.02).
  - `~0.354`: Pure sine wave tone at 0.5 amplitude.
- **Default Threshold**: `0.05` separates ambient silence/noise from voiced phonemes.
- **Minimum Speech Duration (`min_speech_duration_ms`)**:
  - Eliminates transient noise bursts (clicks, thumps).
  - Continuous speech duration is accumulated while chunks exceed the threshold. Only when cumulative duration reaches `min_speech_duration_ms` is `is_speech` confirmed `True`.
  - Ongoing speech runs are finalized into `SpeechSegment` records upon returning to silence or when the stream terminates via `finalize()`.

### 4. Bounded Audio Buffer (`buffer.py`)

A bounded FIFO buffer ensuring deterministic memory consumption:

- **Capacity**: Enforces a strict upper bound `max_capacity` on retained chunks.
- **Backpressure Policy**:
  - `DROP_NEWEST` (Default): When full, incoming chunks are dropped to safeguard historical audio frames.
  - `DROP_OLDEST`: When full, the oldest chunk in the FIFO is evicted (`popleft()`) to prioritize recent audio.
- **Sequence Continuity & Diagnostic Counters**:
  - Rejects late chunks (`sequence_id <= last_seen_sequence_id`) to prevent silent reordering or duplicates.
  - Tracks sequence gaps if sequence IDs arrive with missing intervals.
  - Exposes `dropped_chunks`, `overflow_count`, `sequence_gaps`, `late_chunks`, and `total_duration_ms`.

---

## Quick Start & Verification

### 1. Running Unit Tests

Execute the comprehensive test suite (84 tests across all schemas, sources, devices, lifecycle, VAD, and buffer components) using Python's standard `unittest`:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

### 2. Running the Week 2 Demonstration

Run the complete 11-step end-to-end pipeline demonstration:

```powershell
$env:PYTHONPATH="src"
python -m academiaai.audio.cli --demo-week2
```

The demonstration guides you through:

1. Enumerating mock devices.
2. Selecting an active input device.
3. Requesting and simulating microphone permission.
4. Starting the audio lifecycle controller.
5. Generating synthetic speech-like audio.
6. Performing real-time RMS Voice Activity Detection.
7. Pushing chunks into the bounded FIFO buffer.
8. Demonstrating buffer capacity enforcement and overflow counters.
9. Pausing the stream (verifying chunk rejection) and resuming.
10. Stopping the session cleanly.
11. Printing a diagnostic execution summary.

### 3. Running Week 1 Demonstrations (Preserved)

Streaming synthetic speech-like chunks:

```powershell
$env:PYTHONPATH="src"
python -m academiaai.audio.cli --signal speech_like --chunks 10 --verbose
```

Demonstrating error rejection for invalid formats, corrupt chunks, and empty payloads:

```powershell
$env:PYTHONPATH="src"
python -m academiaai.audio.cli --test-invalid
```

---

## Limitations of Deterministic Mock VAD

- **Energy Metric Baseline**: The current VAD calculates time-domain RMS energy across the raw PCM frame. It does not perform frequency-domain spectral analysis (e.g. FFT, spectral tilt, zero-crossing rate) or machine-learning feature extraction (e.g. Silero VAD, WebRTC VAD GMMs).
- **Acoustic Noise Sensitivity**: High-energy non-speech sounds (e.g. loud uniform white noise with amplitude > 0.1) will exceed the RMS threshold. Downstream production systems should front this with acoustic echo cancellation (AEC) and spectral noise suppression.
- **Purpose**: This implementation provides a deterministic, zero-dependency, testable software contract for pipeline integration and co-pilot state coordination without physical audio hardware dependencies.
