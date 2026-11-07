"""Unit tests for AudioLifecycleController (Week 2)."""

import unittest

from academiaai.audio.devices import (
    DeviceNotSelectedError,
    DevicePermissionError,
    MockAudioDeviceAdapter,
)
from academiaai.audio.lifecycle import (
    AudioLifecycleController,
    AudioLifecycleError,
    InvalidStateTransitionError,
    LifecycleState,
    SessionNotRunningError,
)
from academiaai.audio.schemas import AudioChunk, AudioFormat


class TestAudioLifecycleController(unittest.TestCase):
    """Test suite for lifecycle state machine and transition guards."""

    def setUp(self) -> None:
        self.format = AudioFormat(sample_rate=16000, channels=1, sample_width=2)
        self.adapter = MockAudioDeviceAdapter()
        self.controller = AudioLifecycleController(device_adapter=self.adapter)

        # Standard test chunk
        self.test_chunk = AudioChunk(
            data=b"\x00\x00" * 320,
            format=self.format,
            sequence_id=0,
            timestamp_ms=0.0,
        )

    def _prepare_adapter_for_capture(self) -> None:
        """Helper to configure adapter with valid device and granted permission."""
        self.adapter.select_device("mock-mic-default")
        self.adapter.grant_permission()

    def test_initial_state_is_idle(self) -> None:
        """Verify controller starts in IDLE state with zero chunks."""
        self.assertEqual(self.controller.state, LifecycleState.IDLE)
        self.assertTrue(self.controller.is_idle)
        self.assertFalse(self.controller.is_running)
        self.assertFalse(self.controller.is_paused)
        self.assertFalse(self.controller.is_stopped)
        self.assertFalse(self.controller.can_accept_chunks())
        self.assertEqual(self.controller.accepted_chunks_count, 0)

    def test_valid_start_pause_resume_stop_sequence(self) -> None:
        """Test full nominal lifecycle sequence: IDLE -> RUNNING -> PAUSED -> RUNNING -> STOPPED."""
        self._prepare_adapter_for_capture()

        # 1. Start: IDLE -> RUNNING
        self.controller.start()
        self.assertEqual(self.controller.state, LifecycleState.RUNNING)
        self.assertTrue(self.controller.is_running)
        self.assertTrue(self.controller.can_accept_chunks())

        # Accept a chunk
        accepted = self.controller.accept_chunk(self.test_chunk)
        self.assertEqual(accepted, self.test_chunk)
        self.assertEqual(self.controller.accepted_chunks_count, 1)

        # 2. Pause: RUNNING -> PAUSED
        self.controller.pause()
        self.assertEqual(self.controller.state, LifecycleState.PAUSED)
        self.assertTrue(self.controller.is_paused)
        self.assertFalse(self.controller.can_accept_chunks())

        # 3. Resume: PAUSED -> RUNNING
        self.controller.resume()
        self.assertEqual(self.controller.state, LifecycleState.RUNNING)
        self.assertTrue(self.controller.is_running)
        self.assertTrue(self.controller.can_accept_chunks())

        # Sequence tracking continues
        next_chunk = AudioChunk(
            data=b"\x00\x00" * 320,
            format=self.format,
            sequence_id=1,
            timestamp_ms=20.0,
        )
        self.controller.accept_chunk(next_chunk)
        self.assertEqual(self.controller.accepted_chunks_count, 2)

        # 4. Stop: RUNNING -> STOPPED
        self.controller.stop()
        self.assertEqual(self.controller.state, LifecycleState.STOPPED)
        self.assertTrue(self.controller.is_stopped)
        self.assertFalse(self.controller.can_accept_chunks())

    def test_start_blocked_without_selected_device(self) -> None:
        """Test that start() is blocked when no device is selected."""
        self.adapter.grant_permission()
        self.assertIsNone(self.adapter.get_selected_device())

        with self.assertRaises(DeviceNotSelectedError):
            self.controller.start()
        self.assertEqual(self.controller.state, LifecycleState.IDLE)

    def test_start_blocked_without_permission(self) -> None:
        """Test that start() is blocked when permission is UNKNOWN or DENIED."""
        self.adapter.select_device("mock-mic-default")

        # Unknown permission
        with self.assertRaises(DevicePermissionError):
            self.controller.start()
        self.assertEqual(self.controller.state, LifecycleState.IDLE)

        # Denied permission
        self.adapter.deny_permission()
        with self.assertRaises(DevicePermissionError):
            self.controller.start()
        self.assertEqual(self.controller.state, LifecycleState.IDLE)

    def test_invalid_start_transitions(self) -> None:
        """Test that start() raises InvalidStateTransitionError if not IDLE."""
        self._prepare_adapter_for_capture()
        self.controller.start()

        # From RUNNING
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.start()

        # From PAUSED
        self.controller.pause()
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.start()

        # From STOPPED
        self.controller.stop()
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.start()

    def test_invalid_pause_transitions(self) -> None:
        """Test that pause() raises InvalidStateTransitionError if not RUNNING."""
        # From IDLE
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.pause()

        self._prepare_adapter_for_capture()
        self.controller.start()
        self.controller.pause()

        # From PAUSED
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.pause()

        self.controller.stop()

        # From STOPPED
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.pause()

    def test_invalid_resume_transitions(self) -> None:
        """Test that resume() raises InvalidStateTransitionError if not PAUSED."""
        # From IDLE
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.resume()

        self._prepare_adapter_for_capture()
        self.controller.start()

        # From RUNNING
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.resume()

        self.controller.stop()

        # From STOPPED
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.resume()

    def test_invalid_stop_transitions(self) -> None:
        """Test that stop() raises InvalidStateTransitionError if IDLE or already STOPPED."""
        # From IDLE
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.stop()

        self._prepare_adapter_for_capture()
        self.controller.start()
        self.controller.stop()

        # From STOPPED (repeated stop)
        with self.assertRaises(InvalidStateTransitionError):
            self.controller.stop()

    def test_stop_from_paused(self) -> None:
        """Test stopping directly from PAUSED state is valid."""
        self._prepare_adapter_for_capture()
        self.controller.start()
        self.controller.pause()
        self.controller.stop()
        self.assertEqual(self.controller.state, LifecycleState.STOPPED)

    def test_no_chunk_acceptance_while_idle(self) -> None:
        """Verify accept_chunk raises SessionNotRunningError when IDLE."""
        with self.assertRaises(SessionNotRunningError):
            self.controller.accept_chunk(self.test_chunk)
        self.assertEqual(self.controller.accepted_chunks_count, 0)
        self.assertEqual(self.controller.paused_rejection_count, 1)

    def test_no_chunk_acceptance_while_paused(self) -> None:
        """Verify accept_chunk raises SessionNotRunningError when PAUSED."""
        self._prepare_adapter_for_capture()
        self.controller.start()
        self.controller.pause()

        with self.assertRaises(SessionNotRunningError):
            self.controller.accept_chunk(self.test_chunk)
        self.assertEqual(self.controller.accepted_chunks_count, 0)
        self.assertEqual(self.controller.paused_rejection_count, 1)

    def test_no_chunk_acceptance_while_stopped(self) -> None:
        """Verify accept_chunk raises SessionNotRunningError when STOPPED."""
        self._prepare_adapter_for_capture()
        self.controller.start()
        self.controller.stop()

        with self.assertRaises(SessionNotRunningError):
            self.controller.accept_chunk(self.test_chunk)
        self.assertEqual(self.controller.accepted_chunks_count, 0)
        self.assertEqual(self.controller.paused_rejection_count, 1)

    def test_accept_invalid_chunk_type(self) -> None:
        """Verify accept_chunk raises AudioLifecycleError for non-AudioChunk input."""
        self._prepare_adapter_for_capture()
        self.controller.start()

        with self.assertRaises(AudioLifecycleError):
            self.controller.accept_chunk(b"raw bytes")  # type: ignore

    def test_reset_lifecycle(self) -> None:
        """Test reset() transitions STOPPED controller back to IDLE with cleared metrics."""
        self._prepare_adapter_for_capture()
        self.controller.start()
        self.controller.accept_chunk(self.test_chunk)
        self.controller.stop()

        self.assertEqual(self.controller.state, LifecycleState.STOPPED)
        self.controller.reset()
        self.assertEqual(self.controller.state, LifecycleState.IDLE)
        self.assertEqual(self.controller.accepted_chunks_count, 0)


if __name__ == "__main__":
    unittest.main()
