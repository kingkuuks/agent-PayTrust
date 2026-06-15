"""
Agent 2 — The Strategist
Reads trend signals from the Listener, sends to Gemini,
receives a structured production brief with hook, scenes, narration.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


def run_strategist(trend_signals: list[dict]) -> dict:
    """Take trend signals, call Kimi, return a validated production brief."""
    from tools.gemini_client import generate_brief

    logger.info("=== Strategist Agent starting with %d signals ===", len(trend_signals))

    if not trend_signals:
        raise ValueError("No trend signals provided — nothing to strategize on")

    signals_json = json.dumps(trend_signals, indent=2)
    brief = generate_brief(signals_json)

    # Save brief
    today = datetime.now().strftime("%Y-%m-%d")
    brief_dir = DATA_DIR / "briefs"
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief_path = brief_dir / f"{today}_brief.json"

    with open(brief_path, "w") as f:
        json.dump(brief, f, indent=2)
    logger.info("Brief saved: %s", brief_path)

    logger.info(
        "=== Strategist Agent done: hook=%r, style=%s, %d scenes ===",
        brief.get("hook"),
        brief.get("visual_style"),
        len(brief.get("scenes", [])),
    )
    return brief


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_signals = [{
        "source": "twitter",
        "text": "I just lost GHS 2000 to a buyer who sent a fake MoMo screenshot. Selling online in Ghana is becoming too risky.",
        "user": "merchant_gh",
        "engagement": 450,
        "relevance_score": 9.5,
        "keyword": "fake screenshot payment",
    }]
    brief = run_strategist(test_signals)
    print(json.dumps(brief, indent=2))
