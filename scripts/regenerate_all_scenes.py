"""
Regenerate every scene image from output/<folder>/brief.json, then render video once.

Usage:
  python scripts/regenerate_all_scenes.py "output/2026-05-06_26 v"
"""
import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Regenerate all scene PNGs + one video render")
    parser.add_argument("output_folder", help='e.g. output/2026-05-06_26 v')
    args = parser.parse_args()

    out = Path(args.output_folder)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    if not out.is_dir():
        logger.error("Folder not found: %s", out)
        sys.exit(1)

    brief_path = out / "brief.json"
    config_path = out / "config.json"
    if not brief_path.exists() or not config_path.exists():
        logger.error("Need brief.json and config.json in %s", out)
        sys.exit(1)

    with open(brief_path, encoding="utf-8") as f:
        brief = json.load(f)
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    from tools.image_generator import set_style_from_brief, generate_scene_image
    from agents.assembler import run_assembler

    set_style_from_brief(brief)
    scenes_dir = out / "scenes"
    for idx in range(5):
        scene = brief["scenes"][idx]
        logger.info("--- Regenerating scene %d ---", idx)
        generate_scene_image(
            scene_index=idx,
            image_prompt=scene["image_prompt"],
            text_overlay=scene["text_overlay"],
            output_dir=str(scenes_dir),
            visual_type=scene.get("visual_type", "photo"),
            narration=scene.get("narration", ""),
        )

    config["brief"] = brief
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2, ensure_ascii=False)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False, default=str)

    video_path = run_assembler(config)
    logger.info("Video: %s", video_path)
    print(video_path)


if __name__ == "__main__":
    main()
