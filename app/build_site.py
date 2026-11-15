"""build_site.py: pack everything the website draws into two small JavaScript files.

The website (app/site/) is plain HTML and JavaScript. It cannot read parquet files, so this
script reads the pipeline's saved outputs and writes them out as JavaScript data:

    app/site/data/core.js   maps, this week's forecasts, canals, districts, test results
    app/site/data/sim.js    the weekly history (2000 on) that the simulation learns from and replays

Almost nothing is calculated here that the pipeline did not already calculate. This script
selects, rounds and renames. The exceptions, all simple:
  - Texas counties get this week's U.S. Drought Monitor class from the raw Drought Monitor file.
  - Canals get extra detail from OpenStreetMap (kind, piped or open, names) and the canals
    only OpenStreetMap has are added. See app/osm_canals.py. Those extra canals have no soil
    reading, so they are never ranked or priced.
  - The forecast model frozen at the end of 2019 is packed in from app/forecast_pre2020.py.

It first checks the pipeline's files against the data contract (app/contract.py) and refuses
to build from files that break it.

Run it with:   python -m app.build_site        (from the repo root)
Run it again whenever the pipeline outputs change (the daily refresh changes them).
"""
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# The line-matching helpers are shared with the pipeline (src/farmdrought/canal_class.py), so
# both match canals to OpenStreetMap the same way. That module imports nothing heavy.
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))                                                # so "from app import contract" works as a script
from app import contract  # noqa: E402
from farmdrought.canal_class import OSM_KINDS, dense, line_near, point_grid  # noqa: E402
RAW = ROOT / "data" / "raw"
LIVE = ROOT / "data" / "live"        # the daily refresh saves its downloads here; data/raw is a fixed snapshot
PROCESSED = ROOT / "data" / "processed"
SITE = ROOT / "app" / "site"
OUT = SITE / "data"

TEXAS = "48"                       # every Texas county code starts with 48
DM_LABELS = ["None", "D0", "D1", "D2", "D3", "D4"]   # U.S. Drought Monitor classes
SIM_START = "2000-01-01"           # the Drought Monitor record starts in January 2000
APP_DATA = ROOT / "app" / "data"   # files made by app/osm_canals.py and app/forecast_pre2020.py
NOT_MAINLAND = {"02", "15", "60", "66", "69", "72", "78"}   # Alaska, Hawaii and the territories
MAP_WINDOW = (-109.5, 24.5, -92.5, 38.5)   # rivers are kept inside this box (Texas with a margin)
LAKES = [("Amistad", "amistad.csv", -101.058, 29.450), ("Falcon", "falcon.csv", -99.165, 26.559),
         ("Elephant Butte", "elephant-butte.csv", -107.19, 33.15)]   # dam positions, typed in by hand (approximate)
# The four Lower Rio Grande Valley counties. The published farm-loss figures cover only these.
VALLEY = ["48061", "48215", "48427", "48489"]


def rounded(ring, digits):
    """Round a list of [lon, lat] points and drop points that repeat after rounding."""
    out = []
    for lon, lat in (p[:2] for p in ring):
        point = [round(lon, digits), round(lat, digits)]
        if not out or out[-1] != point:
            out.append(point)
    return out


def rings_of(geometry, digits):
    """The outer rings of a Polygon or MultiPolygon, rounded. Holes are dropped (not needed to draw)."""
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [rounded(poly[0], digits) for poly in polys if len(poly[0]) >= 4]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def newest(relative):
    """The newest copy of a file the daily refresh downloads: data/live if it has one, else the
    snapshot in data/raw. The website shows this week, so it reads the newest data."""
    return LIVE / relative if (LIVE / relative).exists() else RAW / relative


def texas_counties(usdm, profiles, photo_files):
    """All 254 Texas counties: outline, this week's drought class, and the photo and profile we hold."""
    last = {fips: series[-1] for fips, series in zip(usdm["counties"], usdm["series"])}
    out = []
    for feature in load_json(RAW / "geojson-counties-fips.json")["features"]:
        fips = feature["id"]
        if not fips.startswith(TEXAS):
            continue
        profile = profiles.get(fips, {})
        mark = last.get(fips, ".")
        out.append({
            "fips": fips,
            "name": feature["properties"]["NAME"],
            "dm": None if mark == "." else int(mark),          # index into DM_LABELS
            "rings": rings_of(feature["geometry"], 3),
            "pop": profile.get("pop2020"),
            "about": profile.get("about", ""),
            "page": profile.get("page", ""),
            "credit": profile.get("photo"),                    # who took the ground photo, and its licence
            "photos": [kind for kind in ("county", "drought", "ground") if f"{fips}-{kind}.jpg" in photo_files],
        })
    return sorted(out, key=lambda c: c["name"])


