"""Load a normalized render-graph JSON (produced verbatim by tools/export-graph.mjs)
and expose the small helpers the pipeline/backend need. See docs/GRAPH-JSON-SCHEMA.md."""
import json


class Graph:
    def __init__(self, data):
        self.data = data
        self.passes = data.get("passes", [])
        self.allocations = data.get("allocations", {})
        self.textures = data.get("textures", {})
        self.programs = data.get("programs", {})
        self.render_surface = data.get("renderSurface")

    def phys(self, tex_id):
        """Virtual texId -> physical pool id (identity if unpooled, e.g. global_*)."""
        return self.allocations.get(tex_id, tex_id)

    def spec(self, tex_id):
        return self.textures.get(tex_id, {"width": "screen", "height": "screen", "format": "rgba16f"})

    def output_tex_id(self):
        """The texId to read back: the render surface, mapped to its global_ surface."""
        rs = self.render_surface
        if rs and not rs.startswith("global_"):
            return "global_" + rs
        return rs


def load(path):
    with open(path) as f:
        return Graph(json.load(f))
