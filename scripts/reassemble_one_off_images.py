"""

Refresh scene images for a one-off project, then re-render video.



Usage:

    python scripts/reassemble_one_off_images.py collectibles-jersey

    python scripts/reassemble_one_off_images.py collectibles-jersey --with-voice

"""



from __future__ import annotations



import argparse

import json

import logging

import math

import os

import shutil

import sys

from pathlib import Path



PROJECT_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(PROJECT_ROOT))



logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",

)

logger = logging.getLogger("reassemble_one_off_images")





def one_off_dir(slug: str) -> Path:

    return (PROJECT_ROOT / "output" / "one-off" / slug).resolve()





def sync_root_assets(slug: str, folder: Path) -> None:

    """Copy refreshed screenshots from paytrust-agent root into assets/."""

    assets = folder / "assets"

    assets.mkdir(parents=True, exist_ok=True)

    pairs = [

        (PROJECT_ROOT / "collectibles.png", assets / "collectibles.png"),

        (PROJECT_ROOT / "collectiblescta.png", assets / "collectibles_cta.png"),

        (PROJECT_ROOT / "originaljersey.png", assets / "originaljersey.png"),

    ]

    for src, dest in pairs:

        if src.is_file():

            shutil.copy2(src, dest)

            logger.info("Synced %s -> %s", src.name, dest.relative_to(folder))





def sync_script_to_brief(folder: Path, brief: dict) -> dict:

    script_path = folder / "script.txt"

    if not script_path.is_file():

        return brief

    from tools.brief_validation import validate_production_brief

    from tools.narration_sync import normalize_text, sync_scene_narrations_from_full



    script_text = normalize_text(script_path.read_text(encoding="utf-8"))

    fn_existing = normalize_text(brief.get("full_narration", ""))

    if script_text and script_text != fn_existing:

        brief["full_narration"] = script_text

        sync_scene_narrations_from_full(brief)

        validate_production_brief(brief)

        (folder / "brief.json").write_text(

            json.dumps(brief, indent=2, ensure_ascii=False),

            encoding="utf-8",

        )

        logger.info("script.txt synced to brief.json")

    return brief





def apply_scene_overrides(folder: Path, manifest: dict) -> None:

    from PIL import Image



    from tools.image_generator import _fit_to_frame



    overrides = manifest.get("scene_overrides") or {}

    if not overrides:

        return

    override_fit = str(manifest.get("override_fit", "contain"))

    scenes_dir = folder / "scenes"

    scenes_dir.mkdir(parents=True, exist_ok=True)

    for key, rel in overrides.items():

        scene_index = int(key)

        src = (folder / rel).resolve()

        dest = scenes_dir / f"scene_{scene_index:02d}.png"

        img = _fit_to_frame(Image.open(src), mode=override_fit)

        img.convert("RGB").save(dest, quality=95)

        logger.info("Scene %d override (%s): %s", scene_index, override_fit, src.name)





def rebuild_images(folder: Path, brief: dict, manifest: dict) -> list[str]:

    from tools.image_generator import generate_scene_image, set_style_from_brief

    from agents.asset_builder import layout_for_scene



    set_style_from_brief(brief)

    scenes_dir = folder / "scenes"

    scenes_dir.mkdir(parents=True, exist_ok=True)

    narrative_arc = str(brief.get("narrative_arc", "") or "")



    jersey_ref = folder / "assets" / "originaljersey.png"

    if not jersey_ref.is_file():

        jersey_ref = folder / "assets" / "ghana_home_jersey.png"

    jersey_reference = str(jersey_ref) if jersey_ref.is_file() else None



    paths: list[str] = []

    for scene in sorted(brief.get("scenes", []), key=lambda s: s.get("scene_number", 0)):

        idx = scene["scene_number"]

        layout = layout_for_scene(idx)

        ref = jersey_reference if idx == 0 else None

        ref_mode = "product" if idx == 0 and ref else "identity"



        path = generate_scene_image(

            scene_index=idx,

            image_prompt=scene["image_prompt"],

            text_overlay=scene.get("text_overlay", ""),

            output_dir=str(scenes_dir),

            visual_type=layout,

            narration=scene.get("narration", ""),

            reference_image_path=ref,

            narrative_arc=narrative_arc,

            brand_asset=str(scene.get("brand_asset", "") or ""),

            asset_fit=str(scene.get("asset_fit", "cover") or "cover"),

            reference_mode=ref_mode,

        )

        paths.append(path)

        logger.info("Scene %d image: %s", idx, path)



    apply_scene_overrides(folder, manifest)

    for i, p in enumerate(paths):

        expected = scenes_dir / f"scene_{i:02d}.png"

        if expected.is_file():

            paths[i] = str(expected.resolve())



    return paths





