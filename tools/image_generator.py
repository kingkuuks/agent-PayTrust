"""
Image generation pipeline:
  1) Gemini image models — GEMINI_IMAGE_MODEL, GEMINI_IMAGE_MODEL_FALLBACK, then built-ins.
  2) Pillow styled text cards — when every Gemini model fails or validation rejects output.

Then: composite text overlay on whatever background was produced.

Discover IDs your key can use:  python scripts/list_gemini_image_models.py
"""

import os
import io
import json
import random
import shutil
import logging
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from dotenv import load_dotenv

from tools import generation_stats

load_dotenv()
logger = logging.getLogger(__name__)

WIDTH = 1080
HEIGHT = 1920
NEGATIVE_SUFFIX = ". Do not include any text, watermarks, logos, or cartoon elements in the image."
# Minimal framing instruction (replaces the old verbose COMPOSITION_SUFFIX). The
# 9:16 aspect is also enforced via the model image_config + _fit_to_frame cover
# crop, so this only needs to discourage letterboxing.
FRAME_SUFFIX = " Vertical 9:16 full-frame photo, no black bars, no letterboxing."
# Single brand aesthetic (Task F / Q8): raw UGC phone realism, lightly cleaned.
# This is the one easily-tunable style knob when visual_style_profile=tiktok.
STYLE_STRING = (
    "authentic raw smartphone photo, real Ghanaian everyday setting, natural"
    " available light, candid and unposed, slightly imperfect, TikTok-native, not"
    " glossy, not studio, not a commercial"
)
# Optional continuity clause (invariant H, default off). Only appended when a
# reference image is actually supplied. Identity/lighting only — never pose,
# composition, or background copy (avoids the "reference collapse" failure mode).
CONTINUITY_CLAUSE = (
    " The reference image is for facial identity and lighting tone ONLY. Do not"
    " copy its pose, composition, framing, or background — compose this scene"
    " fresh from its own description."
)
PRODUCT_CONTINUITY_CLAUSE = (
    " The reference image shows the EXACT official jersey product. Reproduce every"
    " detail of that jersey faithfully in her hands: white base, black five-pointed"
    " star on the chest, red yellow green and blue geometric intersecting line"
    " pattern radiating from the star, black crew neck collar, Puma logo, Ghana"
    " Football Association crest. Do not simplify, alter, or invent the pattern."
)
# Scene 2 (agitation): override model bias toward happy faces
AGITATION_EMOTION_SUFFIX = " CRITICAL: The person must look frustrated, worried, or distressed. No smile. No happy expression."
# Enforce African depiction — single concise demographic anchor (deduplicated).
AFRICAN_REQUIREMENT = "Ghanaian or West African person, African setting, Ghana. "

# Genre-aware shot map (Task E): soft framing HINTS keyed by narrative_arc, one
# per photo scene (indices 0-3). Pure data, non-authoritative (invariant I7) —
# appended after the scene intent and stripped entirely when shot_map_enabled is
# off. Supports narrative pacing; never overrides the image_prompt.
SHOT_MAP = {
    "drama_arc": [
        "emotional close-up",
        "medium establishing shot",
        "tense over-the-shoulder shot",
        "reflective medium shot",
    ],
    "contrast_arc": [
        "bright reassuring medium shot",
        "wide establishing shot",
        "tense close-up",
        "thoughtful medium shot",
    ],
    "tutorial_arc": [
        "clear medium shot",
        "instructive over-the-shoulder shot",
        "cautionary close-up",
        "forward-looking medium shot",
    ],
    "resolution_arc": [
        "hopeful medium shot",
        "setup wide shot",
        "doubtful close-up",
        "confident relieved medium shot",
    ],
}
_DEFAULT_SHOTS = ["medium shot", "wide establishing shot", "close-up", "medium shot"]


def shot_phrase(narrative_arc: str, scene_index: int) -> str:
    """Soft framing hint for a photo scene; '' when out of range."""
    shots = SHOT_MAP.get(narrative_arc or "", _DEFAULT_SHOTS)
    if 0 <= scene_index < len(shots):
        return shots[scene_index]
    return ""

