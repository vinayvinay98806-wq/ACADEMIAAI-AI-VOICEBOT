# AcademiaAI AI Voice Co-Pilot: Workstream W2 (Speech-to-Text) - Week 2

> **Status:** Week 2 Implementation Complete (Orchestration, Reliability & Integration)  
> **Workstream:** W2 — Speech-to-Text (STT)  
> **Environment:** Python 3.10+ (Tested on Python 3.12.10)  
> **Validation:** Pydantic v2  
> **Test Suite:** Built-in `unittest` & `pytest` compatible (108 Tests, 100% Passing)

---

## 1. Overview & Architecture

Week 2 extends the isolated Speech-to-Text (STT) engine from Week 1 into an end-to-end, resilient orchestration layer. It seamlessly integrates the upstream **Worker 1 (W1) Audio Input & VAD** contracts (`AudioChunk`, `AudioFormat`) with provider-neutral transcription adapters, audio preprocessing, bounded retry policies, timeout guards, and chronological reconciliation accumulators.

The entire pipeline runs **100% offline**, requiring zero cloud credentials, external APIs, or physical microphone hardware.

### End-to-End Workflow

```text
AudioChunk (W1 Contract: 48kHz / Stereo / PCM)
    │
    ▼
[AudioPreprocessor]
    ├── Input format validation
    ├── Multi-channel downmixing (Stereo -> Mono)
    ├── Resampling (e.g. 48kHz -> 16kHz standard)
    ├── Peak amplitude normalization (e.g. 0.95 ceiling)
    └── Metadata preservation (sequence_id, timestamp_ms, updated duration_ms)
    │
    ▼
[STTOrchestrator]
    ├── Session-level state management
    ├── Metadata enrichment (attaches chunk telemetry to events)
    ├── Stream lifecycle (process_chunk, process_chunks, flush, reset)
    └── [Reliability Layer: execute_with_retry]
            ├── Configurable per-call timeout
            ├── Bounded exponential backoff retries
            ├── Transient failure recovery (connection drops, HTTP 429/503)
            └── Permanent failure short-circuit (auth errors, bad requests)
            │
            ▼
    [BaseTranscriptionAdapter] (e.g. DeterministicFakeTranscriber)
            │
            ▼
      TranscriptEvents (Interim, Final, Error)
            │
            ▼
[OrderedTranscriptAccumulator]
    ├── Duplicate event suppression (via unique event_id)
    ├── Chronological reordering (start_time, end_time, segment_id)
    ├── Interim hypothesis progression
    ├── Final segment replacement & interim purging
    ├── Error isolation (preserves existing valid transcripts)
    └── Session metrics (final_count, total_duration, duplicate_events_count)
    │
    ▼
Continuous Consolidated Transcript & Structured Timeline
```

### Module Structure

```text
.
├── pyproject.toml              # Build configuration and scripts
├── requirements.txt            # Dependency specification (pydantic>=2.0.0, numpy>=1.24.0)
├── README-W2.md                # Complete Week 2 documentation
├── demo.py                     # Standalone end-to-end demonstration script
├── src/
│   ├── academiaai/             # Shared W1 audio contract definitions
│   │   └── audio/
│   │       ├── schemas.py      # AudioChunk, AudioFormat, AudioError hierarchy
│   │       └── sources.py      # Synthetic audio test fixtures
│   └── w2_stt/
│       ├── __init__.py         # Public exports
│       ├── schemas.py          # TranscriptSegment, TranscriptEvent, TranscriptErrorInfo
│       ├── adapter.py          # BaseTranscriptionAdapter (provider-neutral contract)
│       ├── fake_transcriber.py # DeterministicFakeTranscriber (reproducible mock engine)
│       ├── accumulator.py      # OrderedTranscriptAccumulator (ordering, deduplication)
│       ├── preprocessing.py    # AudioPreprocessor & AudioPreprocessingConfig
│       ├── reliability.py      # RetryConfig & execute_with_retry
│       ├── exceptions.py       # STTError hierarchy and error normalization
│       └── orchestrator.py     # STTOrchestrator & OrchestratorConfig
└── tests/
    ├── __init__.py
    ├── fixtures/
    │   └── sample_events.py    # Controlled test event & segment fixtures
    ├── test_schemas.py         # Week 1: Schema constraint tests
    ├── test_adapter.py         # Week 1: Abstract interface compliance tests
    ├── test_fake_transcriber.py# Week 1: Deterministic mock provider tests
    ├── test_accumulator.py     # Week 1: Accumulator ordering and interim replacement tests
    ├── test_audio/             # Week 1: W1 audio schema regression tests
    ├── test_preprocessing.py   # Week 2: Resampling, normalization, channel downmixing tests
    ├── test_reliability.py     # Week 2: Timeouts, exponential retries, error normalization tests
    ├── test_orchestrator.py    # Week 2: Orchestration, chunk flow, metadata preservation tests
    └── test_integration.py     # Week 2: Complete end-to-end integration tests
```

