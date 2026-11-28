"""
Validation layer for W3 Context & Reasoning requests and results.
"""

from __future__ import annotations

from typing import Optional, Set
from .schemas import ReasoningRequest, ReasoningResult, SourceReference, ContextItem, ScreenContext


class ValidationError(Exception):
    """Base class for all W3 validation errors."""
    pass


class InvalidRequestError(ValidationError):
    """Raised when an incoming ReasoningRequest fails schema validation."""
    pass


class InvalidResultError(ValidationError):
    """Raised when an outgoing ReasoningResult fails schema validation."""
    pass


class GroundingError(ValidationError):
    """Raised when reasoning output references sources not present in the request."""
    pass


ALLOWED_STATUSES = {"success", "clarification_needed", "error", "unsupported"}
ALLOWED_SOURCE_TYPES = {"textbook", "slide", "code", "syllabus", "transcript", "reference"}


def validate_source_reference(ref: SourceReference, index: int) -> None:
    """Validates an individual SourceReference."""
    if not isinstance(ref, SourceReference):
        raise InvalidRequestError(f"source_references[{index}] must be a SourceReference instance.")
    if not ref.source_id or not ref.source_id.strip():
        raise InvalidRequestError(f"source_references[{index}].source_id must not be empty.")
    if not ref.title or not ref.title.strip():
        raise InvalidRequestError(f"source_references[{index}].title must not be empty.")
    if not ref.snippet or not ref.snippet.strip():
        raise InvalidRequestError(f"source_references[{index}].snippet must not be empty.")
    if not (0.0 <= ref.relevance_score <= 1.0):
        raise InvalidRequestError(
            f"source_references[{index}].relevance_score ({ref.relevance_score}) must be between 0.0 and 1.0."
        )


def validate_context_item(item: ContextItem, index: int) -> None:
    """Validates an individual ContextItem."""
    if not isinstance(item, ContextItem):
        raise InvalidRequestError(f"context_items[{index}] must be a ContextItem instance.")
    if not item.item_id or not item.item_id.strip():
        raise InvalidRequestError(f"context_items[{index}].item_id must not be empty.")
    if not item.content or not item.content.strip():
        raise InvalidRequestError(f"context_items[{index}].content must not be empty.")


def validate_screen_context(screen: ScreenContext) -> None:
    """Validates ScreenContext and enforces safe capture defaults."""
    if not isinstance(screen, ScreenContext):
        raise InvalidRequestError("screen_context must be a ScreenContext instance.")
    # Safe demonstration requirement: Real screen capture is prohibited in mock mode
    if screen.capture_enabled and not screen.synthetic:
        raise InvalidRequestError(
            "Live screen capture is not permitted in mock mode. Use synthetic frames (synthetic=True) only."
        )


def validate_request(request: ReasoningRequest) -> None:
    """
    Validates an incoming ReasoningRequest against W3 contracts.

    Raises:
        InvalidRequestError: If any required field is missing or invalid.
    """
    if not isinstance(request, ReasoningRequest):
        raise InvalidRequestError("Request must be an instance of ReasoningRequest.")

    if not request.request_id or not request.request_id.strip():
        raise InvalidRequestError("Field 'request_id' must be a non-empty string.")

    if not request.session_id or not request.session_id.strip():
        raise InvalidRequestError("Field 'session_id' must be a non-empty string.")

    if not request.user_query or not request.user_query.strip():
        raise InvalidRequestError("Field 'user_query' must be a non-empty string.")

    if not request.prompt_version or not request.prompt_version.strip():
        raise InvalidRequestError("Field 'prompt_version' must be a non-empty string.")

    if request.screen_context is not None:
        validate_screen_context(request.screen_context)

    for idx, item in enumerate(request.context_items):
        validate_context_item(item, idx)

    for idx, ref in enumerate(request.source_references):
        validate_source_reference(ref, idx)


def validate_result(result: ReasoningResult, original_request: Optional[ReasoningRequest] = None) -> None:
    """
    Validates an outgoing ReasoningResult against W3 contracts.

    Raises:
        InvalidResultError: If any required result field is missing or invalid.
        GroundingError: If grounded_sources refers to sources absent from original_request.
    """
    if not isinstance(result, ReasoningResult):
        raise InvalidResultError("Result must be an instance of ReasoningResult.")

    if not result.result_id or not result.result_id.strip():
        raise InvalidResultError("Field 'result_id' must be a non-empty string.")

    if not result.request_id or not result.request_id.strip():
        raise InvalidResultError("Field 'request_id' must be a non-empty string.")

    if result.status not in ALLOWED_STATUSES:
        raise InvalidResultError(
            f"Field 'status' must be one of {ALLOWED_STATUSES}, got '{result.status}'."
        )

    if not (0.0 <= result.confidence_score <= 1.0):
        raise InvalidResultError(
            f"Field 'confidence_score' ({result.confidence_score}) must be between 0.0 and 1.0."
        )

    if result.status == "success" and (not result.response_text or not result.response_text.strip()):
        raise InvalidResultError("Field 'response_text' cannot be empty when status is 'success'.")

    # If original request is provided, verify request_id linkage and grounding authenticity
    if original_request is not None:
        if result.request_id != original_request.request_id:
            raise InvalidResultError(
                f"Result request_id '{result.request_id}' does not match original request_id '{original_request.request_id}'."
            )

        valid_source_ids: Set[str] = {ref.source_id for ref in original_request.source_references}
        # Screen context frame_id can also be a valid grounded source if present
        if original_request.screen_context and original_request.screen_context.frame_id:
            valid_source_ids.add(original_request.screen_context.frame_id)

        for source_id in result.grounded_sources:
            if source_id not in valid_source_ids:
                raise GroundingError(
                    f"Grounded source '{source_id}' is not in the request's supplied source references: {valid_source_ids}."
                )
