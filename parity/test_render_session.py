"""Engine-free persistent render-session contract tests."""

import sys
from contextlib import nullcontext
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))

from noisemaker_blender import api
from noisemaker_blender.runtime.output import StaleOutputError
from noisemaker_blender.runtime.checkpoints import ReplayPending
from noisemaker_blender.runtime.inputs import InputFrame


def graph(surface="o0", *, seed=1, size_sensitive=False):
    width = {"param": "seed", "default": 16} if size_sensitive else "screen"
    return {
        "renderSurface": surface,
        "passes": [{
            "passType": "effect", "namespace": "synth", "func": "noise",
            "progName": "noise", "drawMode": None, "inputs": {},
            "outputs": {"color": "global_o0"},
            "uniforms": {"seed": seed}, "effectKey": "noise", "stepIndex": 0,
        }],
        "textures": {
            "global_o0": {"width": width, "height": "screen", "format": "rgba16f"},
            "global_o1": {"width": "screen", "height": "screen", "format": "rgba32f"},
        },
        "allocations": {}, "programs": {},
    }


class FakeOffscreen:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.texture_color = object()


class FakeBackend:
    instances = []

    def __init__(self, shaders_root, *, width, height):
        self.width, self.height = width, height
        self.size = width
        self.setup_count = self.executions = self.free_count = 0
        self.executed_passes = []
        self.frame_read = {
            "o0": FakeOffscreen(width, height),
            "o1": FakeOffscreen(width, height),
        }
        self.tex_dims = {"global_o0": (width, height), "global_o1": (width, height)}
        FakeBackend.instances.append(self)

    def setup(self, graph, defaults):
        self.setup_count += 1
        self.defaults = defaults.copy()

    def frame_begin(self):
        pass

    def set_external_inputs(self, frames):
        self.external_inputs = dict(frames)

    def execute(self, render_pass, graph, engine):
        self.executions += 1
        self.last_pass = render_pass
        self.executed_passes.append(render_pass)
        self.last_engine = engine.copy()

    def swap_after_write(self, tid):
        pass

    def frame_persist(self):
        pass

    def read_surface_float(self, name):
        return (name, self.width, self.height)

    def read_surface(self, name):
        return ("quantized", name)

    def free(self):
        self.free_count += 1


class ContextBackend(FakeBackend):
    current_context = "window-a"
    deferred = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context_token = self.current_context

    def assert_context(self):
        if self.current_context != self.context_token:
            raise RuntimeError("GPU context changed")

    def abandon(self):
        self.deferred.append(self)


