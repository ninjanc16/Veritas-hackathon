"""manifest.py: a fingerprint of every raw input, so a scored result can say what it was scored on.

data/manifest.json holds the sha256 of every file under data/raw (all folders) and of
notebooks/oni.txt, plus the scoring cut-off (config.SCORE_THROUGH). export.evaluate() refuses to
run when any of those files differs from the manifest: a frozen result must come from the exact
inputs it names. The daily refresh overwrites files in data/raw, so after a refresh the check
fails ON PURPOSE. export.predict() (this week's forecast) does not check the manifest.

Run it with:  PYTHONPATH=src python -m farmdrought.manifest          (check, and list differences)
              PYTHONPATH=src python -m farmdrought.manifest build    (write a new manifest)
"""
import hashlib
import json
import sys
from pathlib import Path

from farmdrought.config import ROOT, SCORE_THROUGH

MANIFEST_PATH = Path("data") / "manifest.json"   # relative to the repo root


def sha256_of(path):
    """The sha256 of a file's bytes, as 64 hex characters."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_hashes(root=ROOT):
    """{path relative to root: sha256} for every raw input that exists now.

    Hidden files (a name starting with a dot, like .DS_Store) are not inputs and are skipped.
    """
    root = Path(root)
    files = [p for p in (root / "data" / "raw").rglob("*") if p.is_file() and not p.name.startswith(".")]
    oni = root / "notebooks" / "oni.txt"
    if oni.exists():
        files.append(oni)
    return {p.relative_to(root).as_posix(): sha256_of(p) for p in sorted(files)}


def build_manifest(root=ROOT):
    """Write data/manifest.json under `root` from the files as they are now. Returns its content."""
    manifest = {"score_through": SCORE_THROUGH, "files": input_hashes(root)}
    path = Path(root) / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def check_manifest(root=ROOT):
    """Compare the files as they are now with data/manifest.json. Returns [] when all agree.

    Otherwise a list with one line per problem: the path, then "(changed)", "(missing)" for a
    file the manifest names that is gone, or "(new)" for a file the manifest does not name. A
    missing manifest, or one made for a different cut-off, is also a problem.
    """
    path = Path(root) / MANIFEST_PATH
    if not path.exists():
        return [f"{MANIFEST_PATH.as_posix()} (missing)"]
    manifest = json.loads(path.read_text())
    recorded, now = manifest["files"], input_hashes(root)
    problems = []
    if manifest.get("score_through") != SCORE_THROUGH:
        problems.append(f"score_through (manifest {manifest.get('score_through')}, config {SCORE_THROUGH})")
    for name in sorted(set(recorded) | set(now)):
        if name not in now:
            problems.append(f"{name} (missing)")
        elif name not in recorded:
            problems.append(f"{name} (new)")
        elif recorded[name] != now[name]:
            problems.append(f"{name} (changed)")
    return problems


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        print(f"wrote {MANIFEST_PATH} with {len(build_manifest()['files'])} files")
    else:
        problems = check_manifest()
        print("\n".join(problems) if problems else "every raw input matches data/manifest.json")
        sys.exit(1 if problems else 0)
