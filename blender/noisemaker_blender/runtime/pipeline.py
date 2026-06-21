"""Minimal render-graph pipeline: ensure surfaces, feed engine uniforms, run passes
in order, read back the render surface. Multi-frame settle for stateless effects;
ping-pong / feedback / iteration-swap are P3. See ARCHITECTURE.md."""


def default_engine(size, time, frame):
    """Engine/system uniforms fed by name to every pass (see PORTING-GUIDE.md §engine)."""
    return {
        "resolution": [float(size), float(size)],
        "fullResolution": [float(size), float(size)],
        "tileOffset": [0.0, 0.0],
        "time": float(time),
        "aspect": 1.0,
        "aspectRatio": 1.0,
        "renderScale": 1.0,
        "frame": int(frame),
        "deltaTime": 1.0 / 60.0,
        "seed": 0,
    }


def render(backend, graph, time=0.25, frames=1):
    # Pre-create every surface referenced by the graph.
    for p in graph.passes:
        for tid in list(p.get("inputs", {}).values()) + list(p.get("outputs", {}).values()):
            backend.ensure_offscreen(graph.phys(tid))
    out_phys = graph.phys(graph.output_tex_id())
    backend.ensure_offscreen(out_phys)

    for f in range(frames):
        engine = default_engine(backend.size, time, f)
        for p in graph.passes:
            backend.execute(p, graph, engine)
    return backend.read(out_phys)
