"""
Unit tests for OCR / Vision Adapter (Phase 7B).

Verifies:
- Valid synthetic frame processed.
- Empty extraction handled gracefully.
- Invalid input rejected with proper exceptions.
- Mock response validated against schema.
- Confidence scores calculated.
- Conversion to ScreenContext.
"""

import unittest
from w3_context_reasoning.capture import CapturedFrame
from w3_context_reasoning.vision import (
    MockOCRVisionAdapter,
    OCRResult,
    InvalidFrameError,
)
from w3_context_reasoning.schemas import ScreenContext


class TestOCRVisionAdapter(unittest.TestCase):

    def setUp(self):
        self.adapter = MockOCRVisionAdapter(default_confidence=0.95)

    def test_valid_synthetic_frame_processed(self):
        """Processes valid synthetic frame and returns structured OCRResult."""
        frame = CapturedFrame(
            frame_id="FRAME-BST-01",
            timestamp="2026-01-01T12:00:00Z",
            width=1280,
            height=720,
            format="rgb_synthetic",
            data="Binary Search Tree: left < node < right.\nTime Complexity: O(log n).",
            synthetic=True,
            active_window="Lecture 7 Slides.pdf",
        )
        result = self.adapter.extract_text(frame)

        self.assertIsInstance(result, OCRResult)
        self.assertEqual(result.frame_id, "FRAME-BST-01")
        self.assertEqual(result.active_window, "Lecture 7 Slides.pdf")
        self.assertIn("Binary Search Tree", result.extracted_text)
        self.assertEqual(len(result.lines), 2)
        self.assertGreaterEqual(result.confidence_score, 0.90)

    def test_empty_extraction_handled_gracefully(self):
        """Empty frame string returns empty OCRResult with 0 confidence without crashing."""
        frame = CapturedFrame(
            frame_id="FRAME-EMPTY",
            timestamp="2026-01-01T12:00:00Z",
            width=640,
            height=480,
            format="rgb_synthetic",
            data="   \n   ",
            synthetic=True,
        )
        result = self.adapter.extract_text(frame)
        self.assertEqual(result.extracted_text, "")
        self.assertEqual(result.confidence_score, 0.0)
        self.assertEqual(len(result.lines), 0)
        self.assertTrue(result.metadata.get("empty_frame"))

    def test_invalid_input_rejected(self):
        """Rejects None, wrong types, or missing IDs with InvalidFrameError."""
        with self.assertRaises(InvalidFrameError):
            self.adapter.extract_text(None)

        with self.assertRaises(InvalidFrameError):
            self.adapter.extract_text("not-a-frame")  # type: ignore

        # Frame with empty frame_id
        bad_frame = CapturedFrame(
            frame_id="",
            timestamp="2026-01-01T12:00:00Z",
            width=640,
            height=480,
            format="rgb_synthetic",
            data="some text",
            synthetic=True,
        )
        with self.assertRaises(InvalidFrameError):
            self.adapter.extract_text(bad_frame)

    def test_byte_payload_decoding(self):
        """Supports frames containing UTF-8 encoded bytes."""
        byte_data = "def quicksort(arr): return arr".encode("utf-8")
        frame = CapturedFrame(
            frame_id="FRAME-BYTES-01",
            timestamp="2026-01-01T12:00:00Z",
            width=1024,
            height=768,
            format="rgb_synthetic",
            data=byte_data,
            synthetic=True,
            active_window="editor.py",
        )
        result = self.adapter.extract_text(frame)
        self.assertIn("quicksort", result.extracted_text)
        self.assertEqual(result.active_window, "editor.py")

    def test_corrupted_byte_payload_raises(self):
        """Invalid non-UTF-8 bytes trigger InvalidFrameError."""
        corrupted_bytes = b"\x80\x81\xff\xfe"
        frame = CapturedFrame(
            frame_id="FRAME-CORRUPT",
            timestamp="2026-01-01T12:00:00Z",
            width=1024,
            height=768,
            format="rgb_synthetic",
            data=corrupted_bytes,
            synthetic=True,
        )
        with self.assertRaises(InvalidFrameError):
            self.adapter.extract_text(frame)

    def test_to_screen_context_conversion(self):
        """OCRResult cleanly converts to Week 1 ScreenContext."""
        result = OCRResult(
            frame_id="FRAME-CONVERT",
            extracted_text="Sample lecture slide content",
            confidence_score=0.96,
            active_window="Acrobat Reader",
            lines=["Sample lecture slide content"],
        )
        sc = result.to_screen_context(capture_enabled=True)
        self.assertIsInstance(sc, ScreenContext)
        self.assertEqual(sc.frame_id, "FRAME-CONVERT")
        self.assertEqual(sc.ocr_extracted_text, "Sample lecture slide content")
        self.assertEqual(sc.active_window_title, "Acrobat Reader")
        self.assertTrue(sc.capture_enabled)
        self.assertTrue(sc.synthetic)


if __name__ == "__main__":
    unittest.main()
