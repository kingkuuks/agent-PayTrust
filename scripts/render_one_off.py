"""
Render a hand-crafted one-off video from output/one-off/<slug>/.

Does not invoke run.py or affect the daily escrow pipeline.

Usage:
    python scripts/render_one_off.py collectibles-jersey
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("render_one_off")


def one_off_dir(slug: str) -> Path:
    return (PROJECT_ROOT / "output" / "one-off" / slug).resolve()


def load_manifest(folder: Path) -> dict:
    path = folder / "one-off.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def apply_scene_overrides(folder: Path, manifest: dict) -> None:
    """Replace generated scene PNGs before Remotion assemble (paths relative to folder)."""
    overrides = manifest.get("scene_overrides") or {}
    if not overrides:
        return

    from PIL import Image

    from tools.image_generator import _fit_to_frame

    scenes_dir = folder / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    override_fit = str(manifest.get("override_fit", "contain"))

    for key, rel in overrides.items():
        try:
            scene_index = int(key)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid scene_overrides key: %r", key)
            continue
        src = (folder / rel).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"Scene override source missing: {src}")
        dest = scenes_dir / f"scene_{scene_index:02d}.png"
        img = _fit_to_frame(Image.open(src), mode=override_fit)
        img.convert("RGB").save(dest, quality=95)
        logger.info("Scene %d override applied: %s -> %s", scene_index, src.name, dest.name)


def render_one_off(slug: str) -> str:
    folder = one_off_dir(slug)
    if not folder.is_dir():
        raise FileNotFoundError(f"One-off folder not found: {folder}")

    brief_path = folder / "brief.json"
    if not brief_path.is_file():
        raise FileNotFoundError(f"Missing brief.json in {folder}")

    from tools.brief_validation import load_brief_json, validate_production_brief
    from agents.asset_builder import run_asset_builder
    from agents.assembler import run_assembler

    brief = load_brief_json(brief_path)
    validate_production_brief(brief)

    script_path = folder / "script.txt"
    if script_path.is_file():
        from tools.narration_sync import normalize_text, sync_scene_narrations_from_full

        script_text = normalize_text(script_path.read_text(encoding="utf-8"))
        fn_existing = normalize_text(brief.get("full_narration", ""))
        if script_text and script_text != fn_existing:
            brief["full_narration"] = script_text
            logger.info("script.txt superseded brief.json full_narration")
            sync_scene_narrations_from_full(brief)
            validate_production_brief(brief)
            brief_path.write_text(
                json.dumps(brief, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    manifest = load_manifest(folder)

    logger.info("=== One-off render: %s ===", slug)
    config, _ = run_asset_builder(
        brief,
        output_dir=folder,
        skip_continue_steps=True,
    )

    apply_scene_overrides(folder, manifest)

    scene_images = config.get("scene_images") or []
    for i, p in enumerate(scene_images):
        expected = folder / "scenes" / f"scene_{i:02d}.png"
        if expected.is_file():
            scene_images[i] = str(expected)

    video_path = run_assembler(config, skip_brief_write=True)

    (folder / "STATUS").write_text("complete\n", encoding="utf-8")
    logger.info("=== One-off complete: %s ===", video_path)
    return video_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a one-off custom video")
    parser.add_argument("slug", help="Folder name under output/one-off/")
    args = parser.parse_args()
    try:
        path = render_one_off(args.slug)
        print(f"\nVideo saved: {path}")
    except Exception as e:
        logger.error("%s", e, exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
