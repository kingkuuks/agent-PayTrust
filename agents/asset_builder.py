"""
Agent 3 — The Asset Builder
Takes a production brief from the Strategist and generates all scene images
(Gemini image models, with Pillow text cards as fallback) and voiceover audio (edge-tts).
Returns a config dict with durations and file paths for the Assembler.
"""

import os
import json
import logging
from pathlib import Path

from tools import frame_math
from tools import generation_stats

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
MUSIC_DIR = PROJECT_ROOT / "music"
BRAND_PATH = PROJECT_ROOT / "config" / "brand.json"
FPS = frame_math.FPS


def load_padding_frames() -> int:
    """Read ``video.padding_frames`` from brand.json (once per process — restart if you edit brand mid-run).

    Clamped to ``[0, 60]``. Default **3** on missing or invalid JSON.
    """
    default = 3
    try:
        if not BRAND_PATH.is_file():
            return default
        with open(BRAND_PATH, encoding="utf-8") as f:
            data = json.load(f)
        video = data.get("video") or {}
        raw = video.get("padding_frames", default)
        n = int(raw)
        return max(0, min(n, 60))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning(
            "Invalid or missing brand video.padding_frames — using default %s",
            default,
        )
        return default


def load_transition_frames() -> int:
    """Read ``video.transition_frames`` from brand.json. Clamped to ``[0, 60]``. Default **10**."""
    default = frame_math.DEFAULT_TRANSITION_FRAMES
    try:
        if not BRAND_PATH.is_file():
            return default
        with open(BRAND_PATH, encoding="utf-8") as f:
            data = json.load(f)
        video = data.get("video") or {}
        raw = video.get("transition_frames", default)
        n = int(raw)
        return max(0, min(n, 60))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning(
            "Invalid or missing brand video.transition_frames — using default %s",
            default,
        )
        return default


PADDING_FRAMES = load_padding_frames()
TRANSITION_FRAMES = load_transition_frames()


def layout_for_scene(scene_index: int) -> str:
    """Layout is a function of scene role ONLY (invariant I5).

    Scenes 0-3 are photo frames; Scene 4 is the dedicated CTA card. The brief's
    ``visual_type`` field is never consulted for this decision, so a legacy or
    hand-edited value can never push a card into mid-story or vice versa.
    """
    return "text_card" if scene_index == 4 else "photo"

# Map visual_style from Kimi brief to royalty-free tracks in music/
BGM_STYLE_MAP = {
    "dark_urgent": "On The Flip - The Grey Room & Density & Time.mp3",
    "clean_professional": "For Our Friends - Telecasted.mp3",
    "warm_community": "From Here on In - Everet Almond.mp3",
}
BGM_DEFAULT = "Call me crazy - Patrick Patrikios.mp3"


def _pick_bgm(visual_style: str) -> str | None:
    """Pick a background music track based on visual style. Returns path or None."""
    if not MUSIC_DIR.exists():
        logger.warning("Music folder missing: %s — no background music", MUSIC_DIR)
        return None
    filename = BGM_STYLE_MAP.get(visual_style) or BGM_DEFAULT
    path = MUSIC_DIR / filename
    if path.exists():
        return str(path)
    # Fallback: use any track in music/
    for f in sorted(MUSIC_DIR.glob("*.mp3")):
        logger.info("BGM: using fallback track %s (no match for %s)", f.name, visual_style)
        return str(f)
    logger.warning("No MP3 files in %s — no background music", MUSIC_DIR)
    return None


