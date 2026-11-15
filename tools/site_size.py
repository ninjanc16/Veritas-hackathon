"""site_size.py: a size gate for the website. Run it with:  python tools/site_size.py

It prints the size of the website's tracked files and fails (exit code 1) if one grew past its
limit. The limits sit just above the sizes on 2026-11-15; raise one on purpose, in a commit
that says why, never to make a check pass.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MB = 1_000_000
CORE_LIMIT = 3.2 * MB     # app/site/data/core.js was 2.88 MB
FILE_LIMIT = 1.0 * MB     # any other tracked file under app/site; the largest is 0.34 MB (a photo; 0.67 MB before it was re-encoded)
TOTAL_LIMIT = 50 * MB     # all tracked files under app/site together are 44.1 MB (44.9 MB before the photos were re-encoded)


def tracked_sizes():
    """{path: bytes} for every file git tracks under app/site."""
    names = subprocess.run(["git", "ls-files", "app/site"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    return {name: (ROOT / name).stat().st_size for name in names if name and (ROOT / name).is_file()}


def problems(sizes):
    """The files over their limit, and the total if it is over, as plain sentences."""
    out = []
    for name, size in sorted(sizes.items()):
        limit = CORE_LIMIT if name == "app/site/data/core.js" else FILE_LIMIT
        if size > limit:
            out.append(f"{name} is {size / MB:.2f} MB, over its limit of {limit / MB:.1f} MB")
    total = sum(sizes.values())
    if total > TOTAL_LIMIT:
        out.append(f"app/site is {total / MB:.1f} MB in all, over the limit of {TOTAL_LIMIT / MB:.0f} MB")
    return out


if __name__ == "__main__":
    sizes = tracked_sizes()
    print(f"app/site: {len(sizes)} tracked files, {sum(sizes.values()) / MB:.1f} MB in all (limit {TOTAL_LIMIT / MB:.0f} MB)")
    for name, size in sorted(sizes.items(), key=lambda item: -item[1])[:8]:
        print(f"  {size / MB:6.2f} MB  {name}")
    found = problems(sizes)
    print("\n".join(found) if found else "every file is within its limit")
    sys.exit(1 if found else 0)
