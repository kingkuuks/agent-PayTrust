"""
Load and validate production briefs for the human `--continue` path.
Read-only structural checks only — does not mutate the brief dict.
"""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED_TOP_LEVEL = (
    "chosen_trend",
    "hook",
    "narrative",
    "visual_style",
    "scenes",
    "full_narration",
    "cta",
)

SCENE_STRING_FIELDS = ("image_prompt", "text_overlay", "narration")


def load_brief_json(path: Path) -> dict:
    """
    UTF-8 JSON load. Raises json.JSONDecodeError on invalid syntax (caller prints and exits).
    """
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def validate_brief_structure(brief: dict) -> None:
    """
    Structural validation only — does not modify `brief`.
    Allows empty scene string fields and empty full_narration (filled before strict validation).
    """
    if not isinstance(brief, dict):
        raise ValueError("Brief must be a JSON object at the root.")

    for key in REQUIRED_TOP_LEVEL:
        if key not in brief:
            raise ValueError(f"Brief missing required key: {key}")

    fn = brief.get("full_narration")
    if not isinstance(fn, str):
        raise ValueError("full_narration must be a string.")

    scenes = brief.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("scenes must be a JSON array.")
    if len(scenes) != 5:
        raise ValueError(f"Expected 5 scenes, got {len(scenes)}.")

    numbers = []
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {i} must be an object.")
        sn = scene.get("scene_number")
        if sn is None:
            raise ValueError(f"Scene {i} missing scene_number.")
        if not isinstance(sn, int):
            raise ValueError(f"Scene {i} scene_number must be an integer.")
        numbers.append(sn)
        for field in SCENE_STRING_FIELDS:
            if field not in scene:
                raise ValueError(f"Scene {i} missing field: {field}")
            val = scene[field]
            if not isinstance(val, str):
                raise ValueError(f"Scene {i} field {field} must be a string.")

    sorted_nums = sorted(numbers)
    if sorted_nums != list(range(5)):
        raise ValueError(
            f"scene_number values must be exactly 0,1,2,3,4 once each; got {sorted_nums}."
        )


def validate_production_brief(brief: dict) -> None:
    """
    Structural validation only — does not modify `brief`.
    Used when resuming from a human-edited brief.json.
    """
    if not isinstance(brief, dict):
        raise ValueError("Brief must be a JSON object at the root.")

    for key in REQUIRED_TOP_LEVEL:
        if key not in brief:
            raise ValueError(f"Brief missing required key: {key}")

    fn = brief.get("full_narration")
    if not isinstance(fn, str) or not str(fn).strip():
        raise ValueError("full_narration must be a non-empty string.")

    scenes = brief.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("scenes must be a JSON array.")
    if len(scenes) != 5:
        raise ValueError(f"Expected 5 scenes, got {len(scenes)}.")

    numbers = []
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {i} must be an object.")
        sn = scene.get("scene_number")
        if sn is None:
            raise ValueError(f"Scene {i} missing scene_number.")
        if not isinstance(sn, int):
            raise ValueError(f"Scene {i} scene_number must be an integer.")
        numbers.append(sn)
        for field in SCENE_STRING_FIELDS:
            if field not in scene:
                raise ValueError(f"Scene {i} missing field: {field}")
            val = scene[field]
            if not isinstance(val, str):
                raise ValueError(f"Scene {i} field {field} must be a string.")
            if not str(val).strip():
                raise ValueError(f"Scene {i} field {field} must be non-empty.")

    sorted_nums = sorted(numbers)
    if sorted_nums != list(range(5)):
        raise ValueError(
            f"scene_number values must be exactly 0,1,2,3,4 once each; got {sorted_nums}."
        )
