"""
Lightweight per-run telemetry.

A process-global counter that pipeline steps increment as they make API calls and
produce assets. The asset builder snapshots it into config.json so later phases can
measure what changes (e.g. text_card scenes) actually save. Optional cost estimates
are derived from operator-supplied unit prices in brand.json (no prices are assumed).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_stats: dict[str, float] = {}


def reset() -> None:
    """Clear all counters. Call once at the start of a pipeline run."""
    _stats.clear()


def incr(key: str, n: float = 1) -> None:
    _stats[key] = _stats.get(key, 0) + n


def set_value(key: str, value) -> None:
    _stats[key] = value


def get(key: str, default: float = 0):
    return _stats.get(key, default)


def snapshot() -> dict:
    """Return a copy of current counters."""
    return dict(_stats)


# Counter keys (documented so call sites stay consistent):
#   gemini_text_calls     - Gemini text generate_content calls (brief, overlay refresh, captions)
#   gemini_image_calls    - Gemini image generate_content attempts (per model tried)
#   gemini_image_success  - image attempts that produced a valid image
#   photo_scenes          - scenes rendered as photos (route through Gemini)
#   text_card_scenes      - scenes rendered as Pillow text cards (skip Gemini image)
#   image_fallback_cards  - photo scenes that fell back to a text-free background card
#   brand_asset_scenes    - photo scenes satisfied by a reused brand asset (no Gemini call)
#   tts_calls             - edge-tts syntheses
#   tts_fallback_voice    - syntheses that used the fallback voice
#   render_seconds        - Remotion render wall time
#   captions_generated    - 1 if social captions were written, else 0


COST_UNIT_KEYS = {
    "gemini_text_calls": "gemini_text_call",
    "gemini_image_calls": "gemini_image_call",
    "tts_calls": "tts_call",
}


def apply_cost_estimate(stats: dict, brand: dict | None) -> dict:
    """
    Add a ``cost_estimate`` block to ``stats`` using operator-supplied unit prices.

    Reads ``brand["costs"]`` (a flat map of unit -> price). If no prices are
    configured, records the billable counts and a zeroed total so the estimate is
    explicit rather than invented.
    """
    costs_cfg = (brand or {}).get("costs") or {}
    breakdown: dict[str, float] = {}
    total = 0.0
    priced_any = False
    for count_key, unit_key in COST_UNIT_KEYS.items():
        count = float(stats.get(count_key, 0) or 0)
        unit_price = costs_cfg.get(unit_key)
        if isinstance(unit_price, (int, float)):
            priced_any = True
            line = count * float(unit_price)
            breakdown[count_key] = round(line, 6)
            total += line
    stats["cost_estimate"] = {
        "currency": costs_cfg.get("currency", "USD"),
        "prices_configured": priced_any,
        "breakdown": breakdown,
        "total": round(total, 6),
    }
    return stats