---

## 2. Week 2 Features & Components

### 2.1 STT Orchestrator (`w2_stt.orchestrator`)

* **`STTOrchestrator`**: The primary coordinator connecting audio sources, preprocessing, transcription adapters, and accumulation.
  * `process_chunk(chunk: Union[AudioChunk, bytes], context: Optional[dict]) -> List[TranscriptEvent]`: Ingests an individual chunk, automatically validates, preprocesses, invokes adapter under retry policy, enriches events with chunk telemetry, and stores results in the accumulator.
  * `process_chunks(chunks: Iterable[AudioChunk], context: Optional[dict]) -> List[TranscriptEvent]`: Sequentially processes a stream of chunks.
  * `flush() -> List[TranscriptEvent]`: Forces provider to finalize and emit any trailing interim hypotheses before stream closure.
  * `reset() -> None`: Clears all internal provider buffers, accumulator state, sequence counters, and resets session metrics.
  * `get_transcript(include_interim: bool = False, separator: str = " ") -> str`: Retrieves continuous assembled text.
  * `get_segments(include_interim: bool = False) -> List[TranscriptSegment]`: Retrieves chronologically sorted segments.
  * `errors -> List[TranscriptErrorInfo]`: Returns diagnostic errors encountered without state corruption.
* **`OrchestratorConfig`**:
  * `session_id: Optional[str]`: Session tracking ID (auto-generated if omitted).
  * `default_language: str`: Default language code (`"en-US"`).
  * `raise_on_error: bool`: If `True`, exceptions are raised; if `False`, error events are recorded safely in the stream.
  * `preserve_chunk_metadata: bool`: Enriches emitted events with `chunk_sequence_id`, `chunk_timestamp_ms`, `chunk_duration_ms`, and `provider_name`.
  * `preprocessing_config: Optional[AudioPreprocessingConfig]`: Preprocessing directives.
  * `retry_config: Optional[RetryConfig]`: Retry and timeout policy.

### 2.2 Audio Preprocessor (`w2_stt.preprocessing`)

* **`AudioPreprocessor`**:
  * **Input Validation**: Rejects empty payloads, misaligned frames, or unsupported formats.
  * **Fast-Path Bypass**: If an incoming `AudioChunk` already matches the target configuration and normalization is disabled, returns the input chunk directly without memory copying.
  * **Downmixing / Upmixing**: Averages multi-channel audio (e.g. Stereo 2ch -> Mono 1ch) or duplicates mono across stereo channels.
  * **Resampling**: High-performance linear interpolation resampling from any standard rate (8kHz, 44.1kHz, 48kHz) to the target STT sample rate (default 16kHz).
  * **Peak Normalization**: Scales peak amplitude to a configurable target ceiling (e.g., 0.95) without clipping or division-by-zero on silence.
  * **Metadata Preservation**: Retains original `sequence_id` and starting `timestamp_ms`, recalculating `duration_ms` from new sample count and sample rate.
