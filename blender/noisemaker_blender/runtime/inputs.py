"""Explicit host texture bindings and acyclic instance dependency ordering."""

from dataclasses import dataclass
import re


_MEDIA = re.compile(r"^(imageTex|textTex)_step_\d+$")
_MESH = re.compile(r"^global_mesh\d+_(positions|normals|uvs)(?:_chain_\d+)?$")


class UnboundInputError(RuntimeError):
    """A graph needs a host input that has no provider for this evaluation."""


@dataclass(frozen=True)
class InputFrame:
    texture: object
    width: int
    height: int
    revision: str | int
    color_space: str = "scene_linear"
    alpha_mode: str = "straight"
    origin: str = "bottom_left"
    vertex_count: int | None = None

    @property
    def texture_color(self):
        return self.texture

    def validate(self, binding):
        if self.texture is None:
            raise ValueError("%s returned no texture" % binding)
        if (isinstance(self.width, bool) or isinstance(self.height, bool)
                or not isinstance(self.width, int) or not isinstance(self.height, int)
                or self.width < 1 or self.height < 1):
            raise ValueError("%s returned invalid dimensions" % binding)
        if not isinstance(self.revision, (str, int)):
            raise ValueError("%s must return a scalar revision" % binding)
        if self.origin != "bottom_left":
            raise ValueError("%s must return bottom-left GPU texture data" % binding)
        if self.color_space not in ("scene_linear", "data"):
            raise ValueError("%s has unsupported color space" % binding)
        if self.alpha_mode not in ("straight", "premultiplied", "none"):
            raise ValueError("%s has unsupported alpha mode" % binding)
        if self.vertex_count is not None and (
                isinstance(self.vertex_count, bool) or not isinstance(self.vertex_count, int)
                or self.vertex_count < 1 or self.vertex_count % 3):
            raise ValueError("%s has invalid triangle vertex count" % binding)
        return self


def input_kind(tex_id):
    match = _MEDIA.fullmatch(tex_id)
    if match:
        return "image" if match.group(1) == "imageTex" else "text"
    if _MESH.fullmatch(tex_id):
        return "mesh"
    return None


def declared_host_inputs(graph):
    result = {}
    for render_pass in graph.passes:
        for tex_id in render_pass.get("inputs", {}).values():
            kind = input_kind(tex_id)
            if kind:
                result[tex_id] = kind
    return result


class InputRegistry:
    def __init__(self, graph):
        self.required = declared_host_inputs(graph)
        self.providers = {}

    def bind(self, binding, provider):
        if binding not in self.required:
            raise KeyError("undeclared host input %s" % binding)
        if not callable(provider) and not callable(getattr(provider, "resolve", None)):
            raise TypeError("host input provider must be callable or implement resolve")
        self.providers[binding] = provider

    def unbind(self, binding):
        if binding not in self.required:
            raise KeyError("undeclared host input %s" % binding)
        self.providers.pop(binding, None)

    def resolve(self, request):
        missing = sorted(set(self.required) - set(self.providers))
        if missing:
            raise UnboundInputError("unbound host inputs: %s" % ", ".join(missing))
        frames = {}
        for name in sorted(self.required):
            provider = self.providers[name]
            result = (provider.resolve(request) if callable(getattr(provider, "resolve", None))
                      else provider(request))
            if not isinstance(result, InputFrame):
                raise TypeError("%s provider must return InputFrame" % name)
            frames[name] = result.validate(name)
        return frames

    def revision_snapshot(self, request):
        """Read declared input revisions without creating or binding GPU textures."""
        missing = sorted(set(self.required) - set(self.providers))
        if missing:
            raise UnboundInputError("unbound host inputs: %s" % ", ".join(missing))
        revisions = []
        for name in sorted(self.required):
            revision_for = getattr(self.providers[name], "revision_for", None)
            if not callable(revision_for):
                raise RuntimeError("%s provider lacks CPU revision_for(request)" % name)
            revision = revision_for(request)
            if not isinstance(revision, (str, int)):
                raise TypeError("%s must return a scalar revision" % name)
            revisions.append((name, revision))
        return tuple(revisions)

    def source_identity(self):
        """Stable within a live session; provider changes invalidate replay."""
        result = {}
        for name, provider in sorted(self.providers.items()):
            identity = getattr(provider, "source_identity", None)
            result[name] = identity() if callable(identity) else str(id(provider))
        return result


def topological_order(dependencies):
    """Order instance IDs so each producer evaluates before its consumers."""
    pending = {node: set(deps) for node, deps in dependencies.items()}
    unknown = set().union(*pending.values()) - set(pending) if pending else set()
    if unknown:
        raise ValueError("unknown instance dependencies: %s" % ", ".join(sorted(unknown)))
    ordered = []
    while pending:
        ready = sorted(node for node, deps in pending.items() if not deps)
        if not ready:
            raise ValueError("current-frame dependency cycle: %s" % ", ".join(sorted(pending)))
        for node in ready:
            ordered.append(node)
            pending.pop(node)
        for deps in pending.values():
            deps.difference_update(ready)
    return tuple(ordered)
