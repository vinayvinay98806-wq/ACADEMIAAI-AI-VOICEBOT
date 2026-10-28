# Academiaai AI Voice Co-Pilot

## Worker 1 (W1): Audio Input & Voice Activity Detection (VAD)

This directory contains the Week 1 implementation for **Worker 1 (W1)** of the Academiaai AI Voice Co-Pilot project.

### Week 1 Scope Overview

- **Days 1–2 (Data Contracts & Schemas):**
  - `AudioFormat`: Enforces sample-rate validation against standard speech rates (e.g. 16kHz default) and channel validation (mono/stereo).
  - `AudioChunk`: Atomic payload unit containing raw PCM bytes, format metadata, strictly monotonic `sequence_id`, and exact stream timestamp `timestamp_ms`.
  - `AudioError` Hierarchy: Structured exceptions (`AudioFormatError`, `AudioChunkError`, `EmptyChunkError`, `CorruptChunkError`).
- **Days 3–4 (Mock Sources & Chunker):**
  - `FakeMicrophoneSource`: Synthetic deterministic audio generator supporting sine waves, silence, seeded white noise, and speech-like cadences without hardware/driver dependencies.
  - `DeterministicChunker`: Stream buffer slicer transforming arbitrary incoming byte buffers into validated, aligned `AudioChunk` packets with continuous timestamps and sequence IDs.
- **Days 5–6 (CLI Demo & Validation Testing):**
  - CLI Demo (`academiaai.audio.cli`): Command-line tool to test audio streaming and inspect chunk metadata.
  - Comprehensive Unit Test Suite covering valid operations as well as invalid, empty, and corrupt chunk scenarios.
- **Day 7 (PR Readiness & Test Documentation):**
  - Clean modular architecture, complete documentation, and reproducible test suite.

---

### Project Structure

```text
ACADEMIAAI-AI-VOICEBOT/
├── pyproject.toml
├── README.md
├── PULL_REQUEST.md
├── .gitignore
├── src/
│   └── academiaai/
│       ├── __init__.py
│       └── audio/
│           ├── __init__.py
│           ├── schemas.py      # AudioFormat, AudioChunk, AudioError hierarchy
│           ├── sources.py      # DeterministicChunker, FakeMicrophoneSource, SignalType
│           └── cli.py          # Interactive CLI demo & validation runner
└── tests/
    ├── __init__.py
    └── test_audio/
        ├── __init__.py
        ├── test_schemas.py     # Schema and parameter validation tests
        ├── test_sources.py     # Deterministic chunking & source tests
        └── test_edge_cases.py  # Invalid, empty, and corrupt chunk tests
```

---

### Quick Start

#### 1. Running Unit Tests

Execute the full deterministic test suite with Python's built-in `unittest`:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

#### 2. Running the CLI Demo

Generate 10 chunks of synthetic speech-like audio at 16kHz mono:

```powershell
$env:PYTHONPATH="src"
python -m academiaai.audio.cli --signal speech_like --chunks 10 --verbose
```

Demonstrate error handling for invalid formats, corrupt chunks, and empty payloads:

```powershell
$env:PYTHONPATH="src"
python -m academiaai.audio.cli --test-invalid
```

Available CLI arguments:
- `--signal`: Synthetic signal (`sine_wave`, `silence`, `white_noise`, `speech_like`)
- `--chunks`: Number of chunks to produce (default: 15)
- `--chunk-duration-ms`: Duration per chunk in ms (default: 20.0)
- `--sample-rate`: Sample rate in Hz (default: 16000)
- `--channels`: Channels (default: 1)
- `--frequency`: Tone frequency in Hz (default: 440.0)
- `--amplitude`: Amplitude scale 0.0 to 1.0 (default: 0.5)
- `--seed`: Seed for reproducible white noise (default: 42)
- `--verbose`: Detailed output for all chunks
- `--test-invalid`: Explicit demonstration of error handling
