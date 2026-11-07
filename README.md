# AcademiaAI AI Voice Co-Pilot: Worker 3 (W3) – Context & Reasoning

**Module:** `w3_context_reasoning`  
**Milestones:** Week 1 & Week 2 Implementation  
**Assignment:** Opt-in Capture, Context Builder & LLM Adapter  
**Execution Mode:** 100% Offline / Deterministic Mock Mode (Zero external API keys or network calls required)

---

## 1. Project Overview

Worker 3 (W3) is the **Context & Reasoning** module of the **AcademiaAI AI Voice Co-Pilot** system. It operates between upstream orchestrators (W1 STT, W2 Orchestrator) and downstream synthesizers (W4 TTS).

### Core Responsibilities:
1. **Safe Opt-In Screen Capture:** Captures visual screen context exclusively with explicit user consent and strict dimension/sampling limits.
2. **OCR / Vision Processing:** Extracts structured text, line items, and confidence metrics from captured frames without third-party cloud dependencies.
3. **Bounded Context Building:** Selects, deduplicates, filters stale data, ranks by recency and relevance, and enforces strict token budgets.
4. **Prompt Trust Separation:** Structurally encapsulates system directives in `<trusted_system_instruction>` tags and separates untrusted user queries and retrieved snippets.
5. **LLM Client Adapter:** Dispatches structured requests to LLM providers with automatic timeout handling, exponential retry policies, and schema validation.
6. **Grounding Verification:** Enforces that every cited source in `grounded_sources` exists within the request or active frame.

---

## 2. Week 2 Architecture & Pipeline Flow

The integrated Week 2 reasoning pipeline connects seven modular stages:

```
+--------------------------------------------------------------------------+
|                        Opt-in Screen Capture                             |
|       (Default disabled; requires explicit consent; synthetic-only)      |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                          Capture Validator                               |
|        (Consent check, sampling rate limits, dimensions, max bytes)      |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                         OCR / Vision Adapter                             |
|          (Structured text extraction, line tokens, confidence score)      |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                        Bounded Context Builder                           |
|       (Recency scoring, relevance ranking, deduplication, stale TTL,     |
|                         strict token budgeting)                          |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                       Versioned Prompt Manager                           |
|            (Structural trust separation with tag sanitization)           |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                         LLM Client Adapter                               |
|          (Timeout handling, configurable retries, JSON parsing)          |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                     Structured Output Validation                         |
|         (validate_result: status enum, confidence, source grounding)      |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                            Final Response                                |
|                        (ReasoningResult schema)                          |
+--------------------------------------------------------------------------+
```

---

## 3. Key Components & Interfaces

### A. Opt-in Capture Adapter (`w3_context_reasoning/capture.py`)
- `CaptureConfig`: Configuration with `consent_granted: bool = False` (default), `sampling_interval_seconds: float = 2.0`, `max_width: int = 1920`, `max_height: int = 1080`, `max_size_bytes: int = 5_000_000`, `allow_synthetic_only: bool = True`.
- `CapturedFrame`: Encapsulates frame payload, format, dimensions, timestamps, active window, and synthetic flags.
- `CaptureValidator`: Validates consent, frame dimensions, byte sizes, formats, and sampling rates.
- `SyntheticCaptureAdapter`: Generates and validates synthetic test frames for academic slide/code scenarios.
- Exceptions: `CaptureConsentError`, `CaptureValidationError`, `SamplingRateExceededError`.

### B. OCR / Vision Adapter (`w3_context_reasoning/vision.py`)
- `OCRVisionAdapter`: Abstract interface defining `extract_text(frame: CapturedFrame) -> OCRResult`.
- `MockOCRVisionAdapter`: Deterministic extractor parsing frame payloads, calculating confidence scores, and extracting lines.
- `OCRResult`: Structured extraction results (`extracted_text`, `confidence_score`, `lines`, `active_window`, `to_screen_context()`).
- Exceptions: `VisionError`, `InvalidFrameError`, `ExtractionError`.

### C. Bounded Context Builder (`w3_context_reasoning/context_builder.py`)
- `ContextBuilderConfig`: `max_token_budget: int = 1500`, `max_context_entries: int = 10`, `recency_threshold_seconds: float = 3600.0`, `relevance_threshold: float = 0.20`, `stale_context_threshold_seconds: float = 7200.0`, `approx_chars_per_token: float = 4.0`.
- `ContextBuilder`: Implements deterministic token budgeting, recency scoring, relevance scoring via token overlap, deduplication, and stale data eviction.
- `BuiltContext`: Bounded items, source references, screen context, and audit log.