# Primary default if GEMINI_IMAGE_MODEL is unset — override in .env.
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
# After primary + GEMINI_IMAGE_MODEL_FALLBACK (comma-separated), deduped in order.
# Intentionally excludes deprecated gemini-2.5-flash-image-preview (stable primary is above).
_BUILT_IN_GEMINI_IMAGE_MODELS = [
    "gemini-3.1-flash-image-preview",  # Nano Banana 2 / Flash-class image
    "gemini-3-pro-image-preview",
    "nano-banana-pro-preview",  # Pro image alias some accounts list from ListModels
]

VISUAL_STYLE_MAP = {
    "dark_urgent": "low-key lighting, teal and orange color grade, high contrast, film grain, moody shadows",
    "clean_professional": "bright key light, white and blue palette, clean backgrounds, modern, minimal",
    "warm_community": "golden hour lighting, warm tones, earthy colors, natural light, community feel",
}

_current_style_prefix = ""
BRAND_ASSETS_DIR = Path(__file__).parent.parent / "config" / "brand_assets"


def _load_manifest() -> dict:
    manifest_path = BRAND_ASSETS_DIR / "manifest.json"
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def verify_brand_assets() -> list[str]:
    """
    Log which manifest-referenced brand assets are missing on disk.

    Phase 8 brand hygiene: the pipeline degrades gracefully when assets are
    absent (no watermark, no asset reuse), but that gap is otherwise invisible.
    Returns the list of missing filenames so callers can surface it.
    """
    try:
        manifest = _load_manifest()
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Brand asset manifest unreadable: %s", e)
        return []

    referenced: list[str] = []
    for entry in (manifest.get("branding") or {}).values():
        if isinstance(entry, dict) and entry.get("file"):
            referenced.append(entry["file"])
    for entry in manifest.get("scenes") or []:
        if isinstance(entry, dict) and entry.get("file"):
            referenced.append(entry["file"])

    missing = [f for f in referenced if not (BRAND_ASSETS_DIR / f).exists()]
    if missing:
        logger.warning(
            "Brand assets missing in %s (watermark/asset-reuse disabled for these): %s",
            BRAND_ASSETS_DIR.name,
            ", ".join(missing),
        )
    return missing


def _load_brand():
    brand_path = Path(__file__).parent.parent / "config" / "brand.json"
    with open(brand_path) as f:
        return json.load(f)


def _workflow() -> dict:
    """Read the ``workflow`` flag block from brand.json (empty dict on error)."""
    try:
        return _load_brand().get("workflow") or {}
    except Exception:
        return {}


def _cta_endcard_path() -> str | None:
    """Absolute path to the fixed CTA end-card image from brand.json.

    Returns ``None`` when ``cta_endcard_image`` is unset or the file is missing,
    in which case the final scene falls back to the generated styled text card.
    """
    try:
        rel = _load_brand().get("cta_endcard_image")
    except Exception:
        rel = None
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = Path(__file__).parent.parent / rel
    return str(p) if p.is_file() else None


def set_style_from_brief(brief: dict):
    """Lock the visual style prefix for this run.

    With ``visual_style_profile=tiktok`` (default) the single raw-UGC STYLE_STRING
    is used for every scene (Task F). With ``legacy`` the previous behavior is
    kept: the brief's ``style_description`` or the ``VISUAL_STYLE_MAP`` entry.
    """
    global _current_style_prefix
    profile = str(_workflow().get("visual_style_profile", "tiktok") or "tiktok")
    if profile == "tiktok":
        _current_style_prefix = STYLE_STRING
    else:
        style_desc = brief.get("style_description", "")
        visual_style = brief.get("visual_style", "dark_urgent")
        _current_style_prefix = style_desc or VISUAL_STYLE_MAP.get(
            visual_style, VISUAL_STYLE_MAP["dark_urgent"]
        )
    logger.info("Visual style locked (%s): %s", profile, _current_style_prefix)


def _hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


# ─── ASPECT / LETTERBOX ─────────────────────────────────────────────

