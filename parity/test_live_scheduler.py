"""A live preview queue never duplicates work or erases its last good result."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from noisemaker_blender.integration.scheduler import LiveScheduler


class LiveSchedulerTests(unittest.TestCase):
    def test_source_changes_debounce_and_one_instance_runs_per_tick(self):
        calls = []
        scheduler = LiveScheduler(debounce_seconds=0.1, min_interval=0.05)
        scheduler.register("a", lambda: calls.append("a") or "A")
        scheduler.register("b", lambda: calls.append("b") or "B")
        scheduler.mark_dirty("a", "source", now=0)
        scheduler.mark_dirty("a", "source", now=0.08)
        scheduler.mark_dirty("a", "time", now=0.08)
        scheduler.mark_dirty("b", "time", now=0)
        self.assertEqual(scheduler.tick(now=0.09), "b")
        self.assertEqual(calls, ["b"])
        self.assertIsNone(scheduler.tick(now=0.1))
        self.assertEqual(scheduler.tick(now=0.18), "a")
        self.assertEqual(calls, ["b", "a"])
        self.assertIsNone(scheduler.tick(now=0.2))

    def test_error_keeps_last_good_and_pause_suspends_work(self):
        output = ["good", RuntimeError("bad")]
        def render():
            value = output.pop(0)
            if isinstance(value, Exception): raise value
            return value
        scheduler = LiveScheduler()
        scheduler.register("a", render)
        scheduler.mark_dirty("a", "time", now=0)
        scheduler.tick(now=0)
        scheduler.mark_dirty("a", "source", now=1)
        scheduler.tick(now=2)
        self.assertEqual(scheduler.status("a").last_good, "good")
        self.assertIn("bad", scheduler.status("a").error)
        scheduler.pause("a")
        scheduler.mark_dirty("a", "time", now=3)
        self.assertIsNone(scheduler.tick(now=3))
        scheduler.resume("a")
        self.assertIn("bad", scheduler.status("a").error)

    def test_pending_replay_preserves_last_good_and_requeues(self):
        from noisemaker_blender.runtime.checkpoints import ReplayPending, ReplayStatus
        output = ["good", ReplayPending(ReplayStatus(10, 2, 10, False)), "current"]
        def render():
            value = output.pop(0)
            if isinstance(value, Exception): raise value
            return value
        scheduler = LiveScheduler(min_interval=0.1)
        scheduler.register("a", render)
        scheduler.mark_dirty("a", "time", now=0)
        scheduler.tick(now=0)
        scheduler.mark_dirty("a", "time", now=1)
        scheduler.tick(now=1)
        self.assertEqual(scheduler.status("a").last_good, "good")
        self.assertEqual(scheduler.status("a").replay_progress.completed_steps, 2)
        self.assertEqual(scheduler.status("a").error, "")
        self.assertIsNone(scheduler.tick(now=1.05))
        scheduler.tick(now=1.1)
        self.assertEqual(scheduler.status("a").last_good, "current")
        self.assertIsNone(scheduler.status("a").replay_progress)

    def test_dependent_waits_for_producer_then_uses_its_completed_generation(self):
        calls = []
        scheduler = LiveScheduler(min_interval=0.01)
        scheduler.register("b", lambda: calls.append("b") or "B", continuous=True)
        scheduler.register("a", lambda: calls.append("a") or "A", continuous=True)
        scheduler.mark_dirty("b", "time", now=0)
        scheduler.mark_dirty("a", "time", now=0)
        order = ("a", "b")
        dependencies = {"b": {"a"}}
        self.assertEqual(scheduler.tick(now=0, order=order, dependencies=dependencies), "a")
        self.assertEqual(scheduler.tick(now=0.01, order=order, dependencies=dependencies), "b")
        self.assertEqual(calls, ["a", "b"])
        self.assertEqual(scheduler.tick(now=0.02, order=order, dependencies=dependencies), "a")
        self.assertEqual(scheduler.tick(now=0.03, order=order, dependencies=dependencies), "b")
        self.assertEqual(calls, ["a", "b", "a", "b"])

    def test_deadline_delay_excludes_elapsed_render_work_and_uses_instance_cap(self):
        scheduler = LiveScheduler()
        scheduler.register("a", lambda: "frame", continuous=True)
        scheduler.set_max_fps("a", 60)
        scheduler.mark_dirty("a", "time", now=0)
        scheduler.tick(now=0)
        self.assertAlmostEqual(scheduler.next_delay(now=0.005), 1/60 - 0.005)
        self.assertEqual(scheduler.next_delay(now=0.02), 0.002)

    def test_free_run_cadence_and_global_suspend_are_bounded(self):
        calls = []
        scheduler = LiveScheduler(min_interval=0.1)
        scheduler.register("a", lambda: calls.append(1), continuous=True)
        scheduler.mark_dirty("a", "time", now=0)
        scheduler.tick(now=0)
        self.assertEqual(len(calls), 1)
        self.assertIsNone(scheduler.tick(now=0.05))
        scheduler.suspend("render")
        self.assertIsNone(scheduler.tick(now=0.2))
        scheduler.resume_all("render")
        scheduler.tick(now=0.2)
        self.assertEqual(len(calls), 2)

if __name__ == "__main__": unittest.main()
