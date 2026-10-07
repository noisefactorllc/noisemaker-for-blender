"""Explicit scene-time mapping for new live sessions; legacy bake time is unchanged."""
from __future__ import annotations

from dataclasses import dataclass
import math


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class FrameRequest:
    frame: int
    subframe: float = 0.0
    fps: float = 24.0
    fps_base: float = 1.0
    origin_frame: int = 1
    loop_seconds: float = 10.0
    offset_seconds: float = 0.0
    fixed_step_seconds: float | None = None
    mode: str = "timeline"
    purpose: str = "preview"
    wall_seconds: float | None = None


@dataclass(frozen=True)
class ClockSample:
    elapsed_seconds: float
    normalized_time: float
    frame_index: int
    simulation_step: int
    fps_effective: float
    mode: str


def map_frame(request: FrameRequest) -> ClockSample:
    """Map scene or preview time without advancing any GPU state.

    ``wall_seconds`` is elapsed time since free-run began, supplied by the caller.
    Final and cache consumers are admitted only on the evaluated scene timeline.
    The offset affects shader phase, while fixed simulation steps remain anchored
    to the origin frame (or free-run start).
    """
    if request.mode not in ("timeline", "free_run"):
        raise ValueError("mode must be timeline or free_run")
    if request.purpose not in ("preview", "final", "cache"):
        raise ValueError("purpose must be preview, final or cache")
    if request.mode == "free_run" and request.purpose != "preview":
        raise ValueError("free_run is preview-only")
    if not isinstance(request.frame, int) or isinstance(request.frame, bool):
        raise TypeError("frame must be an integer")
    if not isinstance(request.origin_frame, int) or isinstance(request.origin_frame, bool):
        raise TypeError("origin_frame must be an integer")
    for name in ("subframe", "fps", "fps_base", "loop_seconds", "offset_seconds"):
        if not _finite(getattr(request, name)):
            raise ValueError("%s must be finite" % name)
    if not 0 <= request.subframe < 1:
        raise ValueError("subframe must be in [0, 1)")
    if request.fps <= 0 or request.fps_base <= 0 or request.loop_seconds <= 0:
        raise ValueError("fps, fps_base and loop_seconds must be positive")
    fps_effective = request.fps / request.fps_base
    step_seconds = request.fixed_step_seconds
    if step_seconds is None:
        step_seconds = 1 / fps_effective
    if not _finite(step_seconds) or step_seconds <= 0:
        raise ValueError("fixed_step_seconds must be positive and finite")
    if request.mode == "timeline":
        elapsed = (request.frame + request.subframe - request.origin_frame) / fps_effective
        frame_index = request.frame
    else:
        if not _finite(request.wall_seconds) or request.wall_seconds < 0:
            raise ValueError("free_run requires nonnegative wall_seconds")
        elapsed = request.wall_seconds
        frame_index = request.origin_frame + math.floor(elapsed * fps_effective)
    if not math.isfinite(elapsed):
        raise ValueError("mapped time is not finite")
    normalized = ((elapsed + request.offset_seconds) / request.loop_seconds) % 1.0
    step = max(0, math.floor(elapsed / step_seconds + 1e-9))
    return ClockSample(elapsed, normalized, frame_index, step, fps_effective, request.mode)
