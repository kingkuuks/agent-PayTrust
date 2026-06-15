"""
List Gemini base models whose names suggest image / Imagen support.

Uses GEMINI_API_KEY from .env. Paste any IDs you want into .env:
  GEMINI_IMAGE_MODEL=...
  GEMINI_IMAGE_MODEL_FALLBACK=model-a,model-b

Usage (from paytrust-agent directory):
  python scripts/list_gemini_image_models.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    from google import genai

    client = genai.Client(api_key=api_key)
    seen: list[str] = []
    for m in client.models.list(config={"page_size": 100}):
        blob = f"{m.name or ''} {m.display_name or ''} {m.description or ''}".lower()
        if "image" in blob or "imagen" in blob:
            raw = m.name or ""
            mid = raw.split("/")[-1] if raw else ""
            if mid and mid not in seen:
                seen.append(mid)

    if not seen:
        print("No models matched 'image' / 'imagen' in name or description.")
        print("Try upgrading google-genai or check your API key project.")
        return

    print("Candidate image-related model IDs (try in GEMINI_IMAGE_MODEL / FALLBACK):\n")
    for mid in seen:
        print(mid)


if __name__ == "__main__":
    main()