* **`AudioPreprocessingConfig`**:
  * `target_sample_rate: int = 16000` (8000, 16000, 22050, 44100, 48000)
  * `target_channels: int = 1` (1=mono, 2=stereo)
  * `target_sample_width: int = 2` (16-bit PCM)
  * `normalize_audio: bool = False`
  * `target_peak_level: float = 0.95`
  * `enabled: bool = True`

### 2.3 Reliability & Retry Policies (`w2_stt.reliability`)

* **`RetryConfig`**:
  * `max_retries: int = 3`: Maximum retry attempts (>= 0).
  * `initial_backoff_seconds: float = 0.05`: Initial backoff delay (>= 0.0).
  * `max_backoff_seconds: float = 1.0`: Maximum backoff ceiling.
  * `backoff_multiplier: float = 2.0`: Exponential multiplier per attempt.
  * `timeout_seconds: Optional[float] = 5.0`: Maximum execution time per attempt.
  * `retry_on_transient_only: bool = True`: Only transient errors are retried.
* **`execute_with_retry`**:
  * Wraps provider invocations with per-call thread pool timeouts.
  * Computes bounded exponential backoff delays.
  * Short-circuits immediately on permanent errors without wasting retries.
  * Re-raises normalized errors preserving cause and diagnostic trace.

### 2.4 Error Normalization & Exceptions (`w2_stt.exceptions`)

* **Exception Hierarchy**:
  * `STTError`: Root domain exception.
    * `STTConfigurationError`: Configuration validation errors.
    * `STTInputError`: Corrupted or invalid audio chunk input.
    * `STTPreprocessingError`: Audio resampling or conversion failures.
    * `STTProviderError`: Provider failures.
      * `STTTransientError`: Recoverable issues (HTTP 429, 502, 503, connection drops).
      * `STTTimeoutError`: Specific transient timeout condition.
      * `STTPermanentError`: Non-recoverable failures (HTTP 401 Unauthorized, 403 Forbidden, 400 Bad Request, Quota Exceeded).
* **`normalize_provider_error(error, provider_name)`**: Normalizes arbitrary external or system exceptions into structured `STTProviderError` instances.
* **`to_transcript_error_info(error)`**: Converts exceptions to validated `TranscriptErrorInfo` models.

### 2.5 Accumulator & Reconciliation (`w2_stt.accumulator`)

* **`OrderedTranscriptAccumulator`**:
  * **Duplicate Event Suppression**: Deduplicates incoming events based on `event_id`, tracking `duplicate_events_count`.
  * **Chronological Ordering**: Maintains strict sort order `(start_time, end_time, segment_id)`.
  * **Interim Replacement**: Supersedes and purges earlier interim hypotheses when newer interims or final segments arrive for that `segment_id`.
  * **Late Interim Protection**: Discards stale interim events arriving after a final segment has already landed.
  * **Session Metrics**: Tracks `session_id`, `final_count`, `total_duration`, `total_event_count`, and `duplicate_events_count`.

---

## 3. Installation & Setup

### Prerequisites

* Python 3.10+ (Tested on Python 3.12.10)
* `pip`

### Installation

```bash
# Clone repository and navigate to W2 directory
cd W2

# Set PYTHONPATH to include src
$env:PYTHONPATH = "src;."

# Install required dependencies
pip install -r requirements.txt
```

### Dependencies (`requirements.txt`)

* `pydantic>=2.0.0` (Strict schema contract validation)
* `numpy>=1.24.0` (Deterministic audio resampling and normalization)

---

## 4. Running the Tests

The entire test suite uses Python's standard `unittest` framework and is also 100% compatible with `pytest`.

### Run All Tests via Unittest:

```bash
$env:PYTHONPATH = "src;."
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run by Functional Area:

```bash
# Week 2 Orchestrator tests
python -m unittest tests/test_orchestrator.py -v

# Week 2 Audio Preprocessing tests
python -m unittest tests/test_preprocessing.py -v

# Week 2 Reliability and Error Handling tests
python -m unittest tests/test_reliability.py -v

