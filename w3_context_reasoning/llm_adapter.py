"""
LLM Client Adapter for W3 Context & Reasoning.

Provides a modular LLM adapter interface supporting timeout handling, configurable retries,
JSON payload parsing, and strict schema & grounding validation.
Defaults to 100% offline MockLLMClient requiring zero API keys or external network calls.
"""

from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .schemas import ReasoningRequest, ReasoningResult, SourceReference, ScreenContext, ContextItem
from .validation import validate_result, InvalidResultError, GroundingError
from .prompts.manager import RenderedPrompt


class LLMClientError(Exception):
    """Base exception for all LLM client errors."""
    pass


class LLMTimeoutError(LLMClientError):
    """Raised when an LLM inference request exceeds the configured timeout."""
    pass


class LLMMalformedResponseError(LLMClientError):
    """Raised when an LLM returns unparseable or non-JSON content."""
    pass


class LLMValidationError(LLMClientError):
    """Raised when an LLM structured response fails schema or grounding validation."""
    pass


class MaxRetriesExceededError(LLMClientError):
    """Raised when request attempts exhaust the configured retry budget."""
    pass


@dataclass
class LLMConfig:
    """
    Configuration governing LLM adapter execution and reliability policies.
    """
    model_name: str = "mock-academic-llm-v1"
    timeout_seconds: float = 2.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.02
    temperature: float = 0.0
    mock_mode: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LLMConfig:
        return cls(
            model_name=data.get("model_name", "mock-academic-llm-v1"),
            timeout_seconds=float(data.get("timeout_seconds", 2.0)),
            max_retries=int(data.get("max_retries", 2)),
            retry_backoff_seconds=float(data.get("retry_backoff_seconds", 0.02)),
            temperature=float(data.get("temperature", 0.0)),
            mock_mode=bool(data.get("mock_mode", True)),
        )


@dataclass
class LLMRequest:
    """
    Standard request payload dispatched to an LLM client.
    """
    request_id: str
    session_id: str
    rendered_prompt: str
    prompt_version: str = "v1"
    user_query: str = ""
    source_references: List[SourceReference] = field(default_factory=list)
    screen_context: Optional[ScreenContext] = None
    context_items: List[ContextItem] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Optional[float] = None

    @classmethod
    def from_reasoning_request(
        cls, request: ReasoningRequest, rendered: RenderedPrompt, timeout: Optional[float] = None
    ) -> LLMRequest:
        return cls(
            request_id=request.request_id,
            session_id=request.session_id,
            rendered_prompt=rendered.full_prompt,
            prompt_version=rendered.version,
            user_query=request.user_query,
            source_references=request.source_references,
            screen_context=request.screen_context,
            context_items=request.context_items,
            parameters=request.parameters,
            timeout_seconds=timeout,
        )


@dataclass
class LLMResponse:
    """
    Standard response payload received from an LLM client.
    """
    raw_text: str
    structured_output: Optional[Dict[str, Any]] = None
    reasoning_result: Optional[ReasoningResult] = None
    latency_seconds: float = 0.0
    model: str = "mock-academic-llm-v1"
    attempts: int = 1
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "structured_output": self.structured_output,
            "reasoning_result": self.reasoning_result.to_dict() if self.reasoning_result else None,
            "latency_seconds": self.latency_seconds,
            "model": self.model,
            "attempts": self.attempts,
            "success": self.success,
            "error_message": self.error_message,
        }


class LLMClientAdapter(ABC):
    """
    Abstract interface for LLM client adapters.
    Provides standard inference, retries, and output validation hooks.
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Dispatches an inference request to the underlying model with retry logic."""
        pass

    @abstractmethod
    def generate_reasoning_result(
        self, request: ReasoningRequest, rendered_prompt: RenderedPrompt
    ) -> ReasoningResult:
        """High-level call returning a schema-validated ReasoningResult."""
        pass


