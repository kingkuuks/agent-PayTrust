"""Unit tests for tools/brief_continue.py and --continue validation ordering."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _win_story_brief_with_empty_overlays() -> dict:
    scenes_t = [
        "Hook line one.",
        "Setup line two.",
        "Conflict line three.",
        "Debate question here?",
        "Skip the debate. Use PayTrust. Pay Trust G H dot com.",
    ]
    return {
        "chosen_trend": "win_story",
        "hook": "hook",
        "narrative": "narr",
        "visual_style": "dark_urgent",
        "scenes": [
            {
                "scene_number": i,
                "image_prompt": "" if i < 3 else "img3",
                "text_overlay": "" if i < 3 else str(i),
                "narration": scenes_t[i],
            }
            for i in range(5)
        ],
        "full_narration": " ".join(scenes_t),
        "cta": scenes_t[4],
    }


class TestBriefContinue(unittest.TestCase):
    def test_structure_allows_empty_overlays(self):
        from tools.brief_validation import validate_brief_structure

        brief = _win_story_brief_with_empty_overlays()
        validate_brief_structure(brief)

    def test_structure_rejects_missing_key(self):
        from tools.brief_validation import validate_brief_structure

        brief = _win_story_brief_with_empty_overlays()
        del brief["cta"]
        with self.assertRaises(ValueError) as ctx:
            validate_brief_structure(brief)
        self.assertIn("cta", str(ctx.exception))

    def test_production_rejects_empty_overlays_before_regen(self):
        from tools.brief_validation import validate_production_brief

        brief = _win_story_brief_with_empty_overlays()
        with self.assertRaises(ValueError) as ctx:
            validate_production_brief(brief)
        self.assertIn("Scene 0 field", str(ctx.exception))
        self.assertIn("must be non-empty", str(ctx.exception))

    @patch("tools.gemini_client.regenerate_scene_visuals_from_narration")
    def test_prepare_then_validate_passes(self, mock_regen):
        from tools.brief_continue import ensure_scene4_defaults, prepare_brief_for_continue
        from tools.brief_validation import validate_production_brief

        def _fill_visuals(brief, scene_indices, brand):
            for i in scene_indices:
                scene = next(s for s in brief["scenes"] if s["scene_number"] == i)
                scene["image_prompt"] = f"prompt {i}"
                scene["text_overlay"] = f"overlay {i}"

        mock_regen.side_effect = _fill_visuals

        brief = _win_story_brief_with_empty_overlays()
        brand = {"website": "PayTrustGH.com", "name": "PayTrust"}
        prepare_brief_for_continue(brief, brand)
        ensure_scene4_defaults(brief, brand)
        validate_production_brief(brief)

        for i in range(5):
            scene = next(s for s in brief["scenes"] if s["scene_number"] == i)
            self.assertTrue(str(scene["text_overlay"]).strip())
            self.assertTrue(str(scene["image_prompt"]).strip())

    def test_scene4_defaults_fill_empty_fields(self):
        from tools.brief_continue import ensure_scene4_defaults

        brief = _win_story_brief_with_empty_overlays()
        brief["scenes"][4]["text_overlay"] = ""
        brief["scenes"][4]["image_prompt"] = ""
        ensure_scene4_defaults(brief, {"website": "PayTrustGH.com", "name": "PayTrust"})
        scene4 = brief["scenes"][4]
        self.assertEqual(scene4["text_overlay"], "PayTrustGH.com")
        self.assertIn("PayTrust", scene4["image_prompt"])

    @patch("tools.gemini_client.regenerate_scene_visuals_from_narration")
    def test_prepare_regen_failure_propagates(self, mock_regen):
        from tools.brief_continue import prepare_brief_for_continue

        mock_regen.side_effect = RuntimeError("Gemini unavailable")
        brief = _win_story_brief_with_empty_overlays()
        with self.assertRaises(RuntimeError):
            prepare_brief_for_continue(brief, {})


if __name__ == "__main__":
    unittest.main()
