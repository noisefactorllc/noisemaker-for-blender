"""Render-graph pipeline — reference/04 §10 control flow.

Per frame: reset frame surface bindings, run each pass (honoring repeat-count and
skip conditions), ping-pong global outputs after each execution, persist state at
end of frame. Supports multi-frame settle and sampling for stateful effects.
"""
import math


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
    conds = p.get("conditions")
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


def render(backend, graph, time=0.25, frames=1, samples=None, timed=False):
    """Run `frames` frames. `timed` drives the stateful/feedback convention
    (reference/04 / godot timed-sampling): advancing time ((f+1)/600)%1 at dt=1/600,
    so sims evolve. If `samples` (set of frame indices) given, return {frame: array};
    else return the final render-surface array."""
    defaults = collect_default_uniforms(graph)
    backend.setup(graph, defaults)
    out_name = graph.render_surface  # surface name, e.g. "o1"
    sampled = {}
    for f in range(frames):
        if timed:
            t = ((f + 1) / 600.0) % 1.0
            engine = default_engine(backend.size, t, f, 1.0 / 600.0)
        else:
            engine = default_engine(backend.size, time, f)
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
        if samples is not None and f in samples:
            sampled[f] = backend.read_surface(out_name)
    if samples is not None:
        return sampled
    return backend.read_surface(out_name)