### D. LLM Client Adapter (`w3_context_reasoning/llm_adapter.py`)
- `LLMConfig`: `model_name: str`, `timeout_seconds: float = 2.0`, `max_retries: int = 2`, `retry_backoff_seconds: float = 0.02`, `mock_mode: bool = True`.
- `LLMClientAdapter`: Abstract client interface for LLM dispatch.
- `MockLLMClient`: Generates deterministic JSON responses matching `ReasoningResult` schemas, implements timeout handling, configurable retries, and strict schema validation.
- Exceptions: `LLMClientError`, `LLMTimeoutError`, `LLMMalformedResponseError`, `LLMValidationError`, `MaxRetriesExceededError`.

### E. Integrated Pipeline (`w3_context_reasoning/pipeline.py`)
- `ContextReasoningPipeline`: Orchestrates end-to-end execution from opt-in capture to validated reasoning result with graceful fallback error recovery.

---

## 4. Directory Structure

```
W3/
├── README.md                          # Comprehensive Week 1 & Week 2 documentation
├── AGENTS.md                          # Contributor boundaries & ownership contracts
├── demo.py                            # Standalone 8-scenario demonstration script
├── w3_context_reasoning/              # W3 core package
│   ├── __init__.py                    # Public exports (Week 1 + Week 2)
│   ├── schemas.py                     # Data contracts (ScreenContext, ReasoningRequest, etc.)
│   ├── validation.py                  # Strict schema validators & custom exceptions
│   ├── engine.py                      # Week 1 deterministic mock reasoning engine
│   ├── capture.py                     # Week 2 opt-in screen capture adapter & validator
│   ├── vision.py                      # Week 2 OCR/Vision adapter & OCRResult
│   ├── context_builder.py             # Week 2 bounded context builder & budgeting
│   ├── llm_adapter.py                 # Week 2 LLM client adapter with retries/timeouts
│   ├── pipeline.py                    # Week 2 end-to-end integrated reasoning pipeline
│   ├── fixtures.py                    # Safe synthetic frames & demonstration fixtures
│   └── prompts/                       # Versioned prompt management
│       ├── __init__.py
│       ├── manager.py                 # PromptManager with structural trust separation
│       └── v1/
│           ├── system_prompt.txt      # v1 trusted system instructions
│           └── template.json          # v1 metadata & variable specifications
└── tests/                             # Comprehensive test suite (64 tests)
    ├── __init__.py
    ├── test_schemas.py                # Schema serialization & default values
    ├── test_validation.py             # Validation checks & grounding enforcement
    ├── test_mock_reasoning.py         # Determinism, intent classification, fallbacks
    ├── test_prompt_versioning.py      # Version management & prompt injection defense
    ├── test_safe_capture_defaults.py  # Safe screen capture defaults & synthetic checks
    ├── test_capture_adapter.py        # Phase 7A: Consent, sampling, dimensions, limits
    ├── test_ocr_vision_adapter.py     # Phase 7B: Frame extraction, confidence, formats
    ├── test_context_builder.py        # Phase 7C: Recency, relevance, token budgeting, deduplication
    ├── test_llm_adapter.py            # Phase 7D: Retries, timeouts, malformed JSON, validation
    └── test_integration_pipeline.py   # Phase 7E: End-to-end pipeline, fallbacks, capture flows
```

---

## 5. Capture Consent & Safety Invariants

1. **Safe Capture Defaults:**
   - `CaptureConfig.consent_granted` defaults strictly to `False`.
   - `ScreenContext.capture_enabled` defaults strictly to `False`.
   - Attempting screen capture without explicit consent raises `CaptureConsentError`.
2. **Synthetic-Only Enforcement:**
   - Real desktop screen grabbing, webcam recording, or audio interception is strictly prohibited in mock mode.
   - Any live screen capture attempt without synthetic flags (`synthetic=True`) raises `CaptureValidationError` or `InvalidRequestError`.
3. **Data Retention & Privacy:**
   - Sensitive screen buffers are not persisted in memory longer than the immediate extraction step.
   - Stale context older than `stale_context_threshold_seconds` (2 hours) is purged automatically.

---

## 6. Installation & Prerequisites

