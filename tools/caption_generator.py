"""
Social caption + description packs for each video, from the production brief / script.
Uses the same Gemini text stack as tools.gemini_client.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from tools import generation_stats  # noqa: E402
from tools.gemini_client import _text_model_fallback_chain  # noqa: E402

CAPTION_INSTRUCTIONS = """You are writing social posts for PayTrust (Ghanaian escrow / online safety). You will receive the story behind a short vertical video.

Create between 3 and 5 completely original options. Each option must include:
- tone: a short label for the vibe (e.g. Suspense, Emotional, Debate, Humorous).
- caption: maximum 100 characters. No newlines.
- description: maximum 500 characters. No newlines.

Rules:
- Do NOT merely summarize. Each option must feel like a mini social post or cinematic hook.
- Vary tone and hook across options (suspense, emotional, debate-bait, humor/sarcasm, etc.).
- Use concrete details from the story (cities like Accra, Kumasi, Tamale; amounts; MoMo; Jiji; items).
- Write for a Ghanaian audience.
- Make each scroll-stopping and distinct.
- Do not exceed 5 options.

Output ONLY valid JSON (no markdown, no code fences) with this exact shape:
{"options":[{"tone":"","caption":"","description":""}, ...]}

CRITICAL: Do not use the double-quote character inside any JSON string value. Use straight apostrophes or rephrase. Each string must be a single line."""

MAX_CAPTION = 100
MAX_DESCRIPTION = 500
MIN_OPTIONS = 3
MAX_OPTIONS = 5


def _story_from_brief(brief: dict) -> str:
    lines = [
        f"Chosen trend: {brief.get('chosen_trend', '')}",
        f"Hook: {brief.get('hook', '')}",
        f"Narrative: {brief.get('narrative', '')}",
        f"Full script / narration:\n{brief.get('full_narration', '')}",
        f"CTA: {brief.get('cta', '')}",
    ]
    for s in brief.get("scenes") or []:
        lines.append(
            f"Scene {s.get('scene_number', '')}: on-screen line {s.get('text_overlay', '')} — {s.get('narration', '')}"
        )
    return "\n\n".join(lines)


def _call_gemini_json(user_prompt: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    from google import genai
    from google.genai.errors import ClientError, ServerError
    from google.genai.types import GenerateContentConfig

    client = genai.Client(api_key=api_key)
    full_prompt = f"{CAPTION_INSTRUCTIONS}\n\n---\n\nHere is the story:\n\n{user_prompt}"
    models = _text_model_fallback_chain()
    last_err: Exception | None = None
    raw = ""

    for model in models:
        logger.info("Captions: trying Gemini model %s", model)
        try:
            generation_stats.incr("gemini_text_calls")
            response = client.models.generate_content(
                model=model,
                contents=full_prompt,
                config=GenerateContentConfig(
                    temperature=0.85,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
        except (ServerError, ClientError) as e:
            last_err = e
            if e.code == 429 and isinstance(e, ClientError):
                logger.warning("Captions 429 on %s: %s", model, getattr(e, "details", e))
            if e.code in (404, 503, 429) and model != models[-1]:
                logger.warning("Captions: %s returned %s; next model", model, e.code)
                continue
            raise

        if hasattr(response, "text") and response.text:
            raw = response.text.strip()
        elif response.candidates and response.candidates[0].content.parts:
            raw = (response.candidates[0].content.parts[0].text or "").strip()
        if raw:
            break
        if model != models[-1]:
            continue

    if not raw:
        if last_err:
            raise last_err
        raise RuntimeError("Gemini returned empty caption response")

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            import json_repair

            repaired = json_repair.repair_json(raw, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
            if isinstance(repaired, str):
                return json.loads(repaired)
        except Exception as e:
            logger.warning("caption JSON repair failed: %s", e)
        raise


def _clamp_options(data: dict[str, Any]) -> list[dict[str, str]]:
    options = data.get("options") or []
    if not isinstance(options, list):
        raise ValueError("captions JSON missing options array")
    out: list[dict[str, str]] = []
    for item in options[:MAX_OPTIONS]:
        if not isinstance(item, dict):
            continue
        tone = str(item.get("tone", "General")).strip() or "General"
        cap = str(item.get("caption", "")).strip().replace("\n", " ")
        desc = str(item.get("description", "")).strip().replace("\n", " ")
        if len(cap) > MAX_CAPTION:
            cap = cap[: MAX_CAPTION - 1] + "…"
        if len(desc) > MAX_DESCRIPTION:
            desc = desc[: MAX_DESCRIPTION - 1] + "…"
        if cap or desc:
            out.append({"tone": tone, "caption": cap, "description": desc})
    if len(out) < MIN_OPTIONS:
        raise ValueError(f"Need at least {MIN_OPTIONS} caption options, got {len(out)}")
    return out


def _format_txt(options: list[dict[str, str]]) -> str:
    blocks = []
    for i, o in enumerate(options, start=1):
        blocks.append(
            f'Option {i} – {o["tone"]}\n'
            f'Caption: "{o["caption"]}"\n'
            f'Description: "{o["description"]}"'
        )
    return "\n\n".join(blocks) + "\n"


def generate_social_caption_pack(brief: dict) -> tuple[list[dict[str, str]], str]:
    """Return (options list, formatted .txt body)."""
    story = _story_from_brief(brief)
    data = _call_gemini_json(story)
    options = _clamp_options(data)
    return options, _format_txt(options)


def write_social_captions(brief: dict, output_dir: str | Path) -> Path | None:
    """
    Write social_captions.txt and social_captions.json next to the video.
    Returns path to .txt or None if skipped/failed.
    """
    if os.getenv("GEMINI_CAPTIONS_SKIP", "").lower() in ("1", "true", "yes"):
        logger.info("Social captions skipped (GEMINI_CAPTIONS_SKIP)")
        return None
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        options, txt_body = generate_social_caption_pack(brief)
    except Exception as e:
        logger.warning("Social caption generation failed: %s", e, exc_info=True)
        return None

    json_path = out / "social_captions.json"
    txt_path = out / "social_captions.txt"
    payload = {"options": options}
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    txt_path.write_text(txt_body, encoding="utf-8")
    logger.info("Social captions saved: %s, %s", txt_path.name, json_path.name)
    return txt_path
