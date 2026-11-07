"""Audio device abstraction and mock device adapters for Worker 1.

This module provides hardware-independent device models and permission management:
- PermissionState: Enum representing microphone permission states.
- AudioDevice: Data model representing audio input devices.
- AudioDeviceAdapter: Interface/protocol for audio device management.
- MockAudioDeviceAdapter: Deterministic mock implementation with simulated permissions.
- DeviceError hierarchy: Typed exceptions for device and permission errors.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .schemas import AudioError


# ============================================================================
# Device Exception Hierarchy
# ============================================================================

class DeviceError(AudioError):
    """Base exception for audio device and hardware adapter errors."""
    pass


class DeviceNotFoundError(DeviceError):
    """Raised when a requested device identifier is unknown or not enumerated."""
    pass


class DevicePermissionError(DeviceError):
    """Raised when audio capture or device operations are blocked by permission policies."""
    pass


class DeviceNotSelectedError(DeviceError):
    """Raised when an operation requires an active device selection but none is selected."""
    pass


# ============================================================================
# Permission States
# ============================================================================

class PermissionState(str, enum.Enum):
    """Represents the microphone access permission status."""
    UNKNOWN = "UNKNOWN"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


# ============================================================================
# Audio Device Data Model
# ============================================================================

@dataclass(frozen=True)
class AudioDevice:
    """Represents an audio input device.

    Attributes:
        device_id: Unique identifier for the device.
        name: Human-readable display name.
        sample_rates: Supported sample rates in Hz.
        channels: Supported input channels (1 for mono, 2 for stereo).
        is_default: Whether this is the system default input device.
    """
    device_id: str
    name: str
    sample_rates: Sequence[int] = field(default_factory=lambda: (16000, 44100, 48000))
    channels: int = 1
    is_default: bool = False

    def __post_init__(self) -> None:
        """Validate device attributes."""
        if not self.device_id or not isinstance(self.device_id, str):
            raise DeviceError("device_id must be a non-empty string")
        if not self.name or not isinstance(self.name, str):
            raise DeviceError("device name must be a non-empty string")
        if self.channels not in {1, 2}:
            raise DeviceError(f"Unsupported channel count: {self.channels} (must be 1 or 2)")


# ============================================================================
# Audio Device Adapter Interface
# ============================================================================

class AudioDeviceAdapter(abc.ABC):
    """Abstract interface for audio capture device adapters."""

    @abc.abstractmethod
    def list_devices(self) -> List[AudioDevice]:
        """List all available audio input devices."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_default_device(self) -> AudioDevice:
        """Get the default input device."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_device(self, device_id: str) -> AudioDevice:
        """Get device by ID or raise DeviceNotFoundError."""
        raise NotImplementedError

    @abc.abstractmethod
    def select_device(self, device_id: str) -> AudioDevice:
        """Select active device by ID. Raises DeviceNotFoundError if invalid."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_selected_device(self) -> Optional[AudioDevice]:
        """Get currently selected device, or None if no device is selected."""
        raise NotImplementedError

    @abc.abstractmethod
    def request_permission(self) -> PermissionState:
        """Request microphone capture permission."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_permission_state(self) -> PermissionState:
        """Return the current permission state."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_capture_allowed(self) -> bool:
        """Check whether capture can proceed (device selected and permission GRANTED)."""
        raise NotImplementedError

    @abc.abstractmethod
    def validate_capture_allowed(self) -> None:
        """Validate capture readiness or raise descriptive DeviceError."""
        raise NotImplementedError


# ============================================================================
# Mock Audio Device Adapter Implementation
# ============================================================================

# Default deterministic mock devices
DEFAULT_MOCK_DEVICES: Sequence[AudioDevice] = (
    AudioDevice(
        device_id="mock-mic-default",
        name="Mock Built-in Microphone",
        sample_rates=(8000, 16000, 44100, 48000),
        channels=1,
        is_default=True,
    ),
    AudioDevice(
        device_id="mock-headset-mic",
        name="Mock USB Headset Microphone",
        sample_rates=(16000, 48000),
        channels=1,
        is_default=False,
    ),
    AudioDevice(
        device_id="mock-studio-mic",
        name="Mock Studio Stereo Microphone",
        sample_rates=(44100, 48000),
        channels=2,
        is_default=False,
    ),
)


