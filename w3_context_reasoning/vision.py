"""
OCR / Vision Adapter for W3 Context & Reasoning.

Provides a modular interface for extracting structured text and metadata from
captured screen frames. Designed with pluggable architecture for future real OCR/Vision
providers (e.g. Tesseract, Google Cloud Vision, Apple Vision), while providing a
deterministic mock adapter for 100% offline testing without external API keys.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .schemas import ScreenContext
from .capture import CapturedFrame


class VisionError(Exception):
    """Base exception for all vision and OCR processing errors."""
    pass


class InvalidFrameError(VisionError):
    """Raised when an input frame is malformed, corrupted, or unsupported."""
    pass


class ExtractionError(VisionError):
    """Raised when text extraction fails catastrophically."""
    pass


@dataclass
class OCRResult:
    """
    Structured extraction result emitted by an OCR/Vision adapter.
    """
    frame_id: str
    extracted_text: str
    confidence_score: float  # Normalized between 0.0 and 1.0
    active_window: Optional[str] = None
    lines: List[str] = field(default_factory=list)
    detected_language: str = "en"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OCRResult:
        return cls(
            frame_id=data.get("frame_id", ""),
            extracted_text=data.get("extracted_text", ""),
            confidence_score=float(data.get("confidence_score", 0.0)),
            active_window=data.get("active_window"),
            lines=list(data.get("lines", [])),
            detected_language=data.get("detected_language", "en"),
            timestamp=data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            metadata=dict(data.get("metadata", {})),
        )

    def to_screen_context(self, capture_enabled: bool = True) -> ScreenContext:
        """
        Converts the OCR result into a standard W3 ScreenContext dataclass.
        """
        return ScreenContext(
            capture_enabled=capture_enabled,
            frame_id=self.frame_id,
            timestamp=self.timestamp,
            ocr_extracted_text=self.extracted_text,
            active_window_title=self.active_window,
            synthetic=True,
            metadata={
                **self.metadata,
                "confidence_score": self.confidence_score,
                "detected_language": self.detected_language,
                "line_count": len(self.lines),
            },
        )


class OCRVisionAdapter(ABC):
    """
    Abstract base interface for OCR / Vision adapters.
    Real providers (Tesseract, Vision API) or mock providers implement this interface.
    """

    @abstractmethod
    def extract_text(self, frame: CapturedFrame) -> OCRResult:
        """
        Extracts structured text from a CapturedFrame.
        Raises InvalidFrameError if the frame is invalid, None, or corrupted.
        """
        pass


class MockOCRVisionAdapter(OCRVisionAdapter):
    """
    Deterministic mock OCR/Vision adapter for testing and offline execution.
    Extracts structured text from synthetic frames, calculates confidence scores,
    and handles empty or malformed frame inputs.
    """

    def __init__(self, default_confidence: float = 0.95):
        self.default_confidence = default_confidence

    def _validate_frame(self, frame: Any) -> None:
        """Validates that input frame meets contract requirements."""
        if frame is None:
            raise InvalidFrameError("Frame cannot be None.")
        if not isinstance(frame, CapturedFrame):
            raise InvalidFrameError(f"Expected CapturedFrame instance, got {type(frame).__name__}.")
        if not frame.frame_id or not frame.frame_id.strip():
            raise InvalidFrameError("Frame frame_id cannot be empty.")
        if frame.data is None:
            raise InvalidFrameError("Frame data payload cannot be None.")

    def extract_text(self, frame: CapturedFrame) -> OCRResult:
        """
        Performs deterministic text extraction on a CapturedFrame.
        """
        self._validate_frame(frame)

        # Decode data payload
        if isinstance(frame.data, bytes):
            try:
                raw_text = frame.data.decode("utf-8")
            except UnicodeDecodeError:
                raise InvalidFrameError("Frame byte payload could not be decoded as text.")
        elif isinstance(frame.data, str):
            raw_text = frame.data
        else:
            raise InvalidFrameError(f"Unsupported frame data type: {type(frame.data).__name__}.")

        cleaned_text = raw_text.strip()

        if not cleaned_text:
            # Handle empty frame safely with 0 confidence
            return OCRResult(
                frame_id=frame.frame_id,
                extracted_text="",
                confidence_score=0.0,
                active_window=frame.active_window,
                lines=[],
                detected_language="en",
                metadata={"ocr_engine": "MockOCRVisionAdapter", "empty_frame": True},
            )

        # Split into structured lines
        lines = [line.strip() for line in cleaned_text.splitlines() if line.strip()]

        # Confidence calculation heuristic: higher for well-formed academic text
        # Penalize if very short or corrupted
        word_count = len(re.findall(r"\w+", cleaned_text))
        if word_count < 3:
            confidence = max(0.40, self.default_confidence * 0.5)
        else:
            confidence = self.default_confidence

        return OCRResult(
            frame_id=frame.frame_id,
            extracted_text=cleaned_text,
            confidence_score=confidence,
            active_window=frame.active_window,
            lines=lines,
            detected_language="en",
            metadata={
                "ocr_engine": "MockOCRVisionAdapter",
                "character_count": len(cleaned_text),
                "word_count": word_count,
                "synthetic": frame.synthetic,
            },
        )
