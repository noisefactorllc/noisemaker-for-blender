#!/usr/bin/env python3
"""Golden trust in scripts/parity-summary.

A golden is graded only when its provenance.json entry matches its sha256 and
names the reference revision pinned in parity/reference-revision; anything else
is 'missing' or 'stale' and counts as missing, never as executed.
"""

import importlib.machinery
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader("parity_summary", str(ROOT / "scripts" / "parity-summary"))
_spec = importlib.util.spec_from_loader("parity_summary", _loader)
parity_summary = importlib.util.module_from_spec(_spec)
_loader.exec_module(parity_summary)

PIN = "a" * 40


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
        self.write(entry={"sha256": "0" * 64, "reference_revision": PIN})
        self.assertEqual(self.state(), "stale")

    def test_golden_minted_at_another_revision_is_stale(self):
        self.write()
        entry = {"sha256": parity_summary.sha256(self.gold), "reference_revision": "b" * 40}
        self.write(entry=entry)
        self.assertEqual(self.state(), "stale")

    def test_golden_without_a_recorded_revision_is_stale(self):
        self.write()
        self.write(entry={"sha256": parity_summary.sha256(self.gold)})
        self.assertEqual(self.state(), "stale")

    def test_golden_minted_at_the_pin_is_ok(self):
        self.write()
        self.write(entry={"sha256": parity_summary.sha256(self.gold), "reference_revision": PIN})
        self.assertEqual(self.state(), "ok")


class PinTests(unittest.TestCase):
    def test_the_pin_is_a_full_commit_sha(self):
        self.assertRegex(parity_summary.pinned_revision(), re.compile(r"^[0-9a-f]{40}$"))


if __name__ == "__main__":
    unittest.main()
