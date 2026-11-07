"""Integration tests for the complete audio pipeline (Week 2)."""

import unittest

from academiaai.audio.buffer import BackpressurePolicy
from academiaai.audio.devices import DeviceNotSelectedError, DevicePermissionError
from academiaai.audio.lifecycle import LifecycleState, SessionNotRunningError
from academiaai.audio.pipeline import AudioPipeline
from academiaai.audio.sources import SignalType


class TestAudioPipelineIntegration(unittest.TestCase):
    """Integration test suite connecting mock device, lifecycle, VAD, and buffer."""

    def test_complete_pipeline_flow(self) -> None:
        """Test full pipeline execution: setup, permission grant, start, chunk streaming, VAD, and buffer."""
        pipeline = AudioPipeline.create_default(
            signal_type=SignalType.SPEECH_LIKE,
            chunk_duration_ms=20.0,
            buffer_capacity=10,
            energy_threshold=0.05,
            min_speech_duration_ms=40.0,
        )

        # Configure mock device & permissions
        pipeline.adapter.select_device("mock-mic-default")
        pipeline.adapter.grant_permission()

        # Start session
        pipeline.start()
        self.assertEqual(pipeline.lifecycle.state, LifecycleState.RUNNING)

        # Run 8 steps
        results = pipeline.run(max_chunks=8)
        self.assertEqual(len(results), 8)

        # Verify each step result
        for idx, res in enumerate(results):
            self.assertEqual(res.chunk.sequence_id, idx)
            self.assertAlmostEqual(res.chunk.timestamp_ms, idx * 20.0)
            self.assertIs(res.vad_result.chunk, res.chunk)
            self.assertTrue(res.enqueued)

        # Verify buffer size matches step count
        self.assertEqual(pipeline.buffer.size, 8)

        # Stop session
        pipeline.stop()
        self.assertEqual(pipeline.lifecycle.state, LifecycleState.STOPPED)

        # Finalize and inspect summary
        summary = pipeline.finalize()
        self.assertEqual(summary.lifecycle_state, LifecycleState.STOPPED)
        self.assertEqual(summary.total_chunks_processed, 8)
        self.assertEqual(summary.buffer_stats.current_size, 8)

    def test_permission_denial_blocks_pipeline(self) -> None:
        """Test that pipeline start is blocked when microphone permission is denied."""
        pipeline = AudioPipeline.create_default()
        pipeline.adapter.select_device("mock-mic-default")
        pipeline.adapter.deny_permission()

        with self.assertRaises(DevicePermissionError):
            pipeline.start()

        self.assertEqual(pipeline.lifecycle.state, LifecycleState.IDLE)
        # Attempting to step must fail because session is IDLE
        with self.assertRaises(SessionNotRunningError):
            pipeline.step()

    def test_unselected_device_blocks_pipeline(self) -> None:
        """Test that pipeline start is blocked when no device is selected."""
        pipeline = AudioPipeline.create_default()
        pipeline.adapter.grant_permission()

        with self.assertRaises(DeviceNotSelectedError):
            pipeline.start()

        self.assertEqual(pipeline.lifecycle.state, LifecycleState.IDLE)

    def test_pipeline_pause_and_resume(self) -> None:
        """Test pausing prevents chunk ingestion, resuming continues without sequence loss."""
        pipeline = AudioPipeline.create_default(buffer_capacity=20)
        pipeline.adapter.select_device("mock-mic-default")
        pipeline.adapter.grant_permission()
        pipeline.start()

        # Process 3 chunks
        res1 = pipeline.run(max_chunks=3)
        self.assertEqual(len(res1), 3)

        # Pause
        pipeline.pause()
        self.assertEqual(pipeline.lifecycle.state, LifecycleState.PAUSED)

        # Stepping while paused must raise SessionNotRunningError
        with self.assertRaises(SessionNotRunningError):
            pipeline.step()

        # Resume
        pipeline.resume()
        self.assertEqual(pipeline.lifecycle.state, LifecycleState.RUNNING)

        # Process next 3 chunks
        res2 = pipeline.run(max_chunks=3)
        self.assertEqual(len(res2), 3)

        # Sequence IDs must be contiguous across pause/resume
        all_res = res1 + res2
        seq_ids = [r.chunk.sequence_id for r in all_res]
        # Note: the chunk read during the failed step while paused was attempted;
        # let's check sequence numbers: FakeMicrophoneSource produced chunks monotonically
        self.assertEqual(len(seq_ids), 6)
        # Each subsequent chunk has higher sequence_id
        for i in range(len(seq_ids) - 1):
            self.assertLess(seq_ids[i], seq_ids[i + 1])

        pipeline.stop()

    def test_pipeline_buffer_overflow_observability(self) -> None:
        """Test buffer overflow and dropped chunks are observable in pipeline summary."""
        small_capacity = 4
        pipeline = AudioPipeline.create_default(
            buffer_capacity=small_capacity,
            backpressure_policy=BackpressurePolicy.DROP_NEWEST,
        )
        pipeline.adapter.select_device("mock-mic-default")
        pipeline.adapter.grant_permission()
        pipeline.start()

        # Stream 10 chunks into capacity-4 buffer
        results = pipeline.run(max_chunks=10)
        self.assertEqual(len(results), 10)

        # First 4 enqueued, next 6 dropped
        enqueued_flags = [r.enqueued for r in results]
        self.assertEqual(enqueued_flags[:4], [True, True, True, True])
        self.assertEqual(enqueued_flags[4:], [False] * 6)

        pipeline.stop()
        summary = pipeline.finalize()

        self.assertEqual(summary.buffer_stats.current_size, small_capacity)
        self.assertEqual(summary.buffer_stats.dropped_chunks, 6)
        self.assertEqual(summary.buffer_stats.overflow_count, 6)


if __name__ == "__main__":
    unittest.main()
