"""
Determinism and Reproducibility Unit Tests for W3 Context & Reasoning.

Verifies:
- Frozen time provider guarantees identical timestamps across repeated invocations.
- Dataclass defaults reflect deterministic time provider.
- Synthetic frame generation produces identical frame IDs, payloads, and timestamps.
- Mock OCR/Vision adapter extraction is reproducible and preserves frame timestamps.
- Context builder produces identical token counts, ranking, and audit outputs.
- DeterministicMockReasoningEngine emits bit-for-bit identical ReasoningResults.
- Full end-to-end pipeline emits reproducible outputs independent of the system clock.
"""

import time
import unittest
from datetime import datetime, timezone

from w3_context_reasoning.clock import (
    TimeProvider,
    freeze_time,
    unfreeze_time,
    is_time_frozen,
    frozen_time_context,
    get_current_time,
    get_current_timestamp,
    DEFAULT_FIXTURE_TIMESTAMP,
)
from w3_context_reasoning.schemas import (
    ContextItem,
    ReasoningRequest,
    ReasoningResult,
    ScreenContext,
    SourceReference,
)
from w3_context_reasoning.fixtures import (
    create_synthetic_screen_context,
    create_sample_context_items,
    create_sample_reasoning_request,
    create_sample_source_references,
)
from w3_context_reasoning.capture import (
    SyntheticCaptureAdapter,
    CaptureConfig,
    CapturedFrame,
)
from w3_context_reasoning.vision import (
    MockOCRVisionAdapter,
    OCRResult,
)
from w3_context_reasoning.context_builder import (
    ContextBuilder,
    ContextBuilderConfig,
)
from w3_context_reasoning.engine import DeterministicMockReasoningEngine
from w3_context_reasoning.pipeline import ContextReasoningPipeline


class TestClockDeterminism(unittest.TestCase):

    def tearDown(self):
        unfreeze_time()

    def test_freeze_time_locks_timestamp(self):
        """Freezing time ensures get_current_timestamp() returns constant string."""
        target_ts = "2026-10-28T12:00:00+00:00"
        freeze_time(target_ts)
        self.assertTrue(is_time_frozen())

        ts1 = get_current_timestamp()
        time.sleep(0.005)
        ts2 = get_current_timestamp()

        self.assertEqual(ts1, target_ts)
        self.assertEqual(ts2, target_ts)
        self.assertEqual(ts1, ts2)

    def test_frozen_time_context_scoping(self):
        """frozen_time_context context manager isolates frozen time without leaking."""
        target_ts = "2026-05-15T08:30:00+00:00"
        self.assertFalse(is_time_frozen())

        with frozen_time_context(target_ts):
            self.assertTrue(is_time_frozen())
            self.assertEqual(get_current_timestamp(), target_ts)

        self.assertFalse(is_time_frozen())

    def test_dataclass_defaults_follow_clock(self):
        """Dataclass defaults for ContextItem, ReasoningResult, and OCRResult respect frozen clock."""
        target_ts = "2026-09-01T10:00:00+00:00"
        with frozen_time_context(target_ts):
            item = ContextItem(item_id="CTX-01", content="Sample")
            self.assertEqual(item.timestamp, target_ts)

            res = ReasoningResult(
                result_id="RES-01",
                request_id="REQ-01",
                status="success",
                response_text="Answer",
            )
            self.assertEqual(res.created_at, target_ts)

            ocr = OCRResult(
                frame_id="FR-01",
                extracted_text="Text",
                confidence_score=0.9,
            )
            self.assertEqual(ocr.timestamp, target_ts)


class TestSyntheticFrameDeterminism(unittest.TestCase):

    def setUp(self):
        self.adapter = SyntheticCaptureAdapter(
            config=CaptureConfig(consent_granted=True, sampling_interval_seconds=0.0)
        )

    def test_repeated_synthetic_captures_produce_identical_frames(self):
        """Capturing synthetic scenario repeatedly yields identical frame data and metadata."""
        frame1 = self.adapter.capture(scenario="binary_search_tree")
        time.sleep(0.005)
        frame2 = self.adapter.capture(scenario="binary_search_tree")

        self.assertEqual(frame1.frame_id, frame2.frame_id)
        self.assertEqual(frame1.timestamp, frame2.timestamp)
        self.assertEqual(frame1.width, frame2.width)
        self.assertEqual(frame1.height, frame2.height)
        self.assertEqual(frame1.data, frame2.data)
        self.assertEqual(frame1.to_dict(), frame2.to_dict())

    def test_synthetic_screen_context_fixture_is_deterministic(self):
        """create_synthetic_screen_context produces identical objects across repeated calls."""
        ctx1 = create_synthetic_screen_context(scenario="binary_search_tree")
        time.sleep(0.005)
        ctx2 = create_synthetic_screen_context(scenario="binary_search_tree")

        self.assertEqual(ctx1.to_dict(), ctx2.to_dict())
        self.assertEqual(ctx1.frame_id, "SYNTH-FRAME-BST-001")
        self.assertEqual(ctx1.timestamp, DEFAULT_FIXTURE_TIMESTAMP)

    def test_create_sample_reasoning_request_is_deterministic(self):
        """create_sample_reasoning_request produces identical objects across repeated calls."""
        req1 = create_sample_reasoning_request()
        time.sleep(0.005)
        req2 = create_sample_reasoning_request()

        self.assertEqual(req1.to_dict(), req2.to_dict())
        self.assertEqual(req1.request_id, "REQ-DEMO-001")
        self.assertEqual(req1.screen_context.timestamp, req2.screen_context.timestamp)


