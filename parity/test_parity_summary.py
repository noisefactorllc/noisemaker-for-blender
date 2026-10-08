#!/usr/bin/env python3
"""Golden trust in scripts/parity-summary.

A golden is graded only when its provenance.json entry matches its sha256,
names the reference revision pinned in parity/reference-revision, and names a
renderer that is the declared authority in parity/authority-renderer; anything
else is 'missing', 'stale' or 'wrong-renderer' and counts as missing, never as
executed.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("parity_summary", str(ROOT / "scripts" / "parity-summary"))
_spec = importlib.util.spec_from_loader("parity_summary", _loader)
parity_summary = importlib.util.module_from_spec(_spec)
_loader.exec_module(parity_summary)

PIN = "a" * 40
METAL = "ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)"
SWIFTSHADER = "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)"
OTHER_GPU = "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11 vs_5_0 ps_5_0, D3D11)"


def png_bytes(width=2, height=2, value=128):
    """A minimal 8-bit RGBA PNG."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([value, value, value, 255]) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class GoldenStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.gold = self.dir / "case.golden.png"

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, data=b"png bytes", entry=None):
        self.gold.write_bytes(data)
        if entry is not None:
            (self.dir / "provenance.json").write_text(json.dumps({"files": {"case": entry}}))

    def state(self):
        return parity_summary.golden_state(self.gold, self.dir, PIN)

    def test_absent_golden_is_missing(self):
        self.assertEqual(self.state(), "missing")

    def test_golden_without_provenance_is_stale(self):
        self.write()
        self.assertEqual(self.state(), "stale")

    def test_golden_whose_bytes_changed_is_stale(self):
        self.write(entry={"sha256": "0" * 64, "reference_revision": PIN, "renderer": METAL})
        self.assertEqual(self.state(), "stale")

    def test_golden_minted_at_another_revision_is_stale(self):
        self.write()
        entry = {"sha256": parity_summary.sha256(self.gold), "reference_revision": "b" * 40, "renderer": METAL}
        self.write(entry=entry)
        self.assertEqual(self.state(), "stale")

    def test_golden_without_a_recorded_revision_is_stale(self):
        self.write()
        self.write(entry={"sha256": parity_summary.sha256(self.gold), "renderer": METAL})
        self.assertEqual(self.state(), "stale")

    def test_golden_minted_at_the_pin_on_the_authority_renderer_is_ok(self):
        self.write()
        self.write(entry={"sha256": parity_summary.sha256(self.gold), "reference_revision": PIN,
                          "renderer": METAL})
        self.assertEqual(self.state(), "ok")

    def test_golden_without_a_recorded_renderer_is_refused(self):
        self.write()
        self.write(entry={"sha256": parity_summary.sha256(self.gold), "reference_revision": PIN})
        self.assertEqual(self.state(), "wrong-renderer")

    def test_golden_minted_on_swiftshader_is_refused(self):
        self.write()
        self.write(entry={"sha256": parity_summary.sha256(self.gold), "reference_revision": PIN,
                          "renderer": SWIFTSHADER})
        self.assertEqual(self.state(), "wrong-renderer")

    def test_golden_minted_on_another_gpu_is_refused(self):
        self.write()
        self.write(entry={"sha256": parity_summary.sha256(self.gold), "reference_revision": PIN,
                          "renderer": OTHER_GPU})
        self.assertEqual(self.state(), "wrong-renderer")


class PinTests(unittest.TestCase):
    def test_the_pin_is_a_full_commit_sha(self):
        self.assertRegex(parity_summary.pinned_revision(), re.compile(r"^[0-9a-f]{40}$"))


