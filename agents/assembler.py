"""
Agent 4 — The Assembler
Takes the config from the Asset Builder, copies assets into the Remotion project,
updates TSX configs with real durations, and triggers the final video render.
"""

import os
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def _finalize_stats(config: dict, output_dir: str, render_seconds: float, captions_ok: bool) -> None:
    """Merge render + caption telemetry into config['generation_stats'] and persist config.json."""
    stats = dict(config.get("generation_stats") or {})
    stats["render_seconds"] = round(render_seconds, 1)
    stats["captions_generated"] = 1 if captions_ok else 0
    config["generation_stats"] = stats
    try:
        cfg_path = Path(output_dir) / "config.json"
        if cfg_path.is_file():
            existing = json.loads(cfg_path.read_text(encoding="utf-8"))
            existing["generation_stats"] = stats
            cfg_path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
            logger.info("generation_stats updated in %s: %s", cfg_path.name, stats)
    except (OSError, ValueError) as e:
        logger.warning("Could not persist generation_stats: %s", e)


def run_assembler(config: dict, skip_brief_write: bool = False) -> str:
    """Copy assets, update Remotion config, render video. Return output path."""
    from tools.remotion_runner import write_render_config, copy_assets_to_public, render_video

    logger.info("=== Assembler Agent starting ===")

    durations = config["durations"]
    scene_images = config["scene_images"]
    audio_files = config["audio_files"]
    output_dir = config["output_dir"]

    # Step 1: Copy generated assets into Remotion's public/ directory
    logger.info("Copying %d images + %d audio files to Remotion public/", len(scene_images), len(audio_files))
    bgm_path = config.get("bgm_path")
    copy_assets_to_public(scene_images, audio_files, bgm_path=bgm_path)

    # Step 2: Write the generated render config (single source of truth for the template)
    has_bgm = bool(bgm_path)
    total_frames = write_render_config(config, has_bgm=has_bgm)
    logger.info("Render config written: %d frames total", total_frames)

    # Step 3: Render the video
    video_path = os.path.join(output_dir, "video.mp4")
    render_started = datetime.now()
    render_video(video_path)
    render_seconds = (datetime.now() - render_started).total_seconds()

    # Step 4: Copy brief + script alongside the video (optional skip for human-reviewed brief.json)
    brief = config.get("brief", {})
    if not skip_brief_write:
        brief_path = os.path.join(output_dir, "brief.json")
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief, f, indent=2, ensure_ascii=False)

    script_text = brief.get("full_narration", "")
    script_path = os.path.join(output_dir, "script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_text)

    # Social captions + descriptions (Gemini, same brief as script)
    captions_ok = False
    try:
        from tools.caption_generator import write_social_captions

        captions_ok = write_social_captions(brief, output_dir) is not None
    except Exception as e:
        logger.warning("Social captions step failed (video still saved): %s", e)

    # Step 5: Finalize generation_stats with render + caption telemetry
    _finalize_stats(config, output_dir, render_seconds, captions_ok)

    file_size = os.path.getsize(video_path)
    logger.info(
        "=== Assembler Agent done: %s (%.1f MB) ===",
        video_path, file_size / 1_048_576,
    )
    return video_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Assembler agent — run via run.py or pass a config dict directly.")
