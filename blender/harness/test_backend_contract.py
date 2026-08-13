"""Run under Blender to verify capability contracts exposed by GpuBackend."""

import os
import sys


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "blender"))

from noisemaker_blender.backend.gpu_backend import GpuBackend


backend = GpuBackend.__new__(GpuBackend)
assert backend.create_frame_export_queue(slots=3) is None
print("BACKEND CONTRACT PASS — asynchronous frame export is explicitly unsupported")
