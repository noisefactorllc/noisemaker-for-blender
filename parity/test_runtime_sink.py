#!/usr/bin/env python3
"""Behavioral parity tests for the renderer sink contract."""

import sys
import unittest
from pathlib import Path


BLENDER_ROOT = Path(__file__).resolve().parents[1] / "blender"
sys.path.insert(0, str(BLENDER_ROOT))

from noisemaker_blender.runtime import FrameExportQueue, SinkManager


class RecordingSink:
    def __init__(self, *, configure_error=None, submit_result=True, submit_error=None,
                 close_error=None):
        self.configure_error = configure_error
        self.submit_result = submit_result
        self.submit_error = submit_error
        self.close_error = close_error
        self.events = []

    def configure(self, descriptor):
        self.events.append(("configure", descriptor))
        if self.configure_error:
            raise self.configure_error

    def submit(self, texture_id, timestamp):
        self.events.append(("submit", texture_id, timestamp))
        if self.submit_error:
            raise self.submit_error
        return self.submit_result

    def close(self, options=None):
        self.events.append(("close", options))
        if self.close_error:
            raise self.close_error


class SinkManagerTests(unittest.TestCase):
    def test_runtime_package_exports_sink_and_frame_queue_contracts(self):
        self.assertEqual(SinkManager.__name__, "SinkManager")
        self.assertEqual(FrameExportQueue.__name__, "FrameExportQueue")

    def test_rejects_malformed_and_duplicate_sinks(self):
        manager = SinkManager()
        sink = RecordingSink()

        for malformed in (None, object()):
            with self.subTest(malformed=malformed):
                with self.assertRaises(TypeError):
                    manager.add(malformed)

        manager.add(sink)
        with self.assertRaises(ValueError):
            manager.add(sink)

    def test_accepts_an_unhashable_sink(self):
        class UnhashableSink(RecordingSink):
            __hash__ = None

        manager = SinkManager()
        sink = UnhashableSink()

        manager.add(sink)
        manager.submit("global_o0", 1)

        self.assertEqual(manager.stats[sink], {"accepted": 1, "dropped": 0, "failed": 0})

    def test_accepts_a_falsey_conforming_sink(self):
        class FalseySink(RecordingSink):
            def __bool__(self):
                return False

        manager = SinkManager()
        sink = FalseySink()

        manager.add(sink)

        self.assertIn(sink, manager.stats)

    def test_registers_distinct_value_equal_sinks_by_identity(self):
        class EqualSink(RecordingSink):
            def __eq__(self, other):
                return isinstance(other, EqualSink)

            def __hash__(self):
                return 1

        manager = SinkManager()
        first = EqualSink()
        second = EqualSink()

        manager.add(first)
        manager.add(second)
        manager.submit("global_o0", 2)

        self.assertEqual(len(manager.stats), 2)
        self.assertEqual(manager.stats[first], {"accepted": 1, "dropped": 0, "failed": 0})
        self.assertEqual(manager.stats[second], {"accepted": 1, "dropped": 0, "failed": 0})

    def test_configures_current_and_later_sinks_with_one_descriptor(self):
        manager = SinkManager()
        early = RecordingSink()
        late = RecordingSink()
        descriptor = {"width": 3, "height": 2, "format": "rgba8unorm"}

        manager.add(early)
        manager.configure(descriptor)
        manager.add(late)

        self.assertEqual(early.events, [("configure", descriptor)])
        self.assertEqual(late.events, [("configure", descriptor)])

    def test_default_descriptor_is_immutable_and_cannot_leak_between_managers(self):
        class MutatingSink(RecordingSink):
            def configure(self, descriptor):
                descriptor["leaked"] = True

        first_manager = SinkManager()
        mutating = MutatingSink()
        first_manager.add(mutating)

        first_manager.configure()

        second_manager = SinkManager()
        observer = RecordingSink()
        second_manager.add(observer)
        second_manager.configure()

        self.assertEqual(first_manager.stats[mutating]["failed"], 1)
        self.assertNotIn("leaked", observer.events[0][1])

    def test_isolates_failures_and_counts_submit_outcomes(self):
        reported = []
        manager = SinkManager(on_error=lambda error, sink: reported.append((str(error), sink)))
        accepted = RecordingSink(submit_result=True)
        dropped = RecordingSink(submit_result=False)
        failed = RecordingSink(submit_error=RuntimeError("submit failed"))
        observed = RecordingSink(submit_result=None)
        for sink in (accepted, dropped, failed, observed):
            manager.add(sink)

        manager.submit("global_o0", 123.5)

        self.assertEqual(manager.stats[accepted], {"accepted": 1, "dropped": 0, "failed": 0})
        self.assertEqual(manager.stats[dropped], {"accepted": 0, "dropped": 1, "failed": 0})
        self.assertEqual(manager.stats[failed], {"accepted": 0, "dropped": 0, "failed": 1})
        self.assertEqual(manager.stats[observed], {"accepted": 0, "dropped": 0, "failed": 0})
        self.assertEqual(reported, [("submit failed", failed)])
        self.assertEqual(observed.events[-1], ("submit", "global_o0", 123.5))

    def test_removal_during_submission_keeps_later_sinks_live_and_closes_once(self):
        manager = SinkManager()
        later = RecordingSink()

        class RemovingSink(RecordingSink):
            def submit(self, texture_id, timestamp):
                result = super().submit(texture_id, timestamp)
                remove()
                return result

        removing = RemovingSink()
        remove = manager.add(removing)
        manager.add(later)

        manager.submit("global_o0", 7)
        remove()
        manager.submit("global_o0", 8)

        self.assertEqual(removing.events, [
            ("submit", "global_o0", 7),
            ("close", None),
        ])
        self.assertEqual(later.events, [
            ("submit", "global_o0", 7),
            ("submit", "global_o0", 8),
        ])
        self.assertNotIn(removing, manager.stats)

    def test_close_attempts_every_sink_forwards_backend_loss_and_is_terminal(self):
        manager = SinkManager()
        first = RecordingSink(close_error=RuntimeError("first close failed"))
        second = RecordingSink()
        manager.add(first)
        manager.add(second)

        with self.assertRaisesRegex(RuntimeError, "first close failed"):
            manager.close({"backend_lost": True})
        manager.close({"backend_lost": False})

        self.assertEqual(first.events, [("close", {"backend_lost": True})])
        self.assertEqual(second.events, [("close", {"backend_lost": True})])
        self.assertEqual(manager.stats, {})
        with self.assertRaises(RuntimeError):
            manager.add(RecordingSink())


if __name__ == "__main__":
    unittest.main()
