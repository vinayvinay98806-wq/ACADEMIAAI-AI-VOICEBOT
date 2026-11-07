"""Audio lifecycle controller for Worker 1.

Manages audio session states:
- IDLE: Session unstarted, awaiting start command.
- RUNNING: Session active, actively processing/accepting audio chunks.
- PAUSED: Session suspended, chunks are rejected/not accepted, sequence tracking preserved.
- STOPPED: Session terminated, no further chunks accepted.

Enforces state transition rules and validates device/permission readiness before capture.
"""

from __future__ import annotations

import enum
from typing import Optional

from .devices import AudioDeviceAdapter, DeviceError, DeviceNotSelectedError, DevicePermissionError
from .schemas import AudioChunk, AudioError


# ============================================================================
# Lifecycle Exception Hierarchy
# ============================================================================

class AudioLifecycleError(AudioError):
    """Base exception for audio session lifecycle errors."""
    pass


class InvalidStateTransitionError(AudioLifecycleError):
    """Raised when an illegal or unsupported state transition is attempted."""
    pass


class SessionNotRunningError(AudioLifecycleError):
    """Raised when an operation (such as chunk ingestion) requires a RUNNING state."""
    pass


# ============================================================================
# Lifecycle States
# ============================================================================

class LifecycleState(str, enum.Enum):
    """Explicit lifecycle states for an audio session."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


# ============================================================================
# Audio Lifecycle Controller
# ============================================================================

class AudioLifecycleController:
    """Manages audio capture session state transitions deterministically.

    Coordinates device validation, session startup, pause/resume, and clean shutdown.
    Preserves sequence tracking across pause/resume cycles.
    """

    def __init__(self, device_adapter: Optional[AudioDeviceAdapter] = None) -> None:
        """Initialize AudioLifecycleController.

        Args:
            device_adapter: Optional AudioDeviceAdapter instance (dependency injected).
        """
        self._state: LifecycleState = LifecycleState.IDLE
        self._device_adapter: Optional[AudioDeviceAdapter] = device_adapter
        self._accepted_chunks: int = 0
        self._paused_rejection_count: int = 0

    @property
    def state(self) -> LifecycleState:
        """Current lifecycle state."""
        return self._state

    @property
    def device_adapter(self) -> Optional[AudioDeviceAdapter]:
        """Associated device adapter."""
        return self._device_adapter

    @device_adapter.setter
    def device_adapter(self, adapter: Optional[AudioDeviceAdapter]) -> None:
        """Set or update the device adapter."""
        self._device_adapter = adapter

    @property
    def is_idle(self) -> bool:
        """Whether controller is in IDLE state."""
        return self._state == LifecycleState.IDLE

    @property
    def is_running(self) -> bool:
        """Whether controller is in RUNNING state."""
        return self._state == LifecycleState.RUNNING

    @property
    def is_paused(self) -> bool:
        """Whether controller is in PAUSED state."""
        return self._state == LifecycleState.PAUSED

    @property
    def is_stopped(self) -> bool:
        """Whether controller is in STOPPED state."""
        return self._state == LifecycleState.STOPPED

    @property
    def accepted_chunks_count(self) -> int:
        """Total chunks accepted across this session."""
        return self._accepted_chunks

    @property
    def paused_rejection_count(self) -> int:
        """Total chunks rejected due to paused or non-running state."""
        return self._paused_rejection_count

    def start(self) -> None:
        """Transition from IDLE to RUNNING.

        Validates that a device is selected and permission is GRANTED on the device adapter.

        Raises:
            InvalidStateTransitionError: If called from RUNNING, PAUSED, or STOPPED.
            DeviceNotSelectedError: If device adapter has no device selected.
            DevicePermissionError: If device adapter permission is not GRANTED.
        """
        if self._state != LifecycleState.IDLE:
            raise InvalidStateTransitionError(
                f"Cannot start session from state {self._state.value}. "
                "start() is only valid from IDLE state."
            )

        # Enforce device and permission readiness via adapter if attached
        if self._device_adapter is not None:
            self._device_adapter.validate_capture_allowed()

        self._state = LifecycleState.RUNNING

    def pause(self) -> None:
        """Transition from RUNNING to PAUSED.

        Suspends chunk acceptance without clearing sequence tracking or session history.

        Raises:
            InvalidStateTransitionError: If called when not in RUNNING state.
        """
        if self._state != LifecycleState.RUNNING:
            raise InvalidStateTransitionError(
                f"Cannot pause session from state {self._state.value}. "
                "pause() is only valid when state is RUNNING."
            )

        self._state = LifecycleState.PAUSED

    def resume(self) -> None:
        """Transition from PAUSED back to RUNNING.

        Resumes chunk acceptance while maintaining sequence tracking and stream time.

        Raises:
            InvalidStateTransitionError: If called when not in PAUSED state.
        """
        if self._state != LifecycleState.PAUSED:
            raise InvalidStateTransitionError(
                f"Cannot resume session from state {self._state.value}. "
                "resume() is only valid when state is PAUSED."
            )

        # Re-verify device and permission still valid if adapter attached
        if self._device_adapter is not None:
            self._device_adapter.validate_capture_allowed()

        self._state = LifecycleState.RUNNING

    def stop(self) -> None:
        """Transition from RUNNING or PAUSED to STOPPED.

        Terminates the active session. Cannot accept further chunks.

        Raises:
            InvalidStateTransitionError: If called when in IDLE or STOPPED state.
        """
        if self._state not in {LifecycleState.RUNNING, LifecycleState.PAUSED}:
            raise InvalidStateTransitionError(
                f"Cannot stop session from state {self._state.value}. "
                "stop() is only valid when RUNNING or PAUSED."
            )

        self._state = LifecycleState.STOPPED

    def reset(self) -> None:
        """Reset the controller from STOPPED back to IDLE.

        Clears chunk counters and allows starting a new session.

        Raises:
            InvalidStateTransitionError: If called while RUNNING or PAUSED.
        """
        if self._state not in {LifecycleState.STOPPED, LifecycleState.IDLE}:
            raise InvalidStateTransitionError(
                f"Cannot reset session from state {self._state.value}. "
                "reset() is only valid when STOPPED or IDLE."
            )
        self._state = LifecycleState.IDLE
        self._accepted_chunks = 0
        self._paused_rejection_count = 0

    def can_accept_chunks(self) -> bool:
        """Check whether the controller is currently accepting audio chunks."""
        return self._state == LifecycleState.RUNNING

    def accept_chunk(self, chunk: AudioChunk) -> AudioChunk:
        """Validate and accept an incoming AudioChunk.

        Args:
            chunk: The AudioChunk to accept.

        Returns:
            The accepted AudioChunk.

        Raises:
            SessionNotRunningError: If called while PAUSED, STOPPED, or IDLE.
            AudioError: If chunk is not a valid AudioChunk instance.
        """
        if not isinstance(chunk, AudioChunk):
            raise AudioLifecycleError(
                f"Expected AudioChunk instance, got {type(chunk).__name__}"
            )

        if self._state != LifecycleState.RUNNING:
            self._paused_rejection_count += 1
            raise SessionNotRunningError(
                f"Cannot accept chunk (seq={chunk.sequence_id}): "
                f"Session is in {self._state.value} state (must be RUNNING)."
            )

        self._accepted_chunks += 1
        return chunk
