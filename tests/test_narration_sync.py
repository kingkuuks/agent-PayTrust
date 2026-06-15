"""Unit tests for tools/narration_sync.py (stdlib unittest)."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import unittest


def _sample_brief(template_full: str | None = None, scenes_t: list[str] | None = None) -> dict:
    if scenes_t is None:
        scenes_t = [
            "One two three.",
            "Four five six.",
            "Seven eight nine.",
            "Ten eleven twelve?",
            "Thirteen fourteen.",
        ]
    return {
        "chosen_trend": "test",
        "hook": "hook",
        "narrative": "narr",
        "visual_style": "dark_urgent",
        "scenes": [
            {"scene_number": i, "image_prompt": "img", "text_overlay": str(i), "narration": scenes_t[i]}
            for i in range(5)
        ],
        "full_narration": template_full if template_full is not None else " ".join(scenes_t),
        "cta": "cta here",
    }


class TestNormalizeAndSync(unittest.TestCase):
    def test_normalize(self):
        from tools.narration_sync import normalize_text

        self.assertEqual(normalize_text("  a  b\nc\t"), "a b c")

    def test_noop_when_already_aligned(self):
        from tools.narration_sync import sync_scene_narrations_from_full

        b = _sample_brief()
        self.assertFalse(sync_scene_narrations_from_full(b))

    def test_resplit_from_full_only(self):
        from tools.narration_sync import normalize_text, sync_scene_narrations_from_full

        scenes_t = [
            "Short.",
            "Medium line here.",
            "Another medium bit of text.",
            "Debate line with a question?",
            "CTA line here.",
        ]
        full = (
            "Edited zero. Edited one sentence. Edited two sentence. "
            "Edited three question maybe? Edited four closes it out."
        )
        b = _sample_brief(template_full=full, scenes_t=scenes_t)
        self.assertTrue(sync_scene_narrations_from_full(b))

        joined = normalize_text(
            " ".join(
                sorted(b["scenes"], key=lambda s: s["scene_number"])[i]["narration"].strip()
                for i in range(5)
            )
        )
        self.assertEqual(joined, normalize_text(b["full_narration"]))
        self.assertNotEqual(joined, normalize_text(" ".join(scenes_t)))

    def test_resplit_preserves_nkoranza(self):
        from tools.narration_sync import sync_scene_narrations_from_full

        scenes_t = [
            "You saw the Qatar letterhead and sent the cash. Now your dream is a ghost.",
            "In Nkoranza, an agent promised a job. He pressured you for GHS 4,200 via MoMo to secure your visa slot before sunset.",
            "You paid, but the tracking link was fake. Now his number is disconnected and your four thousand cedis is gone forever.",
            "Is it your fault for rushing, or should agents never demand full fees before you hold a passport in your hand?",
            "Skip the debate. Use PayTrust. PayTrustGH.com.",
        ]
        full = (
            "You saw the Qatar letterhead and sent the cash. Now your dream is a ghost. In Nkoranza, an agent promised you a job overseas. "
            "He pressured you for GHS 4,200 via MoMo to secure your visa slot before sunset. You prayed and paid, but the next day his website is a blank page. "
            "Now his number is disconnected and your four thousand cedis is gone forever. "
            "Is it your fault for responding to urgency, or should agents never demand full fees before you hold a passport in your hand? "
            "Skip the debate. Use PayTrust. PayTrustGH.com."
        )
        b = _sample_brief(template_full=full, scenes_t=scenes_t)
        self.assertTrue(sync_scene_narrations_from_full(b))
        joined = " ".join(s["narration"] for s in sorted(b["scenes"], key=lambda x: x["scene_number"]))
        self.assertIn("Nkoranza", joined)
        self.assertNotIn("Nkora nza", joined)

    def test_nearest_sentence_boundary_respects_snap_window_edge(self):
        from tools.narration_sync import SNAP_WINDOW, _nearest_sentence_boundary

        # Boundary b: char before b is '.'
        n = "x" * 20 + ". " + "y" * 40
        b_sentence = 21
        self.assertEqual(n[b_sentence - 1], ".")
        ideal = b_sentence + SNAP_WINDOW
        self.assertLessEqual(abs(ideal - b_sentence), SNAP_WINDOW)
        got = _nearest_sentence_boundary(n, ideal, lo=5, hi=min(len(n) - 1, 60))
        self.assertEqual(got, b_sentence)


if __name__ == "__main__":
    unittest.main()
