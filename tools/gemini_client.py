"""
Gemini client for brief generation (replaces Kimi to avoid NVIDIA NIM timeouts).
Uses the same GEMINI_API_KEY as image generation. Fast, reliable on paid tier.
"""

import os
import json
import logging
from dotenv import load_dotenv

from tools import generation_stats

load_dotenv()
logger = logging.getLogger(__name__)

# gemini-2.0-flash is retired for new API keys; 2.5-flash is the stable text default.
DEFAULT_GEMINI_TEXT_MODEL = "gemini-2.5-flash"
# Cheaper / separate quota bucket in AI Studio; tried after 2.5-flash on 429.
FLASH_LITE_TEXT_MODEL = "gemini-2.5-flash-lite"
# Another tier (often separate limits on paid tier); see Gemini API model docs.
FLASH_LITE_31_TEXT_MODEL = "gemini-3.1-flash-lite-preview"

SYSTEM_PROMPT = """You create 25-second vertical video briefs for PayTrust, a Ghanaian PAYMENT ESCROW app. Audience: merchants aged 20-45 who sell on WhatsApp, Instagram, Jiji, Facebook Marketplace, and similar channels. They fear fake MoMo screenshots, ghosting after payment, and sending goods before money is really there.

WHAT PAYTRUST IS (read this before writing any scene)
- Buyer funds can be held in escrow. PayTrust holds the money securely until the buyer confirms they received what they paid for, under the product rules; then the seller is paid.
- The core problem PayTrust addresses: two sides who do not trust each other about who moves first — pay before the item arrives? ship before payment clears? release funds before the handover is real? That is the story space for every video.
- PayTrust transactions are short-term. The maximum holding period is 90 days. Do not write stories where funds are held for months or years — every escrow scenario must involve a payment that is expected to be released within days or weeks after delivery or handover.
- Rental, venue, and booking stories: use short-stay only (weekend let, holiday flat, single key handover). Full payment may be taken up front for that stay, but the release is tied to check-in or access — never frame multi-year residential rent, nine-month event deposits, or off-plan construction spanning years as how PayTrust works.

WHAT PAYTRUST IS NOT
- Not insurance for damaged goods, not a court for fine print, not compensation for bad workmanship discovered weeks later, not landlord–tenant law, not family-inheritance arbitration.
- Do NOT imply PayTrust settles liability for fire, flood, dry-cleaner burns, wedding-dress quality after multiple fittings, or visa-agent mistakes unless you rewrite the scenario into a stranger-to-stranger PAYMENT HOLD/STUCK FUNDS story (see FORBIDDEN / REQUIRED below).

FORBIDDEN STORY CENTER
- Do not build the main conflict around post-service liability, receipt font size, rent-control queues, or "who pays for the damage" unless the money can still be framed as stuck between buyer and seller in an online deal (rare — default to upfront scam / fake payment / pay-before-delivery).
- Non-escrow conflicts: do not let Scene 4 say "use PayTrust" to magically fix a debate that was never about paying a stranger online.
- Do not write scenarios that imply PayTrust should hold funds beyond 90 days (e.g. two years of rent upfront, multi-year off-plan builds, long retainers) — those misrepresent the product even if the payment-trust angle sounds plausible.

REQUIRED STORY CENTER
- Every video must hinge on a payment–trust gap: fake or spoofed payment, pressure to ship before confirmation, MoMo reversal, agent-in-the-middle, pay full upfront to someone you met online and they vanish, phishing number, wrong or empty box after paying, deposit taken and seller ghosts, funds that should stay held until delivery or handover is verified.

DISCOURSE FORMAT — provoke debate about PAYMENT TRUST, not abstract consumer harm. If the trend signals include a "DISCOURSE QUESTION", use it only if it is escrow-relevant (who sends first, is the money real, should goods move before payment clears). If the supplied question is about liability, tenancy, dress quality after months, or fine print, REPLACE it with an escrow-relevant question that still fits the scene emotions.
- Scene 0 HOOK: Open with the scenario. A statement that demands the viewer keeps watching. 8-15 words. 3 seconds.
- Scene 1 SETUP: Introduce the specific situation. Use "you" and "your". Name a city (Accra, Kumasi, Tamale, Takoradi, etc.). 20-28 words. 5-6 seconds.
- Scene 2 CONFLICT: What went wrong. Specific amount in cedis. The twist. 20-28 words. 5-6 seconds.
- Scene 3 DISCOURSE: Pose the question. Spark debate in comments — but the debate must be about payment timing, payment authenticity, or release of funds vs delivery. Offer 2-3 possibilities. Do NOT resolve with PayTrust yet. 20-30 words. 6-7 seconds.

DISCOURSE QUESTION QUALITY RULES (apply to every Scene 3)
- The question must be a genuine dilemma where both sides are arguable and reasonable people could disagree. If only one answer makes sense, rewrite it.
- The question must be stated in clear, conversational English that a real person would actually ask — not a clunky template fill. Read it aloud before finalising; if it sounds like a robot wrote it, rewrite it.
- The question must directly connect to the specific story details in scenes 1-2. Do not use the same generic phrasing across different stories. A dry cleaner story and a seamstress story must produce different questions.
- The question must be self-contained and make sense without reading the rest of the script. Avoid dangling clauses and incomplete comparisons. Bad example: "should payment be released before fabric is real?" Good example: "She paid full price to someone she'd never met. Should any first-time customer ever send 100% upfront before seeing a single stitch of work?"

- Scene 4 CTA: The turn. "Or skip the debate. Use PayTrust." Then: "Pay Trust G H dot com". For text_overlay: "PayTrustGH.com". Do NOT mention Google Play or app stores. 12-18 words. 3-4 seconds.

Total narration must be under 95 words. Shorter is better. Drive comments on who should have verified payment and who should move first — then CTA: skip the debate, use PayTrust.

VOICE-OVER TEXT (read aloud by TTS on every narration string plus full_narration)
- Punctuation matters: use straightforward sentence breaks. Prefer one clear sentence per thought; end with a period or a single question mark or exclamation when needed for tone.
- Avoid stacked punctuation (... ?! !!!), long semicolon chains, and strings of commas that force an unnatural single breath — they often sound clumsy or mumbled when synthesized.
- Do not use dramatic ellipses for pauses unless unavoidable; omit them unless the line truly needs trailing suspense.
- Ghanaian placenames are written normally and read as spoken words — e.g. Nkoranza is one word like any English word, not hyphenated syllables for effect. Same for other towns unless the signals explicitly demand a pronunciation note.

Before outputting the JSON, review the Scene 4 CTA against Scene 3. If "Or skip the debate. Use PayTrust." does not feel like a natural resolution to the debate you just posed — if PayTrust does not actually solve that specific trust problem — rewrite the debate so it does. The CTA must feel like the answer to the question, not a topic change.

CRITICAL JSON RULES: Output must be valid JSON. Do not put the double-quote character inside any string value. Rephrase (e.g. say Consumer Protection without quotes around it). Each string value must be a single line — no raw line breaks inside strings. Use straight ASCII quotes only.

CONTENT MODE — the trend signal will state CONTENT TYPE: scam_story, safety_tip, or win_story. Match it. Scene 0 is ALWAYS a hook and Scene 4 is ALWAYS the PayTrust CTA in every mode, and every escrow-accuracy rule applies in every mode. The REQUIRED/FORBIDDEN STORY CENTER, the loss requirement, and the Scene 1-3 DISCOURSE rules above apply to scam_story ONLY.
- scam_story: a loss or dispute story exactly as described above. Scene 3 is the DISCOURSE question (use the supplied discourse_question if escrow-relevant). narrative_arc: drama_arc or contrast_arc.
- safety_tip: NOT a victim story and NOT a loss. Teach how to stay safe when paying. Scenes 1-2 show the smart step or the avoidable mistake; Scene 3 poses a forward-looking question to the viewer. Helpful and confident, never preachy. narrative_arc: tutorial_arc.
- win_story: a POSITIVE outcome where PayTrust escrow makes the deal succeed. Do NOT frame it as a loss, scam, or regret. Scene 1 SETUP (who, what, named city, cedis amount), Scene 2 a moment of TENSION or doubt (a delayed payment, a dispute, dealing with a stranger), Scene 3 the RESOLUTION where PayTrust held the funds and released them on confirmation so both sides won — no debate. It must feel real and earned, not like an advert. narrative_arc: resolution_arc.

When the signal supplies a forward_question (safety_tip) or social_proof_prompt (win_story), put that text in Scene 3 text_overlay (the on-screen caption) and NOT in narration — the caption is shown on screen, the narration is read aloud and must keep telling the story.

ESCROW ACCURACY CHECK (all modes, win_story especially) — before output, confirm the story does not misrepresent PayTrust: funds are held and released on confirmation or handover; the maximum hold is 90 days; PayTrust is not insurance, not a court, not compensation for bad workmanship. A win story must stay realistic, never marketing fantasy.

NARRATIVE ARC — set narrative_arc to match the content mode. Scene 0 is ALWAYS the hook and Scene 4 is ALWAYS the PayTrust CTA. Keep a specific cedis amount and a named city.
- drama_arc (scam): Scene 1 SETUP, Scene 2 CONFLICT, Scene 3 DISCOURSE — as specified above.
- contrast_arc (scam): Scene 1 shows the deal going RIGHT (safe handover), Scene 2 shows the SAME kind of deal going wrong (scammed), Scene 3 is the DISCOURSE question about who should have moved first.
- tutorial_arc (safety): Scene 1 is the smart step to take, Scene 2 is the costly mistake to avoid, Scene 3 is the forward-looking question to the viewer.
- resolution_arc (win): Scene 1 SETUP, Scene 2 TENSION or doubt, Scene 3 PayTrust RESOLVES it positively (no debate).
Pick the arc that matches the stated content type.

VISUAL TYPE — set visual_type on every scene.
- Default every scene to "photo".
- Only Scene 4 (the CTA) may be "text_card"; Scenes 0, 1, 2, and 3 MUST be "photo". Scene 3 is a real photo of the protagonist with the caption rendered over it, not a flat card. Still write an image_prompt for the text_card scene.

Reply with ONLY a valid JSON object (no markdown, no code fences). Output complete JSON — do not truncate.
Schema: {"chosen_trend":"","hook":"","narrative":"","narrative_arc":"drama_arc|contrast_arc|tutorial_arc|resolution_arc","visual_style":"dark_urgent|clean_professional|warm_community","style_description":"","scenes":[{"scene_number":0,"image_prompt":"","text_overlay":"","narration":"","visual_type":"photo|text_card","delivery":"fast_punchy|slow_emphatic|warm_confident|neutral"}],"full_narration":"","cta":""}

You MUST set full_narration to the single string made by joining every scene's narration in order (scene 0 through 4), separated by single spaces — same text as the voice-over, no extra words.

Every scene gets an image_prompt. Describe what the CAMERA sees:
- Camera angle (close-up, medium, wide), subject (who, pose, expression), lighting (side-lit, backlit, phone-glow), depth of field, color temperature, environment.
- VISUAL VARIETY ACROSS SCENES: Scenes 0 through 3 each depict the narrated moment with ONE coherent setting and ONE focal subject. Let the setting follow each scene's narration naturally and avoid repeating the identical room, desk, or framing in every scene. A recurring protagonist is welcome but NOT required - different people may appear when the narration calls for it. Do NOT force a fixed storyboard template; just show each moment clearly in its own fitting location.
- CRITICAL - MATCH THE NARRATION: each image_prompt must depict the narrated moment of THAT scene - the specific subject, object, and action (the item, the phone, the person experiencing it), not an unrelated abstract mood. If the narration mentions a laptop deal, the scene shows that laptop deal.
- CRITICAL: ALL people in every scene MUST be Ghanaian or West African. Use "Ghanaian", "West African", or "African" in every image_prompt that shows a person. Never depict white or Caucasian people. This content is for Ghana.
- Do NOT include text in the image. Text overlay is separate.
- Scene 0: striking visual that matches the hook emotion and establishes the protagonist + setting.
- Scene 4: confident, bright, hopeful image matching the CTA (this is the only text_card scene).
- Example: "Medium shot of a Ghanaian woman behind a market stall, looking at phone with furrowed brow, side-lit by afternoon sun, shallow bokeh, warm tones" """


