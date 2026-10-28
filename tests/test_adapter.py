"""Tests for BaseTranscriptionAdapter interface contract."""

import unittest
from typing import Any, Dict, List, Optional

from w2_stt.adapter import BaseTranscriptionAdapter
from w2_stt.schemas import TranscriptEvent


class IncompleteAdapter(BaseTranscriptionAdapter):
    """Adapter missing required abstract methods."""
    pass


class MinimalConcreteAdapter(BaseTranscriptionAdapter):
    """Compliant minimal adapter for testing the interface contract."""

    @property
    def provider_name(self) -> str:
        return "MinimalTestAdapter"

    def process_audio_chunk(
        self,
        chunk: bytes,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[TranscriptEvent]:
        return []

    def flush(self) -> List[TranscriptEvent]:
        return []

    def reset(self) -> None:
        pass


class TestTranscriptionAdapterInterface(unittest.TestCase):
    """Test suite ensuring BaseTranscriptionAdapter behaves as a strict abstract base class."""

    def test_direct_instantiation_forbidden(self) -> None:
        """Verify BaseTranscriptionAdapter cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            BaseTranscriptionAdapter()  # type: ignore[abstract]

    def test_subclass_missing_methods_forbidden(self) -> None:
        """Verify subclass lacking abstract implementations cannot be instantiated."""
        with self.assertRaises(TypeError):
            IncompleteAdapter()  # type: ignore[abstract]

    def test_compliant_subclass_instantiation(self) -> None:
        """Verify compliant subclass satisfies contract cleanly."""
        adapter = MinimalConcreteAdapter()
        self.assertEqual(adapter.provider_name, "MinimalTestAdapter")
        self.assertEqual(adapter.process_audio_chunk(b"1234"), [])
        self.assertEqual(adapter.flush(), [])
        adapter.reset()
        adapter.close()


if __name__ == "__main__":
    unittest.main()