def _strip_letterbox(img: Image.Image, threshold: int = 18) -> Image.Image:
    """
    Crop near-black horizontal bars baked into the top/bottom of a frame.

    Some image models return a "cinematic" letterboxed composition; left in
    place those bars survive the resize and clash with full-bleed scenes. We
    only trim bars in the outer thirds and bail out if trimming would remove
    most of the image (defensive against a genuinely dark photo).
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    step = max(1, w // 40)

    def row_is_dark(y: int) -> bool:
        for x in range(0, w, step):
            r, g, b = px[x, y]
            if r > threshold or g > threshold or b > threshold:
                return False
        return True

    top = 0
    while top < h // 3 and row_is_dark(top):
        top += 1
    bottom = h - 1
    while bottom > (h * 2) // 3 and row_is_dark(bottom):
        bottom -= 1

    if (top > 0 or bottom < h - 1) and (bottom - top) > h // 2:
        return rgb.crop((0, top, w, bottom + 1))
    return rgb


def _fit_contain_to_frame(img: Image.Image) -> Image.Image:
    """Scale to fit entirely inside the 9:16 frame; pad with brand secondary color."""
    rgb = img.convert("RGB")
    src_w, src_h = rgb.size
    scale = min(WIDTH / src_w, HEIGHT / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    resized = rgb.resize((new_w, new_h), Image.LANCZOS)
    try:
        secondary = _load_brand().get("secondary_color", "#0D1117")
        bg = tuple(int(secondary.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    except Exception:
        bg = (13, 17, 23)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), bg)
    canvas.paste(resized, ((WIDTH - new_w) // 2, (HEIGHT - new_h) // 2))
    return canvas


def _fit_to_frame(img: Image.Image, mode: str = "cover") -> Image.Image:
    """Strip letterbox bars, then fit to 9:16. ``cover`` crops; ``contain`` letterboxes."""
    cleaned = _strip_letterbox(img)
    if mode == "contain":
        return _fit_contain_to_frame(cleaned)
    return ImageOps.fit(cleaned, (WIDTH, HEIGHT), Image.LANCZOS)


# ─── PERCEPTUAL HASH (adjacency de-dupe safety net) ─────────────────

def dhash(path: str, hash_size: int = 8) -> int | None:
    """64-bit difference hash of an image, or None on failure.

    Resizes to (hash_size+1 x hash_size) grayscale and compares horizontally
    adjacent pixels. Used only as a cheap adjacency near-duplicate guard.
    """
    try:
        img = Image.open(path).convert("L").resize(
            (hash_size + 1, hash_size), Image.LANCZOS
        )
    except Exception as e:
        logger.warning("dhash failed for %s: %s", path, e)
        return None
    px = img.load()
    bits = 0
    for y in range(hash_size):
        for x in range(hash_size):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    """Hamming distance between two integer hashes."""
    return bin(a ^ b).count("1")


# ─── IMAGE VALIDATION ───────────────────────────────────────────────

def _validate_image(path: str) -> bool:
    """Check that an image file is usable: exists, big enough, opens, not blank."""
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < 50_000:
        logger.warning("Image too small: %d bytes", os.path.getsize(path))
        return False
    try:
        img = Image.open(path)
        img.verify()
        img = Image.open(path)
        if img.size[0] < 256 or img.size[1] < 256:
            logger.warning("Image dimensions too small: %s", img.size)
            return False
        pixels = [img.getpixel((random.randint(0, img.size[0] - 1), random.randint(0, img.size[1] - 1))) for _ in range(20)]
        unique = set(p[:3] if isinstance(p, tuple) and len(p) >= 3 else (p, p, p) for p in pixels)
        if len(unique) < 3:
            logger.warning("Image appears monochrome (%d unique colors in sample)", len(unique))
            return False
    except Exception as e:
        logger.warning("Image validation failed: %s", e)
        return False
    return True


# ─── TIER 1: GEMINI (multi-model chain) ──────────────────────────────

def _gemini_image_model_chain() -> list[str]:
    """Ordered Gemini model IDs to try for image output."""
    primary = (os.getenv("GEMINI_IMAGE_MODEL") or DEFAULT_GEMINI_IMAGE_MODEL).strip()
    chain: list[str] = []
    if primary:
        chain.append(primary)
    extra = os.getenv("GEMINI_IMAGE_MODEL_FALLBACK", "")
    for part in extra.split(","):
        m = part.strip()
        if m and m not in chain:
            chain.append(m)
    for m in _BUILT_IN_GEMINI_IMAGE_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


def _generate_gemini(
    prompt: str,
    output_path: str,
    model: str,
    reference_image_path: str | None = None,
    shot_hint: str = "",
    reference_mode: str = "identity",
) -> bool:
    """Generate image with a single Gemini model. Returns True on success.

    Prompt assembly (Task A) leads with the authoritative scene intent, then a
    soft shot hint, one style string, an identity-only continuity clause (only
    when a reference image is in play), a single demographic anchor, and minimal
    negatives. When ``reference_image_path`` is supplied it is passed alongside
    the prompt for optional same-protagonist continuity.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set, skipping Gemini")
        return False

    try:
        from google import genai
        from google.genai.errors import ClientError
        from google.genai.types import GenerateContentConfig, Modality

        client = genai.Client(api_key=api_key)

        # Open the optional identity reference first so the continuity clause is
        # appended only when a reference is actually used (invariant H).
        reference_image = None
        if reference_image_path and os.path.exists(reference_image_path):
            try:
                reference_image = Image.open(reference_image_path).convert("RGB")
            except Exception as e:
                logger.warning("Could not open reference image %s: %s", reference_image_path, e)
                reference_image = None

        style = _current_style_prefix or STYLE_STRING
        segments = [prompt.strip().rstrip(".")]
        if shot_hint:
            segments.append(shot_hint)
        segments.append(f"Style: {style}")
        if reference_image is not None:
            clause = (
                PRODUCT_CONTINUITY_CLAUSE
                if reference_mode == "product"
                else CONTINUITY_CLAUSE
            )
            segments.append(clause.strip().rstrip("."))
        segments.append(AFRICAN_REQUIREMENT.strip().rstrip("."))
        full_prompt = ". ".join(s for s in segments if s) + "." + FRAME_SUFFIX + NEGATIVE_SUFFIX

        logger.info("Gemini image (%s)%s: %s...", model, " [chained]" if reference_image else "", full_prompt[:80])

        contents = [reference_image, full_prompt] if reference_image is not None else full_prompt

        generation_stats.incr("gemini_image_calls")
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=GenerateContentConfig(
                response_modalities=[Modality.IMAGE],
                image_config={
                    "aspect_ratio": "9:16",
                },
            ),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image = Image.open(io.BytesIO(part.inline_data.data))
                image = _fit_to_frame(image)
                image.save(output_path, quality=95)
                if _validate_image(output_path):
                    generation_stats.incr("gemini_image_success")
                    logger.info("Gemini image saved (%s): %s (%dx%d)", model, output_path, WIDTH, HEIGHT)
                    return True
                logger.warning("Gemini image failed validation (%s)", model)
                return False

        logger.warning("Gemini response had no image data (%s)", model)
        return False
    except ClientError as e:
        if e.code == 429:
            logger.warning("Gemini image %s 429: %s", model, getattr(e, "details", e))
        else:
            logger.warning("Gemini image %s client error: %s", model, e)
        return False
    except Exception as e:
        logger.warning("Gemini image %s failed: %s", model, e)
        return False


