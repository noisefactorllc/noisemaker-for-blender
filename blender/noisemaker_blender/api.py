"""CPU-importable public facade for reusable programs and GPU render sessions."""

from .runtime.session import Program, RenderSession
from .runtime.output import OutputHandle, OutputDescriptor, StaleOutputError
from .runtime.clock import FrameRequest
from .integration.render import RenderPolicy, PreparedRender
from .integration.parameters import PreparedParameterSnapshots


def _instance_scene(instance):
    scene = getattr(instance, "id_data", None)
    if scene is None or not getattr(instance, "instance_id", None):
        raise TypeError("expected a registered Noisemaker instance")
    return scene


def _instance_values(instance, program):
    from .compiler.registry import get_effect
    from .integration.parameters import (
        BindingStore, BlenderPropertyAdapter, specs_from_effects,
        seed_values_from_program)
    definitions = []
    seen = set()
    for render_pass in program.graph().passes:
        identity = (render_pass.get("effectKey"), render_pass.get("stepIndex"))
        if not identity[0] or identity in seen:
            continue
        seen.add(identity)
        definition = get_effect(identity[0])
        if definition is not None:
            definitions.append(definition)
    store = BindingStore(specs_from_effects(definitions))
    store.seed(seed_values_from_program(program, definitions))
    adapter = BlenderPropertyAdapter(instance)
    adapter.load(store)
    scene = _instance_scene(instance)
    if any(adapter.property_name(key) not in instance for key in store.active_keys):
        if getattr(scene, "library", None) is not None or getattr(instance, "library", None) is not None:
            raise ValueError("linked instance has missing keyed parameters")
        adapter.persist(store)
        tag = getattr(scene, "update_tag", None)
        if callable(tag):
            tag(refresh={"TIME"})
    try:
        import bpy
    except ImportError:
        return store.values()
    current_layer = getattr(bpy.context, "view_layer", None)
    name = getattr(current_layer, "name", "")
    view_layer = scene.view_layers.get(name) or scene.view_layers[0]
    with bpy.context.temp_override(scene=scene, view_layer=view_layer):
        view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_scene = scene.evaluated_get(depsgraph)
    evaluated = next((item for item in evaluated_scene.noisemaker_instances
                      if item.instance_id == instance.instance_id), None)
    if evaluated is None:
        raise KeyError("evaluated instance missing: %s" % instance.instance_id)
    return adapter.evaluated_values(store, depsgraph, evaluated_owner=evaluated)


def compile(source):
    """Compile DSL into an immutable graph snapshot."""
    from .compiler import compile_graph
    return Program.from_graph(source, compile_graph(source))


def open_session(program, *, size=None, width=None, height=None,
                 backend_factory=None, shaders_root=None):
    instance = None
    prepared = program if isinstance(program, PreparedParameterSnapshots) else None
    if prepared is not None:
        program = prepared.program
    if not isinstance(program, Program) and getattr(program, "instance_id", None):
        from .integration.persistence import source_for_instance
        instance = program
        program = compile(source_for_instance(instance))
        if program.graph().is_stateful():
            from .integration.parameters import animated_parameter_keys
            animated = animated_parameter_keys(_instance_scene(instance), instance,
                                               program.parameter_values().keys())
            if animated:
                raise ValueError("stateful instance has animated parameters without "
                                 "historical snapshots: %s" % ", ".join(animated))
        if size is None:
            width = instance.preview_width if width is None else width
            height = instance.preview_height if height is None else height
    instance_values = _instance_values(instance, program) if instance is not None else None
    session = RenderSession(program, size=size, width=width, height=height,
                            backend_factory=backend_factory, shaders_root=shaders_root)
    if prepared is not None:
        try:
            compiled_values = program.parameter_values()
            for key, value in prepared.static_values:
                if compiled_values.get(key) != value:
                    session.set_parameter(key, value)
            session.set_parameter_snapshot_provider(prepared)
        except Exception:
            session.close()
            raise
    if instance is not None:
        try:
            compiled_values = program.parameter_values()
            for key, value in instance_values.items():
                if compiled_values.get(key) != value:
                    session.set_parameter(key, value)
            from .integration.inputs import BlenderImageProvider
            for item in getattr(instance, "input_bindings", ()):
                if item.image is None:
                    raise ValueError("input binding %s has no Image" % item.binding_name)
                session.bind_input(item.binding_name, BlenderImageProvider(item.image))
            from .integration.lifecycle import registry
            record = registry.get(_instance_scene(instance), instance.instance_id)
            for binding, provider in record.host_providers.items():
                session.bind_input(binding, provider)
            def sync_request(request):
                scene = _instance_scene(instance)
                if hasattr(scene, "frame_current"):
                    actual = (scene.frame_current, scene.frame_subframe,
                              scene.render.fps, scene.render.fps_base)
                    requested = (request.frame, request.subframe,
                                 request.fps, request.fps_base)
                    if actual != requested:
                        raise ValueError("instance evaluation requires current Scene time and fps")
                if source_for_instance(instance) != session.program.source:
                    raise RuntimeError("instance source changed; open a new session")
                if session.graph.is_stateful():
                    from .integration.parameters import animated_parameter_keys
                    animated = animated_parameter_keys(scene, instance,
                                                       session.program.parameter_values().keys())
                    if animated:
                        raise ValueError("stateful instance has animated parameters without "
                                         "historical snapshots: %s" % ", ".join(animated))
                resolved = _instance_values(instance, session.program)
                active = dict(session.program.parameter_values(), **session._parameters)
                for key, value in resolved.items():
                    if active.get(key) != value:
                        session.set_parameter(key, value)
            session._request_sync = sync_request
            session._instance_output_owner = instance
        except Exception:
            session.close()
            raise
    return session