class MockAudioDeviceAdapter(AudioDeviceAdapter):
    """Deterministic mock audio device adapter.

    Simulates device enumeration, selection, and permission workflow without
    interacting with physical hardware or OS audio drivers.
    """

    def __init__(
        self,
        devices: Optional[Sequence[AudioDevice]] = None,
        default_device_id: Optional[str] = None,
        initial_permission: PermissionState = PermissionState.UNKNOWN,
    ) -> None:
        """Initialize MockAudioDeviceAdapter.

        Args:
            devices: Optional sequence of devices. Uses DEFAULT_MOCK_DEVICES if omitted.
            default_device_id: Optional device ID to select by default.
            initial_permission: Initial PermissionState (default: UNKNOWN).
        """
        device_list = list(devices) if devices is not None else list(DEFAULT_MOCK_DEVICES)
        if not device_list:
            raise DeviceError("MockAudioDeviceAdapter requires at least one device")

        self._devices: Dict[str, AudioDevice] = {d.device_id: d for d in device_list}
        self._selected_device: Optional[AudioDevice] = None
        self._permission_state: PermissionState = PermissionState(initial_permission)

        if default_device_id is not None:
            if default_device_id not in self._devices:
                raise DeviceNotFoundError(f"Configured default device not found: {default_device_id}")
            self._selected_device = self._devices[default_device_id]

    def list_devices(self) -> List[AudioDevice]:
        """List all available mock input devices."""
        return list(self._devices.values())

    def get_default_device(self) -> AudioDevice:
        """Get the default input device (first marked is_default or first in catalog)."""
        for dev in self._devices.values():
            if dev.is_default:
                return dev
        return next(iter(self._devices.values()))

    def get_device(self, device_id: str) -> AudioDevice:
        """Get device by ID or raise DeviceNotFoundError."""
        if not isinstance(device_id, str):
            raise DeviceNotFoundError(f"Device ID must be a string, got {type(device_id).__name__}")
        if device_id not in self._devices:
            available = sorted(self._devices.keys())
            raise DeviceNotFoundError(
                f"Device with ID {device_id!r} not found. Available devices: {available}"
            )
        return self._devices[device_id]

    def select_device(self, device_id: str) -> AudioDevice:
        """Select active device by ID.

        Args:
            device_id: ID of device to select.

        Returns:
            The selected AudioDevice.

        Raises:
            DeviceNotFoundError: If device_id is unknown.
        """
        dev = self.get_device(device_id)
        self._selected_device = dev
        return dev

    def get_selected_device(self) -> Optional[AudioDevice]:
        """Return currently selected device, or None."""
        return self._selected_device

    def request_permission(self, granted: bool = True) -> PermissionState:
        """Simulate a permission request.

        Args:
            granted: If True, resolves to GRANTED; if False, resolves to DENIED.

        Returns:
            The updated PermissionState.
        """
        self._permission_state = PermissionState.REQUESTED
        self._permission_state = PermissionState.GRANTED if granted else PermissionState.DENIED
        return self._permission_state

    def grant_permission(self) -> PermissionState:
        """Explicitly simulate granting microphone permission."""
        self._permission_state = PermissionState.GRANTED
        return self._permission_state

    def deny_permission(self) -> PermissionState:
        """Explicitly simulate denying microphone permission."""
        self._permission_state = PermissionState.DENIED
        return self._permission_state

    def reset_permission(self) -> PermissionState:
        """Reset permission state back to UNKNOWN."""
        self._permission_state = PermissionState.UNKNOWN
        return self._permission_state

    def get_permission_state(self) -> PermissionState:
        """Return current permission state."""
        return self._permission_state

    def is_capture_allowed(self) -> bool:
        """Check whether capture can proceed (device selected and permission GRANTED)."""
        return (
            self._selected_device is not None
            and self._permission_state == PermissionState.GRANTED
        )

    def validate_capture_allowed(self) -> None:
        """Validate capture readiness or raise descriptive typed exception.

        Raises:
            DeviceNotSelectedError: If no device is currently selected.
            DevicePermissionError: If permission is not GRANTED.
        """
        if self._selected_device is None:
            raise DeviceNotSelectedError(
                "Audio capture blocked: No audio input device selected. "
                "Call select_device() with a valid device ID first."
            )
        if self._permission_state != PermissionState.GRANTED:
            raise DevicePermissionError(
                f"Audio capture blocked: Microphone permission is {self._permission_state.value}. "
                "Permission must be GRANTED to start capture."
            )
