"""Live instance/session ownership and safe GUI-timer lifecycle."""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import hashlib
import math
import time

from ..runtime.clock import FrameRequest, map_frame
from ..runtime.checkpoints import ReplayPending
from ..runtime.inputs import topological_order
from .parameters import BindingStore, BlenderPropertyAdapter, specs_from_effects, seed_values_from_program, animated_parameter_keys
from .persistence import ensure_unique_ids, instance_for_id, source_for_instance, pack_outputs_before_save, set_image_binding
from .scheduler import LiveScheduler


def request_for_scene(scene, config, *, purpose="preview", free_run_elapsed=None,
                      playing=False):
    """Final/cache requests always use evaluated scene time, never preview phase."""
    mode = "free_run" if purpose == "preview" and config.time_mode == "free_run" and not playing else "timeline"
    fixed = config.fixed_step_seconds if config.fixed_step_seconds > 0 else None
    return FrameRequest(
        frame=scene.frame_current, subframe=scene.frame_subframe,
        fps=scene.render.fps, fps_base=scene.render.fps_base,
        origin_frame=config.origin_frame, loop_seconds=config.loop_seconds,
        offset_seconds=config.offset_seconds, fixed_step_seconds=fixed,
        mode=mode, purpose=purpose,
        wall_seconds=free_run_elapsed if mode == "free_run" else None,
    )


@dataclass
class LiveInstance:
    scene: object
    config: object
    session: object = None
    publisher: object = None
    program: object = None
    bindings: BindingStore | None = None
    source_hash: str = ""
    observed_hash: str = ""
    applied_values: dict = field(default_factory=dict)
    host_providers: dict = field(default_factory=dict)
    image_providers: dict = field(default_factory=dict)
    observed_input_refs: tuple | None = None
    observed_inputs: tuple | None = None
    observed_time: tuple | None = None
    observed_params: tuple | None = None
    observed_original_params: tuple | None = None
    free_run_started: float = field(default_factory=time.monotonic)
    reset_requested: bool = False
    pending_preview_request: FrameRequest | None = None
    pending_preview_signature: tuple | None = None