def _text_model_fallback_chain() -> list[str]:
    """Primary model first; optional env fallback; auto-stable fallback for preview/3.x models."""
    primary = os.getenv("GEMINI_TEXT_MODEL", DEFAULT_GEMINI_TEXT_MODEL)
    chain: list[str] = [primary]
    fb = os.getenv("GEMINI_TEXT_MODEL_FALLBACK")
    if fb and fb not in chain:
        chain.append(fb)
    pl = primary.lower()
    if ("preview" in pl or "gemini-3" in pl) and DEFAULT_GEMINI_TEXT_MODEL not in chain:
        chain.append(DEFAULT_GEMINI_TEXT_MODEL)
    # Separate RPM/TPM buckets; helps when preview + 2.5-flash return 429.
    if FLASH_LITE_TEXT_MODEL not in chain:
        chain.append(FLASH_LITE_TEXT_MODEL)
    if FLASH_LITE_31_TEXT_MODEL not in chain:
        chain.append(FLASH_LITE_31_TEXT_MODEL)
    return chain


def generate_brief(trend_signals_json: str) -> dict:
    """Send trend signals to Gemini and get a structured production brief."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set — cannot generate brief")

    from google import genai
    from google.genai.errors import ClientError, ServerError
    from google.genai.types import GenerateContentConfig

    client = genai.Client(api_key=api_key)
    models = _text_model_fallback_chain()
    last_err: Exception | None = None
    validation_err: ValueError | None = None

    for attempt in range(2):
        extra = ""
        if attempt == 1 and validation_err is not None:
            extra = f"""

