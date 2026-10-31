"""
Tests enforcing safe capture defaults and synthetic frame protections.
"""

import unittest
from w3_context_reasoning.schemas import ScreenContext, ReasoningRequest
from w3_context_reasoning.fixtures import create_synthetic_screen_context
from w3_context_reasoning.validation import validate_screen_context, InvalidRequestError


class TestSafeCaptureDefaults(unittest.TestCase):

    def test_default_screen_context_capture_is_disabled(self):
        """Screen capture MUST be disabled by default."""
        sc = ScreenContext()
        self.assertFalse(sc.capture_enabled, "capture_enabled must default to False.")
        self.assertTrue(sc.synthetic, "synthetic must default to True.")

    def test_fixture_generator_defaults_to_disabled(self):
        """create_synthetic_screen_context must default to disabled capture."""
        sc = create_synthetic_screen_context()
        self.assertFalse(sc.capture_enabled, "Synthetic fixtures must default to capture_enabled=False.")
        self.assertTrue(sc.synthetic)
        self.assertIsNotNone(sc.frame_id)
        self.assertIsNotNone(sc.ocr_extracted_text)

    def test_rejection_of_live_screen_capture_in_mock_mode(self):
        """Any attempt to enable live, non-synthetic screen capture is explicitly rejected."""
        live_sc = ScreenContext(capture_enabled=True, synthetic=False)
        with self.assertRaises(InvalidRequestError) as ctx:
            validate_screen_context(live_sc)
        self.assertIn("Live screen capture is not permitted", str(ctx.exception))

    def test_synthetic_capture_allowed_when_explicitly_set(self):
        """Synthetic capture may be enabled for test simulations only when synthetic=True."""
        test_sc = ScreenContext(capture_enabled=True, synthetic=True, frame_id="SYNTH-TEST-01")
        try:
            validate_screen_context(test_sc)
        except InvalidRequestError as e:
            self.fail(f"validate_screen_context rejected valid synthetic test frame: {e}")


if __name__ == "__main__":
    unittest.main()
