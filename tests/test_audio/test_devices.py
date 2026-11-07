"""Unit tests for AudioDevice and MockAudioDeviceAdapter (Week 2)."""

import unittest

from academiaai.audio.devices import (
    AudioDevice,
    DeviceError,
    DeviceNotFoundError,
    DeviceNotSelectedError,
    DevicePermissionError,
    MockAudioDeviceAdapter,
    PermissionState,
)


class TestMockAudioDeviceAdapter(unittest.TestCase):
    """Test suite for MockAudioDeviceAdapter and device permissions."""

    def setUp(self) -> None:
        self.adapter = MockAudioDeviceAdapter()

    def test_mock_device_enumeration(self) -> None:
        """Test enumerating mock input devices."""
        devices = self.adapter.list_devices()
        self.assertGreaterEqual(len(devices), 3)

        ids = [d.device_id for d in devices]
        self.assertIn("mock-mic-default", ids)
        self.assertIn("mock-headset-mic", ids)
        self.assertIn("mock-studio-mic", ids)

    def test_default_device_retrieval(self) -> None:
        """Test getting default input device."""
        default_dev = self.adapter.get_default_device()
        self.assertTrue(default_dev.is_default)
        self.assertEqual(default_dev.device_id, "mock-mic-default")

    def test_valid_device_selection(self) -> None:
        """Test selecting a valid device by ID."""
        self.assertIsNone(self.adapter.get_selected_device())
        dev = self.adapter.select_device("mock-headset-mic")
        self.assertEqual(dev.device_id, "mock-headset-mic")
        self.assertEqual(self.adapter.get_selected_device(), dev)

    def test_invalid_device_selection(self) -> None:
        """Test selecting an unknown device ID raises DeviceNotFoundError."""
        with self.assertRaises(DeviceNotFoundError) as ctx:
            self.adapter.select_device("non-existent-device-id")
        self.assertIn("non-existent-device-id", str(ctx.exception))

        with self.assertRaises(DeviceNotFoundError):
            self.adapter.select_device(12345)  # type: ignore

    def test_permission_initial_state(self) -> None:
        """Test initial permission state defaults to UNKNOWN."""
        self.assertEqual(self.adapter.get_permission_state(), PermissionState.UNKNOWN)
        self.assertFalse(self.adapter.is_capture_allowed())

    def test_permission_granted(self) -> None:
        """Test simulating granted permission."""
        self.adapter.select_device("mock-mic-default")
        result = self.adapter.request_permission(granted=True)
        self.assertEqual(result, PermissionState.GRANTED)
        self.assertEqual(self.adapter.get_permission_state(), PermissionState.GRANTED)
        self.assertTrue(self.adapter.is_capture_allowed())

    def test_permission_denied(self) -> None:
        """Test simulating denied permission."""
        self.adapter.select_device("mock-mic-default")
        result = self.adapter.request_permission(granted=False)
        self.assertEqual(result, PermissionState.DENIED)
        self.assertEqual(self.adapter.get_permission_state(), PermissionState.DENIED)
        self.assertFalse(self.adapter.is_capture_allowed())

    def test_capture_blocked_without_permission(self) -> None:
        """Test that validate_capture_allowed raises when permission is not GRANTED."""
        self.adapter.select_device("mock-mic-default")

        # Unknown state
        with self.assertRaises(DevicePermissionError):
            self.adapter.validate_capture_allowed()

        # Denied state
        self.adapter.deny_permission()
        with self.assertRaises(DevicePermissionError):
            self.adapter.validate_capture_allowed()

        # Granted state succeeds
        self.adapter.grant_permission()
        self.adapter.validate_capture_allowed()  # Should not raise

    def test_capture_blocked_without_device_selection(self) -> None:
        """Test that validate_capture_allowed raises when no device is selected."""
        self.adapter.grant_permission()
        self.assertIsNone(self.adapter.get_selected_device())
        with self.assertRaises(DeviceNotSelectedError):
            self.adapter.validate_capture_allowed()

    def test_reset_permission(self) -> None:
        """Test resetting permission back to UNKNOWN."""
        self.adapter.grant_permission()
        self.assertEqual(self.adapter.get_permission_state(), PermissionState.GRANTED)
        self.adapter.reset_permission()
        self.assertEqual(self.adapter.get_permission_state(), PermissionState.UNKNOWN)

    def test_custom_device_catalog(self) -> None:
        """Test adapter with custom injected device catalog."""
        custom_dev = AudioDevice(device_id="custom-1", name="Custom Mic", sample_rates=(16000,), channels=1)
        adapter = MockAudioDeviceAdapter(devices=[custom_dev], default_device_id="custom-1")
        self.assertEqual(len(adapter.list_devices()), 1)
        self.assertEqual(adapter.get_selected_device(), custom_dev)

    def test_empty_devices_raises(self) -> None:
        """Test constructing adapter with empty device sequence raises DeviceError."""
        with self.assertRaises(DeviceError):
            MockAudioDeviceAdapter(devices=[])


if __name__ == "__main__":
    unittest.main()