class TestOCRVisionDeterminism(unittest.TestCase):

    def test_ocr_extraction_identical_outputs(self):
        """MockOCRVisionAdapter yields identical results and preserves frame timestamp."""
        frame = CapturedFrame(
            frame_id="FRAME-TEST-001",
            timestamp="2026-10-28T12:00:00+00:00",
            width=1280,
            height=720,
            format="rgb_synthetic",
            data="Binary Search Tree properties: left < root < right.",
            synthetic=True,
            active_window="Lecture 4.pdf",
        )
        adapter = MockOCRVisionAdapter()

        res1 = adapter.extract_text(frame)
        time.sleep(0.005)
        res2 = adapter.extract_text(frame)

        self.assertEqual(res1.to_dict(), res2.to_dict())
        self.assertEqual(res1.timestamp, frame.timestamp)
        self.assertEqual(res2.timestamp, frame.timestamp)


class TestContextBuilderDeterminism(unittest.TestCase):

    def test_context_builder_identical_outputs(self):
        """ContextBuilder generates identical token counts, ranking, and audit log."""
        builder = ContextBuilder(config=ContextBuilderConfig(max_token_budget=500))
        ref = SourceReference(
            source_id="REF-01",
            title="Tree Algorithms",
            snippet="Binary search trees offer logarithmic lookup time.",
            relevance_score=0.9,
        )
        item = ContextItem(
            item_id="CTX-01",
            content="Student studying binary search trees",
            timestamp="2026-10-28T11:55:00+00:00",
        )
        fixed_time = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

        built1 = builder.build_context(
            user_query="binary search tree complexity",
            context_items=[item],
            source_references=[ref],
            current_time=fixed_time,
        )
        built2 = builder.build_context(
            user_query="binary search tree complexity",
            context_items=[item],
            source_references=[ref],
            current_time=fixed_time,
        )

        self.assertEqual(built1.to_dict(), built2.to_dict())
        self.assertEqual(built1.total_approx_tokens, built2.total_approx_tokens)
        self.assertEqual(built1.dropped_items_count, built2.dropped_items_count)


class TestReasoningEngineDeterminism(unittest.TestCase):

    def test_reasoning_engine_identical_outputs(self):
        """DeterministicMockReasoningEngine generates bit-for-bit identical outputs."""
        engine = DeterministicMockReasoningEngine()
        req = create_sample_reasoning_request(
            query="What is the property of a binary search tree?",
            scenario="binary_search_tree",
        )

        res1 = engine.reason(req)
        time.sleep(0.005)
        res2 = engine.reason(req)

        self.assertEqual(res1.result_id, res2.result_id)
        self.assertEqual(res1.request_id, res2.request_id)
        self.assertEqual(res1.status, res2.status)
        self.assertEqual(res1.response_text, res2.response_text)
        self.assertEqual(res1.grounded_sources, res2.grounded_sources)
        self.assertEqual(res1.confidence_score, res2.confidence_score)
        self.assertEqual(res1.intent, res2.intent)
        self.assertEqual(res1.reasoning_steps, res2.reasoning_steps)
        self.assertEqual(res1.prompt_version, res2.prompt_version)
        self.assertEqual(res1.created_at, res2.created_at)
        self.assertEqual(res1.to_dict(), res2.to_dict())


class TestPipelineDeterminism(unittest.TestCase):

    def test_pipeline_identical_outputs_across_runs(self):
        """Full reasoning pipeline produces identical outputs when executed repeatedly."""
        fixed_ts = "2026-10-28T12:00:00+00:00"
        with frozen_time_context(fixed_ts):
            pipeline = ContextReasoningPipeline()
            req = create_sample_reasoning_request(
                query="What is the property of a binary search tree?",
                scenario="binary_search_tree",
                timestamp=fixed_ts,
            )

            res1 = pipeline.process(req, capture_consent=False)
            time.sleep(0.005)
            res2 = pipeline.process(req, capture_consent=False)

            self.assertEqual(res1.result_id, res2.result_id)
            self.assertEqual(res1.status, res2.status)
            self.assertEqual(res1.response_text, res2.response_text)
            self.assertEqual(res1.grounded_sources, res2.grounded_sources)
            self.assertEqual(res1.confidence_score, res2.confidence_score)
            self.assertEqual(res1.created_at, res2.created_at)
            self.assertEqual(res1.to_dict(), res2.to_dict())


if __name__ == "__main__":
    unittest.main()