class AuthorityRendererTests(unittest.TestCase):
    def test_the_declared_authority_is_angle_over_metal_on_apple_silicon(self):
        self.assertEqual(parity_summary.declared_renderer(), "ANGLE Metal Renderer: Apple")

    def test_only_the_declared_renderer_is_the_authority(self):
        declared = parity_summary.declared_renderer()
        self.assertTrue(parity_summary.is_authority_renderer(METAL, declared))
        for renderer in (SWIFTSHADER, OTHER_GPU, "", None, "SwiftShader " + METAL):
            self.assertFalse(parity_summary.is_authority_renderer(renderer, declared), renderer)


NODE = shutil.which("node")


class MintAndGradeTests(unittest.TestCase):
    """The minting side records the renderer, and the grading side refuses a
    golden whose recorded renderer is not the declared authority."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.gold_dir = self.work / "gold"
        self.cand_dir = self.work / "cand"
        self.gold_dir.mkdir()
        self.cand_dir.mkdir()
        self.case = parity_summary.manifest_cases()[0]

    def tearDown(self):
        self._tmp.cleanup()

    def record(self, renderer):
        """Record a golden through parity/golden-provenance.mjs, as golden-cdp.mjs does."""
        if NODE is None:
            self.fail("node is required (scripts/test needs it)")
        (self.gold_dir / f"{self.case}.golden.png").write_bytes(png_bytes())
        module = (ROOT / "parity" / "golden-provenance.mjs").as_uri()
        script = ("import { recordGolden } from %s;"
                  "recordGolden(process.argv[1], process.argv[2],"
                  " { referenceRevision: process.argv[3], renderer: process.argv[4] })" % json.dumps(module))
        return subprocess.run([NODE, "--input-type=module", "-e", script, str(self.gold_dir), self.case,
                               parity_summary.pinned_revision(), renderer],
                              capture_output=True, text=True, timeout=60)

    def grade(self):
        """Grade the case with scripts/parity-summary on a reused candidate (no Blender)."""
        (self.cand_dir / f"{self.case}.png").write_bytes(png_bytes())
        env = dict(os.environ, NM_PARITY_WORK=str(self.work))
        env.pop("NM_GOLDEN_AUTO", None)
        run = subprocess.run([sys.executable, str(ROOT / "scripts" / "parity-summary"), "--reuse", self.case],
                             capture_output=True, text=True, timeout=120, env=env)
        lines = [ln for ln in run.stdout.splitlines() if ln.startswith("PARITY-SUMMARY ")]
        self.assertTrue(lines, run.stdout + run.stderr)
        return run, json.loads(lines[-1][len("PARITY-SUMMARY "):])

    def test_minting_records_the_renderer_and_grading_accepts_the_authority(self):
        run = self.record(METAL)
        self.assertEqual(run.returncode, 0, run.stderr)
        pv = json.loads((self.gold_dir / "provenance.json").read_text())
        self.assertEqual(pv["files"][self.case]["renderer"], METAL)
        self.assertEqual(pv["files"][self.case]["reference_revision"], parity_summary.pinned_revision())
        run, counts = self.grade()
        self.assertEqual((counts["executed"], counts["exact"], counts["missing"]), (1, 1, 0), run.stdout)
        self.assertEqual(run.returncode, 0, run.stdout)

    def test_minting_refuses_to_record_a_golden_from_another_renderer(self):
        run = self.record(SWIFTSHADER)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("not the declared authority", run.stderr)
        self.assertFalse((self.gold_dir / "provenance.json").exists())

    def test_grading_refuses_a_golden_recorded_on_another_renderer(self):
        gold = self.gold_dir / f"{self.case}.golden.png"
        gold.write_bytes(png_bytes())
        (self.gold_dir / "provenance.json").write_text(json.dumps({"files": {self.case: {
            "sha256": parity_summary.sha256(gold),
            "reference_revision": parity_summary.pinned_revision(), "renderer": SWIFTSHADER}}}))
        run, counts = self.grade()
        self.assertEqual((counts["executed"], counts["missing"]), (0, 1), run.stdout)
        self.assertIn("not the declared authority", run.stdout)
        self.assertNotEqual(run.returncode, 0)


if __name__ == "__main__":
    unittest.main()