class MockLLMClient(LLMClientAdapter):
    """
    Deterministic mock LLM adapter implementing complete Week 2 contracts.
    Simulates timeouts, retries, malformed outputs, and strict schema validation
    100% offline without external network calls or paid API keys.
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        force_timeout: bool = False,
        force_malformed_json: bool = False,
        force_missing_fields: bool = False,
        force_invalid_status: bool = False,
        force_ungrounded_source: bool = False,
        simulated_timeout_count: int = 0,
        simulated_malformed_count: int = 0,
    ):
        super().__init__(config=config)
        self.force_timeout = force_timeout
        self.force_malformed_json = force_malformed_json
        self.force_missing_fields = force_missing_fields
        self.force_invalid_status = force_invalid_status
        self.force_ungrounded_source = force_ungrounded_source
        self.simulated_timeout_count = simulated_timeout_count
        self.simulated_malformed_count = simulated_malformed_count
        self._total_calls_received: int = 0

    def _simulate_raw_generation(self, request: LLMRequest, attempt: int) -> str:
        """
        Simulates raw model string generation (JSON payload formatted as LLM text).
        """
        # 1. Simulate timeout triggers
        if self.force_timeout:
            raise LLMTimeoutError(f"Simulated request timeout after {self.config.timeout_seconds:.2f}s.")

        if self.simulated_timeout_count > 0:
            self.simulated_timeout_count -= 1
            raise LLMTimeoutError(
                f"Transient timeout on attempt {attempt} after {self.config.timeout_seconds:.2f}s."
            )

        # 2. Simulate malformed JSON triggers
        if self.force_malformed_json:
            return "<<SYSTEM_CORRUPT_OUTPUT: NON_JSON_PAYLOAD_RETURNED>>"

        if self.simulated_malformed_count > 0:
            self.simulated_malformed_count -= 1
            return "{ invalid_json: missing_quotes, bad_data: "

        # 3. Simulate invalid schema / missing fields
        if self.force_missing_fields:
            return json.dumps({
                "result_id": f"RES-{request.request_id}",
                # Missing request_id, status, response_text
                "confidence_score": 0.9,
            })

        if self.force_invalid_status:
            return json.dumps({
                "result_id": f"RES-{request.request_id}",
                "request_id": request.request_id,
                "status": "UNSUPPORTED_STATUS_ENUM_XYZ",
                "response_text": "Invalid status simulated.",
                "confidence_score": 0.95,
            })

        # 4. Normal deterministic structured generation
        q = request.user_query.lower()
        matched_sources: List[str] = []
        intent = "general_qa"
        confidence = 0.85
        status = "success"

        # Check for code debugging
        if any(w in q for w in ["debug", "error", "bug", "recursion", "factorial"]):
            intent = "debug_code"
            ref = next((r for r in request.source_references if "recursion" in r.snippet.lower() or "recursion" in r.title.lower()), None)
            if ref:
                matched_sources.append(ref.source_id)
                response_text = (
                    f"Based on our reference ({ref.title}), your recursive function is missing a base case. "
                    f"{ref.snippet} To fix this, add a stopping condition such as 'if n <= 1: return 1' before the recursive call."
                )
                confidence = 0.95
            else:
                response_text = "Your code requires a base case to terminate recursion properly."
        # Check for BST explain
        elif any(w in q for w in ["bst", "binary search tree", "complexity"]):
            intent = "explain_concept"
            ref = next((r for r in request.source_references if "bst" in r.source_id.lower() or "binary search" in r.title.lower()), None)
            if ref:
                matched_sources.append(ref.source_id)
                response_text = (
                    f"According to {ref.title}: {ref.snippet} This ordering property guarantees efficient search operations."
                )
                confidence = 0.96
            else:
                response_text = "A binary search tree maintains sorted ordering with O(log n) average search."
        # Check for screen context
        elif request.screen_context and request.screen_context.capture_enabled and request.screen_context.ocr_extracted_text:
            intent = "summarize_slide"
            if request.screen_context.frame_id:
                matched_sources.append(request.screen_context.frame_id)
            response_text = (
                f"From your active screen ({request.screen_context.active_window_title}): "
                f"{request.screen_context.ocr_extracted_text.strip()}"
            )
            confidence = 0.90
        # Check for general references
        elif request.source_references:
            ref = request.source_references[0]
            matched_sources.append(ref.source_id)
            response_text = f"Grounded in {ref.title}: {ref.snippet}"
            confidence = 0.88
        else:
            intent = "clarification"
            status = "clarification_needed"
            confidence = 0.40
            response_text = (
                "I need clarification to answer this query with sufficient academic confidence because "
                "no relevant course references or textbook materials were found in the current session context."
            )

        if self.force_ungrounded_source:
            matched_sources.append("HALLUCINATED-SOURCE-REF-999")

        payload = {
            "result_id": f"RES-{request.request_id.replace('REQ-', '')}",
            "request_id": request.request_id,
            "status": status,
            "response_text": response_text,
            "grounded_sources": matched_sources,
            "confidence_score": confidence,
            "intent": intent,
            "reasoning_steps": [
                f"MockLLM: processed prompt version {request.prompt_version}.",
                f"MockLLM: identified intent '{intent}' on attempt {attempt}.",
                f"MockLLM: grounded against sources {matched_sources}.",
            ],
            "prompt_version": request.prompt_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        return json.dumps(payload)

    def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Executes request with timeout handling and configurable retries.
        """
        self._total_calls_received += 1
        max_attempts = self.config.max_retries + 1
        last_error: Optional[Exception] = None
        attempt = 0

        start_time = time.time()

        while attempt < max_attempts:
            attempt += 1
            try:
                raw_json = self._simulate_raw_generation(request, attempt=attempt)
                elapsed = time.time() - start_time

                # Parse JSON
                try:
                    data = json.loads(raw_json)
                except json.JSONDecodeError as jde:
                    raise LLMMalformedResponseError(
                        f"LLM returned malformed JSON on attempt {attempt}: {jde}. Raw payload: '{raw_json[:100]}'"
                    )

                # Validate dictionary fields
                if not isinstance(data, dict):
                    raise LLMMalformedResponseError("LLM output must be a valid JSON dictionary object.")

                # Construct and validate ReasoningResult
                reasoning_result = ReasoningResult.from_dict(data)

                # Convert LLMRequest back to a ReasoningRequest stub for grounding check
                request_stub = ReasoningRequest(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    user_query=request.user_query,
                    screen_context=request.screen_context,
                    source_references=request.source_references,
                    context_items=request.context_items,
                    prompt_version=request.prompt_version,
                )

                try:
                    validate_result(reasoning_result, original_request=request_stub)
                except (InvalidResultError, GroundingError) as ve:
                    raise LLMValidationError(f"LLM output failed contract validation: {ve}")

                return LLMResponse(
                    raw_text=raw_json,
                    structured_output=data,
                    reasoning_result=reasoning_result,
                    latency_seconds=round(elapsed, 4),
                    model=self.config.model_name,
                    attempts=attempt,
                    success=True,
                )

            except (LLMTimeoutError, LLMMalformedResponseError, LLMValidationError) as err:
                last_error = err
                if attempt < max_attempts:
                    if self.config.retry_backoff_seconds > 0:
                        time.sleep(self.config.retry_backoff_seconds)
                    continue
                else:
                    break

        elapsed = time.time() - start_time
        err_msg = f"LLM generation failed after {attempt} attempt(s): {last_error}"

        if isinstance(last_error, LLMTimeoutError):
            raise LLMTimeoutError(err_msg)
        elif isinstance(last_error, LLMMalformedResponseError):
            raise LLMMalformedResponseError(err_msg)
        elif isinstance(last_error, LLMValidationError):
            raise LLMValidationError(err_msg)
        else:
            raise MaxRetriesExceededError(err_msg)

    def generate_reasoning_result(
        self, request: ReasoningRequest, rendered_prompt: RenderedPrompt
    ) -> ReasoningResult:
        """
        High-level helper dispatching request and returning validated ReasoningResult.
        """
        llm_req = LLMRequest.from_reasoning_request(
            request=request,
            rendered=rendered_prompt,
            timeout=self.config.timeout_seconds,
        )
        response = self.generate(llm_req)
        if response.reasoning_result is None:
            raise LLMClientError("LLM response did not contain a valid ReasoningResult.")
        return response.reasoning_result