def river_counties(latest):
    """The 14 Texas counties on the Rio Grande, with this week's forecast."""
    rows = latest[(latest["state"] == "Texas") & (latest["river"] == "Rio Grande")]
    out = []
    for r in rows.itertuples():
        out.append({
            "fips": r.fips, "name": r.county, "lat": round(r.lat, 3), "lon": round(r.lon, 3),
            "cls": int(r.cls),                                   # same scale as "dm" above
            "pSeason": round(float(r.p_season), 3),              # chance of a drought season in 6 months
            "tier": r.season_tier,                               # Low, Watch or Warning
            "p4": round(float(r.p_model), 3),                    # chance of D2 within 4 weeks
            "weeks": round(float(r.weeks_model), 1),             # drought weeks expected in the next year
            "weeksLow": round(float(r.weeks_low), 1), "weeksHigh": round(float(r.weeks_high), 1),
            "reservoir": r.res_name, "reservoirPct": None if r.res_pct_full < 0 else round(float(r.res_pct_full), 1),
        })
    return out


def rio_grande_line():
    """The river itself, clipped to the Texas reach, for the maps."""
    lines = []
    for feature in load_json(RAW / "ne_10m_rivers_lake_centerlines.geojson")["features"]:
        if (feature["properties"].get("name") or "") != "Rio Grande":
            continue
        geometry = feature["geometry"]
        parts = geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]
        for part in parts:
            kept = [p for p in rounded(part, 3) if -107 <= p[0] <= -97 and 25.7 <= p[1] <= 32.1]
            if len(kept) >= 2:
                lines.append(kept)
    return lines


def simplify(points, tolerance):
    """Douglas-Peucker: drop points that sit within `tolerance` degrees of the simplified line."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norm = (dx * dx + dy * dy) ** 0.5
        worst, where = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5 if norm == 0 else abs(dx * (ay - py) - (ax - px) * dy) / norm
            if d > worst:
                worst, where = d, i
        if worst > tolerance:
            keep[where] = True
            stack += [(a, where), (where, b)]
    return [p for p, k in zip(points, keep) if k]


def join_edges(edges):
    """Join loose two-point edges into long lines, so they can be simplified and drawn."""
    near = defaultdict(list)
    for i, (a, b) in enumerate(edges):
        near[a].append(i)
        near[b].append(i)
    used, lines = [False] * len(edges), []

    def walk(start, first):
        line, node, edge = [start], start, first
        while edge is not None:
            used[edge] = True
            a, b = edges[edge]
            node = b if a == node else a
            line.append(node)
            if len(near[node]) != 2:          # a junction or a loose end: stop here
                break
            edge = next((e for e in near[node] if not used[e]), None)
        return line

    for node, touching in near.items():       # lines that start at a junction or a loose end
        if len(touching) != 2:
            for e in touching:
                if not used[e]:
                    lines.append(walk(node, e))
    for i, (a, _) in enumerate(edges):        # what is left are closed loops
        if not used[i]:
            lines.append(walk(a, i))
    return lines


def base_map(counties):
    """What the scan animation draws before it reaches Texas: state lines, the Texas outline,
    and one dot per county in the mainland United States.

    State lines are found from the county shapes: an edge that belongs to only one county, or
    to counties in two different states, is a state line.
    """
    owners = defaultdict(set)
    dots = []
    for feature in counties:
        fips = feature["id"]
        if fips[:2] in NOT_MAINLAND:
            continue
        geometry = feature["geometry"]
        polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        rings = [ring for poly in polys for ring in poly]
        for ring in rings:
            pts = [(round(x, 5), round(y, 5)) for x, y in (p[:2] for p in ring)]
            for a, b in zip(pts, pts[1:]):
                if a != b:
                    owners[(a, b) if a < b else (b, a)].add(fips)
        biggest = max(rings, key=len)
        dots += [round(sum(p[0] for p in biggest) / len(biggest), 2), round(sum(p[1] for p in biggest) / len(biggest), 2)]
    state_edges, texas_edges = [], []
    for edge, fips in owners.items():
        states = {f[:2] for f in fips}
        if len(fips) == 1 or len(states) > 1:
            state_edges.append(edge)
            if TEXAS in states:
                texas_edges.append(edge)
    return {
        "states": [rounded(simplify(line, 0.03), 2) for line in join_edges(state_edges)],
        "texasEdge": [rounded(simplify(line, 0.004), 3) for line in join_edges(texas_edges)],
        "dots": dots, "nCounties": len(dots) // 2,
    }


def rivers_in_window():
    """Every river line inside the map window, with its name (the Rio Grande and its neighbours)."""
    west, south, east, north = MAP_WINDOW
    out = []
    for feature in load_json(RAW / "ne_10m_rivers_lake_centerlines.geojson")["features"]:
        geometry, props = feature["geometry"], feature["properties"]
        if not geometry or props.get("featurecla") != "River":
            continue
        parts = geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]
        for part in parts:
            inside = [(p[0], p[1]) for p in part if west <= p[0] <= east and south <= p[1] <= north]
            if len(inside) > 1:
                out.append({"name": props.get("name") or "", "line": rounded(simplify(inside, 0.003), 3)})
    return out


def lakes():
    """The three reservoirs: where the dam is and how full it was at the last saved reading."""
    out = []
    for name, file, lon, lat in LAKES:
        last = pd.read_csv(newest(Path("reservoirs") / file), comment="#").dropna(subset=["conservation_storage"]).iloc[-1]
        out.append({"name": name, "lon": lon, "lat": lat, "date": str(last["date"])[:10],
                    "pct": round(100 * float(last["conservation_storage"]) / float(last["conservation_capacity"]), 1)})
    return out


# ---------- OpenStreetMap detail for the canals (see app/osm_canals.py) ----------
# dense, point_grid and line_near now live in src/farmdrought/canal_class.py (imported above).
def inside_ring(x, y, ring):
    """Is the point inside this ring? (Ray casting: count the edges a ray going east crosses.)"""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def line_km(line):
    """Length of a [lon, lat] line in kilometres (flat-earth maths, fine over a few km)."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        total += math.hypot((x2 - x1) * math.cos(math.radians((y1 + y2) / 2)) * 111.32, (y2 - y1) * 110.57)
    return total


