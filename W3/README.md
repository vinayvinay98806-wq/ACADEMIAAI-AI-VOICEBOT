# AcademiaAI AI Voice Co-Pilot: Worker 3 (W3) – Context & Reasoning

**Module:** `w3_context_reasoning`
**Milestone:** Week 1 Local Development
**Execution Mode:** 100% Offline / Deterministic Mock Mode (No external API keys or network calls required)

---

## 1. Overview

Worker 3 (W3) is the **Context & Reasoning** component of the **AcademiaAI AI Voice Co-Pilot** system. It is responsible for:
- Maintaining structured conversational, student, and screen context.
- Validating incoming requests and outgoing reasoning decisions.
- Structurally isolating trusted system instructions from untrusted user and retrieved context.
- Performing grounded reasoning using academic references (lecture slides, textbook sections, syllabus, code).
- Emitting explainable, confidence-scored, schema-validated reasoning results to downstream components (e.g., W2 Orchestration, W4 TTS).

---

## 2. Architecture & Schemas

The data contracts in `w3_context_reasoning/schemas.py` define the interaction contracts:

| Schema | Purpose | Key Attributes / Guarantees |
| :--- | :--- | :--- |
| `ScreenContext` | Context derived from visual screen state | `capture_enabled: bool = False` (default disabled), `synthetic: bool = True`, `ocr_extracted_text`, `active_window_title`. |
| `ContextItem` | Dialogue turns, student profile, environment | `item_id`, `category`, `content`, `untrusted: bool = True` (isolated in prompts). |
| `SourceReference` | Grounded academic materials | `source_id`, `title`, `snippet`, `uri_or_path`, `relevance_score` (0.0 to 1.0), `source_type`. |
| `ReasoningRequest` | Input contract consumed by W3 | `request_id`, `session_id`, `user_query`, `screen_context`, `context_items`, `source_references`, `prompt_version`. |
| `ReasoningResult` | Output contract emitted by W3 | `result_id`, `request_id`, `status`, `response_text`, `grounded_sources`, `confidence_score` (0.0 to 1.0), `intent`, `reasoning_steps`. |

---

## 3. Safety & Trust Boundaries

1. **Safe Capture Defaults:**
   * `ScreenContext.capture_enabled` defaults to `False`. Real screen recording, webcam capture, or student PII collection is prohibited.
   * Testing and demonstrations strictly utilize synthetic academic fixtures (`w3_context_reasoning/fixtures.py`).
2. **Structural Prompt Isolation:**
   * Prompts are managed via `PromptManager` (`w3_context_reasoning/prompts/manager.py`).
   * System directives are enclosed within `<trusted_system_instruction>`.
   * User queries and retrieved references are enclosed within `<untrusted_student_query>`, `<untrusted_screen_context>`, and `<untrusted_source_references>`.
   * Delimiter sanitization prevents prompt injection or escape attempts.
3. **Grounding Verification:**
   * Output responses cite the specific `source_id`s used.
   * `validate_result` ensures that any cited source in `grounded_sources` exists within the request's supplied `source_references`.

---

## 4. Directory Structure

```
Harsha V1/
├── README.md                          # Project documentation
├── AGENTS.md                          # Contributor instructions & ownership contracts
├── demo.py                            # Standalone runnable demonstration script
├── w3_context_reasoning/              # W3 core package
│   ├── __init__.py                    # Public exports
│   ├── schemas.py                     # Data contracts (ScreenContext, ReasoningRequest, etc.)
│   ├── validation.py                  # Strict schema validators & custom exceptions
│   ├── engine.py                      # Deterministic mock reasoning engine
│   ├── fixtures.py                    # Safe synthetic frames & demonstration fixtures
│   └── prompts/                       # Versioned prompt management
│       ├── __init__.py
│       ├── manager.py                 # PromptManager with structural trust separation
│       └── v1/
│           ├── system_prompt.txt      # v1 trusted system instructions
│           └── template.json          # v1 metadata & variable specifications
└── tests/                             # Comprehensive unit test suite
    ├── __init__.py
    ├── test_schemas.py                # Schema serialization & default values
    ├── test_validation.py             # Validation checks & error handling
    ├── test_mock_reasoning.py         # Determinism, grounding, & edge cases
    ├── test_prompt_versioning.py      # Version management & prompt injection defense
    └── test_safe_capture_defaults.py  # Safe screen capture defaults & synthetic checks
```

---

## 5. Running the Tests & Demonstration

### Prerequisites
* Python 3.10+ (Tested on Python 3.13.5).
* Standard library only (no external pip dependencies required).

### Execute Unit Tests
```bash
py -m unittest discover tests
```

### Run Demonstration
```bash
py demo.py
```
