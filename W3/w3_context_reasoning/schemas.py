"""
Data contracts and schemas for W3 - Context & Reasoning.

These schemas establish the interfaces for context consumption, prompt grounding,
and reasoning output within the AcademiaAI AI Voice Co-Pilot system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class SourceReference:
    """
    Represents an external or retrieved academic reference grounded in the student's materials
    (e.g., lecture slide, textbook section, syllabus, code file, or transcript).
    """
    source_id: str
    title: str
    snippet: str
    uri_or_path: Optional[str] = None
    relevance_score: float = 1.0
    source_type: str = "textbook"  # Options: textbook, slide, code, syllabus, transcript

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SourceReference:
        return cls(
            source_id=data.get("source_id", ""),
            title=data.get("title", ""),
            snippet=data.get("snippet", ""),
            uri_or_path=data.get("uri_or_path"),
            relevance_score=float(data.get("relevance_score", 1.0)),
            source_type=data.get("source_type", "textbook"),
        )


@dataclass
class ContextItem:
    """
    An individual piece of contextual state, such as conversation history, active task,
    student profile information, or environmental metadata.
    """
    item_id: str
    content: str
    category: str = "conversation_history"  # e.g., conversation_history, student_profile, active_task
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    untrusted: bool = True  # Untrusted by default to require structural isolation in prompts

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ContextItem:
        return cls(
            item_id=data.get("item_id", ""),
            content=data.get("content", ""),
            category=data.get("category", "conversation_history"),
            timestamp=data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            metadata=dict(data.get("metadata", {})),
            untrusted=bool(data.get("untrusted", True)),
        )


@dataclass
class ScreenContext:
    """
    Context derived from user's screen state.

    SAFETY RULE:
    capture_enabled MUST default to False. Real screen capture, recordings,
    or personal data collection is prohibited by default. Demonstrations must use
    synthetic fixtures.
    """
    capture_enabled: bool = False
    frame_id: Optional[str] = None
    timestamp: Optional[str] = None
    ocr_extracted_text: Optional[str] = None
    active_window_title: Optional[str] = None
    synthetic: bool = True  # True when using mock/fixture frames
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScreenContext:
        return cls(
            capture_enabled=bool(data.get("capture_enabled", False)),
            frame_id=data.get("frame_id"),
            timestamp=data.get("timestamp"),
            ocr_extracted_text=data.get("ocr_extracted_text"),
            active_window_title=data.get("active_window_title"),
            synthetic=bool(data.get("synthetic", True)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ReasoningRequest:
    """
    The input contract provided to W3 Context & Reasoning engine (e.g. by W2 Orchestration).
    """
    request_id: str
    session_id: str
    user_query: str
    screen_context: Optional[ScreenContext] = None
    context_items: List[ContextItem] = field(default_factory=list)
    source_references: List[SourceReference] = field(default_factory=list)
    prompt_version: str = "v1"
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "user_query": self.user_query,
            "screen_context": self.screen_context.to_dict() if self.screen_context else None,
            "context_items": [item.to_dict() for item in self.context_items],
            "source_references": [ref.to_dict() for ref in self.source_references],
            "prompt_version": self.prompt_version,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReasoningRequest:
        screen_data = data.get("screen_context")
        screen_obj = ScreenContext.from_dict(screen_data) if screen_data else None

        items_data = data.get("context_items", [])
        context_items = [ContextItem.from_dict(i) for i in items_data]

        refs_data = data.get("source_references", [])
        source_refs = [SourceReference.from_dict(r) for r in refs_data]

        return cls(
            request_id=data.get("request_id", ""),
            session_id=data.get("session_id", ""),
            user_query=data.get("user_query", ""),
            screen_context=screen_obj,
            context_items=context_items,
            source_references=source_refs,
            prompt_version=data.get("prompt_version", "v1"),
            parameters=dict(data.get("parameters", {})),
        )


@dataclass
class ReasoningResult:
    """
    The output contract produced by W3 Context & Reasoning engine.
    """
    result_id: str
    request_id: str
    status: str  # Options: success, clarification_needed, error, unsupported
    response_text: str
    grounded_sources: List[str] = field(default_factory=list)  # List of grounded source_ids
    confidence_score: float = 1.0  # Normalized between 0.0 and 1.0
    intent: str = "general_qa"  # e.g., explain_concept, debug_code, summarize_slide, clarification
    reasoning_steps: List[str] = field(default_factory=list)
    prompt_version: str = "v1"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReasoningResult:
        return cls(
            result_id=data.get("result_id", ""),
            request_id=data.get("request_id", ""),
            status=data.get("status", "success"),
            response_text=data.get("response_text", ""),
            grounded_sources=list(data.get("grounded_sources", [])),
            confidence_score=float(data.get("confidence_score", 1.0)),
            intent=data.get("intent", "general_qa"),
            reasoning_steps=list(data.get("reasoning_steps", [])),
            prompt_version=data.get("prompt_version", "v1"),
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        )
