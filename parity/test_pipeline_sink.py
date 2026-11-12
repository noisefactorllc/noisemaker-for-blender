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

    def test_render_skips_frame_when_sink_defers_render_and_resumes_afterward(self):
        events = []
        backend = RecordingBackend(events)
        graph = EmptyGraph()
        manager = SinkManager()

        class DeferrableSink(RecordingSink):
            def __init__(self, events):
                super().__init__(events)
                self.call_count = 0

            def defer_render(self):
                self.call_count += 1
                return self.call_count <= 2

        sink = DeferrableSink(events)
        manager.add(sink)

        result = pipeline.render(backend, graph, frames=3, sink_manager=manager)
        self.assertEqual(result, "pixels")
        # Only 1 frame was drawn on backend (frame 2)
        frame_begins = [e for e in events if e[0] == "frame_begin"]
        self.assertEqual(len(frame_begins), 1)
        submissions = [e for e in events if e[0] == "submit"]
        self.assertEqual(len(submissions), 1)

    def test_render_reports_each_isolated_sink_error_to_the_throwing_sink(self):
        events = []
        backend = RecordingBackend(events)
        graph = EmptyGraph()
        manager = SinkManager()

        configure_error = RuntimeError("configure failed")
        defer_error = RuntimeError("defer probe failed")
        submit_error = RuntimeError("submit failed")
        reported = []
        state = {"failing": True}

        class FailedSink(RecordingSink):
            def configure(self, descriptor):
                if state["failing"]:
                    raise configure_error

            def defer_render(self):
                if state["failing"]:
                    raise defer_error
                return False

            def submit(self, texture_id, timestamp):
                if state["failing"]:
                    raise submit_error
                return True

            def onError(self, error):
                reported.append(("failed", error))

        class SilentSink(RecordingSink):
            # A sink without onError fails exactly as before: counted and isolated.
            def configure(self, descriptor):
                if state["failing"]:
                    raise RuntimeError("silent configure failed")

            def submit(self, texture_id, timestamp):
                if state["failing"]:
                    raise RuntimeError("silent submit failed")
                return True

        reporter_calls = []

        class ThrowingReporterSink(RecordingSink):
            def configure(self, descriptor):
                if state["failing"]:
                    raise RuntimeError("configure failed again")

            def submit(self, texture_id, timestamp):
                return True

            def onError(self, error):
                reporter_calls.append(error)
                raise RuntimeError("reporter failed")

        healthy_calls = []

        class HealthySink(RecordingSink):
            def configure(self, descriptor):
                healthy_calls.append(("configure", descriptor["width"], descriptor["height"]))

            def defer_render(self):
                healthy_calls.append(("defer_render",))
                return False

            def submit(self, texture_id, timestamp):
                healthy_calls.append(("submit", timestamp))
                return True

            def onError(self, error):
                reported.append(("healthy", error))

        failed = FailedSink(events)
        silent = SilentSink(events)
        throwing_reporter = ThrowingReporterSink(events)
        healthy = HealthySink(events)
        for sink in (failed, silent, throwing_reporter, healthy):
            manager.add(sink)

        result = pipeline.render(backend, graph, time=0.25, frames=1, sink_manager=manager)

        self.assertEqual(result, "pixels")
        self.assertEqual(reported, [
            ("failed", configure_error),
            ("failed", defer_error),
            ("failed", submit_error),
        ])
        self.assertEqual(len(reporter_calls), 1)
        self.assertEqual([call[0] for call in healthy_calls],
                         ["configure", "defer_render", "submit"])
        self.assertEqual(manager.stats[failed], {"accepted": 0, "dropped": 0, "failed": 3})
        self.assertEqual(manager.stats[silent], {"accepted": 0, "dropped": 0, "failed": 2})
        self.assertEqual(manager.stats[throwing_reporter], {"accepted": 1, "dropped": 0, "failed": 1})
        self.assertEqual(manager.stats[healthy], {"accepted": 1, "dropped": 0, "failed": 0})

    def test_render_keeps_a_reporter_the_host_already_gave_the_sink_manager(self):
        events = []
        backend = RecordingBackend(events)
        graph = EmptyGraph()
        host_reported = []
        sink_reported = []
        manager = SinkManager(on_error=lambda error, sink: host_reported.append((sink, error)))

        configure_error = RuntimeError("configure failed")

        class FailingSink(RecordingSink):
            def configure(self, descriptor):
                raise configure_error

            def submit(self, texture_id, timestamp):
                return True

            def onError(self, error):
                sink_reported.append(error)

        sink = FailingSink(events)
        manager.add(sink)

        result = pipeline.render(backend, graph, frames=1, sink_manager=manager)

        self.assertEqual(result, "pixels")
        self.assertEqual(host_reported, [(sink, configure_error)])
        self.assertEqual(sink_reported, [])
        self.assertEqual(manager.stats[sink], {"accepted": 1, "dropped": 0, "failed": 1})

    def test_render_handles_non_callable_should_defer_render_attribute(self):
        events = []
        backend = RecordingBackend(events)
        graph = EmptyGraph()

        class DuckManager:
            should_defer_render = True

            def configure(self, desc):
                pass

            def submit(self, binding, ts):
                pass

        result = pipeline.render(backend, graph, frames=1, sink_manager=DuckManager())
        self.assertEqual(result, "pixels")
        self.assertEqual(len([e for e in events if e[0] == "frame_begin"]), 1)


if __name__ == "__main__":
    unittest.main()
