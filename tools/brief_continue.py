"""
Prepare human-edited briefs for the ``--continue`` resume path.

Script apply, narration sync, overlay regeneration, and scene 4 defaults run here
before strict validation and asset generation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tools.narration_sync import normalize_text, sync_scene_narrations_from_full

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def apply_script_txt(brief: dict, script_path: Path) -> bool:
    """
    If ``script.txt`` exists and normalized text differs from ``full_narration``,
    apply it. Returns whether ``full_narration`` changed.
    """
    if not script_path.is_file():
        return False
    script_text = normalize_text(script_path.read_text(encoding="utf-8"))
    fn_existing = normalize_text(brief.get("full_narration", ""))
    if script_text and script_text != fn_existing:
        brief["full_narration"] = script_text
        logger.info(
            "script.txt superseded brief.json full_narration — resync will follow"
        )
        return True
    return False


def require_nonempty_full_narration(brief: dict) -> None:
    fn = brief.get("full_narration")
    if not isinstance(fn, str) or not str(fn).strip():
        raise ValueError(
            "full_narration is empty after applying script.txt; "
            "edit script.txt or fix brief.json"
        )


def ensure_scene4_defaults(brief: dict, brand: dict | None = None) -> None:
    """Fill empty scene 4 CTA fields from brand defaults."""
    website = (
        str((brand or {}).get("website", "PayTrustGH.com")).strip() or "PayTrustGH.com"
    )
    brand_name = str((brand or {}).get("name", "PayTrust")).strip() or "PayTrust"
    scenes = brief.get("scenes") or []
    scene4 = next(
        (s for s in scenes if isinstance(s, dict) and s.get("scene_number") == 4),
        None,
    )
    if scene4 is None:
        return
    if not str(scene4.get("text_overlay", "")).strip():
        scene4["text_overlay"] = website
    if not str(scene4.get("image_prompt", "")).strip():
        scene4["image_prompt"] = (
            f"Bright {brand_name} CTA end card, brand colors, large website text, "
            "confident hopeful mood"
        )


def prepare_brief_for_continue(brief: dict, brand: dict | None = None) -> bool:
    """
    Sync scene narrations from ``full_narration`` and regenerate visuals for scenes 0–3.

    Raises on failure. Returns whether narration was resplit.
    """
    narration_resplit = sync_scene_narrations_from_full(brief)
    from tools.gemini_client import regenerate_scene_visuals_from_narration

    regenerate_scene_visuals_from_narration(brief, [0, 1, 2, 3], brand)
    return narration_resplit


def load_brand() -> dict:
    brand_path = PROJECT_ROOT / "config" / "brand.json"
    with open(brand_path, encoding="utf-8") as f:
        return json.load(f)
