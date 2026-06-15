"""
Kimi K2.5 client via NVIDIA NIM (OpenAI-compatible API).
Sends trend signals to Kimi and receives a structured production brief.
"""

import os
import json
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You create 25-second vertical video briefs for PayTrust, a Ghanaian escrow payment app. Audience: merchants aged 20-45 who sell on WhatsApp, Instagram, Jiji. They fear fake MoMo screenshots and buyer fraud.

Structure follows PAS (Problem-Agitation-Solution):
- Scene 0 HOOK: Create an open loop. A statement that DEMANDS the viewer keeps watching. 8-12 words max. 3 seconds of audio.
- Scene 1 PROBLEM: Introduce the specific pain. Use "you" and "your". Name a city (Accra, Kumasi, Tamale). 20-28 words. 5-6 seconds.
- Scene 2 AGITATION: Escalate. Make it worse than scene 1. Specific amount in cedis. Emotional consequence. 20-28 words. 5-6 seconds.
- Scene 3 SOLUTION: The turn. PayTrust escrow fixes this. Relief. Confidence. 18-24 words. 5 seconds.
- Scene 4 CTA: Short, decisive, actionable. Direct viewers to PayTrustGH.com to download. For NARRATION (voiceover): spell the site as "Pay Trust G H dot com" so TTS pronounces it clearly. For text_overlay (on-screen): use "PayTrustGH.com". Do NOT mention Google Play or app stores. 8-12 words. 3 seconds.

Total narration must be under 90 words. Shorter is better.

Reply with ONLY a JSON object (no markdown):
{"chosen_trend":"the pain point","source_platform":"twitter","hook":"the hook text","narrative":"2 sentences","visual_style":"dark_urgent or clean_professional or warm_community","style_description":"1 sentence: color palette, lighting, mood for ALL scenes","scenes":[{"scene_number":0,"image_prompt":"cinematographic camera description","text_overlay":"max 6 words on screen","narration":"voiceover text","delivery":"fast_punchy or slow_emphatic or warm_confident or neutral"}],"full_narration":"all narration combined","cta":"call to action text"}

Every scene gets an image_prompt. Describe what the CAMERA sees:
- Camera angle (close-up, medium, wide), subject (who, pose, expression), lighting (side-lit, backlit, phone-glow), depth of field, color temperature, environment.
- Do NOT include text in the image. Text overlay is separate.
- Scene 0: striking visual that matches the hook emotion.
- Scene 4: confident, bright, hopeful image matching the CTA.
- Example: "Medium shot of a Ghanaian woman behind a market stall, looking at phone with furrowed brow, side-lit by afternoon sun, shallow bokeh, warm tones" """


def get_client():
    return OpenAI(
        base_url=os.getenv("NVIDIA_BASE_URL"),
        api_key=os.getenv("NVIDIA_API_KEY"),
        timeout=300,
    )


def generate_brief(trend_signals_json: str) -> dict:
    """Send trend signals to Kimi and get a structured production brief."""
    client = get_client()
    model = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.5")

    logger.info("Sending %d chars of trend data to Kimi (%s)", len(trend_signals_json), model)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": trend_signals_json},
        ],
        max_tokens=6000,
        temperature=0.7,
    )

    raw = response.choices[0].message.content
    if raw is None:
        reasoning = getattr(response.choices[0].message, "reasoning_content", "")
        logger.warning("Kimi returned no content (all tokens used by reasoning). Reasoning: %s", reasoning[:200] if reasoning else "none")
        raise RuntimeError("Kimi returned empty content — model used all tokens for reasoning. Try again.")
    raw = raw.strip()

    # Strip markdown code fences if Kimi wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
        raw = raw.strip()

    brief = json.loads(raw)
    _validate_brief(brief)
    logger.info("Received valid brief: hook=%r", brief.get("hook"))
    return brief


def _validate_brief(brief: dict):
    required_keys = [
        "chosen_trend", "hook", "narrative", "visual_style",
        "scenes", "full_narration", "cta",
    ]
    for key in required_keys:
        if key not in brief:
            raise ValueError(f"Brief missing required key: {key}")
    if "style_description" not in brief:
        brief["style_description"] = "dark moody lighting, teal and orange color grade, high contrast, film grain"
    if len(brief["scenes"]) != 5:
        raise ValueError(f"Expected 5 scenes, got {len(brief['scenes'])}")
    for i, scene in enumerate(brief["scenes"]):
        scene["visual_type"] = "photo"
        if "delivery" not in scene:
            scene["delivery"] = "fast_punchy" if i in (0, 4) else "neutral"
        scene.setdefault("image_prompt", "")
        for field in ("text_overlay", "narration"):
            if field not in scene:
                raise ValueError(f"Scene {i} missing field: {field}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_signals = json.dumps([{
        "source": "twitter",
        "text": "Just got scammed again on Instagram. Buyer sent a fake MoMo screenshot and disappeared with my goods. When will this end?",
        "engagement": 342,
        "relevance_score": 9.1,
    }])
    brief = generate_brief(test_signals)
    print(json.dumps(brief, indent=2))