CRITICAL — previous JSON failed validation: {validation_err}
Return ONLY valid JSON. Include every required key. full_narration must be non-empty (join all five scene narrations with spaces). Do not use double-quote characters inside string values — rephrase. No line breaks inside strings."""

        user_content = f"""Create a video brief from these trend signals:

{trend_signals_json}

Output a valid JSON object matching the schema.{extra}"""

        full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\n{user_content}"
        raw = ""

        for model in models:
            logger.info(
                "Sending %d chars of trend data to Gemini (%s) [attempt %d]",
                len(trend_signals_json),
                model,
                attempt + 1,
            )
            try:
                generation_stats.incr("gemini_text_calls")
                response = client.models.generate_content(
                    model=model,
                    contents=full_prompt,
                    config=GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    ),
                )
            except (ServerError, ClientError) as e:
                last_err = e
                if e.code == 429 and isinstance(e, ClientError):
                    logger.warning(
                        "Gemini %s 429 full details (for support / ai.dev): %s",
                        model,
                        getattr(e, "details", e),
                    )
                if e.code in (404, 503, 429) and model != models[-1]:
                    logger.warning("Gemini %s returned %s; retrying with next model", model, e.code)
                    continue
                raise

            if hasattr(response, "text") and response.text:
                raw = response.text
            elif response.candidates and response.candidates[0].content.parts:
                raw = response.candidates[0].content.parts[0].text
            else:
                raw = ""
            if raw:
                break
            if model != models[-1]:
                logger.warning("Gemini %s returned empty content; trying next model", model)
                continue

        if not raw:
            if last_err:
                raise last_err
            raise RuntimeError("Gemini returned empty content")

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")]
            raw = raw.strip()

        try:
            brief = _parse_brief_json(raw)
            _normalize_brief(brief)
            _validate_brief(brief)
            logger.info("Received valid brief: hook=%r", brief.get("hook"))
            return brief
        except ValueError as e:
            validation_err = e
            logger.warning("Brief validation failed (attempt %d): %s", attempt + 1, e)
            if attempt == 1:
                raise


def refresh_text_overlays_for_brief_scenes(brief: dict, brand: dict | None = None) -> None:
    """
    Rewrite ``text_overlay`` for scenes 0–3 via Gemini using current scene narrations.
    Forces scene 4 caption to ``brand["website"]`` (default PayTrustGH.com).

    Mutates ``brief`` in place.
    """
    scenes_in = sorted(brief.get("scenes") or [], key=lambda s: s.get("scene_number", 0))
    if len(scenes_in) != 5:
        raise ValueError(f"Expected 5 scenes; got {len(scenes_in)}")
    for s in scenes_in:
        if not isinstance(s, dict) or "narration" not in s:
            raise ValueError("Each scene must be a dict with narration")

    website = (
        str((brand or {}).get("website", "PayTrustGH.com")).strip() or "PayTrustGH.com"
    )
    hook = str(brief.get("hook", "") or "").strip()
    narration_lines = "\n".join(
        f"Scene {s['scene_number']}: {str(s.get('narration', '')).strip()}"
        for s in scenes_in
        if isinstance(s.get("scene_number"), int)
    )

    overlay_system = (
        "PayTrust Ghana escrow short vertical reels. Output ONLY JSON with key text_overlays: "
        "exactly four non-empty ASCII headline strings for on-screen captions matching scenes "
        "0,1,2,3 narration order (scene 4 is omitted). "
        "Map: 0=urgent hook, 1=setup, 2=conflict, 3=debate headline. "
        'No branded PayTrust wording in overlays 0-3. No double-quote character inside strings. '
        'Schema: {"text_overlays":["","","",""]} — single-line strings each under 82 characters.'
    )

    overlay_user = f"""Brief hook (context): {hook}