class LiveRegistry:
    def __init__(self):
        self.scheduler = LiveScheduler()
        self._records: dict[str, LiveInstance] = {}
        self.pending_rebuild = False
        self.lifecycle_error = ""
        self._window_id = None

    @staticmethod
    def _key(scene, instance_id):
        pointer = scene.as_pointer() if hasattr(scene, "as_pointer") else id(scene)
        return "%s:%s" % (pointer, instance_id)

    def _record(self, scene, config):
        key = self._key(scene, config.instance_id)
        record = self._records.get(key)
        if record is None:
            record = LiveInstance(scene, config)
            self._records[key] = record
            self.scheduler.register(key, lambda record=record: self._produce(record))
            self.scheduler.mark_dirty(key, "source", now=time.monotonic())
        else:
            record.scene = scene
            record.config = config
        return record

    @staticmethod
    def _ordered_configs(scene, *, preview=False):
        configs = [config for config in getattr(scene, "noisemaker_instances", ())
                   if config.instance_id and (config.live_enabled if preview else
                                               config.live_enabled or config.output_image is not None)]
        by_id = {config.instance_id: config for config in configs}
        if len(by_id) != len(configs):
            raise ValueError("duplicate Noisemaker instance identity in Scene")
        dependencies = {identity: set() for identity in by_id}
        for config in configs:
            for item in getattr(config, "input_bindings", ()):
                image = getattr(item, "image", None)
                getter = getattr(image, "get", None)
                owner = getter("noisemaker_owner") if callable(getter) else None
                if owner in by_id:
                    upstream = by_id[owner]
                    if not preview or not upstream.paused:
                        dependencies[config.instance_id].add(owner)
        topological_order(dependencies)  # Reject current-frame cycles first.
        pending = {identity: set(parents) for identity, parents in dependencies.items()}
        order = []
        while pending:
            ready = [config.instance_id for config in configs
                     if config.instance_id in pending and not pending[config.instance_id]]
            order.extend(ready)
            for identity in ready:
                pending.pop(identity)
            for parents in pending.values():
                parents.difference_update(ready)
        return tuple(by_id[identity] for identity in order), dependencies

    def instances_for_scene(self, scene):
        configs, _dependencies = self._ordered_configs(scene)
        return tuple(self._record(scene, config) for config in configs)

    def get(self, scene, instance_id):
        return self._record(scene, instance_for_id(scene, instance_id))

    def remove(self, scene, instance_id):
        key = self._key(scene, instance_id)
        record = self._records.pop(key, None)
        self.scheduler.unregister(key)
        if record is not None and record.session is not None:
            record.session.close()

    @staticmethod
    def _original_parameters(record):
        if record.bindings is None or not hasattr(record.config, "__contains__"):
            return ()
        adapter = BlenderPropertyAdapter(record.config)
        values = adapter.evaluated_values(record.bindings, None,
                                          evaluated_owner=record.config)
        return tuple(sorted((key, repr(value)) for key, value in values.items()))

    @staticmethod
    def _scene_view_layer(scene):
        import bpy
        current = getattr(bpy.context, "view_layer", None)
        name = getattr(current, "name", "")
        return scene.view_layers.get(name) or scene.view_layers[0]

    @classmethod
    def _tag_scene_for_properties(cls, scene):
        tag = getattr(scene, "update_tag", None)
        if callable(tag):
            tag(refresh={'TIME'})
        try:
            import bpy
            view_layer = cls._scene_view_layer(scene)
            with bpy.context.temp_override(scene=scene, view_layer=view_layer):
                view_layer.update()
        except (ImportError, AttributeError, RuntimeError):
            pass

    def set_parameter(self, scene, instance_id, key, value):
        """Validate and persist a keyed edit without opening a GPU session."""
        record = self.get(scene, instance_id)
        config = record.config
        if getattr(scene, "library", None) is not None or getattr(config, "library", None) is not None:
            raise ValueError("linked live configuration is read-only")
        source = source_for_instance(config)
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        adapter = BlenderPropertyAdapter(config)
        if record.bindings is not None and record.source_hash == source_hash:
            store = record.bindings
        else:
            from .. import api
            candidate = api.compile(source)
            definitions = self._definitions(candidate)
            store = BindingStore(specs_from_effects(definitions))
            store.seed(seed_values_from_program(candidate, definitions))
            adapter.load(store)
        # Dynamic ID properties are absent from RNA's property definitions;
        # Blender raises TypeError for is_property_readonly on their names.
        store.set(key, value)
        adapter.persist(store)
        self._tag_scene_for_properties(scene)
        self.mark_dirty(scene, instance_id, "parameters")
        return store.value(key)

    def bind_input(self, scene, instance_id, binding, provider=None, image=None):
        """Bind a runtime provider or persist one local Blender still Image."""
        if image is not None and provider is not None:
            raise ValueError("choose an Image or a runtime provider")
        record = self.get(scene, instance_id)
        if image is not None or provider is not None:
            if record.session is not None:
                required = record.session.inputs.required
            else:
                from .. import api
                from ..runtime.inputs import declared_host_inputs
                required = declared_host_inputs(api.compile(source_for_instance(record.config)).graph())
            if binding not in required:
                raise KeyError("undeclared host input %s" % binding)
        if image is not None or provider is None:
            set_image_binding(scene, record.config, binding, image)
            record.image_providers.pop(binding, None)
            if provider is None:
                record.host_providers.pop(binding, None)
        if provider is not None:
            record.host_providers[binding] = provider
        if record.session is not None:
            self._sync_inputs(record)
        self.mark_dirty(scene, instance_id, "inputs")

    @staticmethod
    def _input_refs(config):
        result = []
        for item in getattr(config, "input_bindings", ()):
            image = getattr(item, "image", None)
            pointer = image.as_pointer() if image is not None and hasattr(image, "as_pointer") else id(image)
            result.append((item.binding_name, pointer))
        return tuple(result)

    def _sync_inputs(self, record):
        """Keep session providers aligned with saved Image refs and runtime binds."""
        from .inputs import BlenderImageProvider
        required = record.session.inputs.required
        desired = {}
        new_images = {}
        for item in getattr(record.config, "input_bindings", ()):
            binding, image = item.binding_name, item.image
            if binding in new_images:
                raise ValueError("duplicate persisted input binding %s" % binding)
            if image is None:
                raise ValueError("input binding %s has no Image" % binding)
            if getattr(image, "source", None) in ("MOVIE", "SEQUENCE"):
                raise ValueError("movie/sequence input needs an exact-frame runtime provider")
            previous = record.image_providers.get(binding)
            provider = previous if previous is not None and previous.image == image else BlenderImageProvider(image)
            new_images[binding] = provider
            desired[binding] = provider
        desired.update(record.host_providers)
        unknown = set(desired) - set(required)
        if unknown:
            raise ValueError("orphan host input binding: %s" % ", ".join(sorted(unknown)))
        for binding in tuple(record.session.inputs.providers):
            if binding not in desired:
                record.session.unbind_input(binding)
        for binding, provider in desired.items():
            if record.session.inputs.providers.get(binding) is not provider:
                record.session.bind_input(binding, provider)
        record.image_providers = new_images
        record.observed_input_refs = self._input_refs(record.config)

    def request_reset(self, scene, instance_id):
        record = self.get(scene, instance_id)
        record.reset_requested = True
        record.free_run_started = time.monotonic()
        self.mark_dirty(scene, instance_id, "reset")

    def mark_dirty(self, scene, instance_id, reason="configuration"):
        key = self._key(scene, instance_id)
        if key in self._records:
            self.scheduler.mark_dirty(key, reason, now=time.monotonic())

    def mark_scene_dirty(self, scene, reason="time"):
        # Frame handlers only enqueue work. Graph traversal and cycle diagnosis
        # belong to the qualified timer, outside Blender's frame callback.
        now = time.monotonic()
        for config in getattr(scene, "noisemaker_instances", ()):
            if config.live_enabled:
                key = self._key(scene, config.instance_id)
                if key in self._records:
                    self.scheduler.mark_dirty(key, reason, now=now)

    @staticmethod
    def _definitions(program):
        from ..compiler.registry import get_effect
        definitions = []
        seen = set()
        for render_pass in program.graph().passes:
            effect = render_pass.get("effectKey")
            step = render_pass.get("stepIndex")
            if not effect or (effect, step) in seen:
                continue
            seen.add((effect, step))
            definition = get_effect(effect)
            if definition is not None:
                definitions.append(definition)
        return definitions

    @staticmethod
    def _evaluated_owner(record, depsgraph):
        scene = record.scene
        evaluated_scene = scene.evaluated_get(depsgraph) if depsgraph is not None and hasattr(scene, "evaluated_get") else scene
        for config in evaluated_scene.noisemaker_instances:
            if config.instance_id == record.config.instance_id:
                return config
        raise KeyError("evaluated instance missing: %s" % record.config.instance_id)

    def _evaluated_values(self, record, *, strict=False):
        if record.bindings is None:
            return {}
        try:
            import bpy
            view_layer = self._scene_view_layer(record.scene)
            with bpy.context.temp_override(scene=record.scene, view_layer=view_layer):
                depsgraph = bpy.context.evaluated_depsgraph_get()
        except (ImportError, AttributeError, RuntimeError) as exc:
            if strict:
                raise RuntimeError("evaluated Scene dependency graph unavailable") from exc
            depsgraph = None
        evaluated = self._evaluated_owner(record, depsgraph)
        adapter = BlenderPropertyAdapter(record.config)
        # Blender evaluates ID properties through the evaluated Scene's nested
        # PropertyGroup; an original datablock read misses drivers/keyframes.
        return adapter.evaluated_values(record.bindings, depsgraph, evaluated_owner=evaluated)

    def current_identity(self, scene, config, request, width, height,
                         color_role="color", alpha_mode="PREMUL"):
        """Derive exact current cache provenance without a GPU session/backend."""
        from .. import api
        from ..runtime.inputs import InputRegistry
        from ..runtime.session import RenderSession, build_cache_identity
        from .inputs import BlenderImageProvider
        if request.mode != "timeline":
            raise ValueError("render cache requires timeline mode")
        source = source_for_instance(config)
        program = api.compile(source)
        definitions = self._definitions(program)
        store = BindingStore(specs_from_effects(definitions))
        store.seed(seed_values_from_program(program, definitions))
        if program.graph().is_stateful():
            animated = animated_parameter_keys(scene, config, store.active_keys)
            if animated:
                raise RuntimeError("stateful animated parameters need an exact-frame snapshot provider: %s" %
                                   ", ".join(animated))
        BlenderPropertyAdapter(config).load(store)
        temporary = LiveInstance(scene, config, program=program, bindings=store)
        values = self._evaluated_values(temporary, strict=True)
        inputs = InputRegistry(program.graph())
        record = self._records.get(self._key(scene, config.instance_id))
        desired = {}
        seen = set()
        for item in getattr(config, "input_bindings", ()):
            binding, image = item.binding_name, item.image
            if binding in seen:
                raise ValueError("duplicate persisted input binding %s" % binding)
            seen.add(binding)
            if image is None:
                raise ValueError("input binding %s has no Image" % binding)
            owner_get = getattr(image, "get", None)
            owner = owner_get("noisemaker_owner") if callable(owner_get) else None
            if owner and any(item.instance_id == owner
                             for item in getattr(scene, "noisemaker_instances", ())):
                raise RuntimeError("prepared cache cannot validate same-scene owned Image dependency before publication")
            if getattr(image, "source", None) in ("MOVIE", "SEQUENCE"):
                raise ValueError("movie/sequence input needs an exact-frame runtime provider")
            desired[binding] = BlenderImageProvider(image)
        if record is not None:
            desired.update(record.host_providers)
        unknown = set(desired) - set(inputs.required)
        if unknown:
            raise ValueError("orphan host input binding: %s" % ", ".join(sorted(unknown)))
        graph = program.graph()
        if graph.is_stateful():
            inexact = [binding for binding, provider in desired.items()
                       if getattr(provider, "historical_exact", True) is False]
            if inexact:
                raise ValueError("stateful replay requires exact-frame host input: %s" %
                                 ", ".join(sorted(inexact)))
        for binding, provider in desired.items():
            inputs.bind(binding, provider)
        revisions = inputs.revision_snapshot(request)
        input_history = {}
        if graph.is_stateful() and inputs.required:
            sample = map_frame(request)
            step_seconds = request.fixed_step_seconds or 1.0 / sample.fps_effective
            exact_step = sample.elapsed_seconds / step_seconds
            if exact_step < 0 or not math.isclose(exact_step, round(exact_step), abs_tol=1e-6):
                raise ValueError("stateful cache requires exact fixed-step time")
            if sample.simulation_step + 1 > 100000:
                raise ValueError("stateful cache history exceeds replay bound")
            for index in range(sample.simulation_step + 1):
                step_request, _time, _frame, _delta = RenderSession._step_request(
                    request, sample, step_seconds, index)
                input_history[index] = inputs.revision_snapshot(step_request)
        return build_cache_identity(
            program, request, width=width, height=height, parameters=values,
            input_sources=inputs.source_identity(), input_revisions=revisions,
            input_history=input_history, color_role=color_role, alpha_mode=alpha_mode)

    def ensure_session(self, scene, instance_id, width, height, *, force_sync=False):
        record = self.get(scene, instance_id)
        self.sync_instance(scene, record.config, force=force_sync, width=width, height=height)
        return record

    def sync_instance(self, scene, config, *, force=False, width=None, height=None):
        """Compile and apply evaluated properties; strict final callers get errors."""
        record = self._record(scene, config)
        width = width or (record.session.width if record.session else config.preview_width)
        height = height or (record.session.height if record.session else config.preview_height)
        try:
            source = source_for_instance(config)
            source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if record.program is None or source_hash != record.source_hash:
                from .. import api
                candidate = api.compile(source)
                definitions = self._definitions(candidate)
                specs = specs_from_effects(definitions)
                compiled_values = seed_values_from_program(candidate, definitions)
                if candidate.graph().is_stateful():
                    animated = animated_parameter_keys(scene, config,
                                                       (spec.key for spec in specs))
                    if animated:
                        raise RuntimeError("stateful animated parameters need an exact-frame snapshot provider: %s" %
                                           ", ".join(animated))
                previous_keys = set(record.bindings._bindings) if record.bindings is not None else set()
                candidate_bindings = (BindingStore(specs) if record.bindings is None
                                      else copy.deepcopy(record.bindings))
                if record.bindings is not None:
                    candidate_bindings.reconcile(specs)
                candidate_bindings.seed({key: value for key, value in compiled_values.items()
                                         if key not in previous_keys})
                adapter = BlenderPropertyAdapter(config)
                adapter.load(candidate_bindings)
                recompiled = record.session is not None
                if recompiled:
                    record.session.recompile(candidate)
                record.bindings = candidate_bindings
                adapter.persist(record.bindings)
                # Newly created nested ID properties are not visible in the
                # evaluated Scene until its dependency graph is tagged.
                self._tag_scene_for_properties(scene)
                record.program = candidate
                record.source_hash = source_hash
                # Recompilation reconstructs graph defaults. Compare saved
                # keyed values with those new defaults, rather than the old
                # session values, so only actual overrides need reapplication.
                record.applied_values = {
                    key: compiled_values.get(key, binding.spec.default)
                    for key, binding in record.bindings._bindings.items()
                    if not binding.orphaned
                }
            if record.program is not None and record.program.graph().is_stateful() and record.bindings is not None:
                animated = animated_parameter_keys(scene, config, record.bindings.active_keys)
                if animated:
                    raise RuntimeError("stateful animated parameters need an exact-frame snapshot provider: %s" %
                                       ", ".join(animated))
            if record.session is None:
                from .. import api
                record.session = api.open_session(record.program, width=width, height=height)
            elif (record.session.width, record.session.height) != (width, height):
                record.session.resize(width, height)
            if hasattr(record.session, "inputs"):
                self._sync_inputs(record)
            if record.publisher is None:
                from .images import ImagePublisher
                record.publisher = ImagePublisher(config.instance_id, image=config.output_image,
                                                  role=config.color_role, alpha_mode=config.alpha_mode)
            values = self._evaluated_values(record)
            for key, value in values.items():
                if record.applied_values.get(key) != value:
                    record.session.set_parameter(key, value)
                    record.bindings.set(key, value)
                    record.applied_values[key] = value
            record.observed_params = tuple(sorted((key, repr(value)) for key, value in values.items()))
            record.observed_original_params = self._original_parameters(record)
            config.last_error = ""
            return record
        except Exception as exc:
            config.last_error = "%s: %s" % (type(exc).__name__, exc)
            if force:
                raise
            raise

    def _produce(self, record):
        config = record.config
        scene = record.scene
        try:
            self.sync_instance(scene, config, width=config.preview_width,
                               height=config.preview_height)
            if record.reset_requested:
                record.session.reset()
                record.reset_requested = False
                record.pending_preview_request = None
                record.pending_preview_signature = None
            try:
                import bpy
                playing = bool(getattr(bpy.context.screen, "is_animation_playing", False))
            except (ImportError, AttributeError):
                playing = False
            current_request = request_for_scene(
                scene, config, purpose="preview",
                free_run_elapsed=time.monotonic() - record.free_run_started,
                playing=playing,
            )
            signature = (
                record.source_hash,
                tuple(sorted((key, repr(value)) for key, value in record.applied_values.items())),
                record.observed_input_refs,
                getattr(record.session, "_revision", None),
                current_request.mode, current_request.fps, current_request.fps_base,
                current_request.origin_frame, current_request.loop_seconds,
                current_request.offset_seconds, current_request.fixed_step_seconds,
            )
            pending = record.pending_preview_request
            if (pending is not None and signature == record.pending_preview_signature
                    and (playing or current_request.mode == "free_run"
                         or (pending.frame, pending.subframe) ==
                         (current_request.frame, current_request.subframe))):
                request = pending
            else:
                request = current_request
                record.pending_preview_request = None
                record.pending_preview_signature = None
            try:
                output = record.session.evaluate(request, max_steps=2)
            except ReplayPending:
                record.pending_preview_request = request
                record.pending_preview_signature = signature
                raise
            record.pending_preview_request = None
            record.pending_preview_signature = None
            record.publisher.role = config.color_role
            record.publisher.alpha_mode = config.alpha_mode
            image = record.session.publish_image(
                output, publisher=record.publisher, name=config.image_name or config.name,
                role=config.color_role, alpha_mode=config.alpha_mode,
            )
            config.output_image = image
            config.last_error = ""
            if request != current_request:
                self.mark_dirty(scene, config.instance_id, "time")
            return image
        except ReplayPending:
            raise
        except Exception as exc:
            record.pending_preview_request = None
            record.pending_preview_signature = None
            config.last_error = "%s: %s" % (type(exc).__name__, exc)
            raise

    def scan(self, scenes, *, now=None, playing=False):
        """Bounded source/time checks supplement RNA callbacks and frame notices."""
        now = time.monotonic() if now is None else now
        for scene in scenes:
            for config in getattr(scene, "noisemaker_instances", ()):
                if not config.instance_id:
                    continue
                key = self._key(scene, config.instance_id)
                if not config.live_enabled:
                    if key in self._records:
                        self.scheduler.set_continuous(key, False)
                        self.scheduler.pause(key)
                    continue
                record = self._record(scene, config)
                self.scheduler.set_continuous(key, config.time_mode == "free_run" and not playing)
                self.scheduler.set_max_fps(key, getattr(config, "preview_fps", 60))
                if config.paused:
                    self.scheduler.pause(key)
                else:
                    self.scheduler.resume(key)
                try:
                    source_hash = hashlib.sha256(source_for_instance(config).encode("utf-8")).hexdigest()
                except (OSError, ValueError) as exc:
                    source_hash = "error:" + str(exc)
                if source_hash != record.observed_hash:
                    record.observed_hash = source_hash
                    self.scheduler.mark_dirty(key, "source", now=now)
                time_key = (scene.frame_current, scene.frame_subframe,
                            scene.render.fps, scene.render.fps_base,
                            config.origin_frame, config.loop_seconds,
                            config.offset_seconds, config.fixed_step_seconds,
                            config.time_mode, config.preview_width, config.preview_height)
                if time_key != record.observed_time:
                    record.observed_time = time_key
                    self.scheduler.mark_dirty(key, "time", now=now)
                input_refs = self._input_refs(config)
                if input_refs != record.observed_input_refs:
                    record.observed_input_refs = input_refs
                    self.scheduler.mark_dirty(key, "inputs", now=now)
                if record.session is not None and hasattr(record.session, "inputs"):
                    try:
                        request = request_for_scene(scene, config, purpose="preview",
                                                    free_run_elapsed=now - record.free_run_started,
                                                    playing=playing)
                        input_revisions = record.session.inputs.revision_snapshot(request)
                    except Exception as exc:
                        input_revisions = (("error", "%s: %s" % (type(exc).__name__, exc)),)
                    if input_revisions != record.observed_inputs:
                        record.observed_inputs = input_revisions
                        self.scheduler.mark_dirty(key, "inputs", now=now)
                if record.bindings is not None:
                    try:
                        original = self._original_parameters(record)
                        if (record.observed_original_params is not None
                                and original != record.observed_original_params):
                            self._tag_scene_for_properties(scene)
                            self.scheduler.mark_dirty(key, "parameters", now=now)
                        record.observed_original_params = original
                        values = self._evaluated_values(record)
                        parameters = tuple(sorted((name, repr(value)) for name, value in values.items()))
                    except Exception as exc:
                        parameters = (("error", "%s: %s" % (type(exc).__name__, exc)),)
                    if parameters != record.observed_params:
                        record.observed_params = parameters
                        self.scheduler.mark_dirty(key, "parameters", now=now)

    def tick(self, scenes, *, now=None, allowed=True, playing=False, window_id=None):
        now = time.monotonic() if now is None else now
        scenes = tuple(scenes)
        if window_id is not None:
            if self._window_id is not None and self._window_id != window_id:
                self.shutdown()
            self._window_id = window_id
        if self.pending_rebuild:
            self.shutdown()
            ensure_unique_ids(scenes)
            self.pending_rebuild = False
        valid = {self._key(scene, config.instance_id)
                 for scene in scenes
                 for config in getattr(scene, "noisemaker_instances", ())
                 if config.instance_id}
        for key in tuple(self._records):
            if key not in valid:
                record = self._records[key]
                self.remove(record.scene, record.config.instance_id)
        self.scan(scenes, now=now, playing=playing)
        order = []
        dependencies = {}
        for scene in scenes:
            configs, scene_dependencies = self._ordered_configs(scene, preview=True)
            for config in configs:
                key = self._key(scene, config.instance_id)
                order.append(key)
                dependencies[key] = {self._key(scene, parent)
                                     for parent in scene_dependencies[config.instance_id]}
        generations = {key: self.scheduler.status(key).generation
                       for key in order if key in self.scheduler._slots}
        produced = self.scheduler.tick(now=now, allowed=allowed,
                                       order=order, dependencies=dependencies)
        if (produced is not None and produced in generations
                and self.scheduler.status(produced).generation > generations[produced]):
            for child, parents in dependencies.items():
                if produced in parents:
                    self.scheduler.mark_dirty(child, "inputs", now=now)
        return produced

    def suspend(self, reason):
        self.scheduler.suspend(reason)

    def resume(self, reason):
        self.scheduler.resume_all(reason)

    def shutdown(self):
        errors = []
        for record in self._records.values():
            if record.session is not None:
                try:
                    record.session.close()
                except Exception as exc:
                    errors.append("%s: %s" % (type(exc).__name__, exc))
        self._records.clear()
        self.scheduler = LiveScheduler()
        self._window_id = None
        if errors:
            self.lifecycle_error = "; ".join(errors)


