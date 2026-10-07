"""Native 512-square live GPU/Image Editor performance gate.

Run in an isolated Blender GUI with ``--factory-startup --python`` and set
``NM_HARNESS_AUTOCLOSE=1`` plus an evidence directory outside the checkout.
``NM_CONTINUOUS_SECONDS`` is 60 by default; 600 measures resource stability.
The measured producer is the add-on's registered lifecycle timer.
"""
import os
from pathlib import Path
import runpy
import sys

if "--factory-startup" not in sys.argv or os.environ.get("NM_HARNESS_AUTOCLOSE") != "1":
    raise RuntimeError("performance gate requires a disposable --factory-startup Blender GUI")

os.environ["NM_PROBE_PHASE"] = "continuous"
os.environ.setdefault("NM_CONTINUOUS_SECONDS", "60")
runpy.run_path(str(Path(__file__).with_name("probe_live_integration.py")), run_name="__main__")