def regenerate_voice(folder: Path, brief: dict, scene_images: list[str]) -> dict:

    from agents.asset_builder import FPS, PADDING_FRAMES

    from tools.audio_generator import generate_scene_audio



    brand_path = PROJECT_ROOT / "config" / "brand.json"

    with open(brand_path, encoding="utf-8") as f:

        brand = json.load(f)

    voice = brand.get("voice", {}).get("tts_voice", "en-NG-AbeoNeural")



    audio_dir = str(folder / "audio")

    scenes_ordered = sorted(brief["scenes"], key=lambda s: s.get("scene_number", 0))

    audio_files: list[str] = []

    durations: list[float] = []



    for scene in scenes_ordered:

        idx = scene["scene_number"]

        path, dur = generate_scene_audio(

            scene_index=idx,

            narration_text=scene["narration"],

            output_dir=audio_dir,

            voice=voice,

            delivery=scene.get("delivery", "neutral"),

        )

        audio_files.append(path)

        durations.append(dur)

        logger.info("Scene %d audio: %.1fs", idx, dur)



    total_frames = sum(math.ceil(d * FPS) + PADDING_FRAMES for d in durations)

    return {

        "scene_images": scene_images,

        "audio_files": audio_files,

        "durations": durations,

        "total_frames": total_frames,

        "scene_count": len(scenes_ordered),

    }





def reassemble(slug: str, with_voice: bool = False) -> str:

    folder = one_off_dir(slug)

    brief_path = folder / "brief.json"

    config_path = folder / "config.json"

    manifest_path = folder / "one-off.json"



    if not brief_path.is_file():

        raise FileNotFoundError(f"Missing {brief_path}")

    if not config_path.is_file():

        raise FileNotFoundError(f"Missing {config_path} — run a full render first")



    from tools.brief_validation import load_brief_json, validate_production_brief

    from agents.assembler import run_assembler



    sync_root_assets(slug, folder)

    brief = load_brief_json(brief_path)

    brief = sync_script_to_brief(folder, brief)

    validate_production_brief(brief)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}



    scene_images = rebuild_images(folder, brief, manifest)



    with open(config_path, encoding="utf-8") as f:

        config = json.load(f)



    if with_voice:

        voice_data = regenerate_voice(folder, brief, scene_images)

        config.update(voice_data)

    else:

        config["scene_images"] = scene_images



    config["brief"] = brief

    if not config.get("bgm_path") or not os.path.exists(str(config.get("bgm_path", ""))):

        config["bgm_path"] = None



    video_path = run_assembler(config, skip_brief_write=True)

    config_path.write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")

    (folder / "STATUS").write_text("complete\n", encoding="utf-8")

    return video_path





def main() -> None:

    parser = argparse.ArgumentParser(description="Reassemble one-off video with refreshed images")

    parser.add_argument("slug", help="Folder under output/one-off/")

    parser.add_argument(

        "--with-voice",

        action="store_true",

        help="Regenerate TTS from updated script/brief before assemble",

    )

    args = parser.parse_args()

    try:

        path = reassemble(args.slug, with_voice=args.with_voice)

        print(f"\nVideo saved: {path}")

    except Exception as e:

        logger.error("%s", e, exc_info=True)

        print(f"Error: {e}", file=sys.stderr)

        sys.exit(1)





if __name__ == "__main__":

    main()