registry = LiveRegistry()


def _timer():
    import bpy
    if bpy.app.background:
        return 0.25
    window = bpy.context.window
    if window is None:
        return 0.25
    try:
        if bpy.app.is_job_running('RENDER'):
            return 0.05
        screen = bpy.context.screen
        registry.tick(tuple(bpy.data.scenes), allowed=True,
                      playing=bool(getattr(screen, "is_animation_playing", False)),
                      window_id=window.as_pointer())
        for area in screen.areas if screen is not None else ():
            if area.type in {'IMAGE_EDITOR', 'NODE_EDITOR', 'VIEW_3D'}:
                area.tag_redraw()
    except Exception as exc:
        registry.lifecycle_error = "%s: %s" % (type(exc).__name__, exc)
        print("Noisemaker live lifecycle: " + registry.lifecycle_error, flush=True)
        for scene in bpy.data.scenes:
            for config in getattr(scene, "noisemaker_instances", ()):
                if config.live_enabled and not config.last_error:
                    config.last_error = registry.lifecycle_error
    return registry.scheduler.next_delay(now=time.monotonic(), idle=0.033)


def _frame_change(scene, depsgraph=None):
    registry.mark_scene_dirty(scene, "time")


def _pre_rebuild(*_args):
    # Dispose while the old scene/context still exists; post-load GPU handles
    # must never be freed through a replacement context.
    registry.shutdown()
    registry.pending_rebuild = True


