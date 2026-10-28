# AcademiaAI AI Voice Co-Pilot: Workstream W2 (Speech-to-Text) - Week 1

> **Status:** Week 1 Implementation Complete (Isolated Module)  
> **Workstream:** W2 — Speech-to-Text (STT)  
> **Environment:** Python 3.10+ (Tested on Python 3.12.10)  
> **Validation:** Pydantic v2  
> **Test Suite:** Built-in `unittest` & `pytest` compatible

---

## 1. Overview & Architecture

This repository contains the isolated **Week 1** deliverable for the **Speech-to-Text (STT)** workstream of the AcademiaAI AI Voice Co-Pilot project. It operates completely offline with **zero vendor dependencies**, no cloud credentials, and no external network access.

### Module Structure

```text
.
├── pyproject.toml              # Modern Python build & tool configuration
├── requirements.txt            # Dependency specification (pydantic>=2.0.0)
├── README.md                   # Complete architectural and operational documentation
├── demo.py                     # Standalone mock pipeline demonstration script
├── src/
│   └── w2_stt/
│       ├── __init__.py         # Package namespace export
│       ├── schemas.py          # Data models: TranscriptSegment, TranscriptEvent, TranscriptErrorInfo
│       ├── adapter.py          # BaseTranscriptionAdapter (abstract provider-neutral interface)
│       ├── fake_transcriber.py # DeterministicFakeTranscriber (repeatable mock engine)
│       └── accumulator.py      # OrderedTranscriptAccumulator (ordering, interim replacement)
└── tests/
    ├── __init__.py
    ├── fixtures/
    │   ├── __init__.py
    │   └── sample_events.py    # Controlled test event & segment fixtures
    ├── test_schemas.py         # Schema constraint and boundary validation tests
    ├── test_adapter.py         # Abstract interface compliance tests
    ├── test_fake_transcriber.py# Determinism and mock transcription tests
    └── test_accumulator.py     # Ordering, interim replacement, duplicate handling tests
```

---

## 2. Core Components

### 2.1 Transcript Schemas (`w2_stt.schemas`)

* **`TranscriptSegment`**: Represents a bounded segment of transcribed speech.
  * `segment_id: str`: Unique, stable utterance identifier used for interim-to-final correlation.
  * `start_time: float`: Non-negative start offset in seconds ($t \ge 0.0$).
  * `end_time: float`: End offset in seconds ($t_{end} \ge t_{start}$).
  * `text: str`: Normalized transcribed speech content.
  * `confidence: float`: Normalized confidence score strictly bounded in $[0.0, 1.0]$.
  * `is_final: bool`: `True` for immutable final segments; `False` for tentative interims.
  * `language: str`: BCP-47 / ISO language code (default `'en-US'`).
  * `speaker_id: Optional[str]`: Optional diarization label.
  * *Validation*: Enforces non-negative timestamps, $end\_time \ge start\_time$, confidence boundaries, and non-empty text for final segments.

* **`TranscriptEvent`**: Standardized streaming event envelope emitted by adapters.
  * `event_id: str`: Unique UUID for tracing and deduplication.
  * `session_id: Optional[str]`: Connection or session identifier.
  * `event_type: TranscriptEventType`: Enum (`'interim'`, `'final'`, `'error'`).
  * `timestamp: float`: Epoch timestamp of event emission.
  * `segment: Optional[TranscriptSegment]`: Mandatory for interim and final events.
  * `error: Optional[TranscriptErrorInfo]`: Mandatory for error events.
  * `metadata: Dict[str, Any]`: Extensible key-value metadata.
  * *Validation*: Enforces event-type consistency (interim cannot be marked final; error events cannot contain segments).

* **`TranscriptErrorInfo`**:
  * `code: str`: Machine-readable error code (e.g. `'SIMULATED_TRANSCRIBER_ERROR'`).
  * `message: str`: Human-readable description.
  * `details: Optional[Dict[str, Any]]`: Optional diagnostic context.

### 2.2 Provider-Neutral Adapter (`w2_stt.adapter`)

* **`BaseTranscriptionAdapter`**: Pure abstract base class defining the contract:
  * `provider_name -> str`: Provider identification property.
  * `process_audio_chunk(chunk: bytes, context: Optional[dict]) -> List[TranscriptEvent]`: Primary chunk ingestion.
  * `flush() -> List[TranscriptEvent]`: Forces finalization of trailing interims upon stream close.
  * `reset() -> None`: Clears internal stream state for a new session.
  * `close() -> None`: Optional lifecycle hook for cleanup.

### 2.3 Deterministic Fake Transcriber (`w2_stt.fake_transcriber`)

* **`DeterministicFakeTranscriber`**:
  * Implements `BaseTranscriptionAdapter`.
  * Generates reproducible transcript events derived from a SHA-256 hash of audio chunk bytes and chunk sequence count.
  * Repeated runs with identical input chunks produce bit-for-bit identical events and confidence metrics.
  * Emits alternating interim and final events to simulate live streaming STT behavior.
  * Supports deterministic error injection via `error_on_chunk_index` parameter.
  * Supports scripted fixture replay via `scripted_events` parameter.

### 2.4 Ordered Transcript Accumulator (`w2_stt.accumulator`)

* **`OrderedTranscriptAccumulator`**:
  * **Interim Replacement**: Automatically purges and supersedes interim segments when the corresponding final segment arrives for that `segment_id`.
  * **Chronological Sorting**: Sorts segments by `(start_time, end_time, segment_id)`, ensuring out-of-order packet arrivals are placed into their correct chronological position.
  * **Idempotency**: Duplicate final segment updates do not duplicate text in the accumulated transcript.
  * **Late Interim Protection**: Stale interim segments arriving after a final segment has landed are discarded.
  * **Error Isolation**: Error events are recorded in an isolated error log without corrupting accumulated transcripts.
  * **Retrieval API**:
    * `get_segments(include_interim: bool = False) -> List[TranscriptSegment]`
    * `get_full_transcript(include_interim: bool = False, separator: str = " ") -> str`
    * `get_interim_segment() -> Optional[TranscriptSegment]`
    * `get_segment_by_id(segment_id: str) -> Optional[TranscriptSegment]`
    * `reset() -> None`

---

## 3. Installation & Setup

### Prerequisites

* Python 3.10+ (Python 3.12 recommended)
* `pip`

### Installation

Clone or open the workspace and install requirements:

```bash
# Set PYTHONPATH to include src
$env:PYTHONPATH = "src"

# Install dependencies (only pydantic is required)
pip install -r requirements.txt
```

---

## 4. Running the Tests

The test suite is built on Python's standard `unittest` framework (and is also fully compatible with `pytest`).

### Run via Standard Unittest (Built-in, zero dependencies required):

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run via Pytest (if installed):

```bash
pytest -v
```

---

## 5. Running the Mock Demonstration

To execute the end-to-end demonstration script:

```bash
python demo.py
```

The demo demonstrates:
1. Sequential audio chunk ingestion with live interim-to-final transitions.
2. Out-of-order segment arrival and chronological reconstruction.
3. Idempotent duplicate event handling.
4. Error event capture and state isolation.
5. Final consolidated transcript output and structured timeline.

---

## 6. Assumptions & Scope Boundaries

* **Isolated Module**: This implementation does not modify or overwrite any external workstream code.
* **No Network Calls / Paid APIs**: All components operate in offline mock mode. Real cloud provider integrations (e.g. Deepgram, Whisper API) are reserved for subsequent weeks.
* **Standard Audio Format**: Audio chunks are represented as `bytes` (e.g., PCM 16-bit 16kHz mono), matching common streaming standards.