def _try_gemini_image_models(
    prompt: str,
    output_path: str,
    reference_image_path: str | None = None,
    shot_hint: str = "",
    reference_mode: str = "identity",
) -> bool:
    """Try each Gemini image model in the chain until one succeeds."""
    models = _gemini_image_model_chain()
    if not models:
        return False
    logger.info("Gemini image model chain (%d): %s", len(models), ", ".join(models))
    for model in models:
        if _generate_gemini(
            prompt, output_path, model, reference_image_path, shot_hint, reference_mode
        ):
            return True
    return False


# ─── PILLOW STYLED CARDS ────────────────────────────────────────────

def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    if bold:
        candidates = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/Impact.ttf"]
    else:
        candidates = ["C:/Windows/Fonts/arial.ttf"]
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.Draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_noise(img: Image.Image, intensity: int = 15):
    """Add subtle noise texture to a background."""
    import struct
    pixels = img.load()
    for y in range(0, img.size[1], 3):
        for x in range(0, img.size[0], 3):
            r, g, b = pixels[x, y][:3] if isinstance(pixels[x, y], tuple) else (pixels[x, y],) * 3
            noise = random.randint(-intensity, intensity)
            pixels[x, y] = (max(0, min(255, r + noise)), max(0, min(255, g + noise)), max(0, min(255, b + noise)))


