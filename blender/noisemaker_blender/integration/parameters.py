"""Engine-free typed program bindings and Blender ID-property persistence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Mapping

from ..compiler.lang_data import STD_ENUMS


def _snapshot_policy(request):
    return (request.fps, request.fps_base, request.origin_frame,
            request.loop_seconds, request.offset_seconds,
            request.fixed_step_seconds, request.mode)


def _frozen_parameter_value(value):
    if isinstance(value, (list, tuple)):
        return tuple(_frozen_parameter_value(item) for item in value)
    if isinstance(value, Mapping):
        raise TypeError("parameter snapshots require scalar or vector values")
    return value


@dataclass(frozen=True)
class PreparedParameterSnapshots:
    """Frozen evaluated Blender values; independent of later scene mutations."""

    program: object
    policy: tuple
    animated_keys: tuple
    static_values: tuple
    steps: tuple

    def __post_init__(self):
        object.__setattr__(self, "policy", tuple(self.policy))
        object.__setattr__(self, "animated_keys", tuple(self.animated_keys))
        object.__setattr__(self, "static_values", tuple(
            (key, _frozen_parameter_value(value)) for key, value in self.static_values))
        object.__setattr__(self, "steps", tuple(tuple(
            (key, _frozen_parameter_value(value)) for key, value in step)
            for step in self.steps))

    def source_identity(self):
        material = (self.program.source_id, self.policy, self.animated_keys,
                    self.static_values, self.steps)
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def resolve(self, request):
        from ..runtime.clock import map_frame
        if _snapshot_policy(request) != self.policy:
            raise ValueError("parameter snapshot time policy differs from request")
        sample = map_frame(request)
        index = sample.simulation_step
        if index < 0 or index >= len(self.steps):
            raise ValueError("missing historical snapshot for step %d" % index)
        values = dict(self.steps[index])
        revision = hashlib.sha256(json.dumps(
            self.steps[index], sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8")).hexdigest()
        return values, revision


def prepare_parameter_snapshots(instance, request, *, max_steps=64):
    """Capture exact evaluated keyed values before GPU replay.

    This is an explicit, frozen Program-session input. Scene time is restored
    after at most 256 fixed-step samples. Later keyframe/driver edits require a
    new capture; no live-instance freshness is inferred from this snapshot.
    """
    from .. import api
    from ..runtime.clock import map_frame
    from ..runtime.session import RenderSession
    from .lifecycle import LiveRegistry, registry
    from .persistence import source_for_instance

    if request.mode != "timeline":
        raise ValueError("parameter snapshots require timeline mode")
    if type(max_steps) is not int or not 1 <= max_steps <= 256:
        raise ValueError("max_steps must be an integer from 1 to 256")
    sample = map_frame(request)
    step_seconds = request.fixed_step_seconds or 1.0 / sample.fps_effective
    exact_step = sample.elapsed_seconds / step_seconds
    if exact_step < 0 or not math.isclose(exact_step, round(exact_step), abs_tol=1e-6):
        raise ValueError("stateful snapshots require an exact fixed-step target")
    count = sample.simulation_step + 1
    if count > max_steps:
        raise ValueError("historical snapshot count exceeds max_steps")
    scene = getattr(instance, "id_data", None)
    if scene is None or not getattr(instance, "instance_id", None):
        raise TypeError("expected a registered Noisemaker instance")
    if (request.fps != scene.render.fps or not math.isclose(
            request.fps_base, scene.render.fps_base, rel_tol=0, abs_tol=1e-9)):
        raise ValueError("snapshot request fps/fps_base must match Scene render settings")
    source = source_for_instance(instance)
    program = api.compile(source)
    if not program.graph().is_stateful():
        raise ValueError("historical parameter snapshots require a stateful program")
    values = api._instance_values(instance, program)
    animated = animated_parameter_keys(scene, instance, values.keys())
    graph = program.graph()
    for key in animated:
        matches = list(RenderSession._matching_passes(graph, key))
        if not matches or any(location != "uniform" or metadata.get("size") or
                              metadata.get("resource") or
                              RenderSession._resource_sensitive(graph, target) or
                              RenderSession._condition_sensitive(graph, target)
                              for render_pass, target, location, metadata in matches):
            raise ValueError("historical snapshots do not support animated "
                             "define/resource/conditional parameter: %s" % key)
    static = tuple(sorted((key, value) for key, value in values.items()
                          if key not in animated))
    definitions = LiveRegistry._definitions(program)
    store = BindingStore(specs_from_effects(definitions))
    store.seed(seed_values_from_program(program, definitions))
    BlenderPropertyAdapter(instance).load(store)
    try:
        import bpy
    except ImportError as exc:
        raise RuntimeError("Blender evaluated Scene is required for snapshots") from exc
    current_layer = getattr(bpy.context, "view_layer", None)
    name = getattr(current_layer, "name", "")
    view_layer = scene.view_layers.get(name) or scene.view_layers[0]
    original = (scene.frame_current, scene.frame_subframe)
    steps = []
    registry.suspend("parameter_snapshot")
    try:
        for index in range(count):
            step_request, _time, _frame, _delta = RenderSession._step_request(
                request, sample, step_seconds, index)
            scene.frame_set(step_request.frame, subframe=step_request.subframe)
            with bpy.context.temp_override(scene=scene, view_layer=view_layer):
                view_layer.update()
                depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated_scene = scene.evaluated_get(depsgraph)
            evaluated = next((item for item in evaluated_scene.noisemaker_instances
                              if item.instance_id == instance.instance_id), None)
            if evaluated is None:
                raise KeyError("evaluated instance missing: %s" % instance.instance_id)
            evaluated_values = BlenderPropertyAdapter(instance).evaluated_values(
                store, depsgraph, evaluated_owner=evaluated)
            for key, baseline in static:
                if evaluated_values[key] != baseline:
                    raise ValueError("untracked parameter varies during snapshot preparation: %s" % key)
            steps.append(tuple((key, evaluated_values[key]) for key in animated))
        if source_for_instance(instance) != source:
            raise RuntimeError("instance source changed during parameter preparation")
        return PreparedParameterSnapshots(program, _snapshot_policy(request), animated,
                                          static, tuple(steps))
    finally:
        try:
            scene.frame_set(original[0], subframe=original[1])
        finally:
            registry.resume("parameter_snapshot")

_NUMERIC = (int, float)
_VECTOR_LENGTHS = {"vec2": 2, "vec3": 3, "vec4": 4, "mat3": 9}
_INPUT_TYPES = {"surface", "volume", "geometry"}


def _finite(value):
    return isinstance(value, _NUMERIC) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    kind: str
    default: object
    minimum: object = None
    maximum: object = None
    choices: tuple[tuple[str, object], ...] = ()
    description: str = ""
    invalidation: str = "scalar"
    target: str | None = None

    @classmethod
    def from_metadata(cls, key: str, metadata: Mapping) -> "ParameterSpec":
        kind = metadata.get("type")
        if kind in _INPUT_TYPES or kind not in ({"int", "float", "boolean", "color", "string", "member", "palette"} | set(_VECTOR_LENGTHS)):
            raise ValueError("unsupported parameter type %r" % kind)
        choices = metadata.get("choices") or {}
        if kind == "member" and not choices:
            enum_name = metadata.get("enum")
            choices = {label: item["value"] for label, item in STD_ENUMS.get(enum_name, {}).items()}
        if not isinstance(choices, Mapping):
            raise ValueError("choices must be a mapping")
        mapped = tuple((str(label), value) for label, value in choices.items() if value is not None)
        invalidation = "resource" if metadata.get("size") or metadata.get("resource") else (
            "define" if metadata.get("define") else "scalar")
        spec = cls(key, kind, metadata.get("default"), metadata.get("min"),
                   metadata.get("max"), mapped, metadata.get("description") or key,
                   invalidation, metadata.get("uniform") or metadata.get("define"))
        spec.validate(spec.default)
        return spec

    def validate(self, value):
        labels = dict(self.choices)
        if self.choices:
            if isinstance(value, str):
                if value in labels:
                    value = labels[value]
                elif self.kind == "member" and "." in value and value.rsplit(".", 1)[1] in labels:
                    value = labels[value.rsplit(".", 1)[1]]
            if isinstance(value, bool):
                raise TypeError("%s requires an enum choice" % self.key)
            if value not in labels.values():
                raise ValueError("%s has no enum value %r" % (self.key, value))
            return value
        if self.kind == "boolean":
            if not isinstance(value, bool):
                raise TypeError("%s requires bool" % self.key)
            return value
        if self.kind == "string":
            if not isinstance(value, str):
                raise TypeError("%s requires string" % self.key)
            return value
        if self.kind == "color" and isinstance(value, str):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
                raise ValueError("%s requires a hex color" % self.key)
            return value
        if self.kind in _VECTOR_LENGTHS or self.kind == "color":
            if (isinstance(value, (str, bytes, Mapping)) or not hasattr(value, "__len__")
                    or not hasattr(value, "__getitem__")):
                raise TypeError("%s requires a numeric sequence" % self.key)
            try:
                components = tuple(value[index] for index in range(len(value)))
            except (IndexError, KeyError, TypeError) as exc:
                raise TypeError("%s requires indexed numeric components" % self.key) from exc
            expected = _VECTOR_LENGTHS.get(self.kind)
            if expected is not None and len(value) != expected:
                raise ValueError("%s requires %d components" % (self.key, expected))
            if self.kind == "color" and len(value) not in (3, 4):
                raise ValueError("%s requires 3 or 4 color components" % self.key)
            if not all(_finite(item) for item in components):
                raise TypeError("%s requires finite numeric components" % self.key)
            result = tuple(float(item) for item in components)
            for index, item in enumerate(result):
                low = self.minimum[index] if isinstance(self.minimum, (tuple, list)) else self.minimum
                high = self.maximum[index] if isinstance(self.maximum, (tuple, list)) else self.maximum
                if low is not None and item < low or high is not None and item > high:
                    raise ValueError("%s component out of range" % self.key)
            return result
        if self.kind in ("int", "member", "palette"):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError("%s requires integer" % self.key)
        elif not _finite(value):
            raise TypeError("%s requires finite number" % self.key)
        if self.minimum is not None and value < self.minimum or self.maximum is not None and value > self.maximum:
            raise ValueError("%s out of range" % self.key)
        return value

    def encode(self, value):
        """Blender animation stores an integer code for every enumerated value."""
        value = self.validate(value)
        if not self.choices:
            return value
        raw_values = [choice for _, choice in self.choices]
        numeric_codes = (all(isinstance(item, int) and not isinstance(item, bool)
                             and item >= 0 for item in raw_values)
                         and len(set(raw_values)) == len(raw_values))
        index = raw_values.index(value)
        return value if numeric_codes else index

    def decode(self, encoded):
        if not self.choices:
            return self.validate(encoded)
        if not isinstance(encoded, int) or isinstance(encoded, bool):
            raise TypeError("%s requires an integer enum code" % self.key)
        for _, value in self.choices:
            if self.encode(value) == encoded:
                return value
        raise ValueError("%s has no enum code %r" % (self.key, encoded))


@dataclass
class ParameterBinding:
    spec: ParameterSpec
    value: object
    orphaned: bool = False


def specs_from_effects(effects) -> list[ParameterSpec]:
    """Build keys from effect name and same-effect occurrence, not graph index."""
    effects = list(effects)
    ambiguous = {item["func"] for item in effects
                 if sum(other["func"] == item["func"] and other.get("namespace") != item.get("namespace")
                        for other in effects)}
    counts = {}
    result = []
    for definition in effects:
        name = definition["func"]
        if name in ambiguous:
            name = "%s.%s" % (definition["namespace"], name)
        occurrence = counts.get(name, 0)
        counts[name] = occurrence + 1
        for param, metadata in definition.get("globals", {}).items():
            if metadata.get("type") in _INPUT_TYPES:
                continue
            result.append(ParameterSpec.from_metadata("%s#%d.%s" % (name, occurrence, param), metadata))
    return result


def seed_values_from_program(program, definitions):
    """Extract actual compiled values, including explicit DSL arguments."""
    definitions = list(definitions)
    specs = specs_from_effects(definitions)
    graph = program.graph()
    groups = []
    seen = set()
    for render_pass in graph.passes:
        identity = (render_pass.get("effectKey"), render_pass.get("stepIndex"))
        if identity[0] and identity not in seen:
            seen.add(identity)
            groups.append(render_pass)
    values = {}
    position = 0
    for definition, render_pass in zip(definitions, groups):
        for name, metadata in definition.get("globals", {}).items():
            if metadata.get("type") in _INPUT_TYPES:
                continue
            spec = specs[position]
            position += 1
            uniform = metadata.get("uniform")
            define = metadata.get("define")
            if uniform and uniform in render_pass.get("uniforms", {}):
                raw = render_pass["uniforms"][uniform]
            elif define and define in render_pass.get("defines", {}):
                raw = render_pass["defines"][define]
            else:
                continue
            # The graph compiler lowers booleans to integer shader constants.
            # This normalization is only for compiled graph seeds; user edits
            # remain strictly typed bool values.
            if spec.kind == "boolean" and type(raw) is int and raw in (0, 1):
                raw = bool(raw)
            values[spec.key] = spec.validate(raw)
    return values


class BindingStore:
    def __init__(self, specs=()):
        self._bindings: dict[str, ParameterBinding] = {}
        self.reconcile(specs)

    @property
    def orphan_keys(self):
        return tuple(key for key, binding in self._bindings.items() if binding.orphaned)

    @property
    def active_keys(self):
        return tuple(key for key, binding in self._bindings.items() if not binding.orphaned)

    def binding(self, key):
        return self._bindings[key]

    def value(self, key):
        return self._bindings[key].value

    def reconcile(self, specs):
        incoming = {}
        for spec in specs:
            if spec.key in incoming:
                raise ValueError("duplicate parameter key %s" % spec.key)
            incoming[spec.key] = spec
        for key, binding in self._bindings.items():
            binding.orphaned = key not in incoming
            if key in incoming:
                new_spec = incoming[key]
                # A changed type or enum may invalidate the old value; preserve it
                # visibly as an orphan rather than assigning it to another field.
                try:
                    binding.value = new_spec.validate(binding.value)
                except (TypeError, ValueError):
                    binding.orphaned = True
                else:
                    binding.spec = new_spec
        for key, spec in incoming.items():
            if key not in self._bindings:
                self._bindings[key] = ParameterBinding(spec, spec.validate(spec.default))

    def seed(self, values):
        """Initialize new bindings from compiled DSL values before persistence load."""
        for key, value in values.items():
            if key in self._bindings and not self._bindings[key].orphaned:
                self._bindings[key].value = self._bindings[key].spec.validate(value)

    def set(self, key, value):
        binding = self._bindings[key]
        if binding.orphaned:
            raise ValueError("cannot set orphaned parameter %s" % key)
        binding.value = binding.spec.validate(value)
        return binding.spec.invalidation

    def values(self):
        return {key: binding.value for key, binding in self._bindings.items()
                if not binding.orphaned}


class BlenderPropertyAdapter:
    """Store each value on a Blender ID owner; no bpy import is required."""
    def __init__(self, owner):
        self.owner = owner

    @staticmethod
    def property_name(key):
        plain = "nm:" + key
        return plain if len(plain) <= 63 else "nm:" + hashlib.sha256(key.encode()).hexdigest()[:32]

    def persist(self, store: BindingStore):
        for key, binding in store._bindings.items():
            prop = self.property_name(key)
            self.owner[prop] = binding.spec.encode(binding.value)
            ui = self.owner.id_properties_ui(prop)
            metadata = {"description": binding.spec.description,
                        "default": binding.spec.encode(binding.spec.default)}
            if _finite(binding.spec.minimum):
                metadata["min"] = binding.spec.minimum
            if _finite(binding.spec.maximum):
                metadata["max"] = binding.spec.maximum
            ui.update(**metadata)

    def load(self, store: BindingStore):
        """Recover saved values before reconciling a newly compiled program."""
        for key in store.active_keys:
            prop = self.property_name(key)
            if prop in self.owner:
                store.set(key, store.binding(key).spec.decode(self.owner[prop]))

    def evaluated_values(self, store: BindingStore, depsgraph, *, evaluated_owner=None):
        evaluated = evaluated_owner if evaluated_owner is not None else self.owner.evaluated_get(depsgraph)
        values = {}
        for key in store.active_keys:
            binding = store.binding(key)
            prop = self.property_name(key)
            if prop not in evaluated:
                raise KeyError("evaluated property missing: %s" % key)
            values[key] = binding.spec.decode(evaluated[prop])
        return values

    @staticmethod
    def enum_label(store: BindingStore, key: str):
        binding = store.binding(key)
        for label, value in binding.spec.choices:
            if value == binding.value:
                return label
        raise ValueError("parameter has no enum label: %s" % key)


def _action_curves(action, slot=None):
    """Yield legacy and layered Action FCurves for the owning Scene slot."""
    if action is None:
        return
    direct = getattr(action, "fcurves", None)
    if direct is not None:
        yield from direct
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            bags = getattr(strip, "channelbags", ())
            if slot is not None:
                getter = getattr(strip, "channelbag", None)
                if callable(getter):
                    bag = getter(slot)
                    if bag is not None:
                        yield from bag.fcurves
                    continue
                bags = (bag for bag in bags if getattr(bag, "slot", None) == slot)
            for bag in bags:
                yield from bag.fcurves


def animated_parameter_keys(scene, config, keys):
    """Find keyed/driven instance ID properties without changing scene time.

    Returns only active keys supplied by the caller. The paths come from the
    PropertyGroup's current owner path, so unrelated Scene animation is ignored.
    """
    keys = tuple(keys)
    animation = getattr(scene, "animation_data", None)
    if animation is None or not keys:
        return ()
    try:
        prefix = config.path_from_id()
    except (AttributeError, ValueError, RuntimeError):
        prefix = None
    if not prefix:
        for index, item in enumerate(getattr(scene, "noisemaker_instances", ())):
            if item is config:
                prefix = "noisemaker_instances[%d]" % index
                break
    if not prefix:
        raise RuntimeError("cannot locate instance animation path")
    paths = {prefix + '["' + BlenderPropertyAdapter.property_name(key) + '"]': key
             for key in keys}
    curves = list(getattr(animation, "drivers", ()))
    action = getattr(animation, "action", None)
    curves.extend(_action_curves(action, getattr(animation, "action_slot", None)))
    for track in getattr(animation, "nla_tracks", ()):
        for strip in getattr(track, "strips", ()):
            curves.extend(_action_curves(getattr(strip, "action", None),
                                         getattr(strip, "action_slot", None)))
    return tuple(sorted({paths[curve.data_path] for curve in curves
                         if getattr(curve, "data_path", None) in paths}))
