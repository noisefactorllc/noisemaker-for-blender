"""Regular-file test environments and authenticated reference snapshots."""

import importlib.util
import importlib.machinery
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools/test_bootstrap.py"


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def helper(self):
        self.assertTrue(HELPER.is_file(), "test bootstrap must materialize regular files and authenticate source")
        spec = importlib.util.spec_from_file_location("test_bootstrap", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def objects(self):
        store = self.root / "source.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(store)], check=True)
        def git(*args, data=None):
            return subprocess.check_output(["git", "--git-dir", str(store), *args], input=data).strip().decode()
        blob = git("hash-object", "-w", "--stdin", data=b"export const value = 1\n")
        tree = git("mktree", data=f"100644 blob {blob}\tsource.js\n".encode())
        commit = (f"tree {tree}\nauthor Fixture <fixture@example.invalid> 1 +0000\n"
                  "committer Fixture <fixture@example.invalid> 1 +0000\n\nFixture\n").encode()
        pin = git("hash-object", "-t", "commit", "-w", "--stdin", data=commit)
        return store, pin

    def test_reference_preparation_uses_bare_objects_and_exact_regular_files(self):
        helper = self.helper()
        store, pin = self.objects()
        dest = self.root / "reference"
        with mock.patch.object(helper.subprocess, "run", wraps=subprocess.run) as commands:
            helper.prepare_reference(str(store), pin, dest)
        for call in commands.call_args_list:
            argv = call.args[0]
            self.assertNotIn("checkout", argv)
            self.assertNotIn("clone", argv)
            if "init" in argv:
                self.assertIn("--bare", argv)
        self.assertEqual(helper.verify_reference(dest, pin), pin)
        self.assertEqual((dest / "source.js").read_bytes(), b"export const value = 1\n")
        helper.check_regular_tree(dest)
        self.assertFalse((dest / ".git").exists())

    def test_modified_missing_extra_and_wrong_pin_sources_are_refused(self):
        helper = self.helper()
        store, pin = self.objects()
        for change in ("modified", "missing", "extra", "wrong_pin"):
            with self.subTest(change=change):
                dest = self.root / change
                helper.prepare_reference(str(store), pin, dest)
                if change == "modified":
                    (dest / "source.js").write_text("tampered")
                elif change == "missing":
                    (dest / "source.js").unlink()
                elif change == "extra":
                    (dest / "extra.js").write_text("extra executable source")
                with self.assertRaises(ValueError):
                    helper.verify_reference(dest, "f" * 40 if change == "wrong_pin" else pin)

    def test_missing_commit_does_not_materialize_source(self):
        helper = self.helper()
        store, _ = self.objects()
        dest = self.root / "missing"
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            helper.prepare_reference(str(store), "f" * 40, dest)
        self.assertFalse((dest / "source.js").exists())

    def test_git_replacement_objects_cannot_authenticate_modified_source(self):
        helper = self.helper()
        source, pin = self.objects()
        dest = self.root / "reference"
        helper.prepare_reference(str(source), pin, dest)
        store = Path(json.loads((dest / helper.RECEIPT).read_text())["objects"])
        def git(*args, data=None):
            return subprocess.check_output(["git", "--git-dir", str(store), *args], input=data).strip().decode()
        changed = b"export const value = 2\n"
        blob = git("hash-object", "-w", "--stdin", data=changed)
        tree = git("mktree", data=f"100644 blob {blob}\tsource.js\n".encode())
        raw = (f"tree {tree}\nauthor Fixture <fixture@example.invalid> 1 +0000\n"
               "committer Fixture <fixture@example.invalid> 1 +0000\n\nReplacement fixture\n").encode()
        replacement = git("hash-object", "-t", "commit", "-w", "--stdin", data=raw)
        git("update-ref", "refs/replace/" + pin, replacement)
        (dest / "source.js").write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "differs from pinned source"):
            helper.verify_reference(dest, pin)

    def test_archive_rejects_unsafe_entries_before_writing(self):
        helper = self.helper()
        for kind in ("symlink", "hardlink", "traversal", "absolute", "duplicate", "fifo"):
            with self.subTest(kind=kind):
                raw = io.BytesIO()
                with tarfile.open(fileobj=raw, mode="w") as archive:
                    first = tarfile.TarInfo("valid.js")
                    first.size = 1
                    archive.addfile(first, io.BytesIO(b"x"))
                    entry = tarfile.TarInfo({"traversal": "../escape", "absolute": "/escape", "duplicate": "valid.js"}.get(kind, "unsafe"))
                    entry.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE, "fifo": tarfile.FIFOTYPE}.get(kind, tarfile.REGTYPE)
                    entry.linkname = "valid.js" if kind in ("symlink", "hardlink") else ""
                    archive.addfile(entry)
                raw.seek(0)
                dest = self.root / kind
                with self.assertRaises(ValueError):
                    helper.extract_archive(raw, dest)
                self.assertFalse((dest / "valid.js").exists())

    def test_copied_environment_works_and_contains_no_links(self):
        helper = self.helper()
        dest = self.root / "venv"
        helper.create_environment(dest)
        self.assertTrue((dest / "lib64").is_dir())
        helper.check_regular_tree(dest)
        py = dest / "bin/python"
        got = subprocess.check_output([str(py), "-c", "import json,sys;print(json.dumps(list(sys.version_info[:3])))"], text=True)
        self.assertEqual(json.loads(got), list(sys.version_info[:3]))

    def test_golden_generation_authenticates_before_starting_browser(self):
        helper = self.helper()
        store, pin = self.objects()
        dest = self.root / "reference"
        helper.prepare_reference(str(store), pin, dest)
        loader = importlib.machinery.SourceFileLoader("bootstrap_parity_summary", str(ROOT / "scripts/parity-summary"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        summary = importlib.util.module_from_spec(spec)
        loader.exec_module(summary)
        with mock.patch.object(summary, "pinned_revision", return_value=pin), \
                mock.patch.object(summary.shutil, "which", return_value="fake-command"), \
                mock.patch.object(summary, "ensure_golden_infra", return_value=[]) as start:
            for change in ("modified", "missing", "extra", "wrong_pin"):
                (dest / "source.js").write_bytes(b"export const value = 1\n")
                (dest / "extra.js").unlink(missing_ok=True)
                summary.pinned_revision.return_value = pin
                if change == "modified":
                    (dest / "source.js").write_text("changed")
                elif change == "missing":
                    (dest / "source.js").unlink()
                elif change == "extra":
                    (dest / "extra.js").write_text("extra")
                else:
                    summary.pinned_revision.return_value = "f" * 40
                result = summary.generate_goldens([], self.root / "gold", dest, 1, {"size": 8, "time": 0, "frames": 1, "timestep": 0})
                self.assertIn("Cannot authenticate", result)
                start.assert_not_called()

    def test_valid_archive_can_mint_goldens(self):
        helper = self.helper()
        store, pin = self.objects()
        dest = self.root / "reference"
        helper.prepare_reference(str(store), pin, dest)
        loader = importlib.machinery.SourceFileLoader("bootstrap_valid_summary", str(ROOT / "scripts/parity-summary"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        summary = importlib.util.module_from_spec(spec)
        loader.exec_module(summary)
        original_run = subprocess.run
        def command(argv, **kwargs):
            if argv[0] == "git":
                return original_run(argv, **kwargs)
            self.assertTrue(argv[1].endswith("golden-cdp.mjs"))
            self.assertEqual(kwargs["env"]["NM_GOLDEN_REF_REV"], pin)
            return subprocess.CompletedProcess(argv, 0, "", "")
        with mock.patch.object(summary, "pinned_revision", return_value=pin), \
                mock.patch.object(summary.shutil, "which", return_value="fake-command"), \
                mock.patch.object(summary, "ensure_golden_infra", return_value=[]) as start, \
                mock.patch.object(summary.subprocess, "run", side_effect=command):
            result = summary.generate_goldens([], self.root / "gold", dest, 1, {"size": 8, "time": 0, "frames": 1, "timestep": 0})
            self.assertIsNone(result)
            start.assert_called_once()

    def test_entrypoint_uses_copies_with_system_bash_and_preserves_selection(self):
        for use_uv, selected in ((False, False), (True, True)):
            with self.subTest(uv=use_uv, selected=selected):
                repo = self.root / ("uv" if use_uv else "pip")
                for sub in ("scripts", "tools", "blender/noisemaker_blender", "parity/compiler", "parity/corpus", "bin"):
                    (repo / sub).mkdir(parents=True)
                shutil.copyfile(ROOT / "scripts/test", repo / "scripts/test")
                (repo / "parity/reference-revision").write_text("a" * 40)
                (repo / "parity/corpus/probe.dsl").write_text("probe")
                (repo / "parity/test_probe.py").write_text("probe")
                shutil.copyfile(ROOT / "parity/regen-compiler-goldens.sh", repo / "parity/regen-compiler-goldens.sh")
                fake = '''#!PYTHON
import json,os,pathlib,sys
a=sys.argv[1:]; name=pathlib.Path(sys.argv[0]).name
with open(os.environ['CALL_LOG'],'a') as f:f.write(json.dumps([name,*a])+'\\n')
if name=='git':
 assert a==['--version'],a
 print('git version fixture')
elif name=='node':
 print('v26.0.0' if a==['--version'] else '{}')
elif name=='uv':
 assert a[:2]==['pip','install'] and a[a.index('--link-mode')+1]=='copy',a
elif a and a[0]=='tools/test_bootstrap.py':
 if a[1]=='venv':
  p=pathlib.Path(a[2])/'bin/python';p.parent.mkdir(parents=True)
  p.write_bytes(pathlib.Path(sys.argv[0]).read_bytes());p.chmod(0o755)
 elif a[1]=='reference':
  (pathlib.Path(a[4])/'shaders').mkdir(parents=True);print(a[3])
 elif a[1]=='check-tree':pass
 else:raise AssertionError(a)
elif a and a[0]=='-c':
 if 'numpy' in a[1]:print('venv fixture')
 elif 'platform.python_version' in a[1]:print('3.13.9')
elif a[:3]==['-m','pip','install']:pass
elif a and a[0]=='-':
 pathlib.Path(a[2]).write_text('unit fixture\\n');print('unit fixture')
elif a and a[0].endswith('test_pngread.py'):print('  OK fixture\\nPNGREAD PASS')
elif a and '/check_' in a[0]:print('compiler parity fixture')
else:raise AssertionError(a)
'''.replace("PYTHON", sys.executable, 1)
                for name in ("python3", "git", "node", *(("uv",) if use_uv else ())):
                    target = repo / "bin" / name
                    target.write_text(fake)
                    target.chmod(0o755)
                log = repo / "calls.jsonl"
                env = dict(os.environ, PATH=str(repo / "bin") + ":/usr/bin:/bin", NM_TEST_PYTHON=str(repo / "bin/python3"), CALL_LOG=str(log))
                env.pop("NM_CHANGED_FILES", None)
                if selected:
                    env["NM_CHANGED_FILES"] = "parity/test_probe.py\nparity/test_probe.py\n"
                run = subprocess.run(["/bin/bash", str(repo / "scripts/test")], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("ENGINE-FREE TESTS PASS", run.stdout)
                calls = [json.loads(line) for line in log.read_text().splitlines()]
                installers = [c for c in calls if c[1:3] == ["pip", "install"] or c[1:4] == ["-m", "pip", "install"]]
                self.assertEqual(len(installers), 1)
                self.assertIn("numpy==2.4.6", installers[0])
                self.assertIn("pillow==12.3.0", installers[0])
                if selected:
                    units = next(c for c in calls if c[1] == "-")
                    self.assertEqual(units.count("parity/test_probe.py"), 1)


if __name__ == "__main__":
    unittest.main()