def _generate_hook_card(text_overlay: str, brand: dict) -> Image.Image:
    """Scene 0: Bold hook text, high contrast, accent bar."""
    bg = _hex_to_rgb(brand.get("secondary_color", "#0D1117"))
    accent = _hex_to_rgb(brand.get("accent_color", "#FFD700"))
    primary = _hex_to_rgb(brand.get("primary_color", "#1F6FEB"))

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)
    _draw_noise(img, 10)
    draw = ImageDraw.Draw(img)

    # Accent bar across upper portion
    bar_top = HEIGHT // 4
    bar_height = 8
    draw.rectangle([(60, bar_top), (WIDTH - 60, bar_top + bar_height)], fill=accent)

    # Large centered text
    font = _get_font(110)
    lines = _wrap_text(draw, text_overlay, font, WIDTH - 160)
    line_height = 130
    total_h = len(lines) * line_height
    y_start = (HEIGHT - total_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        y = y_start + i * line_height
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    # Brand at bottom
    small = _get_font(36, bold=False)
    brand_name = brand.get("name", "PayTrust")
    bbox = draw.textbbox((0, 0), brand_name, font=small)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, HEIGHT - 120), brand_name, font=small, fill=(*primary, ))

    return img


def _generate_problem_card(text_overlay: str, brand: dict, variant: int = 0) -> Image.Image:
    """Scenes 1-2: Dark textured gradient, colored underline, mid-frame text."""
    bg = _hex_to_rgb(brand.get("secondary_color", "#0D1117"))
    accent = (220, 50, 50) if variant == 0 else _hex_to_rgb(brand.get("primary_color", "#1F6FEB"))

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    # Diagonal gradient
    for y in range(HEIGHT):
        blend = y / HEIGHT
        if variant == 0:
            color = tuple(int(bg[i] * (1 - blend * 0.4) + 30 * blend * 0.4) for i in range(3))
        else:
            color = tuple(int(bg[i] * (1 - blend * 0.3) + accent[i] * blend * 0.15) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    _draw_noise(img, 12)
    draw = ImageDraw.Draw(img)

    # Text centered
    font = _get_font(88)
    lines = _wrap_text(draw, text_overlay, font, WIDTH - 160)
    line_height = 110
    total_h = len(lines) * line_height
    y_start = (HEIGHT - total_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        y = y_start + i * line_height
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    # Colored underline beneath last line of text
    last_y = y_start + (len(lines) - 1) * line_height + line_height + 10
    draw.rectangle([(WIDTH // 4, last_y), (WIDTH * 3 // 4, last_y + 6)], fill=accent)

    return img


def _generate_solution_card(text_overlay: str, brand: dict) -> Image.Image:
    """Scene 3: Brand blue gradient, hopeful upward feel."""
    dark = _hex_to_rgb(brand.get("secondary_color", "#0D1117"))
    primary = _hex_to_rgb(brand.get("primary_color", "#1F6FEB"))

    img = Image.new("RGB", (WIDTH, HEIGHT), dark)
    draw = ImageDraw.Draw(img)

    # Gradient: dark at top -> brand blue at bottom
    for y in range(HEIGHT):
        blend = (y / HEIGHT) ** 1.5
        color = tuple(int(dark[i] * (1 - blend) + primary[i] * blend * 0.7) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    _draw_noise(img, 8)
    draw = ImageDraw.Draw(img)

    # Subtle circle element
    cx, cy = WIDTH // 2, HEIGHT // 3
    for r in range(200, 220):
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=(*primary, ), width=1)

    # Text centered slightly below middle
    font = _get_font(88)
    lines = _wrap_text(draw, text_overlay, font, WIDTH - 160)
    line_height = 110
    total_h = len(lines) * line_height
    y_start = HEIGHT // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        y = y_start + i * line_height
        draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    return img


def _generate_cta_card(text_overlay: str, brand: dict) -> Image.Image:
    """Scene 4: Clean brand colors, large text, prominent brand name."""
    primary = _hex_to_rgb(brand.get("primary_color", "#1F6FEB"))
    dark = tuple(max(0, c - 40) for c in primary)

    img = Image.new("RGB", (WIDTH, HEIGHT), dark)
    draw = ImageDraw.Draw(img)

    # Solid brand gradient
    for y in range(HEIGHT):
        blend = y / HEIGHT
        color = tuple(int(dark[i] * (1 - blend * 0.3) + primary[i] * blend * 0.3) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)

    _draw_noise(img, 6)
    draw = ImageDraw.Draw(img)

    # Large CTA text
    font = _get_font(100)
    lines = _wrap_text(draw, text_overlay, font, WIDTH - 160)
    line_height = 120
    total_h = len(lines) * line_height
    y_start = (HEIGHT - total_h) // 2 - 80

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        y = y_start + i * line_height
        draw.text((x + 4, y + 4), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    # Brand name large
    brand_font = _get_font(72)
    brand_name = brand.get("name", "PayTrust")
    bbox = draw.textbbox((0, 0), brand_name, font=brand_font)
    bx = (WIDTH - (bbox[2] - bbox[0])) // 2
    by = y_start + total_h + 60
    accent = _hex_to_rgb(brand.get("accent_color", "#FFD700"))
    draw.text((bx, by), brand_name, font=brand_font, fill=accent)

    return img


def _generate_styled_card(scene_index: int, text_overlay: str) -> Image.Image:
    """Route to the right card generator based on scene position (text_card only)."""
    brand = _load_brand()
    if scene_index == 0:
        return _generate_hook_card(text_overlay, brand)
    elif scene_index in (1, 2):
        return _generate_problem_card(text_overlay, brand, variant=scene_index - 1)
    elif scene_index == 3:
        return _generate_solution_card(text_overlay, brand)
    else:
        return _generate_cta_card(text_overlay, brand)


def _generate_background_card(scene_index: int) -> Image.Image:
    """
    Text-free branded background for photo scenes when Gemini fails.

    No text is drawn here — the Remotion overlay supplies the caption so photo
    scenes never end up with two copies of the text.
    """
    brand = _load_brand()
    dark = _hex_to_rgb(brand.get("secondary_color", "#0D1117"))
    primary = _hex_to_rgb(brand.get("primary_color", "#1F6FEB"))

    img = Image.new("RGB", (WIDTH, HEIGHT), dark)
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        blend = (y / HEIGHT) ** 1.3
        color = tuple(int(dark[i] * (1 - blend) + primary[i] * blend * 0.45) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    _draw_noise(img, 10)
    return img


# ─── PHOTO FINALIZE (watermark only — text is live in Remotion) ──────

def _finalize_photo(background_path: str, output_path: str, fit_mode: str = "cover") -> str:
    """
    Resize a photo background to frame size and stamp the brand watermark.

    Phase 2: overlay text is no longer baked into photo scenes — it is rendered
    live by Remotion from the generated video-config. Only the small corner
    watermark is composited here.

    ``fit_mode``: ``cover`` (default, crop to fill) or ``contain`` (show full image).
    """
    img = _fit_to_frame(Image.open(background_path), mode=fit_mode).convert("RGBA")
    _add_icon_watermark(img)
    img.convert("RGB").save(output_path, quality=95)
    return output_path


def _add_icon_watermark(img: Image.Image, size: int = 48, margin: int = 30, opacity: float = 0.6):
    """Add the PayTrust icon as a small watermark in the bottom-right corner."""
    icon_path = BRAND_ASSETS_DIR / "icon.png"
    if not icon_path.exists():
        return
    try:
        icon = Image.open(icon_path).convert("RGBA").resize((size, size), Image.LANCZOS)
        alpha = icon.split()[3]
        alpha = alpha.point(lambda p: int(p * opacity))
        icon.putalpha(alpha)
        x = img.width - size - margin
        y = img.height - size - margin
        img.paste(icon, (x, y), icon)
    except Exception as e:
        logger.warning("Failed to add icon watermark: %s", e)


# ─── MAIN ENTRY POINT ───────────────────────────────────────────────

def generate_scene_image(
    scene_index: int,
    image_prompt: str,
    text_overlay: str,
    output_dir: str,
    visual_type: str = "photo",
    narration: str = "",
    reference_image_path: str | None = None,
    clean_copy_path: str | None = None,
    narrative_arc: str = "",
    brand_asset: str = "",
    asset_fit: str = "cover",
    reference_mode: str = "identity",
) -> str:
    """
    Produce scene_NN.png.

    - ``text_card``: a Pillow card whose typography *is* the design (text baked in).
    - ``photo``: a clean image (Gemini, explicit brand asset, or text-free fallback)
      with no baked caption — Remotion renders the caption live from video-config.

    ``reference_image_path``: when set, a previously generated scene image is fed to
    the model for optional same-protagonist continuity.
    ``clean_copy_path``: when set and a Gemini photo is produced, the pre-watermark
    frame is copied here to serve as the continuity anchor for later scenes.
    ``narrative_arc``: keys the soft shot-map hint (Task E); '' disables it.
    ``brand_asset``: explicit brand-asset path (Task G); used only when present.
    ``asset_fit``: ``cover`` (default) or ``contain`` for ``brand_asset`` screenshots.
    ``reference_mode``: ``identity`` (default) or ``product`` for exact product reproduction.
    """
    os.makedirs(output_dir, exist_ok=True)
    final_path = os.path.join(output_dir, f"scene_{scene_index:02d}.png")

    if visual_type == "text_card":
        generation_stats.incr("text_card_scenes")
        endcard = _cta_endcard_path()
        if endcard:
            logger.info(
                "Scene %d: text_card -- using fixed CTA end-card image %s",
                scene_index,
                os.path.basename(endcard),
            )
            _fit_to_frame(Image.open(endcard)).convert("RGB").save(final_path, quality=95)
            return final_path
        logger.info("Scene %d: text_card -- generating styled Pillow card", scene_index)
        card = _generate_styled_card(scene_index, text_overlay)
        card.save(final_path, quality=95)
        logger.info("Text card saved: %s", final_path)
        return final_path

    generation_stats.incr("photo_scenes")

    # visual_type == "photo": explicit brand asset -> Gemini chain -> text-free fallback.
    # Text is NOT baked in any of these paths.
    #
    # Brand assets are EXPLICIT-ONLY (Task G / Q6): used solely when a human sets a
    # ``brand_asset`` path on the scene. The previous keyword auto-pick is removed
    # because random product screenshots mid-story broke narrative flow.
    if brand_asset and os.path.exists(brand_asset):
        generation_stats.incr("brand_asset_scenes")
        fit = "contain" if asset_fit == "contain" else "cover"
        logger.info(
            "Scene %d: using explicit brand asset %s (fit=%s)",
            scene_index,
            os.path.basename(brand_asset),
            fit,
        )
        _finalize_photo(brand_asset, final_path, fit_mode=fit)
        return final_path

    bg_path = os.path.join(output_dir, f"bg_{scene_index:02d}.png")
    prompt = image_prompt
    if scene_index == 2:
        prompt = f"{image_prompt}{AGITATION_EMOTION_SUFFIX}"
        logger.info("Scene 2 (agitation): enforcing frustrated/worried expression")

    shot_hint = ""
    if _workflow().get("shot_map_enabled", True):
        shot_hint = shot_phrase(narrative_arc, scene_index)

    if _try_gemini_image_models(
        prompt, bg_path, reference_image_path, shot_hint, reference_mode
    ):
        if clean_copy_path:
            try:
                shutil.copyfile(bg_path, clean_copy_path)
            except OSError as e:
                logger.warning("Could not save continuity anchor copy: %s", e)
        _finalize_photo(bg_path, final_path)
        _cleanup(bg_path)
        return final_path

    generation_stats.incr("image_fallback_cards")
    logger.info("Scene %d: all Gemini image models failed; using text-free background card", scene_index)
    card = _generate_background_card(scene_index).convert("RGBA")
    _add_icon_watermark(card)
    card.convert("RGB").save(final_path, quality=95)
    return final_path


def _cleanup(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    out = os.path.join(os.path.dirname(__file__), "..", "output", "test_images")
    os.makedirs(out, exist_ok=True)

    # Test photo scene (Gemini). text_overlay is rendered live by Remotion, not baked here.
    generate_scene_image(
        scene_index=1,
        image_prompt="Close-up of a worried Ghanaian merchant staring at his phone, dramatic side lighting, shallow depth of field, dark market background",
        text_overlay="Fake Screenshots Everywhere",
        output_dir=out,
        visual_type="photo",
    )

    # Test text_card scene
    generate_scene_image(
        scene_index=0,
        image_prompt="",
        text_overlay="They Sent Proof. It Was Fake.",
        output_dir=out,
        visual_type="text_card",
    )

    print(f"Test images saved to {out}")
