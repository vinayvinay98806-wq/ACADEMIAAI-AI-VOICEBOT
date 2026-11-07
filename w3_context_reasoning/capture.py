"""
Opt-in Screen Capture Adapter for W3 Context & Reasoning.

SAFETY & PRIVACY INVARIANTS:
1. Screen capture is strictly OFF by default (consent_granted=False).
2. Screen capture requires explicit opt-in user consent before any frame is captured.
3. Only synthetic frames are supported in mock/offline mode (synthetic=True).
4. Real desktop capture or recording is strictly prohibited.
5. Maximum image dimension and byte size limits are strictly enforced.
6. Configurable sampling intervals prevent excessive frame captures.
7. Sensitive frame buffers are not retained longer than required for processing.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


class CaptureError(Exception):
    """Base exception for all capture-related errors."""
    pass


class CaptureConsentError(CaptureError):
    """Raised when screen capture is attempted without explicit user consent."""
    pass


class CaptureValidationError(CaptureError):
    """Raised when a captured frame violates size, format, or synthetic invariants."""
    pass


class SamplingRateExceededError(CaptureError):
    """Raised when capture requests exceed the configured sampling interval."""
    pass


@dataclass
class CaptureConfig:
    """
    Configuration governing screen capture behavior and constraints.
    Capture is OFF by default and requires explicit opt-in.
    """
    consent_granted: bool = False
    sampling_interval_seconds: float = 2.0
    max_width: int = 1920
    max_height: int = 1080
    max_size_bytes: int = 5_000_000  # 5 MB
    allowed_formats: Tuple[str, ...] = ("png", "jpeg", "rgb_synthetic")
    allow_synthetic_only: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CaptureConfig:
        return cls(
            consent_granted=bool(data.get("consent_granted", False)),
            sampling_interval_seconds=float(data.get("sampling_interval_seconds", 2.0)),
            max_width=int(data.get("max_width", 1920)),
            max_height=int(data.get("max_height", 1080)),
            max_size_bytes=int(data.get("max_size_bytes", 5_000_000)),
            allowed_formats=tuple(data.get("allowed_formats", ("png", "jpeg", "rgb_synthetic"))),
            allow_synthetic_only=bool(data.get("allow_synthetic_only", True)),
        )


@dataclass
class CapturedFrame:
    """
    Represents an individual captured frame with associated metadata.
    """
    frame_id: str
    timestamp: str
    width: int
    height: int
    format: str
    data: bytes | str
    synthetic: bool = True
    active_window: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        """Returns the size of frame payload in bytes."""
        if isinstance(self.data, bytes):
            return len(self.data)
        elif isinstance(self.data, str):
            return len(self.data.encode("utf-8"))
        return 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "width": self.width,
            "height": self.height,
            "format": self.format,
            "synthetic": self.synthetic,
            "active_window": self.active_window,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
        }


class CaptureValidator:
    """
    Validates capture permissions, rate limits, frame dimensions, and payload sizes.
    """

    @staticmethod
    def validate_consent(config: CaptureConfig) -> None:
        """Enforces that explicit user consent has been granted."""
        if not config.consent_granted:
            raise CaptureConsentError(
                "Screen capture is disabled. Explicit user consent is required (consent_granted=True)."
            )

    @staticmethod
    def validate_sampling_interval(
        last_capture_time: Optional[float],
        current_time: float,
        config: CaptureConfig,
    ) -> None:
        """Enforces minimum elapsed time between consecutive frame captures."""
        if last_capture_time is not None:
            elapsed = current_time - last_capture_time
            if elapsed < config.sampling_interval_seconds:
                raise SamplingRateExceededError(
                    f"Capture rate limit exceeded: {elapsed:.2f}s elapsed since last capture, "
                    f"minimum interval is {config.sampling_interval_seconds:.2f}s."
                )

    @staticmethod
    def validate_frame(frame: CapturedFrame, config: CaptureConfig) -> None:
        """
        Validates frame against security, dimension, and size limits.
        """
        if not isinstance(frame, CapturedFrame):
            raise CaptureValidationError("Provided frame must be an instance of CapturedFrame.")

        if not frame.frame_id or not frame.frame_id.strip():
            raise CaptureValidationError("CapturedFrame frame_id must not be empty.")

        if config.allow_synthetic_only and not frame.synthetic:
            raise CaptureValidationError(
                "Live screen capture is not permitted in mock mode. Only synthetic frames (synthetic=True) are allowed."
            )

        if frame.width <= 0 or frame.height <= 0:
            raise CaptureValidationError(
                f"Invalid frame dimensions ({frame.width}x{frame.height}). Dimensions must be positive integers."
            )

        if frame.width > config.max_width or frame.height > config.max_height:
            raise CaptureValidationError(
                f"Frame dimensions ({frame.width}x{frame.height}) exceed maximum allowed "
                f"({config.max_width}x{config.max_height})."
            )

        if frame.format not in config.allowed_formats:
            raise CaptureValidationError(
                f"Unsupported frame format '{frame.format}'. Allowed formats: {config.allowed_formats}."
            )

        if frame.size_bytes > config.max_size_bytes:
            raise CaptureValidationError(
                f"Frame size ({frame.size_bytes} bytes) exceeds maximum limit ({config.max_size_bytes} bytes)."
            )


class CaptureAdapter(ABC):
    """
    Abstract interface for screen capture adapters.
    """

    def __init__(self, config: Optional[CaptureConfig] = None):
        self.config = config or CaptureConfig()

    def set_consent(self, granted: bool) -> None:
        """Explicitly grant or revoke capture consent."""
        self.config.consent_granted = granted

    @abstractmethod
    def capture(self, active_window: Optional[str] = None) -> CapturedFrame:
        """Captures a frame if consent and constraints are satisfied."""
        pass


class SyntheticCaptureAdapter(CaptureAdapter):
    """
    Safe mock capture adapter that produces synthetic test frames.
    Strictly enforces consent, rate limits, and dimension/size validation.
    """

    def __init__(
        self,
        config: Optional[CaptureConfig] = None,
        validator: Optional[CaptureValidator] = None,
    ):
        super().__init__(config=config)
        self.validator = validator or CaptureValidator()
        self._last_capture_time: Optional[float] = None
        self._preconfigured_scenarios: Dict[str, Dict[str, Any]] = {
            "binary_search_tree": {
                "window": "PDF Viewer - Lecture 7: Tree Structures.pdf",
                "content": (
                    "SLIDE 14: Binary Search Trees (BST)\n"
                    "Property: For any node X, all keys in left subtree are < key(X), "
                    "and all keys in right subtree are > key(X).\n"
                    "Search Time Complexity: Average O(log N), Worst Case O(N)."
                ),
                "width": 1280,
                "height": 720,
            },
            "recursion_debug": {
                "window": "VS Code - recursion_exercise.py",
                "content": (
                    "def factorial(n):\n"
                    "    # Missing base case! Causes RecursionError\n"
                    "    return n * factorial(n - 1)\n"
                    "print(factorial(5))"
                ),
                "width": 1280,
                "height": 720,
            },
            "course_syllabus": {
                "window": "Browser - Course Outline: CS201 Data Structures",
                "content": (
                    "Unit 3: Balanced Trees and Heaps.\n"
                    "Midterm Assessment: Week 5, covers Units 1 through 3.\n"
                    "Weightage: 25% of final grade."
                ),
                "width": 1024,
                "height": 768,
            },
        }

    def register_scenario(
        self,
        name: str,
        active_window: str,
        content: str,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        """Registers a custom synthetic screen scenario for testing."""
        self._preconfigured_scenarios[name] = {
            "window": active_window,
            "content": content,
            "width": width,
            "height": height,
        }

    def capture(
        self,
        active_window: Optional[str] = None,
        scenario: str = "binary_search_tree",
        current_time_override: Optional[float] = None,
    ) -> CapturedFrame:
        """
        Captures a synthetic frame.
        Raises CaptureConsentError if consent has not been explicitly granted.
        Raises SamplingRateExceededError if called faster than sampling interval.
        Raises CaptureValidationError if frame violates size/format constraints.
        """
        # 1. Enforce user consent check
        self.validator.validate_consent(self.config)

        # 2. Enforce sampling interval check
        now = time.time() if current_time_override is None else current_time_override
        self.validator.validate_sampling_interval(self._last_capture_time, now, self.config)

        # 3. Retrieve scenario data
        scene = self._preconfigured_scenarios.get(
            scenario,
            self._preconfigured_scenarios["binary_search_tree"],
        )

        window_title = active_window or scene["window"]
        frame_id = f"SYNTH-FRAME-{uuid.uuid4().hex[:8].upper()}"

        frame = CapturedFrame(
            frame_id=frame_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            width=scene.get("width", 1280),
            height=scene.get("height", 720),
            format="rgb_synthetic",
            data=scene["content"],
            synthetic=True,
            active_window=window_title,
            metadata={
                "scenario": scenario,
                "capture_engine": "SyntheticCaptureAdapter",
            },
        )

        # 4. Enforce frame validation
        self.validator.validate_frame(frame, self.config)

        # 5. Update state
        self._last_capture_time = now
        return frame
