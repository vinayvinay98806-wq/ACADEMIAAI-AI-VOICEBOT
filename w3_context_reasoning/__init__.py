"""
AcademiaAI AI Voice Co-Pilot - Worker 3 (W3): Context & Reasoning
Week 1 & Week 2 Implementation.

This module provides data models, deterministic mock reasoning, versioned prompt
management, validation, synthetic demonstration fixtures, opt-in capture adapter,
OCR/Vision extraction, bounded context builder, LLM client adapter, and end-to-end pipeline.
"""

from .schemas import (
    ScreenContext,
    ContextItem,
    SourceReference,
    ReasoningRequest,
    ReasoningResult,
)
from .validation import (
    ValidationError,
    InvalidRequestError,
    InvalidResultError,
    GroundingError,
    validate_request,
    validate_result,
)
from .engine import DeterministicMockReasoningEngine
from .prompts.manager import PromptManager, RenderedPrompt
from .fixtures import (
    create_synthetic_screen_context,
    create_sample_context_items,
    create_sample_source_references,
    create_sample_reasoning_request,
    SYNTHETIC_SCREENS,
)
from .capture import (
    CaptureAdapter,
    SyntheticCaptureAdapter,
    CaptureConfig,
    CapturedFrame,
    CaptureValidator,
    CaptureError,
    CaptureConsentError,
    CaptureValidationError,
    SamplingRateExceededError,
)
from .vision import (
    OCRVisionAdapter,
    MockOCRVisionAdapter,
    OCRResult,
    VisionError,
    InvalidFrameError,
    ExtractionError,
)
from .context_builder import (
    ContextBuilder,
    ContextBuilderConfig,
    BuiltContext,
    tokenize_text,
)
from .llm_adapter import (
    LLMClientAdapter,
    MockLLMClient,
    LLMConfig,
    LLMRequest,
    LLMResponse,
    LLMClientError,
    LLMTimeoutError,
    LLMMalformedResponseError,
    LLMValidationError,
    MaxRetriesExceededError,
)
from .pipeline import ContextReasoningPipeline

__all__ = [
    # Schemas
    "ScreenContext",
    "ContextItem",
    "SourceReference",
    "ReasoningRequest",
    "ReasoningResult",
    # Validation
    "ValidationError",
    "InvalidRequestError",
    "InvalidResultError",
    "GroundingError",
    "validate_request",
    "validate_result",
    # Engine & Prompts
    "DeterministicMockReasoningEngine",
    "PromptManager",
    "RenderedPrompt",
    # Fixtures
    "create_synthetic_screen_context",
    "create_sample_context_items",
    "create_sample_source_references",
    "create_sample_reasoning_request",
    "SYNTHETIC_SCREENS",
    # Capture (Week 2)
    "CaptureAdapter",
    "SyntheticCaptureAdapter",
    "CaptureConfig",
    "CapturedFrame",
    "CaptureValidator",
    "CaptureError",
    "CaptureConsentError",
    "CaptureValidationError",
    "SamplingRateExceededError",
    # Vision (Week 2)
    "OCRVisionAdapter",
    "MockOCRVisionAdapter",
    "OCRResult",
    "VisionError",
    "InvalidFrameError",
    "ExtractionError",
    # Context Builder (Week 2)
    "ContextBuilder",
    "ContextBuilderConfig",
    "BuiltContext",
    "tokenize_text",
    # LLM Adapter (Week 2)
    "LLMClientAdapter",
    "MockLLMClient",
    "LLMConfig",
    "LLMRequest",
    "LLMResponse",
    "LLMClientError",
    "LLMTimeoutError",
    "LLMMalformedResponseError",
    "LLMValidationError",
    "MaxRetriesExceededError",
    # Pipeline (Week 2)
    "ContextReasoningPipeline",
]