def add_osm_detail(names, canals, district_list, river, counties):
    """Label the USGS canals with OpenStreetMap's kind, pipe flag and names, then add the canals
    only OpenStreetMap has. Returns a short summary for the page to show.

    Each canal list gains three items at the end: kind (0 canal, 1 ditch, 2 drain, None unknown),
    piped (1 if OpenStreetMap maps most of it underground), source (0 USGS, 1 OpenStreetMap).
    """
    path = APP_DATA / "osm_canals.json"
    if not path.exists():
        for canal in canals:
            canal += [None, 0, 0]
        return None
    osm = load_json(path)
    ways = osm["ways"]

    # 1. Label each USGS canal by the OpenStreetMap lines that run along it.
    grid = point_grid([w["line"] for w in ways])
    named = piped = 0
    for canal in canals:
        points = dense(canal[10])
        hits = [ways[i] for i in (line_near(grid, x, y) for x, y in points) if i is not None]
        kind, is_piped = None, 0
        if len(hits) >= 0.5 * len(points):                       # OpenStreetMap follows at least half of it
            kind = OSM_KINDS.index(Counter(w["kind"] for w in hits).most_common(1)[0][0])
            is_piped = int(sum(w["piped"] for w in hits) >= 0.5 * len(points))
            osm_names = Counter(w["name"] for w in hits if w["name"])
            if canal[0] == 0 and osm_names and osm_names.most_common(1)[0][1] >= 0.5 * len(points):
                name = osm_names.most_common(1)[0][0]
                if name not in names:
                    names.append(name)
                canal[0] = names.index(name)
                named += 1
        piped += is_piped
        canal += [kind, is_piped, 0]

    # 2. Add the lines only OpenStreetMap has. They must sit inside a Texas river county.
    usgs = point_grid([c[10] for c in canals])
    shapes = {f["id"]: ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"])
              for f in counties if f["id"] in {c["fips"] for c in river}}
    chance = {c["fips"]: c["pSeason"] for c in river}
    added = 0
    for way in ways:
        line = way["line"]
        points = dense(line)
        if sum(line_near(usgs, x, y) is not None for x, y in points) >= 0.3 * len(points):
            continue                                             # the USGS file already has this canal
        mx, my = line[len(line) // 2]
        fips = next((f for f, polys in shapes.items() if any(inside_ring(mx, my, poly[0]) for poly in polys)), None)
        if fips is None:
            continue                                             # in Mexico or outside the river counties
        district = next((i for i, d in enumerate(district_list) if any(inside_ring(mx, my, ring) for ring in d["rings"])), -1)
        if way["name"] not in names:
            names.append(way["name"])
        level = "Drain" if way["kind"] == "drain" else "Unknown soil"   # no soil reading, so no seepage rate
        canals.append([names.index(way["name"]), None, level, fips, round(line_km(line), 3), None, chance[fips],
                       district, None, None, rounded(line, 4), OSM_KINDS.index(way["kind"]), int(way["piped"]), 1])
        added += 1
    return {"source": osm["source"], "added": added, "addedKm": round(sum(c[4] for c in canals if c[13] == 1), 1),
            "namesGained": named, "pipedUsgs": piped}


def texas_canals(district_names):
    """Every canal segment in Texas, as a short list (short lists keep the file small).

    [name, soil, level, fips, km, seepage rate, chance of drought season, district number,
     seal rank, seal cost in dollars, [[lon, lat], ...]]
    """
    names, soils, out = [""], [], []
    for feature in load_json(PROCESSED / "canals.geojson")["features"]:
        p = feature["properties"]
        if not p["fips"].startswith(TEXAS):
            continue
        if p["name"] not in names:
            names.append(p["name"])
        if p["soil"] not in soils:
            soils.append(p["soil"])
        out.append([
            names.index(p["name"]), soils.index(p["soil"]), p["level"], p["fips"],
            round(p["length_km"], 3), p["seepage_rate"], round(p["p_season"], 3),
            district_names.index(p["district"]) if p["district"] in district_names else -1,
            p["seal_rank"], p["seal_usd"], rounded(feature["geometry"]["coordinates"], 4),
        ])
    return names, soils, out


def districts(name_to_fips):
    """The 30 Texas irrigation and water districts: outline, risk, and canal totals."""
    out = []
    for feature in load_json(PROCESSED / "districts.geojson")["features"]:
        p = feature["properties"]
        out.append({
            "name": p["district"], "kind": p["kind"], "counties": p["counties"],
            "fips": [name_to_fips[c] for c in p["counties"] if c in name_to_fips],
            "pSeason": p["p_season"], "risk": p["risk"],
            "canalKm": p["canal_km"], "treatableKm": p["treatable_km"],
            "rings": rings_of(feature["geometry"], 4),
        })
    return sorted(out, key=lambda d: d["name"])


def weekly_history(usdm, fips_list):
    """Weekly records from 2000 on, for the simulation: drought class, forecast, reservoirs, losses.

    The forecasts only exist from 2008 (the first year the model was tested on), so earlier
    weeks hold None there.
    """
    all_weeks = pd.date_range(usdm["week0"], periods=usdm["weeks"], freq="7D")
    start = int((all_weeks >= SIM_START).argmax())
    weeks = all_weeks[start:]
    series = dict(zip(usdm["counties"], usdm["series"]))

    # The forecasts the model actually made each week (each from a model trained on earlier years only).
    outlook = pd.read_parquet(PROCESSED / "outlook.parquet")
    outlook = outlook[outlook["fips"].isin(fips_list)]
    forecast, happened = {}, {}
    for fips, rows in outlook.groupby("fips"):
        rows = rows.set_index("date").reindex(weeks)
        forecast[fips] = [None if pd.isna(v) else round(float(v), 2) for v in rows["p_season"]]
        happened[fips] = [None if pd.isna(v) else int(v) for v in rows["y_season"]]

    # Reservoir storage as percent full, one reading a week. Amistad and Falcon are run as one system.
    def percent_full(files):
        storage = capacity = None
        for name in files:
            lake = pd.read_csv(newest(Path("reservoirs") / name), comment="#", parse_dates=["date"]).set_index("date")
            lake = lake[~lake.index.duplicated()].reindex(pd.date_range("1999-12-01", weeks[-1])).ffill()
            storage = lake["conservation_storage"] if storage is None else storage + lake["conservation_storage"]
            capacity = lake["conservation_capacity"] if capacity is None else capacity + lake["conservation_capacity"]
        pct = (100 * storage / capacity).reindex(weeks)
        return [None if pd.isna(v) else round(float(v), 1) for v in pct]

    # Insured crop losses paid for drought, by year, in the Texas river counties (USDA records).
    rma = pd.read_csv(RAW / "rma" / "colsom_rio_grande.csv", dtype={"fips": str})
    rma["fips"] = rma["fips"].str.zfill(5)
    rma = rma[rma["fips"].isin(fips_list) & rma["cause"].str.contains("Drought", case=False, na=False)]
    insured = {fips: {int(y): round(float(v)) for y, v in rows.groupby("year")["indemnity"].sum().items()}
               for fips, rows in rma.groupby("fips")}

    return {
        "week0": str(weeks[0].date()), "nWeeks": len(weeks),
        "cls": {fips: series[fips][start:] for fips in fips_list},      # one character per week, "." = no data
        "forecast": forecast, "happened": happened,
        "reservoirs": {"Amistad-Falcon": percent_full(["amistad.csv", "falcon.csv"]),
                       "Elephant Butte": percent_full(["elephant-butte.csv"])},
        "insuredDroughtLoss": insured,
        "valley": VALLEY,
        # The forecast model frozen at the end of 2019 (see app/forecast_pre2020.py), if it has been run.
        "pre2020": load_json(APP_DATA / "pre2020.json") if (APP_DATA / "pre2020.json").exists() else None,
    }


def write_js(path, variable, data):
    """Save data as a JavaScript file that sets one global variable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    path.write_text(f"// Generated by app/build_site.py. Do not edit by hand.\nwindow.{variable} = {text};\n",
                    encoding="utf-8")
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path   # a test builds outside the repo
    print(f"wrote {shown}  ({path.stat().st_size / 1e6:.2f} MB)")


def check_inputs():
    """Check the four handoff files against the data contract (app/contract.py) BEFORE anything
    is written. If a file is missing or breaks the contract, stop with the list of problems:
    a website built from bad inputs would show wrong numbers without saying so."""
    *_, problems = contract.load()
    if problems:
        raise SystemExit("The site was NOT built, and no file was written, because the pipeline's files do not "
                         "meet the data contract:\n  - " + "\n  - ".join(problems))


def build(out_dir=None):
    """Write core.js and sim.js into out_dir (app/site/data when no folder is given).

    The tests pass a temporary folder, so running them never rewrites the tracked data files.
    """
    out_dir = OUT if out_dir is None else Path(out_dir)
    check_inputs()
    metrics = load_json(ROOT / "reports" / "metrics.json")
    usdm = load_json(newest("usdm-counties.json"))
    latest = pd.read_parquet(PROCESSED / "latest.parquet")
    profiles_file = SITE / "photos" / "profiles.json"
    profiles = load_json(profiles_file) if profiles_file.exists() else {}
    photo_files = {p.name for p in (SITE / "photos").glob("*.jpg")}

    river = river_counties(latest)
    name_to_fips = {c["name"]: c["fips"] for c in river}
    district_list = districts(name_to_fips)
    district_names = [d["name"] for d in district_list]
    canal_names, soils, canals = texas_canals(district_names)
    counties = load_json(RAW / "geojson-counties-fips.json")["features"]
    osm = add_osm_detail(canal_names, canals, district_list, river, counties)

    def optional(name):
        path = ROOT / "reports" / name
        return load_json(path) if path.exists() else None

    plan = metrics["districts"]
    core = {
        "week": str(pd.Timestamp(latest["date"].max()).date()),
        "generatedAt": metrics.get("generated_at"),
        "refresh": optional("refresh.json"),
        "dmLabels": DM_LABELS,
        "texas": texas_counties(usdm, profiles, photo_files),
        "river": river,
        "riverLine": rio_grande_line(),
        "rivers": rivers_in_window(),
        "lakes": lakes(),
        "base": base_map(counties),
        "osm": osm,
        "districts": district_list,
        "canalNames": canal_names, "soils": soils, "canals": canals,
        "levels": metrics["canal_priority"]["levels"],
        "levelRule": metrics["canal_priority"]["rule"],
        "seepage": metrics["canal_priority"]["seepage_gal_sqft_day"],
        "seepageSource": metrics["canal_priority"]["seepage_rate_source"],
        "soilSource": metrics["canal_priority"]["soil_source"],
        "canalSource": metrics["canals"]["source"],
        "plan": {k: v for k, v in plan.items() if k != "districts"},   # the sealant plan's rule, assumptions and totals
        "threshold": metrics["trigger"]["threshold"],
        "trigger": metrics["trigger"],
        "season": metrics["season"]["focus"],
        "trainYears": metrics.get("train_years"), "testYears": metrics.get("test_years"),
        "issues": optional("issues.json"),
        "limits": metrics["limits"],
        "reservoirNote": metrics["reservoir"].get("note"),
    }
    write_js(out_dir / "core.js", "HG", core)
    write_js(out_dir / "sim.js", "HG_SIM", weekly_history(usdm, [c["fips"] for c in river]))


if __name__ == "__main__":
    build()