Narrations to match (write one overlay headline per scenes 0-3 ONLY):

{narration_lines}

Reply with ONLY JSON: {{"text_overlays":["","","",""]}}"""

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set — cannot refresh text overlays")

    from google import genai
    from google.genai.errors import ClientError, ServerError
    from google.genai.types import GenerateContentConfig

    client = genai.Client(api_key=api_key)
    full_prompt = f"{overlay_system}\n\n---\n\n{overlay_user}"
    models = _text_model_fallback_chain()
    last_err: Exception | None = None
    raw = ""

    for model in models:
        logger.info(
            "text_overlay refresh: Gemini %s (~%d chars)", model, len(full_prompt)
        )
        try:
            generation_stats.incr("gemini_text_calls")
            response = client.models.generate_content(
                model=model,
                contents=full_prompt,
                config=GenerateContentConfig(
                    temperature=0.5,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                ),
            )
        except (ServerError, ClientError) as e:
            last_err = e
            if e.code in (404, 503, 429) and model != models[-1]:
                logger.warning(
                    "Gemini %s returned %s; retry overlays with next model",
                    model,
                    e.code,
                )
                continue
            raise

        if getattr(response, "text", None):
            raw = response.text.strip()
        elif response.candidates and response.candidates[0].content.parts:
            raw = (response.candidates[0].content.parts[0].text or "").strip()
        else:
            raw = ""
        if raw:
            break
        if model != models[-1]:
            logger.warning(
                "Gemini %s empty overlay response; trying next model", model
            )
            continue

    if not raw:
        if last_err:
            raise last_err
        raise RuntimeError("Gemini returned empty overlay content")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = _parse_brief_json(raw)

    over = data.get("text_overlays")
    if not isinstance(over, list) or len(over) != 4:
        raise ValueError(f"Invalid text_overlays from model: {over!r}")
    trimmed: list[str] = []
    for piece in over:
        if not isinstance(piece, str):
            raise ValueError("overlay list must contain strings")
        t = piece.strip().replace('"', "").replace("\n", " ")
        while "  " in t:
            t = t.replace("  ", " ")
        if len(t) > 90:
            head = t[:87].strip()
            t = head.rsplit(" ", 1)[0] if " " in head else head
        if not t:
            raise ValueError("sanitised overlay line empty")
        trimmed.append(t)

    by_num: dict[int, dict] = {}
    for s in scenes_in:
        if isinstance(s, dict) and isinstance(s.get("scene_number"), int):
            by_num[s["scene_number"]] = s
    for sn in range(5):
        if sn not in by_num:
            raise ValueError(f"Missing scene {sn}")
    for i in range(4):
        by_num[i]["text_overlay"] = trimmed[i]
    by_num[4]["text_overlay"] = website

    logger.info(
        "text_overlay refresh applied scenes 0-3 + CTA %s",
        website,
    )


def regenerate_scene_visuals_from_narration(
    brief: dict, scene_indices: list[int], brand: dict | None = None
) -> None:
    """
    Resolve-step visual re-sync (invariant I10).

    For each requested PHOTO scene (0-3), regenerate BOTH ``image_prompt`` and
    ``text_overlay`` from that scene's CURRENT narration so the image and caption
    match an edited script. Mutates ``brief`` in place. Scene 4 (CTA) is never
    touched here; indices outside 0-3 are ignored. Scenes not listed are left
    unchanged. Raises on hard failure (caller treats as best-effort).
    """
    targets = sorted({i for i in scene_indices if isinstance(i, int) and 0 <= i <= 3})
    if not targets:
        return

    scenes_in = sorted(brief.get("scenes") or [], key=lambda s: s.get("scene_number", 0))
    by_num: dict[int, dict] = {
        s["scene_number"]: s
        for s in scenes_in
        if isinstance(s, dict) and isinstance(s.get("scene_number"), int)
    }
    for i in targets:
        if i not in by_num:
            raise ValueError(f"Missing scene {i} for visual re-sync")

    hook = str(brief.get("hook", "") or "").strip()
    narrative = str(brief.get("narrative", "") or "").strip()
    narration_lines = "\n".join(
        f"Scene {s['scene_number']}: {str(s.get('narration', '')).strip()}"
        for s in scenes_in
        if isinstance(s.get("scene_number"), int)
    )
    want = ", ".join(str(i) for i in targets)

    visual_system = (
        "You revise the VISUALS of selected scenes of a PayTrust Ghana short vertical video so they "
        "match an edited script. Output ONLY JSON. For each requested scene produce an image_prompt and "
        "a text_overlay that depict THAT scene's narrated moment. "
        "image_prompt: describe what the CAMERA sees - one coherent, real Ghanaian everyday setting and one "
        "focal subject/action taken from that scene's narration (the specific person, object, and action), not "
        "an abstract mood. ALL people MUST be Ghanaian or West African - state it. No baked-in text, captions, "
        "logos, or watermarks in the image. "
        "text_overlay: one short on-screen caption headline under 82 characters, ASCII only, no double-quote "
        "character, no PayTrust or branded wording. "
        'Schema: {"scenes":[{"scene_number":0,"image_prompt":"","text_overlay":""}]}'
    )
    visual_user = f"""Story hook (context): {hook}
