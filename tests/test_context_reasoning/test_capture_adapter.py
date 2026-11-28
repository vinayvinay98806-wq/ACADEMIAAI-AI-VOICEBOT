"""
Unit tests for Opt-in Screen Capture Adapter (Phase 7A).

Verifies:
- Capture disabled by default.
- Consent required before capture.
- Sampling limits enforced.
- Image size limits enforced.
- Invalid frames rejected.
- Synthetic frames processed correctly.
"""

import time
import unittest
from w3_context_reasoning.capture import (
    CaptureConfig,
    CapturedFrame,
    CaptureValidator,
    CaptureAdapter,
    SyntheticCaptureAdapter,
    CaptureConsentError,
    CaptureValidationError,
    SamplingRateExceededError,
)


class TestCaptureAdapter(unittest.TestCase):

    def setUp(self):
        self.config = CaptureConfig(
            consent_granted=False,
            sampling_interval_seconds=1.0,
            max_width=1920,
            max_height=1080,
            max_size_bytes=5000,
            allow_synthetic_only=True,
        )
        self.adapter = SyntheticCaptureAdapter(config=self.config)

    def test_capture_disabled_by_default(self):
        """Screen capture config MUST default to consent_granted=False."""
        default_cfg = CaptureConfig()
        self.assertFalse(default_cfg.consent_granted)
        self.assertTrue(default_cfg.allow_synthetic_only)

    def test_consent_required_before_capture(self):
        """Attempting capture without consent raises CaptureConsentError."""
        self.assertFalse(self.adapter.config.consent_granted)
        with self.assertRaises(CaptureConsentError) as ctx:
            self.adapter.capture()
        self.assertIn("Explicit user consent is required", str(ctx.exception))

    def test_explicit_consent_enables_capture(self):
        """Capture succeeds once explicit consent is set."""
        self.adapter.set_consent(True)
        self.assertTrue(self.adapter.config.consent_granted)
        frame = self.adapter.capture()
        self.assertIsInstance(frame, CapturedFrame)
        self.assertTrue(frame.synthetic)
        self.assertIn("SYNTH-FRAME-", frame.frame_id)
        self.assertGreater(len(frame.data), 0)

    def test_sampling_limits_enforced(self):
        """Consecutive captures faster than sampling_interval_seconds are rejected."""
        self.adapter.set_consent(True)
        now = time.time()
        # First capture succeeds
        frame1 = self.adapter.capture(current_time_override=now)
        self.assertIsNotNone(frame1)

        # Immediate second capture (0.2s elapsed < 1.0s interval) raises SamplingRateExceededError
        with self.assertRaises(SamplingRateExceededError) as ctx:
            self.adapter.capture(current_time_override=now + 0.2)
        self.assertIn("Capture rate limit exceeded", str(ctx.exception))

        # Capture after interval succeeds
        frame2 = self.adapter.capture(current_time_override=now + 1.2)
        self.assertIsNotNone(frame2)

    def test_image_size_limits_enforced(self):
        """Frames exceeding max_width, max_height, or max_size_bytes are rejected."""
        validator = CaptureValidator()

        # Dimension exceeded
        oversized_frame = CapturedFrame(
            frame_id="TEST-OVERSIZED",
            timestamp="2026-01-01T00:00:00Z",
            width=2560,  # exceeds max_width 1920
            height=1440,
            format="rgb_synthetic",
            data="small text",
            synthetic=True,
        )
        with self.assertRaises(CaptureValidationError) as ctx:
            validator.validate_frame(oversized_frame, self.config)
        self.assertIn("exceed maximum allowed", str(ctx.exception))

        # Byte size exceeded
        large_payload = "X" * 10000  # 10,000 bytes > 5,000 max_size_bytes
        heavy_frame = CapturedFrame(
            frame_id="TEST-HEAVY",
            timestamp="2026-01-01T00:00:00Z",
            width=1280,
            height=720,
            format="rgb_synthetic",
            data=large_payload,
            synthetic=True,
        )
        with self.assertRaises(CaptureValidationError) as ctx:
            validator.validate_frame(heavy_frame, self.config)
        self.assertIn("exceeds maximum limit", str(ctx.exception))

    def test_invalid_frame_rejected(self):
        """Invalid dimensions, negative values, and non-synthetic frames are rejected."""
        validator = CaptureValidator()

        # Non-synthetic frame in synthetic-only mode
        live_frame = CapturedFrame(
            frame_id="TEST-LIVE",
            timestamp="2026-01-01T00:00:00Z",
            width=1280,
            height=720,
            format="rgb_synthetic",
            data="content",
            synthetic=False,
        )
        with self.assertRaises(CaptureValidationError) as ctx:
            validator.validate_frame(live_frame, self.config)
        self.assertIn("Only synthetic frames", str(ctx.exception))

        # Negative dimensions
        zero_dim_frame = CapturedFrame(
            frame_id="TEST-ZERO",
            timestamp="2026-01-01T00:00:00Z",
            width=-100,
            height=720,
            format="rgb_synthetic",
            data="content",
            synthetic=True,
        )
        with self.assertRaises(CaptureValidationError) as ctx:
            validator.validate_frame(zero_dim_frame, self.config)
        self.assertIn("Invalid frame dimensions", str(ctx.exception))

        # Unsupported format
        bad_format_frame = CapturedFrame(
            frame_id="TEST-FMT",
            timestamp="2026-01-01T00:00:00Z",
            width=800,
            height=600,
            format="unknown_format",
            data="content",
            synthetic=True,
        )
        with self.assertRaises(CaptureValidationError) as ctx:
            validator.validate_frame(bad_format_frame, self.config)
        self.assertIn("Unsupported frame format", str(ctx.exception))

    def test_synthetic_frames_processed_correctly(self):
        """Synthetic scenarios produce structured, valid frames."""
        self.adapter.set_consent(True)
        frame = self.adapter.capture(scenario="recursion_debug")
        self.assertEqual(frame.synthetic, True)
        self.assertIn("factorial", frame.data)
        self.assertIn("VS Code", frame.active_window)
        self.assertGreater(frame.size_bytes, 0)
        self.assertIsInstance(frame.to_dict(), dict)


if __name__ == "__main__":
    unittest.main()
