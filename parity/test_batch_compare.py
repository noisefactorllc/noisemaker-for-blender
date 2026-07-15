#!/usr/bin/env python3
"""Regression tests for enforceable Blender batch parity classifications."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).with_name("batch-compare.py")


class BatchCompareTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="nm-blender-compare-")
        self.root = Path(self.tempdir.name)
        self.gold = self.root / "gold"
        self.cand = self.root / "cand"
        self.gold.mkdir()
        self.cand.mkdir()
        self.report = self.root / "report.json"

    def tearDown(self):
        self.tempdir.cleanup()

    def _write_near_pair(self, name="near"):
        golden = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
        candidate = golden.copy()
        candidate.putpixel((0, 0), (128, 128, 128, 0))
        golden.save(self.gold / f"{name}.golden.png")
        candidate.save(self.cand / f"{name}.png")

    def _run(self, *extra):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.gold),
                str(self.cand),
                "--out",
                str(self.report),
                *extra,
            ],
            capture_output=True,
            text=True,
        )

    def test_missing_candidate_returns_nonzero(self):
        Image.new("RGBA", (2, 2), (0, 0, 0, 255)).save(
            self.gold / "missing.golden.png"
        )
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_input_directories_return_nonzero(self):
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.report.read_text())["results"], [])

    def test_expected_manifest_rejects_a_missing_golden(self):
        expected = self.root / "expected.txt"
        expected.write_text("required_fixture\n")

        result = self._run("--expected", str(expected))

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(self.report.read_text())["results"][0]
        self.assertEqual(record["name"], "required_fixture")
        self.assertEqual(record["cls"], "MISSING_GOLD")

    def test_unapproved_high_error_case_is_fail(self):
        self._write_near_pair()
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(self.report.read_text())["results"][0]
        self.assertEqual(record["cls"], "FAIL")

    def test_exact_two_code_value_difference_is_strict_pass(self):
        golden = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
        candidate = golden.copy()
        candidate.putpixel((0, 0), (2, 0, 0, 255))
        golden.save(self.gold / "boundary.golden.png")
        candidate.save(self.cand / "boundary.png")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(self.report.read_text())["results"][0]
        self.assertEqual(record["cls"], "PASS")

    def test_explicit_policy_accepts_near_and_records_mechanism(self):
        self._write_near_pair()
        policy = self.root / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": {
                        "near": {
                            "max_abs_diff": 255.001,
                            "mean_abs_diff": 0.1,
                            "ssim_min": 0.99,
                            "mechanism": "single-pixel threshold discontinuity",
                        }
                    },
                }
            )
        )
        result = self._run("--policy", str(policy))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads(self.report.read_text())["results"][0]
        self.assertEqual(record["cls"], "NEAR")
        self.assertEqual(
            record["policy"]["mechanism"],
            "single-pixel threshold discontinuity",
        )

    def test_policy_fails_when_any_bound_is_exceeded(self):
        self._write_near_pair()
        policy = self.root / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": {
                        "near": {
                            "max_abs_diff": 255,
                            "mean_abs_diff": 0,
                            "ssim_min": 0,
                            "mechanism": "deliberately too-tight mean bound",
                        }
                    },
                }
            )
        )
        result = self._run("--policy", str(policy))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.report.exists(), result.stdout + result.stderr)
        record = json.loads(self.report.read_text())["results"][0]
        self.assertEqual(record["cls"], "FAIL")

    def test_expected_sweep_rejects_a_policy_that_no_fixture_uses(self):
        golden = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
        golden.save(self.gold / "exact.golden.png")
        golden.save(self.cand / "exact.png")
        expected = self.root / "expected.txt"
        expected.write_text("exact\n")
        policy = self.root / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": {
                        "exact": {
                            "max_abs_diff": 10,
                            "mean_abs_diff": 1,
                            "ssim_min": 0.9,
                            "mechanism": "dormant allowance must not mask future drift",
                        }
                    },
                }
            )
        )

        result = self._run("--policy", str(policy), "--expected", str(expected))

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.report.read_text())["unused_policies"], ["exact"])


if __name__ == "__main__":
    unittest.main()
