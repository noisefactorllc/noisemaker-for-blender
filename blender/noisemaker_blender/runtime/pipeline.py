"""Render-graph pipeline — reference/04 §10 control flow.

Per frame: reset frame surface bindings, run each pass (honoring repeat-count and
skip conditions), ping-pong global outputs after each execution, persist state at
end of frame. Supports multi-frame settle and sampling for stateful effects.
"""
import math
import re

_PASS_INDEX_RE = re.compile(r"_pass_(\d+)$")


def _pass_conditions(p):
    """Resolve a pass's gating conditions ({runIf/skipIf}).

    Conditions live on the EFFECT DEFINITION, not on the expanded/serialized graph
    (the reference golden graph omits them, so baking them into the graph would break
    graph parity). The reference Pipeline.shouldSkipPass likewise reads conditions off
    the effect-def pass at render time. We mirror that: prefer an inline `conditions`
    if a graph ever carries one, else map the built pass back to its effect-def pass
    (effectKey + `node_*_pass_<i>` index) and read conditions from the registry.

    Returns the conditions dict, or None.
    """
    inline = p.get("conditions")
    if inline:
        return inline
    key = p.get("effectKey") or p.get("effectFunc")
    if not key:
        return None
    m = _PASS_INDEX_RE.search(p.get("id") or "")
    if not m:
        return None
    idx = int(m.group(1))
    try:
        from ..compiler import registry
    except Exception:
        return None
    eff = registry.get_effect(key)
    if not eff:
        return None
    passes = eff.get("passes") or []
    if idx >= len(passes):
        return None
    return passes[idx].get("conditions")


def default_engine(size, time, frame, delta_time=0.0):
    return {
        "resolution": [float(size), float(size)],
        "fullResolution": [float(size), float(size)],
        "tileOffset": [0.0, 0.0],
        "time": float(time),
        "deltaTime": float(delta_time),
        "frame": int(frame),
        "aspect": 1.0,
        "aspectRatio": 1.0,
        "renderScale": 1.0,
        "seed": 0,
    }


def collect_default_uniforms(graph):
    """Merge every pass.uniforms (last-write-wins) — used for dimension/repeat resolution."""
    out = {}
    for p in graph.passes:
        out.update(p.get("uniforms", {}))
    return out


def should_skip(p, lookup):
    if p.get("skip") or p.get("_skip"):
        return True
    conds = _pass_conditions(p)
    if not conds:
        return False
    for c in conds.get("skipIf", []):
        v = lookup.get(c["uniform"], (p.get("uniforms") or {}).get(c["uniform"]))
        if v == c.get("equals"):
            return True
    for c in conds.get("runIf", []):
        v = lookup.get(c["uniform"], (p.get("uniforms") or {}).get(c["uniform"]))
        if v != c.get("equals"):
            return True
    return False


def resolve_repeat_count(p, lookup):
    rep = p.get("repeat")
    if rep is None:
        return 1
    if isinstance(rep, bool):
        return 1
    if isinstance(rep, (int, float)):
        return max(1, int(math.floor(rep)))
    if isinstance(rep, str):
        v = lookup.get(rep, (p.get("uniforms") or {}).get(rep))
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return max(1, int(math.floor(v)))
    return 1


def render(backend, graph, time=0.25, frames=1, timestep=0.0, samples=None):
    """Run `frames` frames, matching the reference golden harness stepping EXACTLY
    (parity/batch-golden.mjs): per frame `tt = (time + i*timestep) % 1`, and engine
    deltaTime = 0 on frame 0 else (tt - tt_prev) — the `lastTime>0` guard, raw diff
    (can go negative at the time wrap, which the speed-driven sims ignore).

    - timestep=0  -> fixed-time deterministic render (deltaTime stays 0): single-pass
      effects and N-frames-from-zero (the 8-frame points/agents convention).
    - timestep>0  -> continuous-solver / agent evolution to steady state (navierStokes,
      points sims): the babylon `_EVO` recipe is frames=1800, timestep=0.0016667 (30s @ 1/600).

    If `samples` (set of frame indices) given, return {frame: array}; else the final
    render-surface array."""
    defaults = collect_default_uniforms(graph)
    backend.setup(graph, defaults)
    out_name = graph.render_surface  # surface name, e.g. "o1"
    sampled = {}
    prev_tt = None
    for f in range(frames):
        tt = (time + f * timestep) % 1.0 if timestep else time
        dt = 0.0 if (prev_tt is None) else (tt - prev_tt)
        prev_tt = tt
        engine = default_engine(backend.size, tt, f, dt)
        lookup = dict(engine)
        lookup.update(defaults)
        backend.frame_begin()
        for p in graph.passes:
            if should_skip(p, lookup):
                continue
            count = resolve_repeat_count(p, lookup)
            for _ in range(count):
                backend.execute(p, graph, engine)
                for tid in p.get("outputs", {}).values():
                    backend.swap_after_write(tid)
        backend.frame_persist()
        # Force GPU submission periodically so long unsynced loops don't overflow Blender's
        # batched command stream (-> NaN / saturation). Read back the RENDER SURFACE (not an
        # arbitrary state surface): that forces the WHOLE frame's passes — including the
        # post-process chain — to complete, which a 1px read of an off-path surface does not
        # (the integration target's 32 passes/frame overflow otherwise). Every 30 frames.
        if timestep and (f % 30 == 29) and not (samples is not None and f in samples):
            backend.read_surface(out_name)
        if samples is not None and f in samples:
            sampled[f] = backend.read_surface(out_name)
    if samples is not None:
        return sampled
    return backend.read_surface(out_name)
