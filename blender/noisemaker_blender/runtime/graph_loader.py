"""Load a normalized render-graph JSON (produced verbatim by tools/export-graph.mjs)
and expose the small helpers the pipeline/backend need. See docs/GRAPH-JSON-SCHEMA.md."""
import json
from .inputs import input_kind


class Graph:
    def __init__(self, data):
        self.data = data
        self.passes = data.get("passes", [])
        self.allocations = data.get("allocations", {})
        self.textures = data.get("textures", {})
        self.programs = data.get("programs", {})
        self.render_surface = data.get("renderSurface")
        self.media_steps = data.get("mediaSteps", [])

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

    def is_stateful(self):
        """Conservatively identify a cross-frame read of a persistent surface."""
        if any(spec.get("persistent") for spec in self.textures.values()):
            return True
        written = set()
        for render_pass in self.passes:
            for tex_id in render_pass.get("inputs", {}).values():
                if (tex_id.startswith("global_") and tex_id not in written
                        and not input_kind(tex_id)):
                    return True
            written.update(render_pass.get("outputs", {}).values())
        return False


def load(path):
    with open(path) as f:
        return Graph(json.load(f))


def validate_execution(graph):
    """Reject graph operations the Blender executor cannot implement."""
    if not graph.render_surface or not isinstance(graph.render_surface, str):
        raise ValueError("graph has no render surface")
    if not isinstance(graph.passes, list):
        raise ValueError("graph passes must be a list")
    declared = set(graph.textures)
    for index, render_pass in enumerate(graph.passes):
        if not isinstance(render_pass, dict):
            raise ValueError("pass %d must be a mapping" % index)
        outputs = render_pass.get("outputs")
        if not isinstance(outputs, dict):
            raise ValueError("pass %d outputs must be a mapping" % index)
        declared.update(tex_id for tex_id in outputs.values()
                        if isinstance(tex_id, str))
    for index, render_pass in enumerate(graph.passes):
        kind = render_pass.get("passType")
        if kind not in ("effect", "blit"):
            raise ValueError("unsupported pass type %r at pass %d" % (kind, index))
        mode = render_pass.get("drawMode")
        if mode not in (None, "points", "billboards", "triangles"):
            raise ValueError("unsupported draw mode %r at pass %d" % (mode, index))
        if mode == "triangles" and (
                render_pass.get("namespace"), render_pass.get("func"),
                render_pass.get("progName")) != ("render", "meshRender", "render"):
            raise ValueError("triangles are supported only for render.meshRender.render")
        if kind == "blit" and (mode is not None or "src" not in render_pass.get("inputs", {})):
            raise ValueError("blit pass %d requires a src input and fullscreen draw" % index)
        if kind == "effect" and not all(render_pass.get(name) for name in
                                         ("namespace", "func", "progName")):
            raise ValueError("effect pass %d lacks shader identity" % index)
        inputs = render_pass.get("inputs", {})
        outputs = render_pass.get("outputs", {})
        if not isinstance(inputs, dict) or not isinstance(outputs, dict) or not outputs:
            raise ValueError("pass %d requires input/output mappings and an output" % index)
        for name, tex_id in inputs.items():
            if not isinstance(name, str) or not isinstance(tex_id, str):
                raise ValueError("invalid input binding in pass %d" % index)
            if tex_id != "none" and tex_id not in declared and not tex_id.startswith("global_") and not input_kind(tex_id):
                raise ValueError("unsupported or unbound input %r in pass %d" % (tex_id, index))
        if mode in ("points", "billboards") and not inputs:
            raise ValueError("%s pass %d needs a particle input" % (mode, index))
        if mode == "triangles" and not {"meshPositions", "meshNormals"} <= set(inputs):
            raise ValueError("triangles pass %d requires meshPositions and meshNormals" % index)
        for name, tex_id in outputs.items():
            if not isinstance(name, str) or not isinstance(tex_id, str) or tex_id == "none":
                raise ValueError("invalid output binding in pass %d" % index)
