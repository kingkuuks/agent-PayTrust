"""
Regenerate one scene image from an output folder's brief.json, then re-render video.

Usage:
  python scripts/regenerate_one_scene.py "output/2026-05-06_26 v" --scene 1
  python scripts/regenerate_one_scene.py output/2026-04-01_06-43 --scene 1 --audio
"""
import argparse
import json
import logging
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Regenerate one scene PNG and re-render video")
    parser.add_argument(
        "output_folder",
        help="Path under output/ e.g. output/2026-05-06_26 v",
    )
    parser.add_argument(
        "--scene",
        type=int,
        default=1,
        help="Scene index 0-4 (default 1)",
    )
    parser.add_argument(
        "--audio",
        action="store_true",
        help="Regenerate TTS for this scene and update config durations + total_frames",
    )
    args = parser.parse_args()

    out = Path(args.output_folder)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    if not out.is_dir():
        logger.error("Folder not found: %s", out)
        sys.exit(1)

    idx = args.scene
    if idx < 0 or idx > 4:
        logger.error("scene must be 0-4")
        sys.exit(1)

    brief_path = out / "brief.json"
    config_path = out / "config.json"
    if not brief_path.exists():
        logger.error("Missing brief.json: %s", brief_path)
        sys.exit(1)
    if not config_path.exists():
        logger.error("Missing config.json: %s", config_path)
        sys.exit(1)

    with open(brief_path, encoding="utf-8") as f:
        brief = json.load(f)
    scene = brief["scenes"][idx]

    from tools.image_generator import set_style_from_brief, generate_scene_image
    from agents.assembler import run_assembler

    set_style_from_brief(brief)
    scenes_dir = out / "scenes"
    generate_scene_image(
        scene_index=idx,
        image_prompt=scene["image_prompt"],
        text_overlay=scene["text_overlay"],
        output_dir=str(scenes_dir),
        visual_type=scene.get("visual_type", "photo"),
        narration=scene.get("narration", ""),
    )
    logger.info("Regenerated %s", scenes_dir / f"scene_{idx:02d}.png")

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    if args.audio:
        from tools.audio_generator import generate_scene_audio
        from agents.asset_builder import FPS, PADDING_FRAMES

        brand_path = PROJECT_ROOT / "config" / "brand.json"
        with open(brand_path, encoding="utf-8") as bf:
            brand = json.load(bf)
        voice = brand.get("voice", {}).get("tts_voice", "en-NG-AbeoNeural")
        audio_dir = out / "audio"
        _, duration = generate_scene_audio(
            scene_index=idx,
            narration_text=scene["narration"],
            output_dir=str(audio_dir),
            voice=voice,
            delivery=scene.get("delivery", "neutral"),
        )
        durs = list(config.get("durations", []))
        while len(durs) <= idx:
            durs.append(3.0)
        durs[idx] = duration
        config["durations"] = durs
        config["total_frames"] = sum(math.ceil(d * FPS) + PADDING_FRAMES for d in durs)
        logger.info("Scene %d new audio duration: %.2fs", idx, duration)

    config["brief"] = brief
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2, ensure_ascii=False)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False, default=str)

    video_path = run_assembler(config)
    logger.info("Video: %s", video_path)


if __name__ == "__main__":
    main()
