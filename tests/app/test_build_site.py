"""Tests for build_site.py: the website's data files match the pipeline's outputs."""
import json

from app.build_site import OUT, build
from app.contract import REPO_ROOT


def _read(name):
    """Load a generated JavaScript data file as a Python dict."""
    text = (OUT / name).read_text(encoding="utf-8")
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


def test_core_matches_the_pipeline():
    build()
    core = _read("core.js")
    metrics = json.loads((REPO_ROOT / "reports" / "metrics.json").read_text())
    assert len(core["texas"]) == 254                      # every Texas county is on the map
    assert len(core["river"]) == 14                       # the Texas counties on the Rio Grande
    assert len(core["districts"]) == metrics["districts"]["n_districts"]
    # Every canal the pipeline ranked is there, and their costs add up to the pipeline's total.
    ranked = [c for c in core["canals"] if c[8] is not None]
    assert abs(sum(c[9] for c in ranked) - metrics["districts"]["cost_to_treat_everything_usd"]) < 5
    assert core["threshold"] == metrics["trigger"]["threshold"]


def test_history_lines_up_week_by_week():
    build()
    sim = _read("sim.js")
    n = sim["nWeeks"]
    for fips, classes in sim["cls"].items():
        assert len(classes) == n and len(sim["forecast"][fips]) == n
    for series in sim["reservoirs"].values():
        assert len(series) == n


def test_openstreetmap_adds_detail_without_touching_the_plan():
    build()
    core = _read("core.js")
    if core["osm"] is None:                               # app/osm_canals.py has not been run
        return
    extra = [c for c in core["canals"] if c[13] == 1]     # canals only OpenStreetMap has
    assert len(extra) == core["osm"]["added"] > 0
    # They have no soil reading, so they are never ranked or priced.
    assert all(c[1] is None and c[5] is None and c[8] is None and c[9] is None for c in extra)
    assert all(len(c) == 14 for c in core["canals"])      # every canal carries kind, piped and source


def test_scan_base_map_and_frozen_model_are_packed():
    build()
    core, sim = _read("core.js"), _read("sim.js")
    assert core["base"]["nCounties"] > 3000 and len(core["base"]["states"]) > 40
    assert {lake["name"] for lake in core["lakes"]} == {"Amistad", "Falcon", "Elephant Butte"}
    assert sim["week0"].startswith("2000")                # the history now starts with the drought record
    frozen = sim["pre2020"]
    if frozen is not None:                                # app/forecast_pre2020.py has been run
        assert frozen["trainedOn"]["to"] < "2020-01-01"   # nothing after the cut-off was learned from
        assert set(frozen["live"]) == {c["fips"] for c in core["river"]}
