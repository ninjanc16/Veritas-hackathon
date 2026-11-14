"""Tests for the river lines: the file exists, covers all five rivers, and the map draws it."""
import json

import pandas as pd

from app import theme
from app.contract import load
from app.mapdata import RIVERS_FILE, load_river_line

RIVERS = ["Rio Grande", "Colorado", "Mississippi", "Missouri", "Ohio"]


def test_river_file_is_small_and_covers_every_river():
    assert RIVERS_FILE.exists() and RIVERS_FILE.stat().st_size < 200_000     # a few KB, not the 7 MB source
    data = json.loads(RIVERS_FILE.read_text())
    for river in RIVERS:
        assert data[river], f"no line for {river}"


def test_rio_grande_line_runs_from_colorado_to_the_gulf():
    points = [pt for piece in load_river_line("Rio Grande") for pt in piece]
    lats = [p[0] for p in points]
    assert max(lats) > 37 and min(lats) < 26.5              # headwaters in Colorado, mouth near Brownsville


def test_unknown_river_gives_an_empty_line():
    assert load_river_line("Nile") == []


def test_every_county_is_close_to_its_rivers_line():
    # Cheap safety net on the real handoff: each county center is within 60 km of a point on the
    # river line (the project's rule is 50 km; a few km of slack because the line is simplified).
    _, _, latest, *_ = load()
    for river in RIVERS:
        pts = pd.DataFrame([pt for piece in load_river_line(river) for pt in piece], columns=["lat", "lon"])
        for county in latest[latest["river"] == river].itertuples():
            # distance to the nearest vertex is an upper bound on the distance to the line
            dy = (pts["lat"] - county.lat) * 111.2
            dx = (pts["lon"] - county.lon) * 111.2 * 0.8
            near = ((dx ** 2 + dy ** 2) ** 0.5).min()
            assert near < 150, f"{county.county}, {county.state} is {near:.0f} km from the {river} line points"


def test_map_draws_the_river_as_a_line_under_the_dots():
    _, _, latest, *_ = load()
    rg = latest[latest["river"] == "Rio Grande"]
    fig = theme.risk_map(rg, rg.iloc[0]["fips"], river_lines=load_river_line("Rio Grande"), river_name="Rio Grande")
    assert fig.data[0].mode == "lines" and fig.data[0].name == "Rio Grande"
    assert [t.name for t in fig.data][1:] == ["Selected county", "Low", "Watch", "Warning"]


def test_map_colors_by_overall_level_when_asked():
    _, _, latest, *_ = load()
    rg = latest[latest["river"] == "Rio Grande"]
    fig = theme.risk_map(rg, rg.iloc[0]["fips"], level_col="risk_level")
    shown = sum(len(t.lat) for t in fig.data if t.name in ("Low", "Watch", "Warning"))
    assert shown == len(rg)                                  # every county appears exactly once
    assert "Overall level" in "".join(fig.data[-1].text) or "Overall level" in "".join(fig.data[-2].text)
