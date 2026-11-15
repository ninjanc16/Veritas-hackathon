"""Tests for build_site.py: the website's data files match the pipeline's outputs."""
import json

import pytest

from app import contract
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


def test_the_build_refuses_inputs_that_break_the_contract(tmp_path, monkeypatch):
    # Arrange: a copy of the real metrics file with one required key removed
    broken = json.loads(contract.REAL_METRICS.read_text())
    del broken["headline"]
    bad_metrics = tmp_path / "metrics.json"
    bad_metrics.write_text(json.dumps(broken))
    monkeypatch.setattr(contract, "REAL_METRICS", bad_metrics)
    out = tmp_path / "site_data"

    # Act / Assert: the build stops with the problem in plain words, and writes nothing
    with pytest.raises(SystemExit) as stopped:
        build(out)
    message = str(stopped.value)
    assert "NOT built" in message and "missing key 'headline'" in message
    assert not out.exists()


def test_the_build_refuses_when_a_handoff_file_is_missing(tmp_path, monkeypatch):
    # Arrange: point the contract at an empty folder
    monkeypatch.setattr(contract, "REAL_DIR", tmp_path)
    out = tmp_path / "site_data"

    # Act / Assert
    with pytest.raises(SystemExit, match="missing real file"):
        build(out)
    assert not out.exists()


def test_deployment_files_route_the_live_reading_and_keep_the_site_deployable():
    # Arrange
    config = json.loads((REPO_ROOT / "vercel.json").read_text())
    ignored = [line.strip() for line in (REPO_ROOT / ".vercelignore").read_text().splitlines()
               if line.strip() and not line.startswith("#")]

    # Assert: the page's relative "api/live" is sent to the root function, which reuses the one handler
    assert {"source": "/app/site/api/live", "destination": "/api/live"} in config["rewrites"]
    assert {"source": "/", "destination": "/app/site/", "permanent": False} in config["redirects"]
    assert 'require("../app/site/api/live.js")' in (REPO_ROOT / "api" / "live.js").read_text()
    assert (REPO_ROOT / "app" / "site" / "api" / "live.js").exists()
    # nothing the site or the function reads is kept out of the deployment
    assert all(line.startswith("/") for line in ignored)                  # root folders only
    assert not {"/app", "/api", "/vercel.json"} & set(ignored)
    assert not any(line.startswith("/app") or line.startswith("/api") for line in ignored)


def test_site_size_gate_passes_today_and_names_a_file_that_grew():
    # Arrange: load tools/site_size.py (it is a script, not a package)
    import importlib.util
    spec = importlib.util.spec_from_file_location("site_size", REPO_ROOT / "tools" / "site_size.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)

    # Act
    today = gate.tracked_sizes()
    grown = {**today, "app/site/data/core.js": int(3.3 * gate.MB), "app/site/photos/new.jpg": int(1.2 * gate.MB)}

    # Assert: today's files are within their limits; a core.js of 3.3 MB and a 1.2 MB photo are not
    assert "app/site/data/core.js" in today and gate.problems(today) == []
    found = gate.problems(grown)
    assert len(found) == 2 and "core.js is 3.30 MB, over its limit of 3.2 MB" in found[0]
    assert "new.jpg is 1.20 MB, over its limit of 1.0 MB" in found[1]
    assert any("in all" in line for line in gate.problems({"app/site/a.bin": 0.9 * gate.MB} | {f"app/site/{i}": 0.9 * gate.MB for i in range(60)}))


def load_tool(name):
    """Load a script from tools/ as a module (tools is not a package)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hash_list_gate_catches_a_changed_or_removed_line_against_the_base_branch(tmp_path):
    # Arrange: a temporary git repository whose main branch holds a list of two hashes
    import shutil
    import subprocess
    if shutil.which("git") is None:
        pytest.skip("git is not installed, so a temporary repository cannot be made")
    gate = load_tool("hash_list_gate")

    def git(*args):
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
                       cwd=tmp_path, check=True, capture_output=True)

    listed = tmp_path / "reports" / "frozen.sha256"
    listed.parent.mkdir()
    listed.write_text("aaa  reports/frozen/one.json\nbbb  reports/frozen/two.json\n")
    git("init", "-q", "-b", "main")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "work")
    name = "reports/frozen.sha256"

    # Act / Assert: a new line is allowed
    listed.write_text(listed.read_text() + "ccc  reports/frozen/three.json\n")
    found, notes = gate.check("main", [name], cwd=str(tmp_path))
    assert found == [] and "all 2 lines from the base are unchanged; 1 new line(s)" in notes[0]
    # editing a scored file's hash line (the way to slip a changed result past the local check) is caught
    listed.write_text("aaa  reports/frozen/one.json\nZZZ  reports/frozen/two.json\nccc  reports/frozen/three.json\n")
    assert gate.check("main", [name], cwd=str(tmp_path))[0] == [
        "reports/frozen.sha256: the recorded hash of reports/frozen/two.json was changed"]
    # so is dropping a line, and so is deleting the list and building it again without that file
    listed.write_text("aaa  reports/frozen/one.json\n")
    assert gate.check("main", [name], cwd=str(tmp_path))[0] == [
        "reports/frozen.sha256: the line for reports/frozen/two.json was removed"]
    listed.unlink()
    assert gate.check("main", [name], cwd=str(tmp_path))[0] == [
        "reports/frozen.sha256 was deleted; it existed on the base branch"]
    # a list that the base does not have, and a base that does not exist, pass and say why
    (tmp_path / "reports" / "prospective.sha256").write_text("ddd  reports/prospective/2027-01-05.json\n")
    found, notes = gate.check("main", ["reports/prospective.sha256"], cwd=str(tmp_path))
    assert found == [] and "does not exist on the base" in notes[0]
    for missing in ("", "0000000000000000000000000000000000000000", "origin/no-such-branch"):
        found, notes = gate.check(missing, [name], cwd=str(tmp_path))
        assert found == [] and "nothing was checked" in notes[0]
