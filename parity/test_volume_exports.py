#!/usr/bin/env python3
"""Volume handoffs through vol0-vol7 keep their producer's atlas size.

Ported from reference `shaders/tests/test_volume_surface_roundtrip.js` (the
expansion-time legs; the reference's live parameter-update legs have no
analogue here, because every bake recompiles the program). write3d exports the
producing volume's texture spec to the global surface, a reader resolves the
producer's volumeSize even when it precedes the writer (previous-frame
feedback), and a filter that rewrites its own input surface does not become the
size owner.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

from noisemaker_blender.compiler import compile_graph  # noqa: E402
from noisemaker_blender.runtime import graph_loader  # noqa: E402
from noisemaker_blender.runtime.pipeline import (  # noqa: E402
    collect_default_uniforms,
    resolve_dimension,
)

CORPUS = ROOT / "parity" / "corpus"
WIDTH, HEIGHT = 192, 128


def load(name):
    graph = graph_loader.Graph(compile_graph((CORPUS / ("%s.dsl" % name)).read_text()))
    return graph, collect_default_uniforms(graph)


def size(graph, uniforms, tex_id):
    spec = graph.textures[tex_id]
    return [resolve_dimension(spec["width"], WIDTH, uniforms),
            resolve_dimension(spec["height"], HEIGHT, uniforms)]


def passes(graph, func):
    return [p for p in graph.passes if p.get("func") == func]


class VolumeExportTests(unittest.TestCase):
    def test_each_export_keeps_its_own_atlas_size(self):
        graph, uniforms = load("volume_exports")
        for index, n in enumerate((16, 32)):
            for surface in ("vol", "geo"):
                self.assertEqual(size(graph, uniforms, "global_%s%d" % (surface, index)), [n, n * n])
        self.assertNotIn("global_o0", graph.textures)
        filters = passes(graph, "palette3d")
        self.assertEqual(len(filters), 2)
        for n, filter_pass in zip((16, 32), filters):
            self.assertEqual(size(graph, uniforms, filter_pass["outputs"]["fragColor"]), [n, n * n])
            self.assertEqual(filter_pass["uniforms"]["volumeSize"], n,
                             "a reader filter inherits its own volume size")
        self.assertEqual([p["uniforms"]["volumeSize"] for p in passes(graph, "renderLandscape3d")], [16, 32])

    def test_readers_before_their_writers_resolve_the_final_producer(self):
        graph, uniforms = load("volume_forward_reads")
        self.assertEqual(passes(graph, "palette3d")[0]["uniforms"]["volumeSize"], 16)
        for name in ("vol0", "geo0", "vol1", "geo1"):
            self.assertEqual(size(graph, uniforms, "global_" + name), [16, 256], name)

    def test_same_surface_rewrites_keep_the_producer_scope(self):
        graph, uniforms = load("volume_rewrites")
        for func in ("palette3d", "renderLandscape3d"):
            for render_pass in passes(graph, func):
                self.assertEqual(render_pass["uniforms"]["volumeSize"], 16, func)
        for name in ("vol0", "geo0"):
            self.assertEqual(size(graph, uniforms, "global_" + name), [16, 256], name)


if __name__ == "__main__":
    unittest.main()
