"""Engine-free contracts for scene time and state replay."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from noisemaker_blender.runtime.clock import FrameRequest, map_frame
from noisemaker_blender.runtime.checkpoints import CheckpointIdentity, CheckpointStore, ReplayController, ReplayCancelled, ReplayPending


class SceneClockTests(unittest.TestCase):
    def test_fractional_fps_origin_subframe_and_offset_are_distinct(self):
        sample = map_frame(FrameRequest(frame=31, subframe=0.5, fps=30000, fps_base=1001,
                                        origin_frame=1, loop_seconds=10, offset_seconds=2,
                                        fixed_step_seconds=0.1))
        self.assertAlmostEqual(sample.fps_effective, 30000 / 1001)
        self.assertAlmostEqual(sample.elapsed_seconds, 30.5 * 1001 / 30000)
        self.assertAlmostEqual(sample.normalized_time, ((30.5 * 1001 / 30000) + 2) / 10)
        self.assertEqual(sample.frame_index, 31)
        self.assertEqual(sample.simulation_step, 10)

    def test_free_run_is_preview_only_and_timeline_restarts_at_scene_time(self):
        preview = map_frame(FrameRequest(frame=90, mode="free_run", purpose="preview",
                                         wall_seconds=0.5, fps=24, origin_frame=1,
                                         fixed_step_seconds=1 / 24))
        timeline = map_frame(FrameRequest(frame=90, mode="timeline", purpose="final",
                                          fps=24, origin_frame=1, fixed_step_seconds=1 / 24))
        self.assertEqual(preview.simulation_step, 12)
        self.assertEqual(timeline.simulation_step, 89)
        for purpose in ("final", "cache"):
            with self.subTest(purpose=purpose), self.assertRaises(ValueError):
                map_frame(FrameRequest(frame=90, mode="free_run", purpose=purpose,
                                       wall_seconds=0.5))

    def test_invalid_rate_and_missing_wall_clock_are_rejected(self):
        for request in (FrameRequest(frame=1, fps_base=0),
                        FrameRequest(frame=1, loop_seconds=0),
                        FrameRequest(frame=1, mode="free_run")):
            with self.subTest(request=request), self.assertRaises(ValueError):
                map_frame(request)


class CheckpointTests(unittest.TestCase):
    def identity(self, **changes):
        data = dict(source="dsl", parameters={"seed": 1}, inputs={"image": 4},
                    width=64, height=32, seed=1, time_mapping={"fps": 24},
                    simulation_policy={"step": 1 / 24})
        data.update(changes)
        return CheckpointIdentity(**data)

    def test_checkpoint_is_verified_and_invalidated_by_every_replay_input(self):
        store = CheckpointStore(max_items=2, max_bytes=4)
        identity = self.identity()
        store.put(identity, 5, b"abc")
        self.assertEqual(store.latest(identity, 5).payload, b"abc")
        self.assertIsNone(store.latest(self.identity(seed=2), 5))
        self.assertIsNone(store.latest(self.identity(parameters={"seed": 2}), 5))
        self.assertIsNone(store.latest(self.identity(inputs={"image": 5}), 5))
        self.assertIsNone(store.latest(self.identity(width=65), 5))
        self.assertIsNone(store.latest(self.identity(time_mapping={"fps": 25}), 5))
        self.assertIsNone(store.latest(self.identity(simulation_policy={"step": 0.1}), 5))
        store.put(identity, 6, b"zz")
        self.assertIsNone(store.latest(identity, 5))
        with self.assertRaises(ValueError):
            store.put(identity, 7, b"oversize")

    def test_without_snapshot_backward_seek_resets_and_replays(self):
        engine = {"state": 0}
        replay = ReplayController(CheckpointStore(max_items=2, max_bytes=8), checkpoint_interval=2)
        identity = self.identity()
        def reset(): engine["state"] = 0
        def advance(step): engine["state"] += step
        replay.seek(4, identity, reset=reset, restore=lambda _: None, advance=advance)
        self.assertEqual(engine["state"], 10)
        replay.seek(2, identity, reset=reset, restore=lambda _: None, advance=advance)
        self.assertEqual(engine["state"], 3)

    def test_preview_replay_reports_pending_then_resumes_without_skips(self):
        engine = {"state": 0}
        steps = []
        replay = ReplayController(CheckpointStore(max_items=1, max_bytes=8))
        identity = self.identity()
        def reset(): engine["state"] = 0
        def advance(step): engine["state"] += step; steps.append(step)
        with self.assertRaises(ReplayPending) as pending:
            replay.seek(6, identity, reset=reset, restore=lambda _: None,
                        advance=advance, max_steps=2)
        self.assertEqual((pending.exception.status.completed_steps,
                          pending.exception.status.target_step), (2, 6))
        with self.assertRaises(ReplayPending):
            replay.seek(6, identity, reset=reset, restore=lambda _: None,
                        advance=advance, max_steps=2)
        status = replay.seek(6, identity, reset=reset, restore=lambda _: None,
                             advance=advance, max_steps=2)
        self.assertTrue(status.complete)
        self.assertEqual(steps, [1, 2, 3, 4, 5, 6])
        self.assertEqual(engine["state"], 21)

    def test_replay_seeks_are_exact_idempotent_and_cancelable(self):
        store = CheckpointStore(max_items=4, max_bytes=64)
        engine = {"state": 0}
        seen = []
        replay = ReplayController(store, checkpoint_interval=5, max_steps_per_seek=100)
        identity = self.identity()

        def reset(): engine["state"] = 0
        def restore(payload): engine["state"] = int(payload.decode())
        def advance(step): engine["state"] += step; seen.append(step)
        def snapshot(): return str(engine["state"]).encode()
        for target in (1, 20, 5, 20, 20):
            replay.seek(target, identity, reset=reset, restore=restore,
                        advance=advance, snapshot=snapshot)
        self.assertEqual(engine["state"], 210)
        self.assertEqual(len(seen), 20)
        self.assertEqual(replay.status.completed_steps, 20)
        with self.assertRaises(ReplayCancelled):
            replay.seek(25, identity, reset=reset, restore=restore, advance=advance,
                        snapshot=snapshot, cancel=lambda: True)
        self.assertFalse(replay.status.complete)
        replay.seek(25, identity, reset=reset, restore=restore, advance=advance,
                    snapshot=snapshot)
        self.assertEqual(engine["state"], 325)


if __name__ == "__main__":
    unittest.main()