# Week 2 End-to-End Integration tests
python -m unittest tests/test_integration.py -v

# Week 1 Regression tests
python -m unittest tests/test_schemas.py tests/test_adapter.py tests/test_fake_transcriber.py tests/test_accumulator.py -v
```

### Test Suite Summary:
* **Total Tests:** 108
* **Failures / Errors:** 0 (100% Passing)
* **Execution Time:** ~1.3 seconds

---

## 5. Running the Demonstration

To execute the Week 2 end-to-end demonstration:

```bash
python demo.py
```

### What the Demo Shows:
1. **Audio Preprocessing**: Ingests synthetic 48kHz Stereo `AudioChunk`s, resamples to 16kHz Mono, and normalizes peak amplitude.
2. **Orchestrated Ingestion**: Streams chunks into `DeterministicFakeTranscriber` through `STTOrchestrator`.
3. **Live Interim Progression**: Displays provisional interim hypotheses being superseded in real time.
4. **Buffer Flushing**: Flushes pending interim state upon stream closure.
5. **Out-of-Order Handling**: Reorders out-of-order packets chronologically.
6. **Deduplication**: Suppresses duplicate events by `event_id`.
7. **Reliability & Recovery**: Simulates a flaky provider that drops connections twice, proving automatic recovery on the 3rd attempt via bounded exponential retries.
8. **Final Timeline**: Displays structured timeline of all finalized segments.

---

## 6. Example Usage

```python
from academiaai.audio.schemas import AudioChunk, AudioFormat
from w2_stt.fake_transcriber import DeterministicFakeTranscriber
from w2_stt.orchestrator import STTOrchestrator, OrchestratorConfig
from w2_stt.preprocessing import AudioPreprocessingConfig
from w2_stt.reliability import RetryConfig

# 1. Configure audio preprocessing (48kHz Stereo -> 16kHz Mono)
pre_cfg = AudioPreprocessingConfig(
    target_sample_rate=16000,
    target_channels=1,
    normalize_audio=True,
    target_peak_level=0.95,
)

# 2. Configure reliability and retries
retry_cfg = RetryConfig(
    max_retries=3,
    initial_backoff_seconds=0.05,
    backoff_multiplier=2.0,
    timeout_seconds=5.0,
)

# 3. Initialize Orchestrator with adapter
adapter = DeterministicFakeTranscriber()
orchestrator = STTOrchestrator(
    adapter=adapter,
    config=OrchestratorConfig(
        session_id="lecture-demo-101",
        preprocessing_config=pre_cfg,
        retry_config=retry_cfg,
    ),
)

# 4. Stream audio chunks (e.g. from Worker 1 VAD)
fmt = AudioFormat(sample_rate=48000, channels=2, sample_width=2)
raw_pcm_bytes = bytes(48000 * 2 * 2 // 10)  # 100ms
chunk = AudioChunk(data=raw_pcm_bytes, format=fmt, sequence_id=0, timestamp_ms=0.0)

events = orchestrator.process_chunk(chunk)

# 5. Flush trailing buffers upon stream end
orchestrator.flush()

# 6. Retrieve continuous transcript
print("Final Transcript:", orchestrator.get_transcript())
```

---

## 7. Known Limitations & Future Scope

1. **Deterministic Mock vs Cloud Providers**: All current demonstrations use `DeterministicFakeTranscriber` for zero-cost, offline repeatability. Real cloud providers (Deepgram, Whisper API, AssemblyAI) implement `BaseTranscriptionAdapter` in subsequent workstreams.
2. **Sample Width**: Preprocessing supports 8-bit, 16-bit (standard), and 32-bit PCM. Exotic encodings (e.g. mu-law / a-law) should be decoded prior to ingestion or handled by external decoders.
3. **Resampling Algorithm**: Resampling uses linear interpolation for fast deterministic execution without external C library bindings. Band-limited polyphase sinc interpolation can be enabled if acoustic fidelity at high Nyquist cutoffs is needed.