Story summary (context): {narrative}

ALL current scene narrations (context - keep the story coherent):

{narration_lines}

Regenerate image_prompt AND text_overlay ONLY for these scene_numbers: {want}
Reply with ONLY JSON for exactly those scenes."""

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set — cannot regenerate scene visuals")

    from google import genai
    from google.genai.errors import ClientError, ServerError
    from google.genai.types import GenerateContentConfig

    client = genai.Client(api_key=api_key)
    full_prompt = f"{visual_system}\n\n---\n\n{visual_user}"
    models = _text_model_fallback_chain()
    last_err: Exception | None = None
    raw = ""

    for model in models:
        logger.info("scene visual re-sync: Gemini %s for scenes %s", model, want)
        try:
            generation_stats.incr("gemini_text_calls")
            response = client.models.generate_content(
                model=model,
                contents=full_prompt,
                config=GenerateContentConfig(
                    temperature=0.6,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                ),
            )
        except (ServerError, ClientError) as e:
            last_err = e
            if e.code in (404, 503, 429) and model != models[-1]:
                logger.warning(
                    "Gemini %s returned %s; retry visual re-sync with next model",
                    model,
                    e.code,
                )
                continue
            raise

        if getattr(response, "text", None):
            raw = response.text.strip()
        elif response.candidates and response.candidates[0].content.parts:
            raw = (response.candidates[0].content.parts[0].text or "").strip()
        else:
            raw = ""
        if raw:
            break
        if model != models[-1]:
            logger.warning(
                "Gemini %s empty visual re-sync response; trying next model", model
            )
            continue

    if not raw:
        if last_err:
            raise last_err
        raise RuntimeError("Gemini returned empty scene-visual content")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = _parse_brief_json(raw)

    out_scenes = data.get("scenes")
    if not isinstance(out_scenes, list) or not out_scenes:
        raise ValueError(f"Invalid scenes from model: {out_scenes!r}")

    applied: list[int] = []
    for item in out_scenes:
        if not isinstance(item, dict):
            continue
        sn = item.get("scene_number")
        if not isinstance(sn, int) or sn not in targets:
            continue

        ip = item.get("image_prompt")
        ov = item.get("text_overlay")
        if not isinstance(ip, str) or not isinstance(ov, str):
            raise ValueError(f"Scene {sn} missing image_prompt/text_overlay strings")

        ip_clean = " ".join(ip.replace("\n", " ").split()).strip()
        if not ip_clean:
            raise ValueError(f"Scene {sn} produced an empty image_prompt")
        if len(ip_clean) > 600:
            ip_clean = ip_clean[:600].rsplit(" ", 1)[0]

        ov_clean = ov.strip().replace('"', "").replace("\n", " ")
        while "  " in ov_clean:
            ov_clean = ov_clean.replace("  ", " ")
        if len(ov_clean) > 90:
            head = ov_clean[:87].strip()
            ov_clean = head.rsplit(" ", 1)[0] if " " in head else head
        if not ov_clean:
            raise ValueError(f"Scene {sn} produced an empty text_overlay")

        by_num[sn]["image_prompt"] = ip_clean
        by_num[sn]["text_overlay"] = ov_clean
        applied.append(sn)

    missing = [i for i in targets if i not in applied]
    if missing:
        raise ValueError(f"Model did not return visuals for scenes {missing}")

    logger.info("Scene visual re-sync applied for scenes %s", applied)


def _parse_brief_json(raw: str) -> dict:
    """Parse JSON, attempting repair if malformed (truncation, unescaped chars)."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed (%s), attempting repair", e)
    try:
        import json_repair

        repaired = json_repair.repair_json(raw, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        if isinstance(repaired, str):
            return json.loads(repaired)
    except Exception as repair_err:
        logger.warning("json_repair failed: %s", repair_err)
    # Try extracting JSON object (from first { to last balanced })
    start = raw.find("{")
    if start >= 0:
        depth = 0
        for i, c in enumerate(raw[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        pass
        repaired = raw[start:]
        if repaired.count('"') % 2 == 1:
            repaired = repaired.rstrip()
            if not repaired.endswith('"'):
                repaired += '"'
        for closer in ["]", "}", "]}", "}]"]:
            try:
                return json.loads(repaired + closer)
            except json.JSONDecodeError:
                pass
    raise ValueError("Could not parse brief JSON from model output")


def _normalize_brief(brief: dict) -> None:
    """Fill missing keys when JSON repair or the model drops fields (e.g. full_narration). Mutates brief."""
    if not isinstance(brief, dict):
        raise ValueError("Brief must be a dict")
    scenes = brief.get("scenes")
    if not isinstance(scenes, list):
        brief["scenes"] = []
        scenes = brief["scenes"]
    else:
        scenes = sorted(
            scenes,
            key=lambda s: s.get("scene_number", 0) if isinstance(s, dict) else 0,
        )
        brief["scenes"] = scenes

    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        scene.setdefault("scene_number", i)
        scene.setdefault("image_prompt", "")
        scene.setdefault("text_overlay", "")
        scene.setdefault("narration", "")
        scene.setdefault("delivery", "fast_punchy" if i in (0, 4) else "neutral")

    narrations = [str(s.get("narration", "")).strip() for s in scenes if isinstance(s, dict)]
    joined = " ".join(n for n in narrations if n)

    fn = brief.get("full_narration")
    if (fn is None or (isinstance(fn, str) and not str(fn).strip())) and joined:
        brief["full_narration"] = joined
        logger.info("Synthesized full_narration from scene narrations (%d chars)", len(joined))

    if not brief.get("narrative") and brief.get("hook"):
        brief["narrative"] = str(brief["hook"])
    if not brief.get("narrative") and joined:
        brief["narrative"] = joined[:800]

    if not brief.get("chosen_trend"):
        brief["chosen_trend"] = "topic_bank"

    if not brief.get("cta") and scenes:
        last = scenes[-1] if isinstance(scenes[-1], dict) else {}
        brief["cta"] = (
            str(last.get("narration", "")).strip()
            or "Or skip the debate. Use PayTrust. Pay Trust G H dot com."
        )

    if not brief.get("visual_style"):
        brief["visual_style"] = "dark_urgent"

    if brief.get("narrative_arc") not in ALLOWED_NARRATIVE_ARCS:
        brief["narrative_arc"] = "drama_arc"

    for i, scene in enumerate(scenes):
        if isinstance(scene, dict):
            scene["visual_type"] = _coerce_visual_type(scene.get("visual_type"), i)


ALLOWED_NARRATIVE_ARCS = {"drama_arc", "contrast_arc", "tutorial_arc", "resolution_arc"}
# text_card is only honored for the CTA (4) scene; every other scene - including
# scene 3 - falls back to photo so the protagonist carries through visually and
# the back half of the video is not a flat graphic card.
TEXT_CARD_SCENES = {4}


def _coerce_visual_type(value, scene_index: int) -> str:
    """Clamp visual_type to photo unless it is a valid text_card on scene 4 (CTA)."""
    if value == "text_card" and scene_index in TEXT_CARD_SCENES:
        return "text_card"
    return "photo"


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
    if brief.get("narrative_arc") not in ALLOWED_NARRATIVE_ARCS:
        brief["narrative_arc"] = "drama_arc"
    if len(brief["scenes"]) != 5:
        raise ValueError(f"Expected 5 scenes, got {len(brief['scenes'])}")
    for i, scene in enumerate(brief["scenes"]):
        scene["visual_type"] = _coerce_visual_type(scene.get("visual_type"), i)
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
