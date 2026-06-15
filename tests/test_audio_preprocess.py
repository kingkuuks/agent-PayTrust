"""Unit tests for TTS preprocessing (Ghana amounts, pauses)."""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.audio_generator import _preprocess_for_tts


class AudioPreprocessTest(unittest.TestCase):
    def test_ghs_converted_and_spelled(self):
        raw = (
            "Total: GHS 25,500. Three bales at GHS 8,500 each. "
            "But GHS 25,500 is not a handshake."
        )
        t = _preprocess_for_tts(raw)
        self.assertNotIn("25500", t)
        self.assertNotIn("8500", t)
        self.assertRegex(t.lower(), r"twenty[- ]five thousand")
        self.assertRegex(t.lower(), r"eight thousand")
        self.assertRegex(t.lower(), r"\bcedis\b")

    def test_total_label_comma_reduces_colon_pause(self):
        self.assertIn(
            "Total,",
            _preprocess_for_tts("Total: GHS 1,000."),
        )


if __name__ == "__main__":
    unittest.main()
