"""Persistent GPU render state, independent of Blender editor/operator context."""

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os

from .clock import map_frame
from .checkpoints import (
    CheckpointIdentity, CheckpointStore, ReplayController, ReplayPending,
    ReplayStatus)
from .graph_loader import Graph, validate_execution
from .inputs import InputRegistry
from .output import OutputDescriptor, OutputHandle
from . import pipeline


def _dimensions(size, width, height):
    if size is not None:
        if width is not None or height is not None:
            raise ValueError("size cannot be combined with width or height")
        width = height = size
    if width is None or height is None:
        raise ValueError("width and height are both required")
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in (width, height)):
        raise ValueError("width and height must be positive integers")
    return width, height


@dataclass(frozen=True)
class Program:
    """Immutable source and normalized graph snapshot, safe to reuse across sessions."""

    source: str
    _serialized_graph: str

    @classmethod
    def from_graph(cls, source, graph):
        if not isinstance(source, str):
            raise TypeError("program source must be a string")
        return cls(source, json.dumps(graph, sort_keys=True, separators=(",", ":")))

    def graph(self):
        return Graph(json.loads(self._serialized_graph))

    def parameter_values(self):
        """Canonical keyed values compiled from DSL, including uniforms/defines."""
        from ..compiler.registry import get_effect
        from ..integration.parameters import seed_values_from_program
        definitions = []
        seen = set()
        for render_pass in self.graph().passes:
            identity = (render_pass.get("effectKey"), render_pass.get("stepIndex"))
            if not identity[0] or identity in seen:
                continue
            seen.add(identity)
            definition = get_effect(identity[0])
            if definition is not None:
                definitions.append(definition)
        return seed_values_from_program(self, definitions)

    @property
    def source_id(self):
        material = (self.source + "\x00" + self._serialized_graph).encode("utf-8")
        return hashlib.sha256(material).hexdigest()


def build_cache_identity(program, request, *, width, height, parameters=None,
                         input_sources=None, input_revisions=(), input_history=None,
                         external_source=None, external_revision=None,
                         external_history=None, parameter_source=None,
                         parameter_revision=None, parameter_history=None,
                         color_role="color", alpha_mode="PREMUL"):
    """Construct the same cache key from a live session or CPU-only scene state."""
    if not isinstance(program, Program):
        raise TypeError("cache identity requires a Program")
    width, height = _dimensions(None, width, height)
    if request.mode != "timeline":
        raise ValueError("render cache requires timeline mode")
    sample = map_frame(request)
    def digest(history):
        return hashlib.sha256(json.dumps(history or {}, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False
                                         ).encode("utf-8")).hexdigest()
    return {
        "source": program.source_id,
        "inputs": {
            "sources": dict(input_sources or {}),
            "current": dict(input_revisions),
            "history_sha256": digest(input_history),
            "automation": {"source": external_source,
                           "current": external_revision,
                           "history_sha256": digest(external_history)},
        },
        "parameters": dict(program.parameter_values(), **(parameters or {})),
        "frame": request.frame, "subframe": request.subframe,
        "fps": request.fps, "fps_base": request.fps_base,
        "origin_frame": request.origin_frame,
        "loop_seconds": request.loop_seconds,
        "offset": request.offset_seconds,
        "width": width, "height": height,
        "color_role": color_role, "alpha_mode": alpha_mode,
        "simulation": {
            "fixed_step_seconds": request.fixed_step_seconds,
            "step": sample.simulation_step,
            "parameter_source": parameter_source,
            "parameter_revision": parameter_revision,
            "parameter_history_sha256": digest(parameter_history),
        },
        "mode": request.mode,
    }