def run_asset_builder(
    brief: dict,
    output_dir: Path | None = None,
    *,
    brief_path: Path | None = None,
    pre_run_brief_bytes: bytes | None = None,
    skip_continue_steps: bool = False,
) -> tuple[dict, bool]:
    """
    Generate all images + audio from a production brief.

    Returns ``(assembler_config_dict, narration_resplit_occurred)``.

    When ``output_dir`` is set (``--continue`` resume path):
    - narration fields are synced from ``full_narration`` when out of sync;
    - ALL photo scenes (0-3) have ``image_prompt`` + ``text_overlay`` regenerated
      from current narrations (I10 v2);
    - resolved ``brief.json`` is persisted before image generation when
      ``brief_path`` and ``pre_run_brief_bytes`` are supplied.

    Fresh runs omit resync and visual re-sync.
    """
    from tools.image_generator import generate_scene_image, set_style_from_brief, verify_brand_assets
    from tools.audio_generator import generate_scene_audio
    from tools.narration_sync import sync_scene_narrations_from_full

    logger.info("=== Asset Builder Agent starting ===")
    generation_stats.reset()
    verify_brand_assets()

    scenes = brief.get("scenes", [])
    if not scenes:
        raise ValueError("Brief has no scenes")

    narration_resplit = False
    if output_dir is not None and not skip_continue_steps:
        narration_resplit = sync_scene_narrations_from_full(brief)

    set_style_from_brief(brief)

    brand_path = PROJECT_ROOT / "config" / "brand.json"
    with open(brand_path) as f:
        brand = json.load(f)

    # I10 RESOLVE (v2): on every --continue, regenerate ALL photo-scene visuals from
    # current narrations so image_prompt cannot stay stale from a prior topic. Scene 4
    # CTA excluded. Persist resolved brief BEFORE image generation.
    if output_dir is not None and not skip_continue_steps:
        try:
            from tools.gemini_client import regenerate_scene_visuals_from_narration

            regenerate_scene_visuals_from_narration(brief, [0, 1, 2, 3], brand)
        except Exception as e:
            logger.warning(
                "Scene visual re-sync skipped (keeping existing image_prompt/text_overlay): %s",
                e,
            )
        if brief_path is not None and pre_run_brief_bytes is not None:
            backup_path = brief_path.parent / "brief.backup.json"
            backup_path.write_bytes(pre_run_brief_bytes)
            brief_path.write_text(
                json.dumps(brief, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "Wrote resolved brief.json and %s (pre-resolve copy) before image generation.",
                backup_path.name,
            )

    workflow = brand.get("workflow") or {}
    continuity_on = bool(workflow.get("continuity_clause_enabled", False))
    dedupe_on = bool(workflow.get("dedupe_retry_enabled", True))
    narrative_arc = str(brief.get("narrative_arc", "") or "")

    voice_cfg = brand.get("voice", {}) or {}
    base_voice = voice_cfg.get("tts_voice", "en-NG-AbeoNeural")
    # Optional per-delivery voice overrides (Phase 6). Absent by default — falls
    # back to the single brand voice, so behavior is unchanged unless configured.
    delivery_voices = voice_cfg.get("delivery_voices", {}) or {}

    if output_dir is not None:
        work_dir = Path(output_dir).resolve()
        timestamp = work_dir.name
    else:
        from tools.output_paths import allocate_output_run_dir

        work_dir = allocate_output_run_dir(PROJECT_ROOT)
        timestamp = work_dir.name
    scenes_dir = work_dir / "scenes"
    audio_dir = work_dir / "audio"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    scene_images = []
    audio_files = []
    durations = []

    scenes_ordered = sorted(scenes, key=lambda s: s.get("scene_number", 0))

    # Continuity anchor: the first photo scene's clean (pre-watermark) frame can
    # be reused as a reference for later scenes for same-protagonist continuity.
    # This is OPT-IN (continuity_clause_enabled, default off) — by default each
    # scene is composed fresh from its own image_prompt for maximum story variety.
    anchor_ref = scenes_dir / "_anchor_ref.png"
    prev_photo_hash = None

    for scene in scenes_ordered:
        idx = scene.get("scene_number", scenes_ordered.index(scene))
        logger.info("--- Building Scene %d ---", idx)

        # Layout is derived from scene index only (invariant I5); the brief
        # visual_type is never consulted here.
        layout = layout_for_scene(idx)

        is_anchor = idx == 0
        reference_image_path = (
            str(anchor_ref)
            if (continuity_on and not is_anchor and anchor_ref.exists())
            else None
        )
        clean_copy_path = str(anchor_ref) if (continuity_on and is_anchor) else None

        def _build_scene_image():
            return generate_scene_image(
                scene_index=idx,
                image_prompt=scene["image_prompt"],
                text_overlay=scene["text_overlay"],
                output_dir=str(scenes_dir),
                visual_type=layout,
                narration=scene.get("narration", ""),
                reference_image_path=reference_image_path,
                clean_copy_path=clean_copy_path,
                narrative_arc=narrative_arc,
                brand_asset=str(scene.get("brand_asset", "") or ""),
                asset_fit=str(scene.get("asset_fit", "cover") or "cover"),
            )

        image_path = _build_scene_image()

        # Adjacency de-dupe safety net (invariant I9): if this photo is nearly
        # identical to the previous photo frame, regenerate once. Not enforcement
        # — just a cheap guard against repeated near-duplicate stock poses.
        if dedupe_on and layout == "photo":
            from tools.image_generator import dhash, hamming

            this_hash = dhash(image_path)
            if (
                prev_photo_hash is not None
                and this_hash is not None
                and hamming(this_hash, prev_photo_hash) <= 8
            ):
                logger.info(
                    "Scene %d nearly duplicates the previous frame (dhash); regenerating once",
                    idx,
                )
                image_path = _build_scene_image()
                this_hash = dhash(image_path)
            if this_hash is not None:
                prev_photo_hash = this_hash

        scene_images.append(image_path)

        # Generate voiceover audio (per-delivery voice override if configured)
        delivery = scene.get("delivery", "neutral")
        scene_voice = delivery_voices.get(delivery, base_voice)
        audio_path, duration = generate_scene_audio(
            scene_index=idx,
            narration_text=scene["narration"],
            output_dir=str(audio_dir),
            voice=scene_voice,
            delivery=delivery,
        )
        audio_files.append(audio_path)
        durations.append(duration)

        logger.info("Scene %d complete: image=%s, audio=%.2fs", idx, os.path.basename(image_path), duration)

    if anchor_ref.exists():
        try:
            anchor_ref.unlink()
        except OSError:
            pass

    total_frames = frame_math.total_composition_frames(durations, FPS, PADDING_FRAMES)

    # Pick background music based on visual style
    bgm_path = _pick_bgm(brief.get("visual_style", "default"))
    if bgm_path:
        logger.info("Background music: %s", os.path.basename(bgm_path))

    stats = generation_stats.snapshot()
    generation_stats.apply_cost_estimate(stats, brand)

    config = {
        "timestamp": timestamp,
        "output_dir": str(work_dir),
        "scene_images": scene_images,
        "audio_files": audio_files,
        "durations": durations,
        "total_frames": total_frames,
        "scene_count": len(scenes),
        "brief": brief,
        "bgm_path": bgm_path,
        "generation_stats": stats,
    }

    # Save config
    config_path = work_dir / "config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2, default=str)
    logger.info("Config saved: %s", config_path)

    # Save script
    script_path = work_dir / "script.txt"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(brief.get("full_narration", ""))
    logger.info("Script saved: %s", script_path)

    logger.info(
        "=== Asset Builder done: %d scenes, total %.1fs (%.0f frames) ===",
        len(scenes), sum(durations), total_frames,
    )
    return config, narration_resplit


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_brief = {
        "chosen_trend": "Fake MoMo screenshots",
        "hook": "Stop Losing Money Today",
        "narrative": "Sellers lose thousands to fake payment screenshots. PayTrust escrow solves this.",
        "visual_style": "dark_urgent",
        "scenes": [
            {
                "scene_number": 0,
                "image_prompt": "Frustrated Ghanaian seller looking at phone with fake payment notification, dark moody lighting",
                "text_overlay": "Tired of Fake Payments?",
                "narration": "Every day, Ghanaian sellers lose money to fake MoMo screenshots. You send the goods, the payment never arrives.",
                "duration_hint": "medium",
            },
            {
                "scene_number": 1,
                "image_prompt": "Close up of mobile phone showing a forged mobile money screenshot, dramatic lighting",
                "text_overlay": "Fake Screenshots Everywhere",
                "narration": "Buyers forge payment confirmations that look completely real. By the time you check, they've disappeared with your product.",
                "duration_hint": "medium",
            },
            {
                "scene_number": 2,
                "image_prompt": "Stressed merchant counting losses at a market stall in Accra, warm but tense atmosphere",
                "text_overlay": "GHS 2000 Gone. Just Like That.",
                "narration": "One seller lost two thousand cedis in a single week. All from fake screenshots that looked genuine.",
                "duration_hint": "medium",
            },
            {
                "scene_number": 3,
                "image_prompt": "Secure digital shield protecting money transfer, blue glowing technology aesthetic",
                "text_overlay": "PayTrust Holds The Money",
                "narration": "With PayTrust, payment goes into escrow first. The buyer can't fake it — the money is verified before you ship.",
                "duration_hint": "medium",
            },
            {
                "scene_number": 4,
                "image_prompt": "Happy confident Ghanaian merchant using phone with PayTrust app, bright optimistic lighting",
                "text_overlay": "Sell With Confidence",
                "narration": "Join thousands of smart sellers protecting their business. Download PayTrust today — it's free.",
                "duration_hint": "short",
            },
        ],
        "full_narration": "Every day, Ghanaian sellers lose money to fake MoMo screenshots...",
        "cta": "Visit PayTrustGH.com to download — sell with confidence",
    }
    config, resplit_flag = run_asset_builder(test_brief)
    print("narration_resplit:", resplit_flag)
    print(json.dumps({k: v for k, v in config.items() if k != "brief"}, indent=2, default=str))
