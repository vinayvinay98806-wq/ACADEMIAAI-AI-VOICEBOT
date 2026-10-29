"""
AcademiaAI AI Voice Co-Pilot - Worker 3 (W3): Context & Reasoning
Week 1 Milestone Implementation.

This module provides data models, deterministic mock reasoning, versioned prompt
management, validation, and synthetic demonstration fixtures for W3.
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
from .prompts.manager import PromptManager
from .fixtures import (
    create_synthetic_screen_context,
    create_sample_context_items,
    create_sample_source_references,
    create_sample_reasoning_request,
)

__all__ = [
    "ScreenContext",
    "ContextItem",
    "SourceReference",
    "ReasoningRequest",
    "ReasoningResult",
    "ValidationError",
    "InvalidRequestError",
    "InvalidResultError",
    "GroundingError",
    "validate_request",
    "validate_result",
    "DeterministicMockReasoningEngine",
    "PromptManager",
    "create_synthetic_screen_context",
    "create_sample_context_items",
    "create_sample_source_references",
    "create_sample_reasoning_request",
]
