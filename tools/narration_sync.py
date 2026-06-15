"""
Re-split scene narrations from full_narration when editors change full_narration only.

Collapsed whitespace matches TTS; comparisons use normalize_text().
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

SNAP_WINDOW = 20


def normalize_text(text: str) -> str:
    """Collapse whitespace runs to single ASCII spaces (strip-equivalent trimming).

    Intentional double spaces or newlines in full_narration are not preserved — TTS does not treat them distinctly.
    """
    return " ".join(text.split())


def _joined_scene_narrations(brief: dict[str, Any]) -> str:
    scenes = sorted(brief.get("scenes") or [], key=lambda s: s.get("scene_number", 0))
    parts = [str(s.get("narration", "") or "").strip() for s in scenes if isinstance(s, dict)]
    return " ".join(p for p in parts if p)


def _allocate_target_lengths(weights: list[int], total: int, n: int = 5) -> list[int]:
    """Proportional positive integer lengths summing to total; equal split if sum(weights)==0."""
    if len(weights) != n:
        raise ValueError("weights must have length 5")

    sw = sum(weights)
    if sw == 0:
        base, rem = divmod(total, n)
        return [base + (1 if j < rem else 0) for j in range(n)]

    ints = [math.floor((weights[i] / sw) * total) for i in range(n)]
    remainder = total - sum(ints)
    order = sorted(
        (((weights[i] / sw) * total - ints[i], i) for i in range(n)),
        key=lambda t: (-t[0], t[1]),
    )
    for j in range(remainder):
        ints[order[j][1]] += 1

    while any(z < 1 for z in ints) and sum(ints) >= n:
        richest = max(range(n), key=lambda i: ints[i])
        poorest = min(range(n), key=lambda i: ints[i])
        if ints[richest] <= ints[poorest]:
            break
        ints[richest] -= 1
        ints[poorest] += 1

    return ints


def _is_safe_word_cut(N: str, b: int) -> bool:
    """Reject mid-word cuts and splits that strand closing punctuation (? ! , . …) onto the wrong chunk for TTS."""
    if b <= 0 or b >= len(N):
        return False
    left, right = N[b - 1], N[b]

    # Mid-token letters/digits across the boundary (e.g. Nkora|nza)
    if left.isalnum() and right.isalnum():
        return False

    # Word then closing punctuation glue (e.g. hand|?)
    if left.isalnum() and right in "?!.;:,)\"'%":
        return False

    return True


def _first_safe_cut_from(N: str, start: int, hi: int) -> int:
    """Smallest ``b`` in [``start``, ``hi``] that is safe; else ``hi``."""
    hi = min(len(N) - 1, hi)
    start = max(1, start)
    for b in range(start, hi + 1):
        if _is_safe_word_cut(N, b):
            return b
    return hi


def _nearest_sentence_boundary(N: str, ideal: int, lo: int, hi: int) -> int | None:
    """
    Closest sentence-ending cut to ``ideal`` in [``lo``, ``hi``].

    Ends a sentence iff the character before the boundary is . ? or ! (tier-0 snaps only).
    This avoids VO chunks that orphan "You|" or "|demands".
    """
    lo = max(1, lo)
    hi = min(len(N) - 1, hi)
    if lo > hi:
        return None
    best_b: int | None = None
    best_abs = None
    for b in range(lo, hi + 1):
        if not _is_safe_word_cut(N, b):
            continue
        if N[b - 1] not in ".?!":
            continue
        delta = abs(b - ideal)
        if best_abs is None or delta < best_abs:
            best_abs = delta
            best_b = b
    return best_b


def _best_snap(N: str, ideal: int, lo: int, hi: int) -> int:
    """Exclusive boundary nearest ``ideal``, only safe word/token cuts; prefer .?! then whitespace."""
    lo = max(1, lo)
    hi = min(len(N) - 1, hi)
    if lo > hi:
        return max(1, min(len(N) - 1, ideal))

    safe_candidates = [b for b in range(lo, hi + 1) if _is_safe_word_cut(N, b)]
    if not safe_candidates:
        for radius in range(SNAP_WINDOW + 1, len(N) + 2):
            lo2 = max(1, ideal - radius)
            hi2 = min(len(N) - 1, ideal + radius)
            safe_candidates = [b for b in range(lo2, hi2 + 1) if _is_safe_word_cut(N, b)]
            if safe_candidates:
                lo, hi = lo2, hi2
                break

    if not safe_candidates:
        return max(lo, min(hi, ideal))

    best_b = safe_candidates[0]
    best_key: tuple[int, int] | None = None
    for b in safe_candidates:
        prev_ch = N[b - 1]
        if prev_ch in ".?!":
            tier = 0
        elif prev_ch.isspace():
            tier = 1
        else:
            tier = 2
        key = (abs(b - ideal), tier)
        if best_key is None or key < best_key:
            best_key = key
            best_b = b
    return best_b


def _split_normalized_full(N: str, old_lens: list[int]) -> tuple[list[str], str]:
    if len(N) < 5:
        raise ValueError(
            "full_narration is shorter than five characters — cannot emit five spoken scenes."
        )

    targets = _allocate_target_lengths(old_lens, len(N))
    boundaries: list[int] = []
    prev = 0
    for idx in range(4):
        tail_scenes_left = 4 - idx  # scenes after this cut incl. remainder
        hi_max = len(N) - tail_scenes_left
        ideal = min(prev + targets[idx], hi_max)
        lo_need = prev + 1

        snapped = _nearest_sentence_boundary(N, ideal, lo_need, hi_max)
        if snapped is None:
            snapped = _best_snap(
                N,
                ideal,
                max(lo_need, ideal - SNAP_WINDOW),
                min(hi_max, ideal + SNAP_WINDOW),
            )

        snapped = max(lo_need, min(snapped, hi_max))
        if boundaries:
            snapped = max(snapped, boundaries[-1] + 1)
        snapped = max(lo_need, min(_first_safe_cut_from(N, snapped, hi_max), hi_max))
        boundaries.append(snapped)
        prev = snapped

    b0, b1, b2, b3 = boundaries
    raw_slices = [N[:b0], N[b0:b1], N[b1:b2], N[b2:b3], N[b3:]]
    if "".join(raw_slices) != N:
        raise ValueError("Slice partition corrupted (internal bug).")

    stripped = [seg.strip() for seg in raw_slices]
    if any(not s for s in stripped):
        raise ValueError(
            "Resplit yielded an empty scene — lengthen full_narration or widen boundary snap."
        )

    canonical_full = normalize_text(" ".join(stripped))
    # ``canonical_full`` can differ whitespace-wise from partition ``N`` when slices are stripped
    # and re-joined — that is intentional; captions/TTS follow scene narrations plus this canonical full.

    return stripped, canonical_full


def sync_scene_narrations_from_full(brief: dict[str, Any]) -> bool:
    """
    If normalized full_narration differs from joined scene narrations,
    regenerate all five scenes[].narration from full_narration (proportional + snap).

    Sets brief[\"full_narration\"] to canonical whitespace form.

    Returns True when scenes changed; False when already aligned (no-op).
    """
    fn_raw = brief.get("full_narration")
    if fn_raw is None or not isinstance(fn_raw, str):
        raise ValueError("full_narration missing or not a string.")
    if not str(fn_raw).strip():
        raise ValueError("full_narration is empty.")

    scenes = sorted(brief.get("scenes") or [], key=lambda s: s.get("scene_number", 0))
    if len(scenes) != 5:
        raise ValueError(f"Expected exactly 5 scenes for narration sync, got {len(scenes)}.")

    N = normalize_text(fn_raw)
    joined_old = normalize_text(_joined_scene_narrations(brief))
    if N == joined_old:
        return False

    old_lens = [len(str((s.get("narration") or ""))) if isinstance(s, dict) else 0 for s in scenes]

    logger.info(
        "full_narration out of sync with scene narrations; resplitting (prior raw lens=%s)",
        old_lens,
    )

    scenes_by_num: dict[int, dict[str, Any]] = {}
    for s in scenes:
        if isinstance(s, dict) and isinstance(s.get("scene_number"), int):
            scenes_by_num[s["scene_number"]] = s

    parts, canon = _split_normalized_full(N, old_lens)
    for idx in range(5):
        box = scenes_by_num.get(idx)
        if box is None:
            raise ValueError(f"Missing scene_number {idx}")
        box["narration"] = parts[idx]

    brief["full_narration"] = canon

    chk = normalize_text(_joined_scene_narrations(brief))
    if chk != normalize_text(canon):
        raise ValueError("Brief scenes no longer aggregate to full_narration after sync.")

    logger.info(
        "Narration sync complete — new lengths=%s",
        [len(p) for p in parts],
    )
    return True
