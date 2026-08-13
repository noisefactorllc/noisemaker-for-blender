#!/usr/bin/env python3
"""Integration tests for sink delivery from the functional Blender render loop."""

import sys
import unittest
from inspect import signature
from pathlib import Path
from unittest import mock


BLENDER_ROOT = Path(__file__).resolve().parents[1] / "blender"
sys.path.insert(0, str(BLENDER_ROOT))

from noisemaker_blender.runtime import SinkManager
from noisemaker_blender.runtime import pipeline


class EmptyGraph:
    passes = []
    render_surface = "o0"


class RecordingBackend:
    def __init__(self, events):
        self.events = events
        self.size = 3
        self.output_binding = object()
        self.frame_read = {"o0": self.output_binding}

    def setup(self, graph, defaults):
        self.events.append(("setup", graph, defaults))

    def frame_begin(self):
        self.events.append(("frame_begin",))

    def frame_persist(self):
        self.events.append(("frame_persist",))

    def read_surface(self, name):
        self.events.append(("read_surface", name))
        return "pixels"


class RecordingSink:
    def __init__(self, events):
        self.events = events

    def configure(self, descriptor):
        self.events.append(("configure", descriptor.copy()))

    def submit(self, texture_id, timestamp):
        self.events.append(("submit", texture_id, timestamp))
        return True

    def close(self, options=None):
        self.events.append(("close", options))


class PipelineSinkTests(unittest.TestCase):
    def test_render_configures_and_submits_each_completed_frame_without_changing_return(self):
        events = []
        backend = RecordingBackend(events)
        graph = EmptyGraph()
        manager = SinkManager()
        sink = RecordingSink(events)
        manager.add(sink)

        self.assertNotIn("timestamp_fn", signature(pipeline.render).parameters)
        with mock.patch.object(pipeline.clock, "perf_counter", side_effect=[1.00025, 1.01075]):
            result = pipeline.render(
                backend,
                graph,
                time=0.25,
                frames=2,
                timestep=0.5,
                sink_manager=manager,
            )

        self.assertEqual(result, "pixels")
        self.assertEqual(events[0], ("setup", graph, {}))
        self.assertEqual(events[1], ("configure", {
            "width": 3,
            "height": 3,
            "format": "rgba8unorm",
            "colorSpace": "srgb",
            "alphaMode": "premultiplied",
            "fps": 60,
        }))
        submissions = [event for event in events if event[0] == "submit"]
        for submission, expected_timestamp in zip(submissions, (1000.25, 1010.75)):
            self.assertAlmostEqual(submission[2], expected_timestamp)
        self.assertTrue(all(event[1] is backend.output_binding for event in submissions))
        for index, event in enumerate(events):
            if event[0] == "submit":
                self.assertEqual(events[index + 1], ("frame_persist",))
        self.assertEqual(events[-1], ("read_surface", "o0"))
        self.assertEqual(manager.stats[sink], {"accepted": 2, "dropped": 0, "failed": 0})

    def test_render_without_a_sink_manager_preserves_existing_behavior(self):
        events = []

        result = pipeline.render(RecordingBackend(events), EmptyGraph(), frames=1)

        self.assertEqual(result, "pixels")
        self.assertFalse(any(event[0] in ("configure", "submit") for event in events))


if __name__ == "__main__":
    unittest.main()