def _rebuild(*_args):
    registry.pending_rebuild = True


def _save_pre(*_args):
    import bpy
    try:
        pack_outputs_before_save(bpy.data.scenes)
    except Exception as exc:
        registry.lifecycle_error = "save output packing failed: %s: %s" % (type(exc).__name__, exc)
        print("Noisemaker " + registry.lifecycle_error, flush=True)
        raise


def _native_render_start(*_args):
    registry.suspend("native_render")


def _native_render_end(*_args):
    registry.resume("native_render")


def register():
    import bpy
    from bpy.app.handlers import persistent
    for callback in (_frame_change, _pre_rebuild, _rebuild,
                     _native_render_start, _native_render_end, _save_pre):
        persistent(callback)
    handlers = bpy.app.handlers
    for collection, callback in (
        (handlers.frame_change_post, _frame_change),
        (handlers.load_pre, _pre_rebuild), (handlers.undo_pre, _pre_rebuild),
        (handlers.redo_pre, _pre_rebuild),
        (handlers.load_post, _rebuild), (handlers.undo_post, _rebuild),
        (handlers.redo_post, _rebuild),
        (handlers.save_pre, _save_pre),
        (handlers.render_init, _native_render_start),
        (handlers.render_complete, _native_render_end),
        (handlers.render_cancel, _native_render_end),
    ):
        if callback not in collection:
            collection.append(callback)
    # addon_utils.enable runs register() under Blender's _RestrictData. Repair
    # duplicated IDs on the first unrestricted timer tick after registration.
    registry.pending_rebuild = True
    if not bpy.app.timers.is_registered(_timer):
        bpy.app.timers.register(_timer, first_interval=0.25, persistent=True)


def unregister():
    import bpy
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    handlers = bpy.app.handlers
    for collection, callback in (
        (handlers.frame_change_post, _frame_change),
        (handlers.load_pre, _pre_rebuild), (handlers.undo_pre, _pre_rebuild),
        (handlers.redo_pre, _pre_rebuild),
        (handlers.load_post, _rebuild), (handlers.undo_post, _rebuild),
        (handlers.redo_post, _rebuild),
        (handlers.save_pre, _save_pre),
        (handlers.render_init, _native_render_start),
        (handlers.render_complete, _native_render_end),
        (handlers.render_cancel, _native_render_end),
    ):
        if callback in collection:
            collection.remove(callback)
    registry.shutdown()
