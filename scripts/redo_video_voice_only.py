"""
Regenerate MP3 voiceover for every scene in an output folder, then render video once.

Reuses existing ``scenes/*.png`` and ``brief.json``. Pickup from ``config.json``: BGM path.

If ``script.txt`` exists and its normalized text differs from ``full_narration`` in ``brief.json``,
``script.txt`` wins (same rules as ``python run.py --continue``), then scene narrations are
re-split from ``full_narration`` when needed before TTS runs.

Typical usage after edits to ``script.txt``, TTS rules in ``tools/audio_generator.py``, or ``brand.json`` voice::

  python scripts/redo_video_voice_only.py output/YYYY-MM-DD_HH-mm

For an absolute folder path::

  python scripts/redo_video_voice_only.py \"C:\\\\PayTrust\\\\paytrust-agent\\\\output\\\\2026-04-14_12-49\"
"""
import math
import sys
import os
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def redo_one(output_dir: Path) -> str:

    brief_path = output_dir / "brief.json"
    script_path = output_dir / "script.txt"

    from tools.brief_validation import load_brief_json, validate_production_brief
    from tools.narration_sync import normalize_text, sync_scene_narrations_from_full

    try:
        brief = load_brief_json(brief_path)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {brief_path}: {e}") from e

    validate_production_brief(brief)

    if script_path.is_file():
        script_text = normalize_text(script_path.read_text(encoding="utf-8"))
        fn_existing = normalize_text(brief.get("full_narration", ""))
        if script_text and script_text != fn_existing:
            brief["full_narration"] = script_text
            logger.info(
                "%s — script.txt superseded brief.json full_narration; validating and syncing scenes",
                brief_path.parent.name,
            )
            validate_production_brief(brief)

    brand_path = PROJECT_ROOT / "config" / "brand.json"
    with open(brand_path, encoding="utf-8") as bf:
        brand = json.load(bf)
    voice = brand.get("voice", {}).get("tts_voice", "en-NG-AbeoNeural")

    from tools.audio_generator import generate_scene_audio
    from agents.asset_builder import FPS, PADDING_FRAMES

    if sync_scene_narrations_from_full(brief):
        logger.info(
            "%s scene narrations were regenerated from full_narration; saving brief.json",
            brief_path.parent.name,
        )
        brief_path.write_text(
            json.dumps(brief, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


    audio_dir = str(output_dir / "audio")
    scenes_ordered = sorted(brief["scenes"], key=lambda s: s.get("scene_number", 0))
    scene_images: list[str] = []
    for scene in scenes_ordered:
        idx = scene["scene_number"]
        png = output_dir / "scenes" / f"scene_{idx:02d}.png"
        if not png.is_file():
            raise FileNotFoundError(f"Missing scene image for scene_{idx:02d}: {png}")
        scene_images.append(str(png.resolve()))
    audio_files = []
    durations = []

    for scene in scenes_ordered:
        idx = scene["scene_number"]
        narration = scene["narration"]
        delivery = scene.get("delivery", "neutral")
        path, dur = generate_scene_audio(
            scene_index=idx,
            narration_text=narration,
            output_dir=audio_dir,
            voice=voice,
            delivery=delivery,
        )
        audio_files.append(path)
        durations.append(dur)

    config_path = output_dir / "config.json"
    bgm_path = None
    timestamp = output_dir.name
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            existing = json.load(f)
            bgm_path = existing.get("bgm_path") if os.path.exists(str(existing.get("bgm_path", ""))) else None
            timestamp = existing.get("timestamp", timestamp)

    total_frames = sum(math.ceil(d * FPS) + PADDING_FRAMES for d in durations)

    config = {
        "timestamp": timestamp,
        "output_dir": str(output_dir),
        "scene_images": scene_images,
        "audio_files": audio_files,
        "durations": durations,
        "total_frames": total_frames,
        "scene_count": len(scenes_ordered),
        "brief": brief,
        "bgm_path": bgm_path,
    }

    from agents.assembler import run_assembler
    video_path = run_assembler(config, skip_brief_write=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False, default=str)
    return video_path


def main():
    folders = sys.argv[1:] if len(sys.argv) > 1 else []
    if not folders:
        logger.error("Usage: python redo_video_voice_only.py <folder1> [folder2] ...")
        sys.exit(1)

    for folder in folders:
        output_dir = Path(folder) if Path(folder).is_absolute() else PROJECT_ROOT / folder
        if not output_dir.exists():
            logger.error("Folder not found: %s", output_dir)
            continue
        logger.info("=== Redoing %s ===", output_dir.name)
        vid = redo_one(output_dir)
        logger.info("Video saved: %s", vid)
        logger.info("")


if __name__ == "__main__":
    main()
