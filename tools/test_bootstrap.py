"""Materialize test dependencies and authenticated reference source as regular files."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

RECEIPT = ".reference-source.json"


def check_regular_tree(root):
    root = Path(root)
    for path in [root, *root.rglob("*")]:
        mode = path.lstat()
        if stat.S_ISLNK(mode.st_mode) or not (stat.S_ISDIR(mode.st_mode) or stat.S_ISREG(mode.st_mode)):
            raise ValueError("non-regular test input: %s" % path)
        if stat.S_ISREG(mode.st_mode) and mode.st_nlink != 1:
            raise ValueError("multiply linked test input: %s" % path)


def create_environment(destination):
    destination = Path(destination)
    # A copied launcher can report an executable outside its installation.
    # Use the installation's interpreter so pyvenv.cfg names its real libraries.
    executable = Path(sys.base_prefix) / "bin" / ("python%d.%d" % sys.version_info[:2])
    if not executable.is_file():
        executable = Path(sys._base_executable)
    executable = executable.resolve()
    version = subprocess.check_output([str(executable), "-c", "import json,sys;print(json.dumps(list(sys.version_info[:3])))"], text=True)
    if json.loads(version) != list(sys.version_info[:3]):
        raise ValueError("test interpreter version changed during environment setup")
    destination.mkdir(parents=True, exist_ok=False)
    # venv otherwise creates this alias on Linux even with --copies.
    (destination / "lib64").mkdir()
    subprocess.run([str(executable), "-m", "venv", "--copies", str(destination)], check=True)
    check_regular_tree(destination)


def git(store, *args):
    return subprocess.check_output(["git", "--no-replace-objects", "--git-dir", str(store), *args], stderr=subprocess.PIPE)


def check_pin(pin):
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        raise ValueError("reference revision must be a full commit SHA")


def extract_archive(stream, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("reference destination already exists")
    with tarfile.open(fileobj=stream, mode="r:") as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or ".git" in path.parts or path.as_posix() == RECEIPT
                    or not (member.isfile() or member.isdir()) or member.linkname):
                raise ValueError("unsafe reference archive member: %s" % member.name)
            name = path.as_posix()
            if name in names:
                raise ValueError("duplicate reference archive member: %s" % name)
            names.add(name)
        destination.mkdir(parents=True)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    check_regular_tree(destination)


def verify_reference(root, pin):
    root = Path(root)
    check_pin(pin)
    receipt = root / RECEIPT
    if not receipt.exists():
        # Preserve the existing checkout path for callers using a pinned checkout.
        actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], stderr=subprocess.PIPE, text=True).strip()
        top = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], stderr=subprocess.PIPE, text=True).strip()
        if actual != pin or Path(top).resolve() != root.resolve():
            raise ValueError("reference checkout does not match the pinned revision")
        return actual
    check_regular_tree(root)
    metadata = json.loads(receipt.read_text())
    if metadata.get("revision") != pin:
        raise ValueError("reference archive does not match the pinned revision")
    store = Path(metadata["objects"])
    check_regular_tree(store)
    if git(store, "rev-parse", "--is-bare-repository").strip() != b"true":
        raise ValueError("reference object store must be bare")
    if git(store, "rev-parse", "--verify", pin + "^{commit}").decode().strip() != pin:
        raise ValueError("reference object store does not contain the pinned commit")
    expected = {}
    for entry in git(store, "ls-tree", "-rz", "--full-tree", pin).split(b"\0"):
        if not entry:
            continue
        info, raw_path = entry.split(b"\t", 1)
        mode, kind, blob = info.decode().split()
        name = raw_path.decode()
        if mode not in ("100644", "100755") or kind != "blob" or name == RECEIPT:
            raise ValueError("reference commit contains a non-regular source entry")
        expected[name] = (mode, blob)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p != receipt}
    if actual != set(expected):
        raise ValueError("reference archive file inventory differs from the pinned commit")
    for name, (mode, blob) in expected.items():
        path = root / name
        data = path.read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if digest != blob or bool(path.stat().st_mode & stat.S_IXUSR) != (mode == "100755"):
            raise ValueError("reference archive differs from pinned source: %s" % name)
    return pin


def prepare_reference(url, pin, destination):
    check_pin(pin)
    destination = Path(destination).absolute()
    store = destination.with_name(destination.name + ".objects.git")
    if destination.exists() or store.exists():
        raise ValueError("reference destination or object store already exists")
    subprocess.run(["git", "init", "--bare", "--template=", "--quiet", str(store)], check=True)
    subprocess.run(["git", "--git-dir", str(store), "fetch", "--quiet", "--depth=1", "--no-tags", url, pin], check=True)
    if git(store, "rev-parse", "--verify", pin + "^{commit}").decode().strip() != pin:
        raise ValueError("fetched reference does not match its pin")
    check_regular_tree(store)
    with tempfile.TemporaryFile() as stream:
        subprocess.run(["git", "--no-replace-objects", "--git-dir", str(store), "archive", "--format=tar", pin], stdout=stream, check=True)
        stream.seek(0)
        extract_archive(stream, destination)
    (destination / RECEIPT).write_text(json.dumps({"revision": pin, "objects": str(store)}) + "\n")
    return verify_reference(destination, pin)


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    if command == "venv" and len(args) == 1:
        create_environment(args[0])
    elif command == "reference" and len(args) == 3:
        print(prepare_reference(*args))
    elif command == "verify" and len(args) == 2:
        print(verify_reference(args[1], args[0]))
    elif command == "check-tree" and len(args) == 1:
        check_regular_tree(args[0])
    else:
        raise SystemExit("invalid test bootstrap command")
