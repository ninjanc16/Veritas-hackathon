"""Tests for export_pitch_kit.py: numbers match metrics.json, status line is right, writes stay in app/pitch_kit/."""
import pytest

from app.contract import REPO_ROOT, load_demo
from app.export_pitch_kit import (OUT_DIR, STATUS_LINES, export, flatten, numbers_md,
                                  status_of, write_text)

SKIP = {".venv", ".git", "__pycache__", ".pytest_cache"}


def _snapshot():
    """{file path: last-changed time} for every file in the repo (ignoring caches and the venv)."""
    return {p: p.stat().st_mtime_ns for p in REPO_ROOT.rglob("*")
            if p.is_file() and not SKIP & set(p.relative_to(REPO_ROOT).parts)}


def test_status_lines():
    _, _, _, metrics = load_demo()
    assert status_of("demo", metrics) == "DEMO"
    assert status_of("real", {"is_final": False}) == "PROVISIONAL"
    assert status_of("real", {"is_final": True}) == "FINAL"
    assert STATUS_LINES["FINAL"] == "STATUS: FINAL"
    assert STATUS_LINES["DEMO"].startswith("STATUS: DEMO DATA")
    assert "DO NOT USE IN THE FINAL" in STATUS_LINES["PROVISIONAL"]


def test_numbers_md_has_every_value_and_the_right_first_line():
    _, _, _, metrics = load_demo()
    text = numbers_md(metrics, "DEMO")
    assert text.splitlines()[0] == "STATUS: DEMO DATA - DO NOT USE"
    for key, value in metrics.items():
        for path, leaf in flatten(key, value):
            shown = "n/a" if leaf is None else str(leaf)
            assert f"- `{path}`: {shown}" in text, f"missing {path}"


def test_final_status_line():
    _, _, _, metrics = load_demo()
    assert numbers_md(metrics, "FINAL").splitlines()[0] == "STATUS: FINAL"


def test_export_writes_only_inside_pitch_kit_and_leaves_no_ai_footprint():
    before = _snapshot()
    export()
    after = _snapshot()
    changed = [p for p, t in after.items() if before.get(p) != t]
    assert changed, "export wrote nothing"
    assert all(OUT_DIR.resolve() in p.resolve().parents for p in changed), changed
    # The kit goes on GitHub, so it must not mention the AI tools used to build it.
    for p in OUT_DIR.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8").lower()
            assert "claude" not in text and "anthropic" not in text, p


def test_kit_has_all_the_pieces():
    export()
    assert (OUT_DIR / "explain.md").read_text().count("\n## ") == 13          # 13 questions
    assert (OUT_DIR / "story.md").read_text().count("\n## ") == 4             # 4 moments
    for name in ("four_week_policies", "twelve_month_error", "other_rivers", "this_week_map"):
        assert (OUT_DIR / "charts" / f"{name}.html").exists()
    for name in ("numbers", "writeup", "explain", "story"):
        assert (OUT_DIR / f"{name}.md").read_text().splitlines()[0].startswith("STATUS:")


def test_write_text_refuses_to_leave_pitch_kit(tmp_path):
    with pytest.raises(ValueError):
        write_text(tmp_path / "oops.md", "x")
    with pytest.raises(ValueError):
        write_text(REPO_ROOT / "README.md", "x")
