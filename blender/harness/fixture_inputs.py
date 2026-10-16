"""Deterministic RGBA32F inputs for parity captures."""

import json
import math


def validate_bindings(bindings):
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("input bindings must be a nonempty mapping")
    for binding, spec in bindings.items():
        if (not isinstance(binding, str) or not binding or not isinstance(spec, dict)
                or not {"width", "height", "pixels"} <= set(spec)
                or set(spec) - {"width", "height", "pixels", "vertex_count"}):
            raise ValueError("invalid input texture %r" % binding)
        width, height = spec["width"], spec["height"]
        pixels = spec["pixels"]
        if (type(width) is not int or type(height) is not int or min(width, height) < 1
                or not isinstance(pixels, list) or len(pixels) != width * height * 4
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in pixels)):
            raise ValueError("invalid input pixels for %s" % binding)
        count = spec.get("vertex_count")
        if count is not None and (type(count) is not int or count < 1
                                  or count % 3 or count > width * height):
            raise ValueError("invalid input vertex count for %s" % binding)
    return bindings


def load(path):
    fixtures = json.loads(path.read_text())
    if not isinstance(fixtures, dict):
        raise ValueError("input fixtures must be a mapping")
    for name, bindings in fixtures.items():
        if not isinstance(name, str) or not name:
            raise ValueError("invalid input fixture name")
        validate_bindings(bindings)
    return fixtures


def make_frames(bindings, graph):
    from gpu.types import Buffer, GPUTexture
    from noisemaker_blender.runtime.inputs import InputFrame

    validate_bindings(bindings)
    declared = {binding for render_pass in graph.passes
                for binding in render_pass.get("inputs", {}).values()}
    if set(bindings) - declared:
        raise ValueError("fixture supplies undeclared graph inputs")
    frames = {}
    for binding, spec in bindings.items():
        texture = GPUTexture((spec["width"], spec["height"]), format="RGBA32F",
                             data=Buffer("FLOAT", len(spec["pixels"]), spec["pixels"]))
        frames[binding] = InputFrame(
            texture, spec["width"], spec["height"], 1, color_space="data",
            alpha_mode="straight", vertex_count=spec.get("vertex_count")).validate(binding)
    return frames
