#!/usr/bin/env python3
"""Behavioral parity tests for the bounded asynchronous export queue."""

import sys
import unittest
from pathlib import Path


BLENDER_ROOT = Path(__file__).resolve().parents[1] / "blender"
sys.path.insert(0, str(BLENDER_ROOT))

from noisemaker_blender.runtime.frame_export import FrameExportQueue


class FakeAdapter:
    def __init__(self):
        self.events = []
        self.slots = []
        self.create_error_at = None
        self.begin_error_for = None
        self.poll_error_for = None

    def create_slot(self, index, descriptor):
        self.events.append(("create", index, descriptor))
        if index == self.create_error_at:
            raise RuntimeError("create failed")
        slot = {"index": index, "ready": False, "texture": None}
        self.slots.append(slot)
        return slot

    def begin(self, slot, texture_id, timestamp):
        self.events.append(("begin", slot["index"], texture_id, timestamp))
        if texture_id == self.begin_error_for:
            raise RuntimeError("begin failed")
        slot["texture"] = texture_id

    def poll(self, slot):
        self.events.append(("poll", slot["index"]))
        if slot["texture"] == self.poll_error_for:
            raise RuntimeError("poll failed")
        return slot["ready"]

    def read(self, slot):
        self.events.append(("read", slot["index"]))
        return {"data": slot["texture"], "row_stride": 4}

    def destroy_slot(self, slot):
        self.events.append(("destroy", slot["index"]))


class FrameExportQueueTests(unittest.TestCase):
    def test_validates_adapter_and_bounded_slot_count(self):
        for malformed in (None, object()):
            with self.subTest(malformed=malformed):
                with self.assertRaises(TypeError):
                    FrameExportQueue(malformed)
        adapter = FakeAdapter()
        for slots in (True, 1, 9, 2.5):
            with self.subTest(slots=slots):
                with self.assertRaises(ValueError):
                    FrameExportQueue(adapter, slots=slots)
        FrameExportQueue(adapter, slots=2)

    def test_accepts_a_falsey_conforming_adapter(self):
        class FalseyAdapter(FakeAdapter):
            def __bool__(self):
                return False

        adapter = FalseyAdapter()

        queue = FrameExportQueue(adapter, slots=2)
        queue.configure({"width": 1})

        self.assertTrue(queue.available)

    def test_reconfigures_slots_and_rolls_back_partial_allocation(self):
        adapter = FakeAdapter()
        queue = FrameExportQueue(adapter, slots=2)
        stats = queue.stats
        first = {"width": 2}
        second = {"width": 3}

        queue.configure(first)
        queue.configure(second)

        self.assertIs(queue.stats, stats)
        self.assertEqual(adapter.events[:6], [
            ("create", 0, first),
            ("create", 1, first),
            ("destroy", 0),
            ("destroy", 1),
            ("create", 0, second),
            ("create", 1, second),
        ])

        adapter.create_error_at = 1
        with self.assertRaisesRegex(RuntimeError, "create failed"):
            queue.configure({"width": 4})
        self.assertFalse(queue.available)
        self.assertEqual(adapter.events[-2:], [
            ("create", 1, {"width": 4}),
            ("destroy", 0),
        ])

    def test_drops_on_saturation_preserves_context_and_reuses_completed_slot(self):
        adapter = FakeAdapter()
        queue = FrameExportQueue(adapter, slots=2)
        completed = []
        queue.configure({"width": 1})

        self.assertTrue(queue.enqueue("a", 10, lambda frame, timestamp, context:
                                      completed.append((frame, timestamp, context)), "ctx-a"))
        self.assertTrue(queue.enqueue("b", 11, lambda *_: None, "ctx-b"))
        self.assertFalse(queue.enqueue("dropped", 12, lambda *_: None))
        self.assertFalse(queue.available)

        queue.poll()
        self.assertEqual(completed, [])
        adapter.slots[0]["ready"] = True
        queue.poll()

        self.assertEqual(completed, [({"data": "a", "row_stride": 4}, 10, "ctx-a")])
        self.assertTrue(queue.available)
        self.assertTrue(queue.enqueue("replacement", 13, lambda *_: None))
        self.assertEqual(queue.stats, {
            "accepted": 3,
            "dropped": 1,
            "completed": 1,
            "failed": 0,
        })

    def test_isolates_begin_poll_and_callback_failures(self):
        errors = []
        adapter = FakeAdapter()
        queue = FrameExportQueue(adapter, slots=2, on_error=lambda error: errors.append(str(error)))
        queue.configure({"width": 1})

        adapter.begin_error_for = "bad-begin"
        self.assertFalse(queue.enqueue("bad-begin", 1, lambda *_: None))
        adapter.begin_error_for = None
        adapter.poll_error_for = "bad-poll"
        self.assertTrue(queue.enqueue("bad-poll", 2, lambda *_: None))
        self.assertTrue(queue.enqueue("callback", 3, lambda *_: (_ for _ in ()).throw(
            RuntimeError("callback failed"))))
        adapter.slots[1]["ready"] = True

        queue.poll()

        self.assertEqual(errors, ["begin failed", "poll failed", "callback failed"])
        self.assertEqual(queue.stats, {
            "accepted": 2,
            "dropped": 0,
            "completed": 0,
            "failed": 3,
        })
        self.assertTrue(queue.available)

    def test_close_destroys_once_or_abandons_slots_after_backend_loss(self):
        normal_adapter = FakeAdapter()
        normal = FrameExportQueue(normal_adapter, slots=2)
        normal.configure({"width": 1})
        normal.enqueue("pending", 1, lambda *_: None)
        normal.close()
        normal.close()
        self.assertEqual([event for event in normal_adapter.events if event[0] == "destroy"], [
            ("destroy", 0),
            ("destroy", 1),
        ])
        self.assertFalse(normal.enqueue("late", 2, lambda *_: None))

        lost_adapter = FakeAdapter()
        lost = FrameExportQueue(lost_adapter, slots=2)
        lost.configure({"width": 1})
        lost.close({"backend_lost": True})
        self.assertEqual([event for event in lost_adapter.events if event[0] == "destroy"], [])
        self.assertIsNone(lost.adapter)


if __name__ == "__main__":
    unittest.main()