def set_parameter(session, key, value):
    """Validate and update a live session parameter by its stable effect key."""
    if not isinstance(session, RenderSession):
        from .integration.lifecycle import registry
        instance = session
        return registry.set_parameter(_instance_scene(instance),
                                      instance.instance_id, key, value)
    return session.set_parameter(key, value)


def bind_input(session, binding, provider=None, *, image=None):
    """Bind a session provider or an instance's persistent Blender Image."""
    if isinstance(session, RenderSession):
        if image is not None:
            from .integration.inputs import BlenderImageProvider
            provider = BlenderImageProvider(image)
        if provider is None:
            raise ValueError("binding requires an Image or provider")
        return session.bind_input(binding, provider)
    from .integration.lifecycle import registry
    instance = session
    return registry.bind_input(_instance_scene(instance), instance.instance_id,
                               binding, provider=provider, image=image)


def set_external_state(session, provider):
    """Bind exact-frame audio/MIDI snapshots for automation uniforms."""
    return session.set_external_state(provider)


def create_instance(scene, program, name="Noisemaker"):
    from .integration.persistence import create_instance as create
    compiled = program if isinstance(program, Program) else compile(program)
    instance = create(scene, compiled, name=name)
    _instance_values(instance, compiled)
    return instance


def prepare_parameter_snapshots(instance, request, *, max_steps=64):
    """Freeze bounded evaluated Scene parameters for a Program replay session."""
    from .integration.parameters import prepare_parameter_snapshots as prepare
    return prepare(instance, request, max_steps=max_steps)


def attach_material(instance, material, image):
    from .integration.materials import attach_material as attach
    return attach(instance, material, image)


def attach_world(instance, world, image):
    from .integration.materials import attach_world as attach
    return attach(instance, world, image)


def attach_compositor(instance, node_tree, image):
    from .integration.compositor import attach_compositor as attach
    return attach(instance, node_tree, image)


def attach_geometry_image(instance, node_tree, image):
    from .integration.geometry import attach_geometry_image as attach
    return attach(instance, node_tree, image)


def prepare_render(scene, frames, policy=None):
    from .integration.render import prepare_render as prepare
    return prepare(scene, frames, policy)


def render_animation(scene, frame_start, frame_end, policy=None):
    from .integration.render import render_animation as render
    return render(scene, frame_start, frame_end, policy)


def render_prepared(scene, prepared, frames=None, policy=None, *, registry=None,
                    renderer=None):
    from .integration.render import render_prepared as render
    return render(scene, prepared, frames, policy, registry=registry, renderer=renderer)


__all__ = ["Program", "RenderSession", "FrameRequest", "RenderPolicy", "PreparedRender",
           "PreparedParameterSnapshots", "prepare_parameter_snapshots",
           "OutputHandle",
           "OutputDescriptor", "StaleOutputError", "compile", "open_session",
           "set_parameter", "bind_input", "set_external_state", "create_instance", "attach_material",
           "attach_world", "attach_compositor", "attach_geometry_image",
           "prepare_render", "render_animation", "render_prepared"]
