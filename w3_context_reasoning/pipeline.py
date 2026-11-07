"""
Integrated Context & Reasoning Pipeline for W3 Week 2.

Connects:
Opt-in Screen Capture
       ↓
Capture Validation
       ↓
OCR / Vision Extraction
       ↓
Bounded Context Builder
       ↓
Versioned Prompt Manager (Trust Separation)
       ↓
LLM Client Adapter (Timeouts & Retries)
       ↓
Structured Output & Grounding Validation
       ↓
Final Response
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .schemas import (
    ReasoningRequest,
    ReasoningResult,
    ScreenContext,
    SourceReference,
    ContextItem,
)
from .validation import (
    validate_request,
    validate_result,
    InvalidRequestError,
    InvalidResultError,
    GroundingError,
)
from .capture import (
    CaptureAdapter,
    SyntheticCaptureAdapter,
    CaptureConfig,
    CaptureValidator,
    CaptureConsentError,
    CaptureValidationError,
    CapturedFrame,
)
from .vision import (
    OCRVisionAdapter,
    MockOCRVisionAdapter,
    OCRResult,
    InvalidFrameError,
)
from .context_builder import (
    ContextBuilder,
    ContextBuilderConfig,
    BuiltContext,
)
from .prompts.manager import (
    PromptManager,
    RenderedPrompt,
)
from .llm_adapter import (
    LLMClientAdapter,
    MockLLMClient,
    LLMConfig,
    LLMClientError,
    LLMTimeoutError,
    LLMMalformedResponseError,
    LLMValidationError,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineExecutionMetadata:
    """Detailed trace metadata collected during pipeline execution."""
    pipeline_id: str
    request_id: str
    capture_occurred: bool = False
    ocr_occurred: bool = False
    tokens_budgeted: int = 0
    items_dropped_count: int = 0
    llm_attempts: int = 1
    duration_seconds: float = 0.0
    audit_trail: List[str] = field(default_factory=list)


class ContextReasoningPipeline:
    """
    End-to-end W3 Context & Reasoning Pipeline integrating capture, vision,
    context bounding, prompting, LLM invocation, and output validation.
    """

    def __init__(
        self,
        capture_adapter: Optional[CaptureAdapter] = None,
        capture_validator: Optional[CaptureValidator] = None,
        vision_adapter: Optional[OCRVisionAdapter] = None,
        context_builder: Optional[ContextBuilder] = None,
        prompt_manager: Optional[PromptManager] = None,
        llm_client: Optional[LLMClientAdapter] = None,
        safe_fallback_on_error: bool = True,
    ):
        self.capture_adapter = capture_adapter or SyntheticCaptureAdapter()
        self.capture_validator = capture_validator or CaptureValidator()
        self.vision_adapter = vision_adapter or MockOCRVisionAdapter()
        self.context_builder = context_builder or ContextBuilder()
        self.prompt_manager = prompt_manager or PromptManager()
        self.llm_client = llm_client or MockLLMClient()
        self.safe_fallback_on_error = safe_fallback_on_error

    def process(
        self,
        request: ReasoningRequest,
        capture_consent: bool = False,
        capture_scenario: Optional[str] = None,
    ) -> ReasoningResult:
        """
        Executes the full reasoning pipeline for a request.

        1. Validates input request.
        2. Optionally captures and extracts screen state if consent is granted.
        3. Bounds and ranks context items, references, and screen context.
        4. Renders prompt enforcing structural trust boundaries.
        5. Invokes LLM client with timeouts, retries, and JSON decoding.
        6. Validates output schema and grounding authenticity.
        7. Returns final ReasoningResult.
        """
        # 1. Strict input validation
        validate_request(request)

        audit: List[str] = [
            f"Pipeline start for request '{request.request_id}', session '{request.session_id}'."
        ]

        active_screen_context: Optional[ScreenContext] = request.screen_context

        # 2. Opt-in Capture & Vision Processing
        # Screen capture only occurs if explicit consent is provided
        if capture_consent:
            audit.append("Explicit capture consent provided; invoking capture adapter.")
            self.capture_adapter.set_consent(True)
            try:
                # Capture synthetic frame
                frame: CapturedFrame = self.capture_adapter.capture(
                    active_window=(
                        request.screen_context.active_window_title
                        if request.screen_context
                        else None
                    ),
                    scenario=capture_scenario or "binary_search_tree",
                )
                audit.append(f"Captured synthetic frame '{frame.frame_id}' ({frame.width}x{frame.height}).")

                # Validate frame
                self.capture_validator.validate_frame(frame, self.capture_adapter.config)

                # OCR / Vision extraction
                ocr_result: OCRResult = self.vision_adapter.extract_text(frame)
                active_screen_context = ocr_result.to_screen_context(capture_enabled=True)
                audit.append(
                    f"OCR extracted text (confidence: {ocr_result.confidence_score:.2f}) from frame '{frame.frame_id}'."
                )

            except Exception as cap_err:
                audit.append(f"Capture/Vision step encountered error: {cap_err}")
                if not self.safe_fallback_on_error:
                    raise
        else:
            # When consent is not granted, ensure capture_enabled is False
            if active_screen_context and active_screen_context.capture_enabled:
                raise CaptureConsentError(
                    "ScreenContext requested capture_enabled=True but pipeline capture_consent was not granted."
                )
            audit.append("Screen capture disabled (consent not granted).")

        # 3. Bounded Context Building
        built_context: BuiltContext = self.context_builder.build_context(
            user_query=request.user_query,
            context_items=request.context_items,
            source_references=request.source_references,
            screen_context=active_screen_context,
        )
        audit.extend(built_context.audit_log)

        # Assemble bounded ReasoningRequest
        bounded_request = ReasoningRequest(
            request_id=request.request_id,
            session_id=request.session_id,
            user_query=request.user_query,
            screen_context=built_context.screen_context,
            context_items=built_context.selected_context_items,
            source_references=built_context.selected_source_references,
            prompt_version=request.prompt_version,
            parameters=request.parameters,
        )

        # 4. Render versioned prompt with structural trust isolation
        rendered_prompt: RenderedPrompt = self.prompt_manager.render_prompt(bounded_request)
        audit.append(f"Rendered prompt version '{rendered_prompt.version}' with trust boundaries.")

        # 5. Invoke LLM Client Adapter with retries and timeout management
        try:
            result = self.llm_client.generate_reasoning_result(
                request=bounded_request,
                rendered_prompt=rendered_prompt,
            )
            audit.append(f"LLM generated response with status '{result.status}'.")

            # 6. Validate output schema and grounding
            validate_result(result, original_request=request)
            audit.append("Output validated successfully against schema and grounding authenticity.")

            # Append pipeline audit trace to result steps
            updated_steps = list(result.reasoning_steps) + [
                f"Pipeline: {entry}" for entry in audit if "Pipeline" not in entry and "ContextBuilder" not in entry
            ]
            result.reasoning_steps = updated_steps

            return result

        except Exception as llm_err:
            audit.append(f"LLM/Validation failure: {llm_err}")
            if not self.safe_fallback_on_error:
                raise

            # Graceful fallback response when LLM or validation fails in safe mode
            fallback_result = ReasoningResult(
                result_id=f"RES-{request.request_id.replace('REQ-', '')}",
                request_id=request.request_id,
                status="error",
                response_text=(
                    f"A system error occurred during reasoning processing: {str(llm_err)}. "
                    "The request has been safely halted without crashing."
                ),
                grounded_sources=[],
                confidence_score=0.0,
                intent="general_qa",
                reasoning_steps=audit + [f"Fallback triggered due to error: {type(llm_err).__name__}"],
                prompt_version=request.prompt_version,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            return fallback_result
