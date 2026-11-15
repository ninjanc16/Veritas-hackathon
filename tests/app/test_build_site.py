"""Tests for build_site.py: the website's data files match the pipeline's outputs."""
import json

import pytest

from app.build_site import OUT, build
from app.contract import REPO_ROOT


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """The website's data files, built ONCE into a temporary folder. The tracked files in
    app/site/data are never written by a test."""
    folder = tmp_path_factory.mktemp("site_data")
    build(folder)
    return folder


def _read(folder, name):
    """Load a generated JavaScript data file as a Python dict."""
    text = (folder / name).read_text(encoding="utf-8")
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


def test_a_test_build_leaves_the_tracked_site_data_untouched(tmp_path):
    # Arrange: the tracked files' bytes and modification times
    tracked = sorted(OUT.glob("*.js"))
    before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in tracked}

    # Act: a full build into a temporary folder
    build(tmp_path)

    # Assert: the build wrote its two files there, and nothing in app/site/data moved
    assert sorted(path.name for path in tmp_path.iterdir()) == ["core.js", "sim.js"]
    assert {"core.js", "sim.js"} <= set(before)
    assert {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in tracked} == before
    assert sorted(OUT.glob("*.js")) == tracked


def test_core_matches_the_pipeline(site):
    core = _read(site, "core.js")
    metrics = json.loads((REPO_ROOT / "reports" / "metrics.json").read_text())
    assert len(core["texas"]) == 254                      # every Texas county is on the map
    assert len(core["river"]) == 14                       # the Texas counties on the Rio Grande
    assert len(core["districts"]) == metrics["districts"]["n_districts"]
    # Every canal the pipeline ranked is there, and their costs add up to the pipeline's total.
    ranked = [c for c in core["canals"] if c[8] is not None]
    assert abs(sum(c[9] for c in ranked) - metrics["districts"]["cost_to_treat_everything_usd"]) < 5
    assert core["threshold"] == metrics["trigger"]["threshold"]


def test_history_lines_up_week_by_week(site):
    sim = _read(site, "sim.js")
    n = sim["nWeeks"]
    for fips, classes in sim["cls"].items():
        assert len(classes) == n and len(sim["forecast"][fips]) == n
    for series in sim["reservoirs"].values():
        assert len(series) == n


def test_openstreetmap_adds_detail_without_touching_the_plan(site):
    core = _read(site, "core.js")
    if core["osm"] is None:                               # app/osm_canals.py has not been run
        return
    extra = [c for c in core["canals"] if c[13] == 1]     # canals only OpenStreetMap has
    assert len(extra) == core["osm"]["added"] > 0
    # They have no soil reading, so they are never ranked or priced.
    assert all(c[1] is None and c[5] is None and c[8] is None and c[9] is None for c in extra)
    assert all(len(c) == 14 for c in core["canals"])      # every canal carries kind, piped and source


def test_scan_base_map_and_frozen_model_are_packed(site):
    core, sim = _read(site, "core.js"), _read(site, "sim.js")
    assert core["base"]["nCounties"] > 3000 and len(core["base"]["states"]) > 40
    assert {lake["name"] for lake in core["lakes"]} == {"Amistad", "Falcon", "Elephant Butte"}
    assert sim["week0"].startswith("2000")                # the history now starts with the drought record
    frozen = sim["pre2020"]
    if frozen is not None:                                # app/forecast_pre2020.py has been run
        assert frozen["trainedOn"]["to"] < "2020-01-01"   # nothing after the cut-off was learned from
        assert set(frozen["live"]) == {c["fips"] for c in core["river"]}
