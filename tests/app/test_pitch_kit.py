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


def test_export_writes_only_inside_pitch_kit():
    before = _snapshot()
    export()
    after = _snapshot()
    changed = [p for p, t in after.items() if before.get(p) != t]
    assert changed, "export wrote nothing"
    assert all(OUT_DIR.resolve() in p.resolve().parents for p in changed), changed


def test_kit_has_all_the_pieces():
    export()
    assert (OUT_DIR / "explain.md").read_text().count("\n## ") == 17          # 17 questions
    assert (OUT_DIR / "story.md").read_text().count("\n## ") == 5             # 5 moments (4 + the canal plan)
    for name in ("four_week_policies", "twelve_month_error", "other_rivers", "this_week_map"):
        assert (OUT_DIR / "charts" / f"{name}.html").exists()
    # Charts load the chart library from the same folder, never from the internet.
    assert (OUT_DIR / "charts" / "plotly.min.js").exists()
    for chart in (OUT_DIR / "charts").glob("*.html"):
        text = chart.read_text(encoding="utf-8")
        assert 'src="plotly.min.js"' in text and "cdn.plot.ly" not in text, chart
    for name in ("numbers", "writeup", "explain", "story"):
        assert (OUT_DIR / f"{name}.md").read_text().splitlines()[0].startswith("STATUS:")


def test_write_text_refuses_to_leave_pitch_kit(tmp_path):
    with pytest.raises(ValueError):
        write_text(tmp_path / "oops.md", "x")
    with pytest.raises(ValueError):
        write_text(REPO_ROOT / "README.md", "x")


def test_numbers_md_has_the_canal_headings_and_explain_has_17_questions():
    from app.export_pitch_kit import explain_md
    _, _, _, metrics = load_demo()
    text = numbers_md(metrics, "DEMO")
    for heading in ("## Pre-season trigger", "## Reservoirs", "## Measured drought losses"):
        assert heading in text
    assert "- `trigger.forecast_beats_d1_rule`: True" in text
    explain = explain_md(metrics, "DEMO")
    assert "## 14. What does the forecast have to do with canals?" in explain
    assert "## 17. Where is the AI and where is it not?" in explain
