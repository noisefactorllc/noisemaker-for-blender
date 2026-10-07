#!/usr/bin/env python3
"""Standalone archive identity tests.

Every distributed form of the add-on must carry its license notice and identify
its source. The standalone ZIP is produced either by the documented README
command (`cd blender && zip -r noisemaker_blender.zip noisemaker_blender`) or by
the kit builder's subtree zip mode (kit.config.json: blender/noisemaker_blender
-> engine/noisemaker_blender.zip) — both package the same directory tree, so the
inventory asserted here is the inventory of both forms.
"""

import io
import json
import re
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender"))

import noisemaker_blender  # noqa: E402

ADDON_DIR = ROOT / "blender" / "noisemaker_blender"
LICENSE_SHA = "e502d1baf14c5fde7a7476f8a860665352d31d26f75b7a6977943606c8b51259"


def build_standalone_zip():
    """Replicate the documented / builder packaging: zip the addon directory."""
    entries = sorted(p for p in ADDON_DIR.rglob("*") if p.is_file())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in entries:
            zf.write(p, p.relative_to(ADDON_DIR.parent).as_posix())
    return buf.getvalue()


class StandaloneArchiveIdentityTests(unittest.TestCase):
    def test_addon_version_identifies_an_upgrade(self):
        version = noisemaker_blender.bl_info["version"]
        self.assertIsInstance(version, tuple)
        self.assertEqual(len(version), 3)
        self.assertTrue(all(isinstance(n, int) for n in version))
        self.assertGreater(version, (0, 1, 0))
        self.assertEqual(version, noisemaker_blender.VERSION)

    def test_standalone_zip_carries_the_license_notice(self):
        data = build_standalone_zip()
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        self.assertIn("noisemaker_blender/LICENSE.txt", names)
        lic = zf.read("noisemaker_blender/LICENSE.txt")
        self.assertIn("MIT License", lic.decode("utf-8"))
        self.assertIn("Noise Factor LLC", lic.decode("utf-8"))

    def test_standalone_zip_license_matches_the_repo_notice(self):
        import hashlib

        data = build_standalone_zip()
        zf = zipfile.ZipFile(io.BytesIO(data))
        lic = zf.read("noisemaker_blender/LICENSE.txt")
        self.assertEqual(
            hashlib.sha256(lic).hexdigest(), LICENSE_SHA,
            "packaged notice must be byte-identical to the repository LICENSE",
        )

    def test_standalone_zip_entry_point_and_source_identity(self):
        import ast

        data = build_standalone_zip()
        zf = zipfile.ZipFile(io.BytesIO(data))
        init = zf.read("noisemaker_blender/__init__.py").decode("utf-8")
        self.assertIn("def register():", init)
        # Blender parses bl_info with ast.literal_eval at install time: it must be
        # a literal dict (a constant reference would break bl_info parsing).
        m = re.search(r"bl_info = (\{.*?\n\})", init, re.S)
        self.assertIsNotNone(
            m, "no literal bl_info dict matched in the packaged __init__.py")
        bl_info = ast.literal_eval(m.group(1))
        self.assertEqual(bl_info["version"], (0, 1, 14))
        self.assertEqual(bl_info["version"], noisemaker_blender.VERSION,
                         "bl_info version must stay in lockstep with VERSION")
        # The zip ships the same tree the checkout does (inventory identity).
        tracked = sorted(
            p.relative_to(ADDON_DIR.parent).as_posix()
            for p in ADDON_DIR.rglob("*") if p.is_file()
        )
        self.assertEqual(sorted(zf.namelist()), tracked)

    def test_kit_config_ships_the_license_notice_to_the_enclosing_kit(self):
        config = json.loads((ROOT / "export-kit" / "kit.config.json").read_text())
        licenses = {entry["from"]: entry["to"] for entry in config["licenses"]}
        self.assertEqual(licenses.get("LICENSE"),
                         "LICENSES/noisemaker-for-blender-LICENSE.txt")
        self.assertTrue((ROOT / "LICENSE").read_bytes().startswith(b"MIT License"))
        self.assertIn(
            {"from": "blender/noisemaker_blender",
             "to": "engine/noisemaker_blender.zip", "mode": "zip"},
            config["subtrees"],
        )


if __name__ == "__main__":
    unittest.main()
