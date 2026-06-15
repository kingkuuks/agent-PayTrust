"""
Single source of truth for scene/transition frame math.

Used by the asset builder, the Remotion render-config writer, and tests so the
Python side and the generated Remotion config never disagree on timing.

Timing model (must match templates/MarketingVideo/src/MarketingVideo.tsx):
- base scene frames        = ceil(audioDuration * fps) + paddingFrames
- with TransitionSeries, every scene except the last is extended by
  transitionFrames so cross-scene audio never overlaps speech, while the
  composition total stays equal to the sum of base scene frames.
"""

from __future__ import annotations

import math

FPS = 30
DEFAULT_PADDING_FRAMES = 3
DEFAULT_TRANSITION_FRAMES = 10


def scene_base_frames(audio_duration: float, fps: int = FPS, padding_frames: int = DEFAULT_PADDING_FRAMES) -> int:
    """Frames a scene occupies based on its measured audio length plus tail padding."""
    return math.ceil(audio_duration * fps) + padding_frames


def base_frames_for_durations(
    durations: list[float],
    fps: int = FPS,
    padding_frames: int = DEFAULT_PADDING_FRAMES,
) -> list[int]:
    """Per-scene base frame counts for a list of audio durations (seconds)."""
    return [scene_base_frames(d, fps, padding_frames) for d in durations]


def total_composition_frames(
    durations: list[float],
    fps: int = FPS,
    padding_frames: int = DEFAULT_PADDING_FRAMES,
) -> int:
    """
    Total composition length in frames.

    With TransitionSeries this equals the sum of base scene frames: each of the
    (n-1) transitions shortens the timeline by transitionFrames, and we extend
    those same (n-1) outgoing scenes by transitionFrames, so the two cancel.
    """
    return sum(base_frames_for_durations(durations, fps, padding_frames))


def sequence_frames(
    base_frames: list[int],
    transition_frames: int = DEFAULT_TRANSITION_FRAMES,
) -> list[int]:
    """
    TransitionSeries.Sequence durations: every scene except the last gets a
    transition tail so the next scene's audio starts during silent padding,
    not over the prior narration.
    """
    if not base_frames:
        return []
    out = [b + transition_frames for b in base_frames[:-1]]
    out.append(base_frames[-1])
    return out
