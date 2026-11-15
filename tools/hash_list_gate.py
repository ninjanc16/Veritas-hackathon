"""hash_list_gate.py: has a recorded hash been changed or removed since the base branch?

Run it with:  python tools/hash_list_gate.py <base ref> <list file> [<list file> ...]
              (for example: python tools/hash_list_gate.py origin/main reports/frozen.sha256)

WHY. reports/frozen.sha256 lists the hash of every scored file, and `python -m farmdrought.manifest
frozen` checks the files against it. But that check compares the working tree with itself: someone
who edits a scored file AND its line in the list in the same commit passes it, and so does someone
who deletes the list and builds it again. It guards against accidents only.

This script closes that door in CI. It compares each list with the SAME file on the base branch:
a line that was there must still be there, unchanged. New lines are allowed (a new result, a new
week's forecast). If the list does not exist on the base, there is nothing to compare, and it says so.
"""
import subprocess
import sys


def lines_of(text):
    """{path: sha256} from lines of "<sha256>  <path>"."""
    return {name: digest for digest, name in (line.split(maxsplit=1) for line in text.splitlines() if line.strip())}


def problems(base_text, current_text, list_name):
    """What an append-only list must never show: a line from the base that changed or is gone.

    current_text is None when the list file itself no longer exists.
    """
    if current_text is None:
        return [f"{list_name} was deleted; it existed on the base branch"]
    base, current = lines_of(base_text), lines_of(current_text)
    out = []
    for name, digest in sorted(base.items()):
        if name not in current:
            out.append(f"{list_name}: the line for {name} was removed")
        elif current[name] != digest:
            out.append(f"{list_name}: the recorded hash of {name} was changed")
    return out


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def check(base_ref, list_files, cwd="."):
    """Compare each list with its version at base_ref. Returns (problems, notes for the log)."""
    found, notes = [], []
    if not base_ref or set(base_ref) == {"0"} or git(["cat-file", "-e", f"{base_ref}^{{commit}}"], cwd).returncode != 0:
        return [], [f"no base commit to compare with ({base_ref or 'none given'}): nothing was checked, so this passes"]
    for name in list_files:
        base = git(["show", f"{base_ref}:{name}"], cwd)
        if base.returncode != 0:
            notes.append(f"{name} does not exist on the base ({base_ref}): nothing to compare, so this passes")
            continue
        try:
            with open(f"{cwd}/{name}") as f:
                current = f.read()
        except FileNotFoundError:
            current = None
        here = problems(base.stdout, current, name)
        found += here
        if not here:
            kept = len(lines_of(base.stdout))
            notes.append(f"{name}: all {kept} lines from the base are unchanged; "
                         f"{len(lines_of(current)) - kept} new line(s)")
    return found, notes


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python tools/hash_list_gate.py <base ref> <list file> [<list file> ...]")
    found, notes = check(sys.argv[1], sys.argv[2:])
    print("\n".join(notes + found))
    sys.exit(1 if found else 0)
