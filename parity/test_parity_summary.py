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
import contextlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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


def png_bytes(width=2, height=2, value=128, overrides=None):
    """A minimal 8-bit RGBA PNG."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    overrides = overrides or {}
    raw = b"".join(
        b"\x00" + b"".join(bytes(overrides.get((x, y), (value, value, value, 255)))
                         for x in range(width))
        for y in range(height)
    )
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class GoldenStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.gold = self.dir / "case.golden.png"
        self.dsl = self.dir / "case.dsl"
        self.dsl.write_text("original fixture")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, data=b"png bytes", entry=None):
        self.gold.write_bytes(data)
        if entry is not None:
            (self.dir / "provenance.json").write_text(json.dumps({"files": {"case": entry}}))

    def state(self):
        return parity_summary.golden_state(self.gold, self.dir, PIN,
                                           {"size": 256, "time": 0.25, "frames": 8, "timestep": 0},
                                           self.dsl)

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
                          "renderer": METAL,
                          "protocol": {"size": 256, "time": 0.25, "frames": 8, "timestep": 0},
                          "dsl_sha256": parity_summary.sha256(self.dsl)})
        self.assertEqual(self.state(), "ok")
        self.dsl.write_text("edited fixture")
        self.assertEqual(self.state(), "stale")

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


class CompareTests(unittest.TestCase):
    def test_reviewed_ortho_alpha_policy_only_matches_its_protocol(self):
        policy = parity_summary.load_policies()["heightGrid_billboard_ortho_alpha"]
        reviewed = {"size": 256, "time": 0.25, "frames": 8, "timestep": 0}
        unreviewed = {"size": 128, "time": 0.25, "frames": 8, "timestep": 0}
        self.assertIsNotNone(parity_summary.policy_for_protocol(policy, reviewed))
        self.assertIsNone(parity_summary.policy_for_protocol(policy, unreviewed))

    def test_near_policy_enforces_separate_rgb_and_alpha_bounds(self):
        policy = {"max_abs_diff": 7, "max_rgb_abs_diff": 1, "max_alpha_abs_diff": 7,
                  "mean_abs_diff": 0.00013, "ssim_min": 0.98,
                  "mechanism": "measured sparse channel differences"}
        with tempfile.TemporaryDirectory() as tmp:
            gold = Path(tmp) / "gold.png"
            cand = Path(tmp) / "cand.png"
            gold.write_bytes(png_bytes(width=256, height=256))
            cand.write_bytes(png_bytes(width=256, height=256,
                                       overrides={(0, 0): (134, 128, 128, 255)}))
            self.assertEqual(parity_summary.compare(gold, cand, policy)["cls"], "fail")
            cand.write_bytes(png_bytes(width=256, height=256,
                                       overrides={(0, 0): (128, 128, 128, 248)}))
            self.assertEqual(parity_summary.compare(gold, cand, policy)["cls"], "near")

    def test_size_mismatch_is_a_countable_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold = Path(tmp) / "gold.png"
            cand = Path(tmp) / "cand.png"
            gold.write_bytes(png_bytes(width=2))
            cand.write_bytes(png_bytes(width=3))
            self.assertEqual(parity_summary.compare(gold, cand, None)["cls"], "fail")

    def test_reviewed_near_bound_applies_only_to_its_protocol(self):
        policy = parity_summary.load_policies()["north_star"]
        reviewed = {"size": 128, "time": 0.25, "frames": 8, "timestep": 0}
        unreviewed = {"size": 64, "time": 0.25, "frames": 8, "timestep": 0}
        self.assertIsNotNone(parity_summary.policy_for_protocol(policy, reviewed))
        self.assertIsNone(parity_summary.policy_for_protocol(policy, unreviewed))

    def test_evolving_state_near_bounds_apply_only_to_reviewed_protocol(self):
        reviewed = {"size": 128, "time": 0.25, "frames": 8, "timestep": 0.01}
        unreviewed = {"size": 128, "time": 0.25, "frames": 8, "timestep": 0.02}
        policies = parity_summary.load_policies()
        for name in ("north_star", "integration_target"):
            self.assertIsNotNone(parity_summary.policy_for_protocol(policies[name], reviewed))
            self.assertIsNone(parity_summary.policy_for_protocol(policies[name], unreviewed))
        self.assertEqual(parity_summary.policy_for_protocol(policies["flock_smoke"], reviewed)["ssim_min"], 0.99970)
        self.assertEqual(parity_summary.policy_for_protocol(policies["flock_smoke"], unreviewed)["ssim_min"], 0.99993)


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

    def record(self, renderer, protocol=None, pixels=None):
        """Record a golden through parity/golden-provenance.mjs, as golden-cdp.mjs does."""
        if NODE is None:
            self.fail("node is required (scripts/test needs it)")
        (self.gold_dir / f"{self.case}.golden.png").write_bytes(pixels or png_bytes())
        module = (ROOT / "parity" / "golden-provenance.mjs").as_uri()
        script = ("import { recordGolden } from %s;"
                  "recordGolden(process.argv[1], process.argv[2],"
                  " { referenceRevision: process.argv[3], renderer: process.argv[4],"
                  " protocol: JSON.parse(process.argv[5]), dslSha256: process.argv[6] })" % json.dumps(module))
        return subprocess.run([NODE, "--input-type=module", "-e", script, str(self.gold_dir), self.case,
                               parity_summary.pinned_revision(), renderer,
                               json.dumps(protocol or {"size": 256, "time": 0.25, "frames": 8, "timestep": 0}),
                               parity_summary.sha256(ROOT / "parity" / "programs" / f"{self.case}.dsl")],
                              capture_output=True, text=True, timeout=60)

    def grade(self, overrides=None, candidate_protocol=None, pixels=None):
        """Grade the case with scripts/parity-summary on a reused candidate (no Blender)."""
        cand = self.cand_dir / f"{self.case}.png"
        cand.write_bytes(pixels or png_bytes())
        env = dict(os.environ, NM_PARITY_WORK=str(self.work))
        env.pop("NM_GOLDEN_AUTO", None)
        env.update(overrides or {})
        if not (self.cand_dir / "provenance.json").exists():
            protocol = candidate_protocol or {
                "size": int(env.get("NM_SIZE", "256")),
                "time": float(env.get("NM_TIME", "0.25")),
                "frames": int(env.get("NM_FRAMES", "8")),
                "timestep": float(env.get("NM_TIMESTEP", "0")),
            }
            source = parity_summary.source_fingerprint()
            self.assertIsNotNone(source)
            parity_summary.record_candidate(cand, self.cand_dir, protocol, source)
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
        self.assertEqual(pv["files"][self.case]["protocol"],
                         {"size": 256, "time": 0.25, "frames": 8, "timestep": 0})
        self.assertEqual(pv["files"][self.case]["dsl_sha256"],
                         parity_summary.sha256(ROOT / "parity" / "programs" / f"{self.case}.dsl"))
        run, counts = self.grade()
        self.assertEqual((counts["executed"], counts["exact"], counts["missing"]), (1, 1, 0), run.stdout)
        self.assertEqual(run.returncode, 0, run.stdout)

    def test_texture_fixture_bytes_are_part_of_the_capture_protocol(self):
        cases = parity_summary.manifest_cases()
        protocols = parity_summary.capture_protocols(cases, 256, 0.25, 8, 0)
        self.assertEqual(protocols["media_host_pattern"].get("inputs_sha256"),
                         parity_summary.sha256(ROOT / "parity" / "input-fixtures.json"))
        self.assertNotIn("inputs_sha256", protocols["noise"])

    def test_grading_refuses_an_input_golden_without_its_fixture_hash(self):
        self.case = "media_host_pattern"
        protocol = {"size": 256, "time": 0.25, "frames": 8, "timestep": 0,
                    "inputs_sha256": parity_summary.sha256(ROOT / "parity" / "input-fixtures.json")}
        run = self.record(METAL, protocol)
        self.assertEqual(run.returncode, 0, run.stderr)
        run, counts = self.grade({"NM_BLENDER": "/usr/bin/false"}, candidate_protocol=protocol)
        self.assertEqual((counts["executed"], counts["exact"]), (1, 1), run.stdout)
        self.assertEqual(run.returncode, 0, run.stdout)
        provenance_path = self.gold_dir / "provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["files"][self.case]["protocol"].pop("inputs_sha256")
        provenance_path.write_text(json.dumps(provenance))
        run, counts = self.grade({"NM_BLENDER": "/usr/bin/false"}, candidate_protocol=protocol)
        self.assertEqual((counts["executed"], counts["missing"]), (0, 1), run.stdout)
        self.assertNotEqual(run.returncode, 0, run.stdout)

    def test_invalid_input_pixels_are_rejected_before_capture(self):
        cases = parity_summary.manifest_cases()
        for dimensions, pixels in (({"width": 2, "height": 1}, [0, 0, 0, 1]),
                                    ({"width": True, "height": 1}, [0, 0, 0, 1]),
                                    ({"width": 1, "height": 1}, [float("nan"), 0, 0, 1])):
            with self.subTest(dimensions=dimensions, pixels=pixels):
                fixture_path = self.work / "invalid-inputs.json"
                fixture_path.write_text(json.dumps({cases[0]: {"inputTex": {
                    **dimensions, "pixels": pixels}}}))
                with mock.patch.object(parity_summary, "INPUT_FIXTURES", fixture_path, create=True):
                    with self.assertRaises(ValueError):
                        parity_summary.capture_protocols(cases, 256, 0.25, 8, 0)

    def test_minting_refuses_an_invalid_input_fixture_hash(self):
        protocol = {"size": 256, "time": 0.25, "frames": 8, "timestep": 0,
                    "inputs_sha256": "invalid"}
        run = self.record(METAL, protocol)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("invalid input fixture SHA-256", run.stderr)

    def test_rectangular_protocol_mints_grades_and_rejects_swapped_axes(self):
        protocol = {"width": 3, "height": 2, "time": 0.25, "frames": 8, "timestep": 0}
        pixels = png_bytes(3, 2, overrides={(2, 1): (12, 34, 56, 255)})
        run = self.record(METAL, protocol, pixels)
        self.assertEqual(run.returncode, 0, run.stderr)
        run, counts = self.grade({"NM_WIDTH": "3", "NM_HEIGHT": "2", "NM_BLENDER": "/usr/bin/false"},
                                 candidate_protocol=protocol, pixels=pixels)
        self.assertEqual((counts["executed"], counts["exact"], counts["missing"]), (1, 1, 0), run.stdout)
        self.assertEqual(run.returncode, 0, run.stdout)
        swapped = {**protocol, "width": 2, "height": 3}
        (self.cand_dir / "provenance.json").unlink()
        run, counts = self.grade({"NM_WIDTH": "2", "NM_HEIGHT": "3", "NM_BLENDER": "/usr/bin/false"},
                                 candidate_protocol=swapped, pixels=png_bytes(2, 3))
        self.assertEqual((counts["executed"], counts["missing"]), (0, 1), run.stdout)
        self.assertNotEqual(run.returncode, 0, run.stdout)

    def test_rectangular_fixture_runs_at_its_declared_default_dimensions(self):
        self.case = "noise_rectangular"
        protocol = {"width": 257, "height": 129, "time": 0.25, "frames": 8, "timestep": 0}
        pixels = png_bytes(257, 129, overrides={(256, 128): (12, 34, 56, 255)})
        run = self.record(METAL, protocol, pixels)
        self.assertEqual(run.returncode, 0, run.stderr)
        run, counts = self.grade({"NM_BLENDER": "/usr/bin/false"},
                                 candidate_protocol=protocol, pixels=pixels)
        self.assertEqual((counts["executed"], counts["exact"], counts["missing"]), (1, 1, 0), run.stdout)
        self.assertEqual(run.returncode, 0, run.stdout)

    def test_minting_refuses_png_dimensions_that_disagree_with_rectangular_protocol(self):
        protocol = {"width": 3, "height": 2, "time": 0.25, "frames": 8, "timestep": 0}
        run = self.record(METAL, protocol, png_bytes(2, 2))
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("PNG dimensions do not match render protocol", run.stderr)

    def test_minting_refuses_invalid_rectangular_dimensions(self):
        for dimensions in ({"width": 3}, {"width": 0, "height": 2},
                           {"width": 3, "height": -2}, {"width": 3.5, "height": 2}):
            with self.subTest(dimensions=dimensions):
                run = self.record(METAL, {**dimensions, "time": 0.25, "frames": 8, "timestep": 0})
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("invalid render protocol", run.stderr)

    def test_grading_refuses_a_golden_for_another_fixture_revision(self):
        run = self.record(METAL)
        self.assertEqual(run.returncode, 0, run.stderr)
        provenance_path = self.gold_dir / "provenance.json"
        original = json.loads(provenance_path.read_text())
        for wrong_hash in (None, "0" * 64):
            with self.subTest(wrong_hash=wrong_hash):
                provenance = json.loads(json.dumps(original))
                if wrong_hash is None:
                    provenance["files"][self.case].pop("dsl_sha256", None)
                else:
                    provenance["files"][self.case]["dsl_sha256"] = wrong_hash
                provenance_path.write_text(json.dumps(provenance))
                run, counts = self.grade()
                self.assertEqual((counts["executed"], counts["missing"]), (0, 1), run.stdout)
                self.assertNotEqual(run.returncode, 0, run.stdout)

    def test_grading_refuses_golden_from_another_render_protocol(self):
        run = self.record(METAL)
        self.assertEqual(run.returncode, 0, run.stderr)
        for overrides in ({"NM_SIZE": "128"}, {"NM_TIME": "0.75"},
                          {"NM_FRAMES": "1"}, {"NM_TIMESTEP": "0.0125"}):
            with self.subTest(overrides=overrides):
                (self.cand_dir / "provenance.json").unlink(missing_ok=True)
                run, counts = self.grade(overrides)
                self.assertEqual((counts["executed"], counts["missing"]), (0, 1), run.stdout)
                self.assertNotEqual(run.returncode, 0, run.stdout)

    def test_reuse_rerenders_candidate_from_another_protocol(self):
        run = self.record(METAL, {"size": 256, "time": 0.75, "frames": 8, "timestep": 0})
        self.assertEqual(run.returncode, 0, run.stderr)
        run, counts = self.grade({"NM_TIME": "0.75", "NM_BLENDER": "/usr/bin/false"},
                                 candidate_protocol={"size": 256, "time": 0.25,
                                                     "frames": 8, "timestep": 0})
        self.assertEqual((counts["executed"], counts["fail"]), (0, 1), run.stdout)

    def test_reuse_rerenders_candidate_from_another_source(self):
        run = self.record(METAL)
        self.assertEqual(run.returncode, 0, run.stderr)
        cand = self.cand_dir / f"{self.case}.png"
        cand.write_bytes(png_bytes())
        (self.cand_dir / "provenance.json").write_text(json.dumps({"files": {self.case: {
            "sha256": parity_summary.sha256(cand),
            "protocol": {"size": 256, "time": 0.25, "frames": 8, "timestep": 0},
            "source_fingerprint": "different-source",
        }}}))
        run, counts = self.grade({"NM_BLENDER": "/usr/bin/false"})
        self.assertEqual((counts["executed"], counts["fail"]), (0, 1), run.stdout)

    def test_grading_refuses_candidate_replaced_during_golden_generation(self):
        run = self.record(METAL)
        self.assertEqual(run.returncode, 0, run.stderr)
        gold_provenance = (self.gold_dir / "provenance.json").read_text()
        (self.gold_dir / "provenance.json").write_text("{}")
        cand = self.cand_dir / f"{self.case}.png"
        cand.write_bytes(png_bytes())
        source = parity_summary.source_fingerprint()
        self.assertIsNotNone(source)
        protocol = {"size": 256, "time": 0.25, "frames": 8, "timestep": 0}
        parity_summary.record_candidate(cand, self.cand_dir, protocol, source)

        def regenerate(*_args):
            (self.gold_dir / "provenance.json").write_text(gold_provenance)
            cand.write_bytes(png_bytes(value=129))
            parity_summary.record_candidate(cand, self.cand_dir,
                                            {**protocol, "time": 0.75}, source)
            return None

        output = io.StringIO()
        env = {"NM_PARITY_WORK": str(self.work), "NM_GOLDEN_AUTO": "1",
               "NM_REFERENCE_ROOT": str(self.work)}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(sys, "argv", ["parity-summary", "--reuse", self.case]), \
             mock.patch.object(parity_summary, "generate_goldens", side_effect=regenerate), \
             contextlib.redirect_stdout(output):
            status = parity_summary.main()
        summary = [line for line in output.getvalue().splitlines()
                   if line.startswith("PARITY-SUMMARY ")]
        self.assertEqual(len(summary), 1, output.getvalue())
        counts = json.loads(summary[0][len("PARITY-SUMMARY "):])
        self.assertEqual((counts["executed"], counts["fail"]), (0, 1), output.getvalue())
        self.assertNotEqual(status, 0)

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