- **Python Version:** Python 3.10+ (Tested with Python 3.13.5).
- **Dependencies:** Standard library only (`dataclasses`, `typing`, `json`, `time`, `datetime`, `re`, `math`, `uuid`, `unittest`).
- **External Network Access:** None required (100% offline).

---

## 7. Running the Tests

To run the complete automated test suite (all 64 unit and integration tests):

```bash
py -m unittest discover tests
```

To run individual test suites:

```bash
# Capture Adapter Tests (Phase 7A)
py -m unittest tests/test_capture_adapter.py

# OCR / Vision Tests (Phase 7B)
py -m unittest tests/test_ocr_vision_adapter.py

# Context Builder Tests (Phase 7C)
py -m unittest tests/test_context_builder.py

# LLM Adapter Tests (Phase 7D)
py -m unittest tests/test_llm_adapter.py

# Integration Pipeline Tests (Phase 7E)
py -m unittest tests/test_integration_pipeline.py

# Week 1 Backward-Compatibility Tests
py -m unittest tests/test_schemas.py tests/test_validation.py tests/test_mock_reasoning.py tests/test_prompt_versioning.py tests/test_safe_capture_defaults.py
```

---

## 8. Running the Demonstration

To execute the runnable demonstration showcasing all 8 scenarios:

```bash
py demo.py
```

### Demonstration Scenarios Covered:
1. **Scenario 1:** Screen capture disabled by default (raises `CaptureConsentError`).
2. **Scenario 2:** Explicitly enabled synthetic capture with full metadata verification.
3. **Scenario 3:** OCR/Vision mock processing with structured line extraction and confidence scores.
4. **Scenario 4:** Context selection based on relevance and recency scoring.
5. **Scenario 5:** Token-budget enforcement with strict bounds checking.
6. **Scenario 6:** Successful mock LLM response with grounded academic citations.
7. **Scenario 7:** Timeout and retry handling with automatic recovery on retry.
8. **Scenario 8:** Malformed output handling with safe error fallback without crashing.

---

## 9. Configuration Options

| Class | Parameter | Default | Description |
| :--- | :--- | :--- | :--- |
| `CaptureConfig` | `consent_granted` | `False` | Explicit user opt-in required for screen capture |
| `CaptureConfig` | `sampling_interval_seconds` | `2.0` | Minimum elapsed seconds between captures |
| `CaptureConfig` | `max_width` | `1920` | Maximum allowed frame width in pixels |
| `CaptureConfig` | `max_height` | `1080` | Maximum allowed frame height in pixels |
| `CaptureConfig` | `max_size_bytes` | `5,000,000` | Maximum allowed frame payload size (5 MB) |
| `CaptureConfig` | `allow_synthetic_only` | `True` | Prohibits live desktop capture |
| `ContextBuilderConfig` | `max_token_budget` | `1500` | Strict token budget ceiling for reasoning prompt |
| `ContextBuilderConfig` | `max_context_entries` | `10` | Maximum number of context items retained |
| `ContextBuilderConfig` | `recency_threshold_seconds` | `3600.0` | Time window (1 hour) for recency scoring |
| `ContextBuilderConfig` | `relevance_threshold` | `0.20` | Minimum relevance score to avoid pruning |
| `ContextBuilderConfig` | `stale_context_threshold_seconds` | `7200.0` | Items older than 2 hours are discarded as stale |
| `LLMConfig` | `timeout_seconds` | `2.0` | Per-request inference timeout limit |
| `LLMConfig` | `max_retries` | `2` | Number of retry attempts on transient failure |
| `LLMConfig` | `retry_backoff_seconds` | `0.02` | Sleep interval between retry attempts |
| `LLMConfig` | `mock_mode` | `True` | Offline deterministic execution without cloud APIs |

---

## 10. Known Limitations

1. **Deterministic Mock Inference:** LLM responses are generated using deterministic mock logic based on token overlaps and curated academic fixtures. Pluggable `LLMClientAdapter` interface is ready for live models when API keys and network permissions are configured.
2. **Synthetic Frames Only:** Desktop capturing is mocked using synthetic frame payloads to ensure 100% privacy compliance and prevent unintended capture of student PII.
3. **Token Approximation:** Uses standard character-based heuristic (`ceil(chars / 4.0)`). When integrating real models (e.g., Gemini or OpenAI), a BPE tokenizer (e.g. `tiktoken`) may be substituted.
