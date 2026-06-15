"""
Audio generator using edge-tts (Microsoft Edge TTS, free, unlimited).
Generates voiceover MP3 files and measures their durations.
"""

import os
import re
import asyncio
import logging
from pathlib import Path
from mutagen.mp3 import MP3
from dotenv import load_dotenv

from tools import generation_stats

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-US-AndrewNeural"
FALLBACK_VOICE = "en-US-GuyNeural"

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_LEXICON_PATH = _CONFIG_DIR / "pronunciation_lexicon.json"
_pronunciation_lexicon: dict[str, str] | None = None


def _load_pronunciation_lexicon() -> dict[str, str]:
    """Load surface -> speak_as map; empty if file missing."""
    global _pronunciation_lexicon
    if _pronunciation_lexicon is not None:
        return _pronunciation_lexicon
    _pronunciation_lexicon = {}
    if not _LEXICON_PATH.is_file():
        return _pronunciation_lexicon
    import json

    try:
        with open(_LEXICON_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not load pronunciation lexicon %s: %s", _LEXICON_PATH, e)
        return _pronunciation_lexicon
    if not isinstance(raw, dict):
        return _pronunciation_lexicon
    for k, v in raw.items():
        if not k.startswith("_") and isinstance(v, str) and v.strip():
            _pronunciation_lexicon[k] = v.strip()
    return _pronunciation_lexicon


def _apply_pronunciation_lexicon(text: str) -> str:
    """Replace whole words using config/pronunciation_lexicon.json (longest match first)."""
    lex = _load_pronunciation_lexicon()
    if not lex:
        return text
    for surface in sorted(lex.keys(), key=len, reverse=True):
        speak_as = lex[surface]
        pattern = re.compile(r"\b" + re.escape(surface) + r"\b", re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(speak_as, text)
    return text


# Replace GHS with cedis so TTS says "cedis" not "G H S"
def _amount_int_to_words(n: int) -> str:
    """Spell a non-negative integer for TTS — avoids digit-by-digit reading of plain numerals."""
    from num2words import num2words

    words = num2words(n, to="cardinal")
    # num2words (en) often inserts ", " — Edge TTS may treat that as an extra pause
    return words.replace(", ", " ").replace(",", " ")


def _replace_cedis_amounts_with_words(text: str) -> str:
    r"""Replace ``<digits> cedis`` (any case) with spoken words + ``cedis``.

    Runs after thousand-separator commas are stripped so digits are contiguous.
    """

    def repl(m: re.Match[str]) -> str:
        amt = int(m.group(1))
        return _amount_int_to_words(amt) + " cedis"

    return re.sub(r"\b(\d+)\s+(cedis)\b", repl, text, flags=re.IGNORECASE)


def _soften_money_label_colons(text: str) -> str:
    """Colons before amounts often cue a long TTS pause; a comma yields a shorter pause."""
    return re.sub(r"\bTotal:\s*", "Total, ", text, flags=re.IGNORECASE)


def _normalize_thousand_commas(text: str) -> str:
    """Strip commas used only as ASCII thousand-separators (Edge TTS often pauses on them).

    Uses the regex digit pattern one-to-three digits, then comma triplets. Examples: 45,000 → 45000.
    ``$45,000`` and decimals like 45,000.50 are not matched and are left unchanged.
    """

    def repl(m: re.Match[str]) -> str:
        whole = m.group(0).replace(",", "")
        return whole

    return re.sub(r"\b\d{1,3}(?:,\d{3})+\b", repl, text)


def _preprocess_for_tts(text: str) -> str:
    """Convert GHS amounts to 'X cedis'; drop thousand commas; apply Ghanaian pronunciation lexicon for TTS."""
    text = re.sub(r"GHS\s*(\d[\d,]*(?:\.\d+)?)", r"\1 cedis", text, flags=re.IGNORECASE)
    text = _normalize_thousand_commas(text)
    text = _soften_money_label_colons(text)
    text = _replace_cedis_amounts_with_words(text)
    text = _apply_pronunciation_lexicon(text)
    return text


DELIVERY_PARAMS = {
    "fast_punchy": {"rate": "+15%", "pitch": "+5Hz"},
    "slow_emphatic": {"rate": "-10%", "pitch": "-5Hz"},
    "warm_confident": {"rate": "+0%", "pitch": "+0Hz"},
    "neutral": {"rate": "+0%", "pitch": "+0Hz"},
}


async def _generate_audio_async(text: str, output_path: str, voice: str, rate: str = "+0%", pitch: str = "+0%") -> str:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)
    return output_path


def generate_audio(text: str, output_path: str, voice: str | None = None, delivery: str = "neutral") -> str:
    """Generate a single MP3 voiceover file from text."""
    if voice is None:
        voice = DEFAULT_VOICE

    text = _preprocess_for_tts(text)
    params = DELIVERY_PARAMS.get(delivery, DELIVERY_PARAMS["neutral"])

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    logger.info("Generating audio [%s]: %s... -> %s", delivery, text[:50], output_path)

    generation_stats.incr("tts_calls")
    try:
        asyncio.run(_generate_audio_async(text, output_path, voice, params["rate"], params["pitch"]))
    except Exception as e:
        logger.warning("Primary voice failed (%s), trying fallback: %s", voice, e)
        generation_stats.incr("tts_fallback_voice")
        asyncio.run(_generate_audio_async(text, output_path, FALLBACK_VOICE, params["rate"], params["pitch"]))

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
        raise RuntimeError(f"Audio generation failed for: {output_path}")

    logger.info("Audio saved: %s (%.1f KB)", output_path, os.path.getsize(output_path) / 1024)
    return output_path


def measure_duration(audio_path: str) -> float:
    """Measure the duration of an MP3 file in seconds."""
    audio = MP3(audio_path)
    duration = audio.info.length
    logger.info("Duration of %s: %.2f seconds", os.path.basename(audio_path), duration)
    return duration


def generate_scene_audio(
    scene_index: int,
    narration_text: str,
    output_dir: str,
    voice: str | None = None,
    delivery: str = "neutral",
) -> tuple[str, float]:
    """Generate audio for a single scene and return (path, duration_seconds)."""
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"audio_{scene_index:02d}.mp3")
    generate_audio(narration_text, output_path, voice, delivery)
    duration = measure_duration(output_path)
    return output_path, duration


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_dir = os.path.join(os.path.dirname(__file__), "..", "output", "test_audio")
    path, dur = generate_scene_audio(
        scene_index=0,
        narration_text="Are you tired of fake MoMo screenshots? Ghanaian sellers lose thousands of cedis every day to payment fraud.",
        output_dir=test_dir,
    )
    print(f"Test audio: {path} — Duration: {dur:.2f}s")
