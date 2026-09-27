#!/usr/bin/env python3
"""Reproduce the published-kit standalone-archive verification (GAP-006).

Fetches the served kit.json + engine/noisemaker_blender.zip for a given kit
version, and machine-checks every GAP-006 required item against the repository
checkout:

  - archive inventory: every zip entry byte-identical to the checkout tree
    `blender/` (so the archive identifies its source, and no dev files ship);
  - notices: `noisemaker_blender/LICENSE.txt` present, MIT text, byte-identical
    to the repository LICENSE;
  - source revision: kit.json `source.sha` and the zip's SHA-256 vs kit.json;
  - entry point: `noisemaker_blender/__init__.py` with a literal bl_info dict
    (Blender ast.literal_evals it) exposing `def register():`;
  - upgrade identity: the bl_info version tuple.

Usage: python3 parity/verify_standalone_kit.py <kit-version> [out-report.json]
Requires network access; stdlib only.

Kit 0.1.30 was built from source 81ca79e5ea32c87dd273257c04d2e91da48ea078; the
later docs/evidence-only commit 4435f2c767c7ef7e0055b4e21743c49c3cf9558a changes
no engine file (git diff --stat: docs/COMPLETION_GAPS.md + two evidence files),
so 0.1.30 is the current served engine artifact for the published tip.
"""

import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://kits.noisedeck.app/blender"


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def main(argv):
    version = argv[1]
    report_path = argv[2] if len(argv) > 2 else None
    checks = {}

    kit = json.loads(fetch(f"{BASE}/{version}/kit.json"))
    checks["kit_version"] = kit["version"]
    checks["kit_source_sha"] = kit["source"]["sha"]
    checks["kit_source_repo"] = kit["source"]["repo"]

    entry = next(f for f in kit["files"] if f["path"] == "engine/noisemaker_blender.zip")
    body = fetch(f"{BASE}/{version}/engine/noisemaker_blender.zip")
    digest = hashlib.sha256(body).hexdigest()
    checks["engine_zip_sha256"] = digest
    checks["engine_zip_sha_matches_kit_json"] = digest == entry["sha256"]
    checks["engine_zip_bytes"] = len(body)
    checks["engine_zip_bytes_match_kit_json"] = len(body) == entry["bytes"]

    zf = zipfile.ZipFile(io.BytesIO(body))
    names = zf.namelist()
    checks["entry_count"] = len(names)
    checks["all_entries_under_addon_dir"] = all(n.startswith("noisemaker_blender/") for n in names)

    lic_name = "noisemaker_blender/LICENSE.txt"
    checks["notice_present"] = lic_name in names
    lic_bytes = zf.read(lic_name)
    checks["notice_is_mit_text"] = lic_bytes.decode("utf-8").startswith("MIT License")
    repo_lic = (ROOT / "LICENSE").read_bytes()
    checks["notice_byte_identical_to_repo_LICENSE"] = lic_bytes == repo_lic
    checks["notice_sha256"] = hashlib.sha256(lic_bytes).hexdigest()

    init = zf.read("noisemaker_blender/__init__.py").decode("utf-8")
    checks["entry_point_registers"] = "def register():" in init
    import ast
    m = re.search(r"bl_info = (\{.*?\n\})", init, re.S)
    bl_info = ast.literal_eval(m.group(1)) if m else None
    checks["bl_info_literal_parses"] = bl_info is not None
    checks["bl_info_version"] = list(bl_info["version"]) if bl_info else None
    checks["bl_info_version_is_upgrade_over_0_1_0"] = bool(
        bl_info and tuple(bl_info["version"]) > (0, 1, 0))

    # The builder subtree is the addon package only; blender/harness/ is dev
    # tooling intentionally excluded from the distribution (as the 2026-09-22
    # audit recorded: no development files in the archive).
    addon_dir = ROOT / "blender" / "noisemaker_blender"
    mismatches = []
    missing = []
    for n in names:
        rel = n[len("noisemaker_blender/"):]
        disk = addon_dir / rel
        if not disk.is_file():
            missing.append(n)
        elif hashlib.sha256(disk.read_bytes()).hexdigest() != hashlib.sha256(zf.read(n)).hexdigest():
            mismatches.append(n)
    checkout_files = sorted(
        f"noisemaker_blender/{p.relative_to(addon_dir).as_posix()}"
        for p in addon_dir.rglob("*") if p.is_file())
    checks["checkout_files_missing_from_zip"] = [
        f for f in checkout_files if f not in set(names)]
    checks["zip_entries_missing_from_checkout"] = missing
    checks["entry_byte_mismatches_vs_checkout"] = mismatches
    checks["archive_identifies_source_via_checkout_equality"] = not mismatches and not missing \
        and not checks["checkout_files_missing_from_zip"]

    checks["all_passed"] = (
        checks["engine_zip_sha_matches_kit_json"]
        and checks["engine_zip_bytes_match_kit_json"]
        and checks["notice_present"] and checks["notice_is_mit_text"]
        and checks["notice_byte_identical_to_repo_LICENSE"]
        and checks["entry_point_registers"] and checks["bl_info_literal_parses"]
        and checks["bl_info_version_is_upgrade_over_0_1_0"]
        and checks["archive_identifies_source_via_checkout_equality"]
    )

    text = json.dumps(checks, indent=2, sort_keys=True)
    if report_path:
        Path(report_path).write_text(text + "\n")
    print(text)
    return 0 if checks["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
