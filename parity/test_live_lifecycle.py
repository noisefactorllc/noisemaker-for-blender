"""A live instance persists independently of its GPU session and render purpose."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from noisemaker_blender.integration.lifecycle import LiveRegistry, request_for_scene


def config(instance_id, *, enabled=False, image=None, paused=False):
    return SimpleNamespace(instance_id=instance_id, live_enabled=enabled,
                           output_image=image, paused=paused, time_mode="free_run",
                           origin_frame=1, loop_seconds=10, offset_seconds=2,
                           fixed_step_seconds=0, preview_width=64, preview_height=32,
                           render_width=0, render_height=0, source_mode="INLINE",
                           source="noise()", text=None, filepath="", name="X", last_error="")

class Scene:
    def __init__(self, *instances):
        self.noisemaker_instances = list(instances)
        self.frame_current = 42
        self.frame_subframe = 0.25
        self.render = SimpleNamespace(fps=30000, fps_base=1001,
                                      resolution_x=1920, resolution_y=1080,
                                      resolution_percentage=50)
    def as_pointer(self): return id(self)

class LifecycleTests(unittest.TestCase):
    def test_final_request_uses_timeline_even_when_preview_free_runs(self):
        item = config("one", enabled=True)
        scene = Scene(item)
        request = request_for_scene(scene, item, purpose="final")
        self.assertEqual((request.frame, request.subframe), (42, 0.25))
        self.assertEqual((request.fps, request.fps_base), (30000, 1001))
        self.assertEqual((request.mode, request.purpose), ("timeline", "final"))
        preview = request_for_scene(scene, item, purpose="preview", free_run_elapsed=0.5)
        self.assertEqual((preview.mode, preview.wall_seconds), ("free_run", 0.5))

    def test_evaluated_parameter_change_marks_preview_dirty_without_frame_event(self):
        item = config("one", enabled=True)
        scene = Scene(item)
        registry = LiveRegistry()
        registry._evaluated_values = lambda record: {"solid#0.alpha": item.animated_value}
        item.animated_value = 0.5
        record = registry.get(scene, "one")
        record.bindings = object()  # A compiled instance with evaluated bindings.
        registry.scan([scene], now=1)
        registry.scheduler.status(registry._key(scene, "one")).dirty.clear()
        item.animated_value = 0.75
        registry.scan([scene], now=2)
        self.assertIn("parameters", registry.scheduler.status(registry._key(scene, "one")).dirty)
        registry.shutdown()

    def test_recompile_reapplies_persisted_keyed_value(self):
        from noisemaker_blender import api
        from noisemaker_blender.integration import lifecycle
        class Owner(dict):
            def __init__(self):
                super().__init__()
                self.__dict__.update(vars(config("one", enabled=True)))
                self.ui = {}
                self.color_role = "color"
                self.alpha_mode = "PREMUL"
                self.image_name = "Test"
            def id_properties_ui(self, key):
                return SimpleNamespace(update=lambda **kwargs: None)
        class Session:
            width, height = 64, 32
            def __init__(self): self.set_calls = []; self.recompiled = []
            def recompile(self, program): self.recompiled.append(program.source)
            def set_parameter(self, key, value): self.set_calls.append((key, value))
            def close(self): pass
        owner = Owner()
        owner.source = "old"
        scene = Scene(owner)
        scene.tags = 0
        scene.update_tag = lambda **kwargs: setattr(scene, "tags", scene.tags + 1)
        session = Session()
        definition = {"namespace": "synth", "func": "solid", "globals": {
            "alpha": {"type": "float", "default": 0.5, "min": 0, "max": 1,
                      "uniform": "alpha"}}}
        registry = LiveRegistry()
        registry._definitions = lambda program: [definition]
        registry._evaluated_values = lambda record: {
            "solid#0.alpha": record.config["nm:solid#0.alpha"]}
        with patch.object(api, "compile", side_effect=lambda source: SimpleNamespace(
                source=source, graph=lambda: SimpleNamespace(is_stateful=lambda: False))), \
             patch.object(api, "open_session", return_value=session), \
             patch.object(lifecycle, "seed_values_from_program",
                          side_effect=lambda program, definitions: {
                              "solid#0.alpha": 0.25 if program.source == "old" else 0.75}):
            registry.sync_instance(scene, owner, width=64, height=32)
            self.assertGreaterEqual(scene.tags, 1)
            self.assertEqual(owner["nm:solid#0.alpha"], 0.25)
            owner.source = "new"
            registry.sync_instance(scene, owner, width=64, height=32)
        self.assertEqual(session.recompiled, ["new"])
        self.assertEqual(session.set_calls, [("solid#0.alpha", 0.25)])
        registry.shutdown()

    def test_invalid_saved_binding_does_not_replace_last_good_graph(self):
        from noisemaker_blender import api
        from noisemaker_blender.integration import lifecycle
        class Owner(dict):
            def __init__(self):
                super().__init__()
                self.__dict__.update(vars(config("one", enabled=True)))
                self.source = "old"
                self.color_role = "color"
                self.alpha_mode = "PREMUL"
                self.image_name = "Test"
            def id_properties_ui(self, key):
                return SimpleNamespace(update=lambda **kwargs: None)
        class Session:
            width, height = 64, 32
            def __init__(self): self.recompiled = []
            def recompile(self, program): self.recompiled.append(program.source)
            def set_parameter(self, key, value): pass
            def close(self): pass
        owner = Owner()
        scene = Scene(owner)
        scene.update_tag = lambda **kwargs: None
        session = Session()
        definition = {"namespace": "synth", "func": "solid", "globals": {
            "alpha": {"type": "float", "default": 0.5, "min": 0, "max": 1,
                      "uniform": "alpha"}}}
        registry = LiveRegistry()
        registry._definitions = lambda program: [definition]
        registry._evaluated_values = lambda record: {
            "solid#0.alpha": record.config["nm:solid#0.alpha"]}
        with patch.object(api, "compile", side_effect=lambda source: SimpleNamespace(
                source=source, graph=lambda: SimpleNamespace(is_stateful=lambda: False))), \
             patch.object(api, "open_session", return_value=session), \
             patch.object(lifecycle, "seed_values_from_program",
                          return_value={"solid#0.alpha": 0.25}):
            record = registry.sync_instance(scene, owner, width=64, height=32)
            owner["nm:solid#0.alpha"] = "invalid"
            owner.source = "new"
            with self.assertRaises((TypeError, ValueError)):
                registry.sync_instance(scene, owner, force=True, width=64, height=32)
        self.assertEqual(session.recompiled, [])
        self.assertEqual(record.program.source, "old")
        self.assertEqual(record.bindings.value("solid#0.alpha"), 0.25)
        registry.shutdown()

    def test_stateful_keyed_parameter_rejected_before_gpu_session(self):
        from noisemaker_blender import api
        from noisemaker_blender.integration import lifecycle
        class Owner(dict):
            def __init__(self):
                super().__init__()
                self.__dict__.update(vars(config("one", enabled=True)))
                self.source = "stateful"
            def path_from_id(self): return "noisemaker_instances[0]"
        owner = Owner()
        scene = Scene(owner)
        path = 'noisemaker_instances[0]["nm:solid#0.alpha"]'
        scene.animation_data = SimpleNamespace(
            action=SimpleNamespace(fcurves=[SimpleNamespace(data_path=path)], layers=()),
            action_slot=None, drivers=(), nla_tracks=())
        graph = {"renderSurface": "o0", "passes": [{"effectKey": "solid", "stepIndex": 0,
                 "passType": "effect", "namespace": "synth", "func": "solid", "progName": "solid",
                 "inputs": {"stateTex": "global_state"}, "outputs": {"color": "global_o0"},
                 "uniforms": {"alpha": 0.25}}],
                 "textures": {"global_o0": {"width": "screen", "height": "screen", "format": "rgba16f"}},
                 "allocations": {}, "programs": {}}
        program = api.Program.from_graph("stateful", graph)
        registry = LiveRegistry()
        definition = {"namespace": "synth", "func": "solid", "globals": {
            "alpha": {"type": "float", "default": 0.25, "uniform": "alpha"}}}
        registry._definitions = lambda candidate: [definition]
        with patch.object(api, "compile", return_value=program), \
             patch.object(api, "open_session", side_effect=AssertionError("GPU opened")), \
             patch.object(lifecycle, "seed_values_from_program",
                          return_value={"solid#0.alpha": 0.25}):
            with self.assertRaisesRegex(RuntimeError, "exact-frame snapshot provider"):
                registry.sync_instance(scene, owner, width=64, height=32)
        registry.shutdown()

    def test_pending_free_run_preview_holds_request_until_replay_completes(self):
        from noisemaker_blender.integration import lifecycle
        from noisemaker_blender.runtime.checkpoints import ReplayPending, ReplayStatus
        item = config("one", enabled=True)
        item.color_role = "color"
        item.alpha_mode = "PREMUL"
        item.image_name = "Test"
        scene = Scene(item)
        registry = LiveRegistry()
        record = registry.get(scene, "one")
        record.free_run_started = 0
        record.source_hash = "source"
        record.program = SimpleNamespace(graph=lambda: SimpleNamespace(is_stateful=lambda: True))
        record.publisher = SimpleNamespace(role="color", alpha_mode="PREMUL")
        image = object()
        class Session:
            def __init__(self): self.requests = []
            def evaluate(self, request, **kwargs):
                self.requests.append(request)
                if len(self.requests) <= 3:
                    raise ReplayPending(ReplayStatus(24, len(self.requests) * 2, 24, False))
                return object()
            def publish_image(self, *args, **kwargs): return image
            def close(self): pass
        record.session = Session()
        clock = [1.0]
        with patch.object(registry, "sync_instance", return_value=record), \
             patch.object(lifecycle.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(ReplayPending):
                registry._produce(record)
            clock[0] = 1.2
            with self.assertRaises(ReplayPending):
                registry._produce(record)
            clock[0] = 1.4
            with self.assertRaises(ReplayPending):
                registry._produce(record)
            clock[0] = 1.6
            registry._produce(record)
            clock[0] = 1.8
            registry._produce(record)
        first, *rest = record.session.requests
        self.assertTrue(all(request == first for request in rest[:3]))
        self.assertGreater(rest[3].wall_seconds, first.wall_seconds)
        registry.shutdown()

    def test_direct_keyed_property_edit_tags_own_scene_before_evaluated_read(self):
        from noisemaker_blender.integration.parameters import (
            BindingStore, ParameterSpec, BlenderPropertyAdapter)
        class Owner(dict):
            def __init__(self):
                super().__init__()
                self.__dict__.update(vars(config("one", enabled=True)))
            def id_properties_ui(self, key):
                return SimpleNamespace(update=lambda **kwargs: None)
        owner = Owner()
        scene = Scene(owner)
        scene.tags = 0
        scene.update_tag = lambda **kwargs: setattr(scene, "tags", scene.tags + 1)
        registry = LiveRegistry()
        record = registry.get(scene, "one")
        record.bindings = BindingStore([ParameterSpec("solid#0.alpha", "float", 0.25)])
        BlenderPropertyAdapter(owner).persist(record.bindings)
        record.observed_original_params = registry._original_parameters(record)
        registry._evaluated_values = lambda rec: {"solid#0.alpha": owner["nm:solid#0.alpha"]}
        owner["nm:solid#0.alpha"] = 0.75
        registry.scan([scene], now=1)
        self.assertEqual(scene.tags, 1)
        self.assertIn("parameters", registry.scheduler.status(registry._key(scene, "one")).dirty)
        registry.shutdown()

    def test_cpu_current_identity_uses_source_parameters_and_saved_image(self):
        from noisemaker_blender import api
        from noisemaker_blender.runtime.clock import FrameRequest
        class Owner(dict):
            def __init__(self):
                super().__init__()
                self.__dict__.update(vars(config("one", enabled=True)))
                self.source = "search synth\nmedia().write(o0)\nrender(o0)\n"
                image = SimpleNamespace(source="GENERATED", filepath="", size=(2, 2),
                                        alpha_mode="STRAIGHT", name="input")
                self.input_bindings = [SimpleNamespace(binding_name="imageTex_step_0",
                                                      image=image)]
        owner = Owner()
        scene = Scene(owner)
        registry = LiveRegistry()
        registry._evaluated_values = lambda record, **kwargs: record.bindings.values()
        request = FrameRequest(frame=3, fps=24, mode="timeline", purpose="cache")
        with patch.object(api, "open_session", side_effect=AssertionError("GPU opened")):
            identity = registry.current_identity(scene, owner, request, 32, 16)
        self.assertEqual(identity["source"], api.compile(owner.source).source_id)
        self.assertEqual((identity["width"], identity["height"]), (32, 16))
        self.assertIn("imageTex_step_0", identity["inputs"]["current"])
        self.assertIn("media#0.position", identity["parameters"])
        registry.shutdown()

    def test_cpu_current_identity_rejects_owned_image_before_prepared_publication(self):
        from noisemaker_blender.runtime.clock import FrameRequest
        class Image(dict):
            source = "GENERATED"
            filepath = ""
            size = (2, 2)
            alpha_mode = "STRAIGHT"
            name = "upstream"
        class Owner(dict):
            def __init__(self, item):
                super().__init__()
                self.__dict__.update(vars(item))
        consumer = Owner(config("downstream", enabled=True))
        consumer.source = "search synth\nmedia().write(o0)\nrender(o0)\n"
        consumer.input_bindings = [SimpleNamespace(
            binding_name="imageTex_step_0",
            image=Image(noisemaker_owner="upstream"))]
        producer = config("upstream", enabled=True)
        scene = Scene(consumer, producer)
        registry = LiveRegistry()
        registry._evaluated_values = lambda record, **kwargs: record.bindings.values()
        request = FrameRequest(frame=3, fps=24, mode="timeline", purpose="cache")
        with self.assertRaisesRegex(RuntimeError, "cannot validate same-scene owned Image"):
            registry.current_identity(scene, consumer, request, 32, 16)
        registry.shutdown()

    def test_stateful_cpu_identity_rejects_inexact_historical_provider(self):
        from noisemaker_blender import api
        from noisemaker_blender.integration import lifecycle
        from noisemaker_blender.runtime.clock import FrameRequest
        class Owner(dict):
            def __init__(self):
                super().__init__()
                self.__dict__.update(vars(config("one", enabled=True)))
        class Inputs:
            required = {"meshTex_step_0": "mesh"}
            def bind(self, binding, provider):
                self.provider = provider
            def revision_snapshot(self, request):
                raise AssertionError("historical revisions sampled before admission")
        owner = Owner()
        scene = Scene(owner)
        registry = LiveRegistry()
        registry._definitions = lambda program: []
        registry._evaluated_values = lambda record, **kwargs: {}
        record = registry.get(scene, "one")
        record.host_providers["meshTex_step_0"] = SimpleNamespace(historical_exact=False)
        program = SimpleNamespace(graph=lambda: SimpleNamespace(is_stateful=lambda: True))
        request = FrameRequest(frame=3, fps=24, mode="timeline", purpose="cache")
        with patch.object(api, "compile", return_value=program), \
             patch.object(lifecycle, "seed_values_from_program", return_value={}), \
             patch("noisemaker_blender.runtime.inputs.InputRegistry", return_value=Inputs()):
            with self.assertRaisesRegex(ValueError, "exact-frame host input"):
                registry.current_identity(scene, owner, request, 32, 16)
        registry.shutdown()

    def test_public_keyed_edit_persists_without_opening_gpu_session(self):
        from noisemaker_blender import api
        class Owner(dict):
            def __init__(self):
                super().__init__()
                self.__dict__.update(vars(config("one", enabled=True)))
                self.source = ("search synth\n"
                               "solid(color: [0.25, 0.5, 0.75, 1]).write(o0)\n"
                               "render(o0)\n")
            def is_property_readonly(self, key):
                raise TypeError("dynamic IDProperty is not RNA")
            def id_properties_ui(self, key):
                return SimpleNamespace(update=lambda **kwargs: None)
        owner = Owner()
        scene = Scene(owner)
        registry = LiveRegistry()
        with patch.object(api, "open_session", side_effect=AssertionError("GPU opened")):
            actual = registry.set_parameter(scene, "one", "solid#0.color", (0.6, 0.1, 0.3, 1))
        self.assertEqual(actual, (0.6, 0.1, 0.3, 1.0))
        self.assertEqual(tuple(owner["nm:solid#0.color"]), actual)
        registry.shutdown()

    def test_saved_image_input_rebinds_and_removal_unbinds_session(self):
        class Collection(list):
            def add(self):
                item = SimpleNamespace(binding_name="", image=None)
                self.append(item)
                return item
            def remove(self, index): del self[index]
        class Session:
            def __init__(self):
                self.inputs = SimpleNamespace(required={"imageTex_step_0": "image"}, providers={})
                self.unbound = []
            def bind_input(self, binding, provider): self.inputs.providers[binding] = provider
            def unbind_input(self, binding):
                self.unbound.append(binding)
                self.inputs.providers.pop(binding)
            def close(self): pass
        item = config("one", enabled=True)
        item.input_bindings = Collection()
        scene = Scene(item)
        registry = LiveRegistry()
        record = registry.get(scene, "one")
        record.session = Session()
        image_a = SimpleNamespace(source="GENERATED")
        image_b = SimpleNamespace(source="FILE")
        registry.bind_input(scene, "one", "imageTex_step_0", image=image_a)
        provider_a = record.session.inputs.providers["imageTex_step_0"]
        self.assertIs(provider_a.image, image_a)
        registry.bind_input(scene, "one", "imageTex_step_0", image=image_b)
        self.assertIs(record.session.inputs.providers["imageTex_step_0"].image, image_b)
        self.assertEqual(len(item.input_bindings), 1)
        with self.assertRaises(KeyError):
            registry.bind_input(scene, "one", "imageTex_step_9", image=image_a)
        self.assertEqual(len(item.input_bindings), 1)
        registry.bind_input(scene, "one", "imageTex_step_0")
        self.assertEqual(record.session.inputs.providers, {})
        self.assertEqual(record.session.unbound, ["imageTex_step_0"])
        registry.shutdown()

    def test_live_disabled_pauses_existing_and_render_created_work(self):
        item = config("one", enabled=True, image=object())
        scene = Scene(item)
        registry = LiveRegistry()
        record = registry.get(scene, "one")
        key = registry._key(scene, "one")
        registry.scan([scene], now=1)
        self.assertFalse(registry.scheduler.status(key).paused)
        self.assertTrue(registry.scheduler._slots[key].continuous)
        item.live_enabled = False
        registry.scan([scene], now=2)
        self.assertTrue(registry.scheduler.status(key).paused)
        self.assertFalse(registry.scheduler._slots[key].continuous)
        self.assertIs(registry.instances_for_scene(scene)[0], record)
        registry.shutdown()

    def test_owned_image_dependency_orders_final_instances_and_rejects_cycle(self):
        class Image(dict):
            pass
        image_a = Image(noisemaker_owner="a")
        image_b = Image(noisemaker_owner="b")
        consumer = config("b", enabled=True, image=image_b)
        producer = config("a", enabled=True, image=image_a)
        consumer.input_bindings = [SimpleNamespace(binding_name="imageTex_step_0", image=image_a)]
        producer.input_bindings = []
        scene = Scene(consumer, producer)
        registry = LiveRegistry()
        self.assertEqual([record.config.instance_id for record in registry.instances_for_scene(scene)],
                         ["a", "b"])
        producer.input_bindings = [SimpleNamespace(binding_name="imageTex_step_0", image=image_b)]
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            registry.instances_for_scene(scene)
        registry.shutdown()

    def test_frame_notification_only_marks_existing_live_records(self):
        class Image(dict):
            pass
        a = config("a", enabled=True, image=Image(noisemaker_owner="a"))
        b = config("b", enabled=True, image=Image(noisemaker_owner="b"))
        scene = Scene(a, b)
        registry = LiveRegistry()
        registry.get(scene, "a")
        registry.get(scene, "b")
        a.input_bindings = [SimpleNamespace(binding_name="imageTex_step_0", image=b.output_image)]
        b.input_bindings = [SimpleNamespace(binding_name="imageTex_step_0", image=a.output_image)]
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            registry.instances_for_scene(scene)
        registry.scheduler.status(registry._key(scene, "a")).dirty.clear()
        registry.scheduler.status(registry._key(scene, "b")).dirty.clear()
        registry.mark_scene_dirty(scene, "time")
        self.assertEqual(registry.scheduler.status(registry._key(scene, "a")).dirty, {"time"})
        self.assertEqual(registry.scheduler.status(registry._key(scene, "b")).dirty, {"time"})
        registry.shutdown()

    def test_registration_defers_scene_scan_outside_restricted_blender_data(self):
        import types
        from noisemaker_blender.integration import lifecycle
        handlers = types.ModuleType("bpy.app.handlers")
        handlers.persistent = lambda callback: callback
        for name in ("frame_change_post", "load_pre", "undo_pre", "redo_pre",
                     "load_post", "undo_post", "redo_post", "save_pre",
                     "render_init", "render_complete", "render_cancel"):
            setattr(handlers, name, [])
        registered = set()
        timers = SimpleNamespace(
            is_registered=lambda callback: callback in registered,
            register=lambda callback, **kwargs: registered.add(callback),
            unregister=lambda callback: registered.remove(callback))
        app = types.ModuleType("bpy.app")
        app.handlers = handlers
        app.timers = timers
        restricted = types.ModuleType("bpy")
        class RestrictedData:
            def __getattr__(self, name):
                raise AttributeError("_RestrictData has no %s" % name)
        restricted.data = RestrictedData()
        restricted.app = app
        isolated = LiveRegistry()
        scene = Scene()
        repaired = []
        with patch.dict(sys.modules, {"bpy": restricted, "bpy.app": app,
                                      "bpy.app.handlers": handlers}), \
             patch.object(lifecycle, "registry", isolated), \
             patch.object(lifecycle, "ensure_unique_ids",
                          side_effect=lambda scenes: repaired.append(tuple(scenes))):
            lifecycle.register()
            self.assertTrue(isolated.pending_rebuild)
            self.assertEqual(repaired, [])
            isolated.tick([scene], now=0, allowed=False)
            self.assertEqual(repaired, [(scene,)])
            lifecycle.unregister()

    def test_publisher_reconstruction_does_not_read_nested_output_pointer(self):
        import hashlib
        import types
        from noisemaker_blender.integration import images

        class Config:
            instance_id = "one"
            output_image_ref = "image-one"
            source_mode = "INLINE"
            source = "noise()"
            preview_width = 64
            preview_height = 32
            color_role = "color"
            alpha_mode = "PREMUL"
            last_error = ""

            @property
            def output_image(self):
                raise AssertionError("nested Image pointer must not be read")

        image = {"noisemaker_owner": "one", "noisemaker_image_id": "image-one"}
        image_owner = SimpleNamespace(library=None, is_float=True,
                                      get=image.get)
        fake_bpy = types.ModuleType("bpy")
        scene = Scene(Config())
        fake_bpy.data = SimpleNamespace(images=[image_owner], scenes=[scene])
        registry = LiveRegistry()
        record = registry.get(scene, "one")
        record.program = SimpleNamespace(graph=lambda: SimpleNamespace(is_stateful=lambda: False))
        record.source_hash = hashlib.sha256(b"noise()").hexdigest()
        record.session = SimpleNamespace(width=64, height=32, close=lambda: None)
        registry._evaluated_values = lambda _record: {}
        received = []
        with patch.dict(sys.modules, {"bpy": fake_bpy}), \
             patch.object(images, "ImagePublisher",
                          side_effect=lambda owner, **kwargs: received.append(kwargs["image"]) or object()):
            registry.sync_instance(scene, scene.noisemaker_instances[0], width=64, height=32)
        self.assertEqual(received, [image_owner])
        registry.shutdown()

    def test_save_pre_migrates_raw_output_before_pack_read(self):
        import types
        from noisemaker_blender.integration import lifecycle

        class Config(dict):
            instance_id = "one"
            output_image_ref = ""
            library = None
        class Image(dict):
            library = None
            is_float = True
        item = Config(output_image=object())
        scene = Scene(item)
        scene.library = None
        image = Image(noisemaker_owner="one")
        fake_bpy = types.ModuleType("bpy")
        fake_bpy.data = SimpleNamespace(scenes=[scene], images=[image])
        checked = []
        def pack(scenes):
            self.assertNotIn("output_image", item)
            self.assertEqual(item.output_image_ref, image["noisemaker_image_id"])
            checked.append(tuple(scenes))
        with patch.dict(sys.modules, {"bpy": fake_bpy}), \
             patch.object(lifecycle, "pack_outputs_before_save", side_effect=pack):
            lifecycle._save_pre()
        self.assertEqual(checked, [(scene,)])

    def test_publisher_reconstruction_rejects_unrepaired_duplicate_owner(self):
        import types
        image = SimpleNamespace(library=None, is_float=True,
                                get=lambda key: "one" if key == "noisemaker_owner" else None)
        scene = Scene(config("one"))
        duplicate = Scene(config("one"))
        fake_bpy = types.ModuleType("bpy")
        fake_bpy.data = SimpleNamespace(images=[image], scenes=[scene, duplicate])
        with patch.dict(sys.modules, {"bpy": fake_bpy}):
            with self.assertRaisesRegex(ValueError, "duplicate Noisemaker instance identity"):
                LiveRegistry._owned_output_image(scene.noisemaker_instances[0])

    def test_render_enumerates_paused_consumers_and_ignores_unconnected_instances(self):
        scene = Scene(config("off"), config("visible", enabled=True, paused=True),
                      config("linked", image=object(), paused=True))
        registry = LiveRegistry()
        self.assertEqual([record.config.instance_id for record in registry.instances_for_scene(scene)],
                         ["visible", "linked"])
        registry.shutdown()

if __name__ == "__main__": unittest.main()