class RenderSessionTests(unittest.TestCase):
    def setUp(self):
        FakeBackend.instances.clear()
        self.program = api.Program.from_graph("source", graph())

    def session(self, program=None, width=257, height=129):
        return api.open_session(program or self.program, width=width, height=height,
                                backend_factory=FakeBackend)

    def test_public_prepared_render_facade_is_cpu_importable(self):
        from noisemaker_blender.integration import render
        self.assertIs(api.RenderPolicy, render.RenderPolicy)
        self.assertIs(api.PreparedRender, render.PreparedRender)
        scene = object()
        prepared = object()
        with patch.object(render, "render_prepared", return_value="done") as target:
            self.assertEqual(api.render_prepared(scene, prepared, frames=(3,)), "done")
        target.assert_called_once_with(scene, prepared, (3,), None,
                                       registry=None, renderer=None)

    def test_reuses_backend_and_setup_for_repeated_frames(self):
        with self.session() as session:
            first = session.evaluate(api.FrameRequest(frame=1))
            second = session.evaluate(api.FrameRequest(frame=2))
            self.assertEqual(len(FakeBackend.instances), 1)
            self.assertEqual(FakeBackend.instances[0].setup_count, 1)
            self.assertEqual(FakeBackend.instances[0].executions, 2)
            self.assertEqual((second.descriptor.width, second.descriptor.height), (257, 129))
            self.assertEqual((second.frame, second.subframe), (2, 0.0))
            with self.assertRaises(StaleOutputError):
                session.read_float(first)
            self.assertEqual(session.read_float(second), ("o0", 257, 129))
            self.assertEqual(session.read_quantized(second), ("quantized", "o0"))
        with self.assertRaises(StaleOutputError):
            _ = second.texture

    def test_output_handle_cannot_rewrite_borrowed_generation_or_provenance(self):
        with self.session() as session:
            first = session.evaluate(api.FrameRequest(frame=1))
            for attribute, value in (("_epoch", 100), ("frame", 100),
                                     ("source_id", "forged")):
                with self.assertRaises((AttributeError, TypeError)):
                    setattr(first, attribute, value)
            session.evaluate(api.FrameRequest(frame=2))
            with self.assertRaises(StaleOutputError):
                session.read_float(first)

    def test_independent_sessions_and_named_outputs(self):
        with self.session() as left, self.session() as right:
            a = left.evaluate(api.FrameRequest(frame=1))
            b = right.evaluate(api.FrameRequest(frame=1))
            self.assertIsNot(a.texture, b.texture)
            alt = left.output("o1")
            self.assertEqual(alt.descriptor.format, "RGBA32F")
            with self.assertRaises(ValueError):
                right.read_float(alt)
            self.assertEqual(left.read_float(a), ("o0", 257, 129))

    def test_scalar_update_keeps_backend_but_resource_update_rebuilds(self):
        with self.session() as session:
            session.evaluate(api.FrameRequest(frame=1))
            original = FakeBackend.instances[-1]
            session.set_parameter("noise#0.seed", 7)
            output = session.evaluate(api.FrameRequest(frame=2))
            self.assertIs(FakeBackend.instances[-1], original)
            self.assertEqual(original.setup_count, 1)
            self.assertEqual(original.last_pass["uniforms"]["seed"], 7)
            self.assertEqual(output.generation, 2)

        sensitive = api.Program.from_graph("sensitive", graph(size_sensitive=True))
        with self.session(sensitive) as session:
            session.evaluate(api.FrameRequest(frame=1))
            old = FakeBackend.instances[-1]
            session.set_parameter("noise#0.seed", 8)
            session.evaluate(api.FrameRequest(frame=2))
            self.assertIsNot(FakeBackend.instances[-1], old)
            self.assertEqual(old.free_count, 1)

    def test_failed_recompile_keeps_last_valid_graph_and_handle(self):
        with self.session() as session:
            output = session.evaluate(api.FrameRequest(frame=1))
            backend = FakeBackend.instances[-1]
            invalid = api.Program.from_graph("invalid", {"passes": [{"passType": "compute"}],
                                                         "renderSurface": "o0"})
            with self.assertRaises(ValueError):
                session.recompile(invalid)
            self.assertIs(output.texture, backend.frame_read["o0"].texture_color)
            self.assertIs(session.program, self.program)
            self.assertEqual(backend.free_count, 0)

    def test_successful_recompile_and_resize_invalidate_handles(self):
        with self.session() as session:
            old = session.evaluate(api.FrameRequest(frame=1))
            session.recompile(api.Program.from_graph("new", graph(seed=4)))
            with self.assertRaises(StaleOutputError):
                _ = old.texture
            with self.assertRaises(RuntimeError):
                session.output()
            second = session.evaluate(api.FrameRequest(frame=2))
            session.resize(320, 90)
            with self.assertRaises(StaleOutputError):
                _ = second.texture
            with self.assertRaises(RuntimeError):
                session.output()
            third = session.evaluate(api.FrameRequest(frame=3))
            self.assertEqual((third.descriptor.width, third.descriptor.height), (320, 90))

    def test_invalid_request_cannot_mutate_backend(self):
        with self.session() as session:
            backend = session.backend
            with self.assertRaises(ValueError):
                session.evaluate(api.FrameRequest(frame=1, subframe=float("nan")))
            with self.assertRaises(ValueError):
                session.evaluate(api.FrameRequest(frame=1, mode="surprise"))
            self.assertEqual(backend.executions, 0)

    def test_compiled_program_is_immutable_and_uses_stable_effect_key(self):
        program = api.compile("search synth\nnoise(seed: 1).write(o0)\nrender(o0)")
        self.assertEqual(program.parameter_values()["noise#0.seed"], 1)
        first_graph = program.graph()
        first_graph.passes[0]["uniforms"]["seed"] = 99
        self.assertEqual(program.graph().passes[0]["uniforms"]["seed"], 1)
        with self.session(program) as session:
            session.set_parameter("noise#0.seed", 7)
            session.evaluate(api.FrameRequest(frame=1))
            self.assertEqual(session.backend.last_pass["uniforms"], {})
            self.assertEqual(session.graph.passes[0]["uniforms"]["seed"], 7)
            self.assertEqual(session.cache_identity(api.FrameRequest(frame=1))[
                "parameters"]["noise#0.seed"], 7)

    def test_recompile_preserves_matching_parameter_and_orphans_removed_key(self):
        with self.session() as session:
            session.set_parameter("noise#0.seed", 7)
            same = api.Program.from_graph("same", graph(seed=2))
            session.recompile(same)
            self.assertEqual(session.graph.passes[0]["uniforms"]["seed"], 7)
            no_noise = graph()
            no_noise["passes"][0]["effectKey"] = "gradient"
            session.recompile(api.Program.from_graph("new", no_noise))
            self.assertEqual(session.orphaned_parameters, {"noise#0.seed": 7})
            session.recompile(same)
            self.assertEqual(session.orphaned_parameters, {})
            self.assertEqual(session.graph.passes[0]["uniforms"]["seed"], 7)

    def test_stateful_seek_advances_every_step_and_replays_after_backward_seek(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {"stateTex": "global_state"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"].append({
            "passType": "blit", "inputs": {"src": "global_state"},
            "outputs": {"color": "global_o0"},
        })
        program = api.Program.from_graph("stateful", stateful)
        with self.session(program) as session:
            session.evaluate(api.FrameRequest(frame=1))
            initial = session.backend
            self.assertEqual(initial.executions, 2)
            session.evaluate(api.FrameRequest(frame=4))
            self.assertIs(session.backend, initial)
            self.assertEqual(initial.executions, 8)
            session.evaluate(api.FrameRequest(frame=4))
            self.assertEqual(initial.executions, 8)
            session.evaluate(api.FrameRequest(frame=2))
            self.assertIsNot(session.backend, initial)
            self.assertEqual(initial.free_count, 1)
            self.assertEqual(session.backend.executions, 4)
            with self.assertRaises(ValueError):
                session.evaluate(api.FrameRequest(frame=2, subframe=0.5))

    def test_stateful_seek_uses_each_steps_parameter_snapshot(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {"stateTex": "global_state"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"].append({
            "passType": "blit", "inputs": {"src": "global_state"},
            "outputs": {"color": "global_o0"},
        })

        class Snapshots:
            changed = False

            def source_identity(self):
                return "keyed-seed"

            def resolve(self, request):
                value = request.frame + (10 if self.changed and request.frame == 2 else 0)
                return {"noise#0.seed": value}, str(value)

        provider = Snapshots()
        program = api.Program.from_graph("animated-stateful", stateful)
        with self.session(program) as session:
            session.set_parameter_snapshot_provider(provider)
            request = api.FrameRequest(frame=4)
            session.evaluate(request)
            effect_values = [item["uniforms"]["seed"] for item in
                             session.backend.executed_passes if item["passType"] == "effect"]
            self.assertEqual(effect_values, [1, 2, 3, 4])
            identity = session.cache_identity(request)
            provider.changed = True
            self.assertNotEqual(session.current_identity(request), identity)
            previous = session.backend
            session.evaluate(request)
            self.assertIsNot(session.backend, previous)
            effect_values = [item["uniforms"]["seed"] for item in
                             session.backend.executed_passes if item["passType"] == "effect"]
            self.assertEqual(effect_values, [1, 12, 3, 4])

    def test_parameter_snapshot_provider_rejects_conditions_and_failed_setter_is_atomic(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {"stateTex": "global_state"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"][0]["conditions"] = {
            "runIf": [{"uniform": "seed", "equals": 1}]}
        stateful["passes"].append({
            "passType": "blit", "inputs": {"src": "global_state"},
            "outputs": {"color": "global_o0"},
        })
        class Snapshots:
            def source_identity(self): return "conditional-seed"
            def resolve(self, request): return {"noise#0.seed": request.frame}, str(request.frame)
        with self.session(api.Program.from_graph("conditional-stateful", stateful)) as session:
            revision = session._revision
            with self.assertRaisesRegex(TypeError, "source_identity"):
                session.set_parameter_snapshot_provider(lambda request: ({}, "invalid"))
            self.assertIsNone(session._parameter_state_provider)
            self.assertEqual(session._revision, revision)
            session.set_parameter_snapshot_provider(Snapshots())
            with self.assertRaisesRegex(ValueError, "unconditional scalar"):
                session.evaluate(api.FrameRequest(frame=1))
            self.assertEqual(session.backend.executions, 0)

    def test_stateful_free_run_uses_completed_fixed_steps_at_fractional_wall_time(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {"stateTex": "global_state"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"].append({"passType": "blit",
                                   "inputs": {"src": "global_state"},
                                   "outputs": {"color": "global_o0"}})
        with self.session(api.Program.from_graph("free-run-state", stateful)) as session:
            request = api.FrameRequest(frame=1, mode="free_run", wall_seconds=0.137)
            session.evaluate(request)
            self.assertEqual(session.backend.executions, 8)  # steps 0 through 3
            session.evaluate(api.FrameRequest(frame=1, mode="free_run", wall_seconds=0.149))
            self.assertEqual(session.backend.executions, 8)

    def test_prepared_blender_parameter_snapshots_seek_with_fractional_fps(self):
        from noisemaker_blender.integration.lifecycle import registry
        class Owner(dict):
            def id_properties_ui(self, key):
                return SimpleNamespace(update=lambda **kwargs: None)
            def path_from_id(self): return "noisemaker_instances[0]"
        class Collection(list):
            def __init__(self, scene): super().__init__(); self.scene = scene
            def add(self):
                item = Owner()
                item.id_data = self.scene
                item.input_bindings = ()
                item.preview_width = 32
                item.preview_height = 32
                self.append(item)
                return item
        layer = SimpleNamespace(name="View", update=lambda: None)
        class Layers(list):
            def get(self, name): return layer
        class Scene:
            frame_current = 7
            frame_subframe = .25
            def __init__(self):
                self.noisemaker_instances = Collection(self)
                self.view_layers = Layers([layer])
                self.render = SimpleNamespace(fps=30000, fps_base=1001)
                self.eval_owner = None
                self.sampled = []
            def as_pointer(self): return id(self)
            def update_tag(self, **kwargs): pass
            def frame_set(self, frame, subframe=0):
                self.frame_current, self.frame_subframe = frame, subframe
                self.sampled.append((frame, subframe))
                if getattr(self, "fail_at", None) == frame:
                    raise RuntimeError("historical Scene evaluation failed")
                if self.eval_owner is not None:
                    self.eval_owner.update(self.noisemaker_instances[0])
                    self.eval_owner["nm:reactionDiffusion#0.feed"] = (
                        70.0 if frame < 5 else 90.0)
            def evaluated_get(self, depsgraph):
                return SimpleNamespace(noisemaker_instances=[self.eval_owner])
        scene = Scene()
        source = "search synth\nreactionDiffusion().write(o0)\nrender(o0)"
        instance = api.create_instance(scene, api.compile(source))
        scene.eval_owner = Owner(instance)
        scene.eval_owner.instance_id = instance.instance_id
        path = 'noisemaker_instances[0]["nm:reactionDiffusion#0.feed"]'
        scene.animation_data = SimpleNamespace(
            action=SimpleNamespace(fcurves=[SimpleNamespace(data_path=path)], layers=()),
            action_slot=None, drivers=(), nla_tracks=())
        context = SimpleNamespace(view_layer=layer,
                                  temp_override=lambda **kwargs: nullcontext(),
                                  evaluated_depsgraph_get=lambda: object())
        target = api.FrameRequest(frame=20, fps=30000, fps_base=1001)
        try:
            with self.assertRaisesRegex(ValueError, "max_steps"):
                api.prepare_parameter_snapshots(instance, target, max_steps=10)
            self.assertEqual(scene.sampled, [])
            with self.assertRaisesRegex(ValueError, "fps/fps_base"):
                api.prepare_parameter_snapshots(instance, api.FrameRequest(frame=20, fps=24))
            self.assertEqual(scene.sampled, [])
            with patch.dict(sys.modules, {"bpy": SimpleNamespace(context=context)}):
                prepared = api.prepare_parameter_snapshots(instance, target)
            mutable_vector = [1.0, 2.0]
            vector_snapshot = api.PreparedParameterSnapshots(
                prepared.program, prepared.policy, ("vector",),
                (("vector", mutable_vector),), ((("vector", mutable_vector),),))
            mutable_vector[0] = 9.0
            self.assertEqual(vector_snapshot.static_values[0][1], (1.0, 2.0))
            self.assertEqual(vector_snapshot.steps[0][0][1], (1.0, 2.0))
            self.assertEqual((scene.frame_current, scene.frame_subframe), (7, .25))
            self.assertEqual(len(scene.sampled), 21)  # 20 samples, then restore
            self.assertEqual(prepared.resolve(api.FrameRequest(
                frame=4, fps=30000, fps_base=1001))[0][
                    "reactionDiffusion#0.feed"], 70.0)
            self.assertEqual(prepared.resolve(api.FrameRequest(
                frame=5, fps=30000, fps_base=1001))[0][
                    "reactionDiffusion#0.feed"], 90.0)
            scene.animation_data = SimpleNamespace(
                action=None, action_slot=None,
                drivers=[SimpleNamespace(data_path=path)], nla_tracks=())
            with patch.dict(sys.modules, {"bpy": SimpleNamespace(context=context)}):
                driven = api.prepare_parameter_snapshots(instance, target)
            self.assertEqual(driven.source_identity(), prepared.source_identity())
            scene.fail_at = 3
            with patch.dict(sys.modules, {"bpy": SimpleNamespace(context=context)}):
                with self.assertRaisesRegex(RuntimeError, "historical Scene evaluation"):
                    api.prepare_parameter_snapshots(instance, target)
            self.assertEqual((scene.frame_current, scene.frame_subframe), (7, .25))
            scene.fail_at = None
            with self.assertRaisesRegex(ValueError, "time policy"):
                prepared.resolve(api.FrameRequest(frame=5, fps=24))
            frozen_identity = prepared.source_identity()
            scene.frame_set(3)
            self.assertEqual(prepared.source_identity(), frozen_identity)
            self.assertEqual(prepared.resolve(api.FrameRequest(
                frame=5, fps=30000, fps_base=1001))[0][
                    "reactionDiffusion#0.feed"], 90.0)
            class AccumBackend(FakeBackend):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.accumulated = 0.0
                def execute(self, render_pass, graph, engine):
                    super().execute(render_pass, graph, engine)
                    if "feed" in render_pass.get("uniforms", {}):
                        self.accumulated = self.accumulated * 1.01 + render_pass["uniforms"]["feed"]
                def read_surface_float(self, name):
                    return self.accumulated
            def req(frame):
                return api.FrameRequest(frame=frame, fps=30000, fps_base=1001)
            with api.open_session(prepared, size=32, backend_factory=AccumBackend) as sequence:
                for frame in range(1, 21):
                    output = sequence.evaluate(req(frame))
                expected_twenty = sequence.read_float(output)
                output = sequence.evaluate(req(5))
                expected_five = sequence.read_float(output)
            with api.open_session(prepared, size=32, backend_factory=AccumBackend) as session:
                session.evaluate(req(1))
                output = session.evaluate(target)
                self.assertEqual(session.read_float(output), expected_twenty)
                at_twenty = [item["uniforms"].get("feed") for item in
                             session.backend.executed_passes if "feed" in item.get("uniforms", {})]
                self.assertIn(70.0, at_twenty)
                self.assertIn(90.0, at_twenty)
                output = session.evaluate(req(5))
                self.assertEqual(session.read_float(output), expected_five)
                output = session.evaluate(target)
                self.assertEqual(session.read_float(output), expected_twenty)
            with self.assertRaisesRegex(ValueError, "missing historical snapshot"):
                prepared.resolve(api.FrameRequest(frame=21, fps=30000, fps_base=1001))
        finally:
            registry.remove(scene, instance.instance_id)

    def test_prepared_snapshots_reject_animated_define_before_scene_mutation(self):
        source = ("search synth\nnoise(type: simplex).write(o1)\n"
                  "reactionDiffusion().write(o0)\nrender(o0)")
        path = 'noisemaker_instances[0]["nm:noise#0.type"]'
        scene = SimpleNamespace(
            render=SimpleNamespace(fps=24, fps_base=1),
            animation_data=SimpleNamespace(
                action=None, drivers=[SimpleNamespace(data_path=path)], nla_tracks=()))
        scene.noisemaker_instances = []
        scene.frame_set = lambda *args, **kwargs: self.fail("Scene time changed")
        instance = SimpleNamespace(id_data=scene, instance_id="instance", source_mode="INLINE",
                                   source=source, path_from_id=lambda: "noisemaker_instances[0]")
        with patch.object(api, "_instance_values", return_value={"noise#0.type": 0}):
            with self.assertRaisesRegex(ValueError, "define/resource"):
                api.prepare_parameter_snapshots(instance, api.FrameRequest(frame=2))
        conditional_source = "search synth\nreactionDiffusion().write(o0)\nrender(o0)"
        conditional_graph = api.compile(conditional_source).graph()
        conditional_graph.passes[0]["conditions"] = {
            "runIf": [{"uniform": "feed", "equals": 70.0}]}
        conditional_program = api.Program.from_graph(conditional_source, conditional_graph.data)
        instance.source = conditional_source
        scene.animation_data.drivers = [SimpleNamespace(
            data_path='noisemaker_instances[0]["nm:reactionDiffusion#0.feed"]')]
        with patch.object(api, "compile", return_value=conditional_program), patch.object(
                api, "_instance_values", return_value={"reactionDiffusion#0.feed": 70.0}):
            with self.assertRaisesRegex(ValueError, "conditional"):
                api.prepare_parameter_snapshots(instance, api.FrameRequest(frame=2))

    def test_define_parameter_rebuilds_shader_state_transactionally(self):
        program = api.compile("search synth\nnoise(type: simplex).write(o0)\nrender(o0)")
        with self.session(program) as session:
            old_backend = session.backend
            result = session.set_parameter("noise#0.type", 1)
            self.assertEqual(result, "define")
            self.assertIsNot(session.backend, old_backend)
            self.assertEqual(old_backend.free_count, 1)
            self.assertEqual(session.graph.passes[0]["defines"]["NOISE_TYPE"], 1)
            with self.assertRaises(ValueError):
                session.set_parameter("noise#0.type", 10000)
            self.assertEqual(session.graph.passes[0]["defines"]["NOISE_TYPE"], 1)

    def test_borrowed_output_rejects_cross_context_access(self):
        ContextBackend.current_context = "window-a"
        with api.open_session(self.program, width=16, height=8,
                              backend_factory=ContextBackend) as session:
            handle = session.evaluate(api.FrameRequest(frame=1))
            ContextBackend.current_context = "window-b"
            with self.assertRaisesRegex(RuntimeError, "GPU context changed"):
                _ = handle.texture
            with self.assertRaisesRegex(RuntimeError, "GPU context changed"):
                session.read_float(handle)
            with self.assertRaisesRegex(RuntimeError, "GPU context changed"):
                session.evaluate(api.FrameRequest(frame=2))
            ContextBackend.current_context = "window-a"
            self.assertEqual(session.read_float(handle), ("o0", 16, 8))

    def test_context_loss_close_defers_gpu_free(self):
        ContextBackend.current_context = "window-a"
        session = api.open_session(self.program, width=16, height=8,
                                   backend_factory=ContextBackend)
        backend = session.backend
        ContextBackend.current_context = "window-b"
        session.close()
        self.assertTrue(session.closed)
        self.assertEqual(backend.free_count, 0)
        self.assertIn(backend, ContextBackend.deferred)

    def test_bounded_replay_resolves_host_input_at_each_step(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {
            "stateTex": "global_state", "imageTex": "imageTex_step_0"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"].append({"passType": "blit",
                                   "inputs": {"src": "global_state"},
                                   "outputs": {"color": "global_o0"}})
        program = api.Program.from_graph("stateful-input", stateful)
        calls = []
        class Provider:
            def revision_for(self, request):
                return str(request.frame)
            def resolve(self, request):
                calls.append(request.frame)
                return InputFrame(object(), 1, 1, self.revision_for(request))
        provider = Provider()
        with self.session(program) as session:
            session.bind_input("imageTex_step_0", provider)
            first = session.evaluate(api.FrameRequest(frame=1))
            with self.assertRaises(ReplayPending) as pending:
                session.evaluate(api.FrameRequest(frame=4), max_steps=2)
            self.assertEqual(pending.exception.status.completed_steps, 3)
            self.assertEqual(session.generation, 1)
            with self.assertRaises(StaleOutputError):
                _ = first.texture
            with self.assertRaises(ReplayPending):
                session.evaluate(api.FrameRequest(frame=4), max_steps=2)
            result = session.evaluate(api.FrameRequest(frame=4), max_steps=2)
            self.assertEqual(result.frame, 4)
            self.assertEqual(session.generation, 2)
            self.assertEqual(calls, [1, 1, 4, 2, 3, 4, 4])

    def test_changed_historical_input_replays_same_stateful_target(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {
            "stateTex": "global_state", "imageTex": "imageTex_step_0"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"].append({"passType": "blit",
                                   "inputs": {"src": "global_state"},
                                   "outputs": {"color": "global_o0"}})
        class Provider:
            changed = False
            def source_identity(self):
                return "fixed-source"
            def revision_for(self, request):
                return "changed" if self.changed and request.frame == 1 else str(request.frame)
            def resolve(self, request):
                return InputFrame(object(), 1, 1, self.revision_for(request))
        provider = Provider()
        with self.session(api.Program.from_graph("stateful-history", stateful)) as session:
            session.bind_input("imageTex_step_0", provider)
            request = api.FrameRequest(frame=3)
            first = session.evaluate(request)
            backend = session.backend
            prepared = session.cache_identity(request)
            provider.changed = True
            self.assertNotEqual(session.current_identity(request), prepared)
            with self.assertRaises(RuntimeError):
                session.cache_identity(request)
            second = session.evaluate(request)
            self.assertEqual(second.generation, first.generation + 1)
            self.assertIsNot(session.backend, backend)
            self.assertEqual(backend.free_count, 1)

    def test_bounded_preview_checks_only_two_historical_revisions_per_tick(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {
            "stateTex": "global_state", "imageTex": "imageTex_step_0"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"].append({"passType": "blit",
                                   "inputs": {"src": "global_state"},
                                   "outputs": {"color": "global_o0"}})
        checks = []
        class Provider:
            def source_identity(self): return "fixed"
            def revision_for(self, request):
                checks.append(request.frame)
                return str(request.frame)
            def resolve(self, request):
                return InputFrame(object(), 1, 1, str(request.frame))
        request = api.FrameRequest(frame=100)
        with self.session(api.Program.from_graph("bounded-history", stateful)) as session:
            session.bind_input("imageTex_step_0", Provider())
            session.evaluate(request)
            backend = session.backend
            checks.clear()
            with self.assertRaises(ReplayPending):
                session.evaluate(request, max_steps=2)
            self.assertEqual(checks, [100, 1, 2])
            self.assertIs(session.backend, backend)
            checks.clear()
            with self.assertRaises(ReplayPending):
                session.evaluate(request, max_steps=2)
            self.assertEqual(checks, [100, 3, 4])

    def test_cpu_scene_identity_matches_stateful_session_history(self):
        from noisemaker_blender.integration.lifecycle import LiveRegistry
        from noisemaker_blender.integration.inputs import BlenderImageProvider
        data = graph()
        data["passes"][0]["inputs"] = {
            "stateTex": "global_state", "imageTex": "imageTex_step_0"}
        data["passes"][0]["outputs"] = {"color": "global_state"}
        data["passes"].append({"passType": "blit",
                               "inputs": {"src": "global_state"},
                               "outputs": {"color": "global_o0"}})
        program = api.Program.from_graph("stateful-cpu-identity", data)
        image = SimpleNamespace(source="FILE", size=(3, 2),
                                alpha_mode="STRAIGHT", name="Input")
        config = SimpleNamespace(instance_id="one", source_mode="INLINE",
                                 source="stateful-cpu-identity", input_bindings=[
                                     SimpleNamespace(binding_name="imageTex_step_0",
                                                     image=image)])
        scene = SimpleNamespace()
        registry = LiveRegistry()
        registry._definitions = lambda candidate: []
        registry._evaluated_values = lambda record, strict=False: {}
        request = api.FrameRequest(frame=3)
        try:
            with self.session(program, width=32, height=16) as session:
                session.bind_input("imageTex_step_0", BlenderImageProvider(
                    image, texture_from_image=lambda source: source))
                session.evaluate(request)
                live = session.current_identity(request)
            with patch.object(api, "compile", return_value=program):
                cpu = registry.current_identity(scene, config, request, 32, 16)
            self.assertEqual(cpu, live)
        finally:
            registry.shutdown()

    def test_audio_snapshot_provider_updates_same_frame_and_replay_steps(self):
        stateful = graph()
        stateful["passes"][0]["inputs"] = {"stateTex": "global_state"}
        stateful["passes"][0]["outputs"] = {"color": "global_state"}
        stateful["passes"][0]["uniforms"]["scaleX"] = {
            "type": "Audio", "band": 3, "min": 0, "max": 1}
        stateful["passes"].append({"passType": "blit",
                                   "inputs": {"src": "global_state"},
                                   "outputs": {"color": "global_o0"}})
        calls = []
        revision = [0]
        def snapshot(request):
            calls.append(request.frame)
            return {"audio": {"vol": request.frame / 10}}, revision[0]
        with self.session(api.Program.from_graph("audio", stateful)) as session:
            session.set_external_state(snapshot)
            session.evaluate(api.FrameRequest(frame=1))
            self.assertAlmostEqual(session.backend.executed_passes[-2]["uniforms"]["scaleX"], 0.1)
            old_generation = session.generation
            revision[0] = 1
            session.evaluate(api.FrameRequest(frame=1))
            self.assertEqual(session.generation, old_generation + 1)
            session.evaluate(api.FrameRequest(frame=3), max_steps=2)
            self.assertIn(2, calls)
            self.assertIn(3, calls)

    def test_boolean_define_binding_lowers_to_integer_shader_define(self):
        data = graph()
        data["passes"][0].update({"namespace": "synth3d", "func": "noise3d",
                                  "progName": "noise3d", "effectKey": "synth3d.noise3d",
                                  "uniforms": {}, "defines": {"RIDGES": 0}})
        with self.session(api.Program.from_graph("boolean-define", data)) as session:
            self.assertEqual(session.set_parameter("noise3d#0.ridges", True), "define")
            self.assertIs(session.graph.passes[0]["defines"]["RIDGES"], 1)
            self.assertIs(session._parameters["noise3d#0.ridges"], True)

    def test_short_effect_key_rejects_namespace_ambiguity(self):
        data = graph()
        data["passes"][0]["effectKey"] = "synth.noise"
        other = dict(data["passes"][0])
        other["effectKey"] = "custom.noise"
        other["stepIndex"] = 1
        data["passes"].append(other)
        with self.session(api.Program.from_graph("ambiguous", data)) as session:
            with self.assertRaisesRegex(KeyError, "ambiguous"):
                session.set_parameter("noise#0.seed", 7)
            self.assertEqual(session.set_parameter("synth.noise#0.seed", 7), "scalar")

    def test_public_instance_snippet_applies_saved_parameter(self):
        from noisemaker_blender.integration.lifecycle import registry
        class Owner(dict):
            def id_properties_ui(self, key):
                return SimpleNamespace(update=lambda **kwargs: None)
        class Collection(list):
            def __init__(self, scene):
                super().__init__()
                self.scene = scene
            def add(self):
                item = Owner()
                item.id_data = self.scene
                item.preview_width = 64
                item.preview_height = 32
                item.input_bindings = ()
                self.append(item)
                return item
        class Scene:
            def __init__(self):
                self.noisemaker_instances = Collection(self)
            def as_pointer(self):
                return id(self)
        scene = Scene()
        program = api.compile("search synth\nnoise(seed: 1).write(o0)\nrender(o0)")
        instance = api.create_instance(scene=scene, program=program, name="Clouds")
        try:
            self.assertIn("nm:noise#0.type", instance)
            api.set_parameter(instance, key="noise#0.seed", value=7)
            with api.open_session(instance, width=64, height=32,
                                  backend_factory=FakeBackend) as session:
                output = session.evaluate(api.FrameRequest(frame=42))
                self.assertEqual(output.frame, 42)
                self.assertEqual(session.graph.passes[0]["uniforms"]["seed"], 7)
                from noisemaker_blender.integration import images
                owners = []
                published = object()
                class Publisher:
                    def __init__(self, owner_id, image=None, **kwargs):
                        self.owner_id = owner_id
                        self.role = kwargs["role"]
                        self.alpha_mode = kwargs["alpha_mode"]
                        owners.append((owner_id, image))
                    def publish(self, pixels, **kwargs):
                        return published
                with patch.object(images, "ImagePublisher", Publisher):
                    self.assertIs(session.publish_image(output), published)
                self.assertEqual(owners, [(instance.instance_id, None)])
                self.assertIs(instance.output_image, published)
                self.assertEqual(len(registry.instances_for_scene(scene)), 1)
        finally:
            registry.remove(scene, instance.instance_id)

    def test_instance_open_reads_evaluated_parameter_before_gpu_construction(self):
        from noisemaker_blender.integration.lifecycle import registry
        class Owner(dict):
            instance_id = "animated"
            source_mode = "INLINE"
            source = "search synth\nnoise(seed: 1).write(o0)\nrender(o0)"
            preview_width = 16
            preview_height = 8
            input_bindings = ()
            def path_from_id(self):
                return "noisemaker_instances[0]"
        compiled = api.compile(Owner.source)
        defaults = {"nm:" + key: value for key, value in compiled.parameter_values().items()}
        original = Owner(defaults)
        evaluated = Owner(dict(defaults, **{"nm:noise#0.seed": 9}))
        layer = SimpleNamespace(name="View", update=lambda: None)
        class Layers(list):
            def get(self, name): return layer
        scene = SimpleNamespace(
            noisemaker_instances=[original], view_layers=Layers([layer]),
            frame_current=42, frame_subframe=0.0,
            render=SimpleNamespace(fps=24, fps_base=1),
            evaluated_get=lambda depsgraph: SimpleNamespace(noisemaker_instances=[evaluated]),
            as_pointer=lambda: 12345)
        original.id_data = scene
        context = SimpleNamespace(view_layer=layer,
                                  temp_override=lambda **kwargs: nullcontext(),
                                  evaluated_depsgraph_get=lambda: object())
        try:
            with patch.dict(sys.modules, {"bpy": SimpleNamespace(context=context)}):
                with api.open_session(original, backend_factory=FakeBackend) as session:
                    self.assertEqual(session.graph.passes[0]["uniforms"]["seed"], 9)
                    session.evaluate(api.FrameRequest(frame=42))
                    evaluated["nm:noise#0.seed"] = 12
                    session.evaluate(api.FrameRequest(frame=42))
                    self.assertEqual(session.graph.passes[0]["uniforms"]["seed"], 12)
                    count = session.backend.executions
                    with self.assertRaisesRegex(ValueError, "current Scene time"):
                        session.evaluate(api.FrameRequest(frame=43))
                    self.assertEqual(session.backend.executions, count)
        finally:
            registry.remove(scene, original.instance_id)


if __name__ == "__main__":
    unittest.main()