class RenderSession:
    def __init__(self, program, *, size=None, width=None, height=None,
                 backend_factory=None, shaders_root=None):
        self.width, self.height = _dimensions(size, width, height)
        if not isinstance(program, Program):
            raise TypeError("program must be a Program")
        if backend_factory is None:
            from ..backend.gpu_backend import GpuBackend
            backend_factory = GpuBackend
        self._backend_factory = backend_factory
        self._shaders_root = shaders_root or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "shaders", "effects")
        self._epoch = 0
        self.generation = 0
        self.closed = False
        self._last_request = None
        self._last_revision = -1
        self._revision = 0
        self._parameters = {}
        self._last_inputs_revision = None
        self._last_external_revision = None
        self._last_parameter_revision = None
        self._input_frames = {}
        self._input_history = {}
        self._external_history = {}
        self._external_state_provider = None
        self._parameter_state_provider = None
        self._parameter_history = {}
        self._request_sync = None
        self._replay_target = None
        self._replay_target_revision = None
        self._history_validation_request = None
        self._history_validation_cursor = 0
        self._gpu_mutated = False
        self.orphaned_parameters = {}
        self._publisher = None
        self._instance_output_owner = None
        # Blender's public GPU API has no portable full-state snapshot. Replay
        # therefore starts from a clean backend on backward seeks; no checkpoint
        # is ever fabricated from an incomplete texture set.
        self._replay = ReplayController(
            CheckpointStore(max_items=1, max_bytes=1),
            checkpoint_interval=100001, max_steps_per_seek=100000)
        self._fresh_backend = True
        self.program = program
        self.graph, self.backend = self._prepare(program, self.width, self.height)
        self.inputs = InputRegistry(self.graph)

    def _prepare(self, program, width, height, parameters=None):
        graph = program.graph()
        validate_execution(graph)
        if parameters:
            self._apply_parameters(graph, parameters)
        backend = self._backend_factory(self._shaders_root, width=width, height=height)
        try:
            max_texture_size = getattr(backend, "max_texture_size", None)
            if callable(max_texture_size):
                pipeline._clamp_graph_volume_sizes(graph, max_texture_size())
            backend.setup(graph, pipeline.collect_default_uniforms(graph))
            compiler = getattr(backend, "compile", None)
            if callable(compiler):
                for render_pass in graph.passes:
                    if render_pass["passType"] == "effect":
                        compiler(render_pass["namespace"], render_pass["func"],
                                 render_pass["progName"], render_pass.get("defines"))
                    else:
                        compiler(None, "blit", "blit", None)
        except Exception:
            backend.free()
            raise
        return graph, backend

    def _assert_open(self):
        if self.closed:
            raise RuntimeError("render session is closed")

    def _assert_context(self):
        checker = getattr(self.backend, "assert_context", None)
        if callable(checker):
            checker()

    def _replace(self, program, width, height, parameters=None):
        self._assert_open()
        self._assert_context()
        candidate_graph, candidate_backend = self._prepare(program, width, height, parameters)
        try:
            candidate_inputs = InputRegistry(candidate_graph)
            for binding, provider in self.inputs.providers.items():
                if binding in candidate_inputs.required:
                    candidate_inputs.bind(binding, provider)
            candidate_frames = {binding: frame for binding, frame in self._input_frames.items()
                                if binding in candidate_inputs.required}
            if candidate_frames:
                setter = getattr(candidate_backend, "set_external_inputs", None)
                if callable(setter):
                    setter(candidate_frames)
        except Exception:
            candidate_backend.free()
            raise
        previous = self.backend
        self.graph, self.backend = candidate_graph, candidate_backend
        self.inputs = candidate_inputs
        self._input_frames = candidate_frames
        self.program = program
        self.width, self.height = width, height
        self._epoch += 1
        self._last_request = None
        self._last_inputs_revision = None
        self._last_external_revision = None
        self._last_parameter_revision = None
        self._input_history = {}
        self._external_history = {}
        self._parameter_history = {}
        self._history_validation_request = None
        self._history_validation_cursor = 0
        self._fresh_backend = True
        self._replay.invalidate()
        previous.free()

    def resize(self, width, height):
        width, height = _dimensions(None, width, height)
        if (width, height) != (self.width, self.height):
            self._replace(self.program, width, height, self._parameters)

    def reset(self):
        self._replace(self.program, self.width, self.height, self._parameters)

    def recompile(self, program):
        if not isinstance(program, Program):
            raise TypeError("program must be a Program")
        candidate = program.graph()
        retained = dict(self._parameters, **self.orphaned_parameters)
        active = {key: value for key, value in retained.items()
                  if list(self._matching_passes(candidate, key))}
        orphaned = {key: value for key, value in retained.items() if key not in active}
        self._replace(program, self.width, self.height, active)
        self._parameters = active
        self.orphaned_parameters = orphaned
        self._revision += 1

    @staticmethod
    def _matching_passes(graph, key):
        try:
            effect_occurrence, uniform = key.rsplit(".", 1)
            effect, occurrence = effect_occurrence.rsplit("#", 1)
            occurrence = int(occurrence)
        except (ValueError, TypeError):
            raise KeyError(key) from None
        if "." not in effect:
            candidates = {render_pass.get("effectKey") for render_pass in graph.passes
                          if isinstance(render_pass.get("effectKey"), str)
                          and (render_pass["effectKey"] == effect or
                               render_pass["effectKey"].endswith("." + effect))}
            if len(candidates) > 1:
                raise KeyError("ambiguous effect key %s" % key)
        seen = []
        for render_pass in graph.passes:
            actual = render_pass.get("effectKey")
            if actual != effect and not (
                    isinstance(actual, str) and "." not in effect
                    and actual.endswith("." + effect)):
                continue
            step = render_pass.get("stepIndex")
            if step not in seen:
                seen.append(step)
            if len(seen) - 1 != occurrence:
                continue
            from ..compiler.registry import get_effect
            definition = get_effect(actual) or {}
            metadata = (definition.get("globals") or {}).get(uniform) or {}
            define = metadata.get("define")
            uniform_target = metadata.get("uniform") or uniform
            if define and define in render_pass.get("defines", {}):
                yield render_pass, define, "define", metadata
            elif uniform_target in render_pass.get("uniforms", {}):
                yield render_pass, uniform_target, "uniform", metadata

    @classmethod
    def _apply_parameters(cls, graph, parameters):
        for key, value in parameters.items():
            matches = list(cls._matching_passes(graph, key))
            if not matches:
                raise KeyError(key)
            for render_pass, target, location, metadata in matches:
                slot = render_pass["defines" if location == "define" else "uniforms"]
                slot[target] = (int(value) if metadata.get("type") == "boolean"
                                and (location == "define" or type(slot[target]) is int)
                                else value)

    @staticmethod
    def _resource_sensitive(graph, uniform):
        def mentions(value):
            if isinstance(value, dict):
                return value.get("param") == uniform or value.get("screenDivide") == uniform or any(
                    mentions(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return any(mentions(item) for item in value)
            return False
        return any(mentions(spec) for spec in graph.textures.values())

    def set_parameter(self, key, value):
        self._assert_open()
        matches = list(self._matching_passes(self.graph, key))
        if not matches:
            raise KeyError(key)
        render_pass, target, location, metadata = matches[0]
        if metadata:
            from ..integration.parameters import ParameterSpec
            value = ParameterSpec.from_metadata(key, metadata).validate(value)
        else:
            old_value = render_pass["defines" if location == "define" else "uniforms"][target]
            if isinstance(old_value, bool) and not isinstance(value, bool):
                raise TypeError("%s requires bool" % key)
            if isinstance(old_value, int) and (isinstance(value, bool) or not isinstance(value, int)):
                raise TypeError("%s requires integer" % key)
            if isinstance(old_value, float) and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise TypeError("%s requires number" % key)
            if isinstance(old_value, (list, tuple)) and (
                    not isinstance(value, (list, tuple)) or len(value) != len(old_value)):
                raise TypeError("%s requires %d components" % (key, len(old_value)))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if not math.isfinite(value):
                    raise ValueError("%s requires finite value" % key)
                specs = render_pass.get("uniformSpecs", {}).get(target, {})
                minimum, maximum = specs.get("min"), specs.get("max")
                if minimum is not None and value < minimum or maximum is not None and value > maximum:
                    raise ValueError("%s out of range" % key)
        updated = dict(self._parameters, **{key: value})
        invalidation = ("define" if location == "define" else
                        "resource" if self._resource_sensitive(self.graph, target)
                        or metadata.get("size") or metadata.get("resource") else "scalar")
        if invalidation != "scalar":
            self._replace(self.program, self.width, self.height, updated)
        else:
            for selected_pass, name, _location, selected_metadata in matches:
                slot = selected_pass["uniforms"]
                slot[name] = (int(value) if selected_metadata.get("type") == "boolean"
                              and type(slot[name]) is int else value)
            self._last_request = None
            if self.graph.is_stateful():
                self._replay.invalidate()
                self._history_validation_request = None
                self._history_validation_cursor = 0
        self._parameters = updated
        self._revision += 1
        return invalidation

    def _render_at(self, time, frame, delta_time=0.0, external_state=None,
                   parameter_overrides=None):
        engine = pipeline.default_engine(self.width, time, frame, delta_time,
                                         width=self.width, height=self.height)
        lookup = dict(engine)
        lookup.update(pipeline.collect_default_uniforms(self.graph))
        self._gpu_mutated = True
        self.backend.frame_begin()
        for render_pass in self.graph.passes:
            if pipeline.should_skip(render_pass, lookup):
                continue
            effective = pipeline._resolve_pass_uniforms(render_pass, time, external_state or {})
            overrides = (parameter_overrides or {}).get(id(render_pass))
            if overrides:
                effective = dict(effective)
                effective["uniforms"] = dict(effective.get("uniforms") or {}, **overrides)
            pipeline.resolve_pass_viewport(effective, self.width, self.height,
                                           cache_holder=render_pass)
            media_id = effective.get("inputs", {}).get("imageTex")
            media = self._input_frames.get(media_id)
            if media is not None and "imageSize" in effective.get("uniforms", {}):
                effective["uniforms"]["imageSize"] = [media.width, media.height]
                effective["uniforms"]["inputPremultiplied"] = int(
                    media.alpha_mode == "premultiplied")
            effective_lookup = dict(engine)
            effective_lookup.update(effective.get("uniforms") or {})
            for _ in range(pipeline.resolve_repeat_count(effective, effective_lookup)):
                self.backend.execute(effective, self.graph, engine)
                for tex_id in effective.get("outputs", {}).values():
                    self.backend.swap_after_write(tex_id)
        self.backend.frame_persist()
        self._fresh_backend = False

    def _replay_identity(self, request):
        return CheckpointIdentity(
            source=self.program.source_id,
            parameters=self._parameters,
            inputs={"textures": self.inputs.source_identity(),
                    "automation": self._external_source_identity(),
                    "parameters": self._parameter_source_identity()},
            width=self.width,
            height=self.height,
            seed=0,
            time_mapping={
                "fps": request.fps, "fps_base": request.fps_base,
                "origin_frame": request.origin_frame,
                "loop_seconds": request.loop_seconds,
                "offset_seconds": request.offset_seconds,
            },
            simulation_policy={"fixed_step_seconds": request.fixed_step_seconds,
                               "mode": request.mode},
        )

    def _reset_for_replay(self):
        if not self._fresh_backend:
            self._replace(self.program, self.width, self.height, self._parameters)

    def _bind_host_inputs(self, request, *, step=None):
        frames = self.inputs.resolve(request)
        setter = getattr(self.backend, "set_external_inputs", None)
        if frames and not callable(setter):
            raise RuntimeError("backend does not support host texture bindings")
        if callable(setter):
            setter(frames)
        self._input_frames = frames
        revisions = tuple((name, frame.revision) for name, frame in frames.items())
        if step is not None and frames:
            self._input_history[step] = revisions
        return revisions

    def _external_source_identity(self):
        provider = self._external_state_provider
        if provider is None:
            return None
        if isinstance(provider, dict):
            try:
                payload = json.dumps(provider, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")
            except (TypeError, ValueError):
                return "opaque:%s" % id(provider)
            return hashlib.sha256(payload).hexdigest()
        identity = getattr(provider, "source_identity", None)
        return identity() if callable(identity) else str(id(provider))

    def _parameter_source_identity(self):
        provider = self._parameter_state_provider
        if provider is None:
            return None
        identity = getattr(provider, "source_identity", None)
        if not callable(identity):
            raise TypeError("parameter snapshot provider needs source_identity()")
        result = identity()
        if not isinstance(result, (str, int)):
            raise TypeError("parameter source identity must be scalar")
        return result

    def _resolve_parameter_state(self, request, *, step=None):
        provider = self._parameter_state_provider
        if provider is None:
            return {}, None
        resolver = getattr(provider, "resolve", None)
        values, revision = (resolver(request) if callable(resolver) else provider(request))
        if not isinstance(values, dict) or not isinstance(revision, (str, int)):
            raise TypeError("parameter provider must return (keyed values, scalar revision)")
        overrides = {}
        for key, value in values.items():
            matches = list(self._matching_passes(self.graph, key))
            if not matches:
                raise KeyError(key)
            for render_pass, target, location, metadata in matches:
                if location != "uniform" or self._resource_sensitive(self.graph, target) or (
                        metadata.get("size") or metadata.get("resource")):
                    raise ValueError("stateful parameter snapshots support scalar uniforms only: %s" % key)
                if metadata:
                    from ..integration.parameters import ParameterSpec
                    value = ParameterSpec.from_metadata(key, metadata).validate(value)
                overrides.setdefault(id(render_pass), {})[target] = (
                    int(value) if metadata.get("type") == "boolean"
                    and type(render_pass["uniforms"][target]) is int else value)
        if step is not None:
            self._parameter_history[step] = revision
        return overrides, revision

    def set_parameter_snapshot_provider(self, provider):
        """Supply deterministic per-step scalar values for stateful replay."""
        self._assert_open()
        if provider is not None and not callable(provider) and not callable(
                getattr(provider, "resolve", None)):
            raise TypeError("parameter snapshot provider must be callable")
        self._parameter_state_provider = provider
        self._parameter_source_identity()
        self._revision += 1
        self._replay.invalidate()
        self._last_request = None
        self._history_validation_request = None
        self._history_validation_cursor = 0

    def _resolve_external_state(self, request, *, step=None):
        provider = self._external_state_provider
        if provider is None:
            return {}, None
        if isinstance(provider, dict):
            state, revision = provider, self._external_source_identity()
        else:
            resolver = getattr(provider, "resolve", None)
            state, revision = (resolver(request) if callable(resolver)
                               else provider(request))
        if not isinstance(state, dict) or not isinstance(revision, (str, int)):
            raise TypeError("external state provider must return (dict, scalar revision)")
        if step is not None:
            self._external_history[step] = revision
        return state, revision

    @staticmethod
    def _step_request(request, sample, step_seconds, index):
        elapsed = index * step_seconds
        time = ((elapsed + request.offset_seconds) / request.loop_seconds) % 1.0
        position = request.origin_frame + elapsed * sample.fps_effective
        frame = math.floor(position + 1e-9)
        subframe = max(0.0, position - frame)
        step_request = replace(request, frame=frame, subframe=subframe,
                               wall_seconds=elapsed if request.mode == "free_run"
                               else request.wall_seconds)
        delta = 0.0 if index == 0 else step_seconds / request.loop_seconds
        return step_request, time, frame, delta

    def _history_matches(self, request, sample, step_seconds, *, max_checks=None):
        if not self._input_history and not self._external_history and not self._parameter_history:
            return True
        total = max(len(self._input_history), len(self._external_history),
                    len(self._parameter_history))
        if self._history_validation_request != request:
            self._history_validation_cursor = 0
        start = self._history_validation_cursor
        stop = total if max_checks is None else min(total, start + max_checks)
        for index in range(start, stop):
            step_request, _time, _frame, _delta = self._step_request(
                request, sample, step_seconds, index)
            if index in self._input_history and self.inputs.revision_snapshot(
                    step_request) != self._input_history[index]:
                self._history_validation_request = None
                self._history_validation_cursor = 0
                return False
            if index in self._external_history:
                _state, revision = self._resolve_external_state(step_request)
                if revision != self._external_history[index]:
                    self._history_validation_request = None
                    self._history_validation_cursor = 0
                    return False
            if index in self._parameter_history:
                _overrides, revision = self._resolve_parameter_state(step_request)
                if revision != self._parameter_history[index]:
                    self._history_validation_request = None
                    self._history_validation_cursor = 0
                    return False
        if stop < total:
            self._history_validation_request = request
            self._history_validation_cursor = stop
            raise ReplayPending(ReplayStatus(total, stop, total, False))
        self._history_validation_request = None
        self._history_validation_cursor = 0
        return True

    def _assert_historical_inputs(self):
        inexact = [binding for binding, provider in self.inputs.providers.items()
                   if getattr(provider, "historical_exact", True) is False]
        if inexact:
            raise ValueError("stateful replay requires exact-frame host input: %s" %
                             ", ".join(sorted(inexact)))

    def evaluate(self, request, *, max_steps=None, cancel=None):
        self._assert_open()
        sample = map_frame(request)  # validate every field before mutating GPU state
        if self._request_sync is not None:
            self._request_sync(request)
        self._assert_context()
        stateful = self.graph.is_stateful()
        if stateful:
            self._assert_historical_inputs()
            step_seconds = request.fixed_step_seconds or 1.0 / sample.fps_effective
            exact_step = sample.elapsed_seconds / step_seconds
            if request.mode == "timeline" and (exact_step < 0 or not math.isclose(
                    exact_step, round(exact_step), abs_tol=1e-6)):
                raise ValueError("stateful evaluation requires an exact fixed-step time")
            # Replay correctness requires a CPU-readable revision for earlier
            # frames; a callable that only returns GPU textures cannot provide it.
            self.inputs.revision_snapshot(request)
            if not self._history_matches(request, sample, step_seconds,
                                         max_checks=max_steps):
                self._replay.invalidate()
                self._last_request = None
                self._replay_target = None
        # A target-frame resolve admits required inputs before any GPU work.
        input_revisions = self._bind_host_inputs(request)
        external_state, external_revision = self._resolve_external_state(request)
        parameter_overrides, parameter_revision = self._resolve_parameter_state(request)
        if (self._last_request == request and self._last_revision == self._revision
                and self._last_inputs_revision == input_revisions
                and self._last_external_revision == external_revision
                and self._last_parameter_revision == parameter_revision):
            return self.output()
        self._gpu_mutated = False
        try:
            if stateful:
                if self._replay_target == request and self._replay_target_revision != (
                        input_revisions, external_revision, parameter_revision):
                    self._replay.invalidate()
                self._replay_target = request
                self._replay_target_revision = (
                    input_revisions, external_revision, parameter_revision)
                identity = self._replay_identity(request)
                def advance(step):
                    index = step - 1
                    step_request, time, frame, delta = self._step_request(
                        request, sample, step_seconds, index)
                    self._bind_host_inputs(step_request, step=index)
                    step_state, _step_revision = self._resolve_external_state(
                        step_request, step=index)
                    step_parameters, _parameter_revision = self._resolve_parameter_state(
                        step_request, step=index)
                    self._render_at(time, frame, delta, step_state, step_parameters)
                self._replay.seek(
                    sample.simulation_step + 1, identity,
                    reset=self._reset_for_replay,
                    restore=lambda _payload: None,
                    advance=advance,
                    cancel=cancel,
                    max_steps=max_steps,
                )
            else:
                self._render_at(sample.normalized_time, sample.frame_index,
                                external_state=external_state,
                                parameter_overrides=parameter_overrides)
        except ReplayPending:
            if self._gpu_mutated:
                self._epoch += 1
                self._last_request = None
            raise
        except Exception:
            if self._gpu_mutated:
                self._epoch += 1
                self._last_request = None
                self._replay.invalidate()
            raise
        self.generation += 1
        self._epoch += 1
        self._last_request = request
        self._last_revision = self._revision
        self._last_inputs_revision = tuple(
            (name, frame.revision) for name, frame in self._input_frames.items())
        self._last_external_revision = external_revision
        self._last_parameter_revision = parameter_revision
        self._gpu_mutated = False
        return self.output()

    @property
    def replay_status(self):
        return self._replay.status

    def bind_input(self, binding, provider):
        self._assert_open()
        self.inputs.bind(binding, provider)
        self._revision += 1
        self._replay.invalidate()
        self._history_validation_request = None
        self._history_validation_cursor = 0

    def unbind_input(self, binding):
        self._assert_open()
        self.inputs.unbind(binding)
        self._input_frames.pop(binding, None)
        setter = getattr(self.backend, "set_external_inputs", None)
        if callable(setter):
            setter(self._input_frames)
        self._revision += 1
        self._replay.invalidate()
        self._history_validation_request = None
        self._history_validation_cursor = 0

    def set_external_state(self, provider):
        """Bind deterministic audio/MIDI snapshots by requested scene time.

        A callable or object with ``resolve(request)`` returns ``(state, revision)``.
        State is a mapping with optional ``audio`` and ``midi`` entries. A static
        mapping is also accepted for scripts with fixed snapshots.
        """
        self._assert_open()
        if not isinstance(provider, dict) and not callable(provider) and not callable(
                getattr(provider, "resolve", None)):
            raise TypeError("external state must be a mapping or snapshot provider")
        self._external_state_provider = provider
        self._revision += 1
        self._replay.invalidate()
        self._history_validation_request = None
        self._history_validation_cursor = 0

    def current_identity(self, request, *, color_role="color", alpha_mode="PREMUL"):
        """CPU-only identity of the current source, inputs, parameters and frame."""
        if request.mode != "timeline":
            raise ValueError("render cache requires timeline mode")
        sample = map_frame(request)
        if self.graph.is_stateful():
            self._assert_historical_inputs()
        revisions = self.inputs.revision_snapshot(request)
        _state, external_revision = self._resolve_external_state(request)
        input_history = {}
        external_history = {}
        parameter_history = {}
        if self.graph.is_stateful() and (self.inputs.required or self._external_state_provider
                                        or self._parameter_state_provider):
            step_seconds = request.fixed_step_seconds or 1.0 / sample.fps_effective
            exact_step = sample.elapsed_seconds / step_seconds
            if exact_step < 0 or not math.isclose(exact_step, round(exact_step), abs_tol=1e-6):
                raise ValueError("stateful evaluation requires an exact fixed-step time")
            if sample.simulation_step + 1 > self._replay.max_steps_per_seek:
                raise ValueError("replay exceeds max_steps_per_seek")
            for index in range(sample.simulation_step + 1):
                step_request, _time, _frame, _delta = self._step_request(
                    request, sample, step_seconds, index)
                if self.inputs.required:
                    input_history[index] = self.inputs.revision_snapshot(step_request)
                if self._external_state_provider is not None:
                    _step_state, external_history[index] = self._resolve_external_state(
                        step_request)
                if self._parameter_state_provider is not None:
                    _step_params, parameter_history[index] = self._resolve_parameter_state(
                        step_request)
        _params, parameter_revision = self._resolve_parameter_state(request)
        return build_cache_identity(
            self.program, request, width=self.width, height=self.height,
            parameters=self._parameters,
            input_sources=self.inputs.source_identity(), input_revisions=revisions,
            input_history=input_history,
            external_source=self._external_source_identity(),
            external_revision=external_revision, external_history=external_history,
            parameter_source=self._parameter_source_identity(),
            parameter_revision=parameter_revision, parameter_history=parameter_history,
            color_role=color_role, alpha_mode=alpha_mode)

    def cache_identity(self, request, *, color_role="color", alpha_mode="PREMUL"):
        """Exact scalar identity for a completed binary prepared-frame cache."""
        identity = self.current_identity(request, color_role=color_role,
                                         alpha_mode=alpha_mode)
        revisions = self.inputs.revision_snapshot(request)
        _state, external_revision = self._resolve_external_state(request)
        _params, parameter_revision = self._resolve_parameter_state(request)
        if (self._last_request != request or self._last_revision != self._revision
                or self._last_inputs_revision != revisions
                or self._last_external_revision != external_revision
                or self._last_parameter_revision != parameter_revision):
            raise RuntimeError("evaluate the requested frame before caching it")
        written_inputs = hashlib.sha256(json.dumps(
            self._input_history, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        written_external = hashlib.sha256(json.dumps(
            self._external_history, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        written_parameters = hashlib.sha256(json.dumps(
            self._parameter_history, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        if (written_inputs != identity["inputs"]["history_sha256"]
                or written_external != identity["inputs"]["automation"]["history_sha256"]
                or written_parameters != identity["simulation"]["parameter_history_sha256"]):
            raise RuntimeError("historical input revisions changed; re-evaluate before caching")
        return identity

    def _binding(self, name):
        self._assert_open()
        self._assert_context()
        if name not in self.backend.frame_read:
            raise KeyError(name)
        return self.backend.frame_read[name]

    def _texture(self, name):
        return self._binding(name).texture_color

    def output(self, name=None):
        self._assert_open()
        if self.generation == 0 or self._last_request is None:
            raise RuntimeError("evaluate a frame before requesting output")
        name = name or self.graph.render_surface
        binding = self._binding(name)
        spec = self.graph.spec("global_" + name)
        fmt = self.backend.surfaces[name].fmt if hasattr(self.backend, "surfaces") else (
            {"rgba16f": "RGBA16F", "rgba32f": "RGBA32F", "rgba8": "RGBA8"}.get(
                spec.get("format", "rgba16f"), spec.get("format", "rgba16f")))
        descriptor = OutputDescriptor(
            binding.width, binding.height, fmt,
            color_space=spec.get("colorSpace", "scene_linear"),
            alpha_mode=spec.get("alphaMode", "premultiplied"))
        request = self._last_request
        return OutputHandle(self, self._epoch, name, descriptor, self.generation,
                            request.frame, request.subframe, self.program.source_id)

    def _validate_handle(self, handle):
        if not isinstance(handle, OutputHandle):
            raise TypeError("expected OutputHandle")
        session = handle._validated_session()
        if session is not self:
            raise ValueError("output belongs to another session")

    def read_float(self, handle):
        self._validate_handle(handle)
        self._assert_context()
        return self.backend.read_surface_float(handle.name)

    def read_quantized(self, handle):
        self._validate_handle(handle)
        self._assert_context()
        return self.backend.read_surface(handle.name)

    def publish_image(self, handle, *, name="Noisemaker", role="color",
                      alpha_mode="PREMUL", publisher=None):
        self._validate_handle(handle)
        owner = self._instance_output_owner
        if owner is not None and publisher is None:
            role = getattr(owner, "color_role", role)
            alpha_mode = getattr(owner, "alpha_mode", alpha_mode)
        if publisher is None:
            from ..integration.images import ImagePublisher
            if self._publisher is None:
                self._publisher = ImagePublisher(
                    owner_id=owner.instance_id if owner is not None else str(id(self)),
                    image=getattr(owner, "output_image", None) if owner is not None else None,
                    role=role, alpha_mode=alpha_mode)
            elif owner is not None:
                self._publisher.role = role
                self._publisher.alpha_mode = alpha_mode
            elif (self._publisher.role, self._publisher.alpha_mode) != (role, alpha_mode):
                raise ValueError("Image role and alpha mode must remain stable for one session")
            publisher = self._publisher
        image = publisher.publish(self.read_float(handle), generation=handle.generation,
                                  provenance=handle.provenance, name=name)
        if owner is not None and getattr(publisher, "owner_id", None) == owner.instance_id:
            owner.output_image = image
        return image

    def close(self):
        if not self.closed:
            self.closed = True
            self._epoch += 1
            try:
                self._assert_context()
            except RuntimeError:
                abandon = getattr(self.backend, "abandon", None)
                if not callable(abandon):
                    raise
                abandon()
            else:
                self.backend.free()

    def __enter__(self):
        self._assert_open()
        return self

    def __exit__(self, *_exc):
        self.close()
