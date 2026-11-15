"""build_data.py: pack the pipeline's finished outputs into demo/data.js for the offline demo.

The demo page (demo/index.html) runs no model. It only draws numbers this script copies out
of data/processed/ and reports/metrics.json. Run it again whenever those files change:

    python demo/build_data.py

Needs pandas and pyarrow (both already in requirements-pipeline.txt).
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, PROCESSED, REPORTS = ROOT / "data" / "raw", ROOT / "data" / "processed", ROOT / "reports"
TEXAS = "48"
NOT_CONUS = {"02", "15", "60", "66", "69", "72", "78"}  # Alaska, Hawaii and territories
LEVELS = ["Low", "Watch", "Inspect first", "Drain", "Unknown soil"]
# Map window for rivers: Texas with a margin, so the Rio Grande headwaters reach is visible.
WINDOW = (-109.5, 24.5, -92.5, 38.5)
# Dam positions are approximate (typed in by hand, not from a file in this repo).
RESERVOIRS = [("Amistad", "amistad.csv", -101.058, 29.450), ("Falcon", "falcon.csv", -99.165, 26.559)]


def simplify(points, tol):
    """Douglas-Peucker: drop points that sit within `tol` degrees of the simplified line."""
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
            if norm == 0:
                d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
            else:
                d = abs(dx * (ay - py) - (ax - px) * dy) / norm
            if d > worst:
                worst, where = d, i
        if worst > tol:
            keep[where] = True
            stack += [(a, where), (where, b)]
    return [p for p, k in zip(points, keep) if k]


def pack(points, scale=10000):
    """Line as integers: first point, then the change from each point to the next."""
    out, px, py = [], 0, 0
    for x, y in points:
        ix, iy = round(x * scale), round(y * scale)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def rings_of(geometry):
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    return [ring for poly in polys for ring in poly]


def chain(edges):
    """Join loose two-point edges into long lines so they can be simplified and drawn."""
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
            if len(near[node]) != 2:  # a junction or a loose end: stop here
                break
            edge = next((e for e in near[node] if not used[e]), None)
        return line

    for node, touching in near.items():  # lines that start at a junction or loose end
        if len(touching) != 2:
            for e in touching:
                if not used[e]:
                    lines.append(walk(node, e))
    for i, (a, _) in enumerate(edges):   # what is left are closed loops
        if not used[i]:
            lines.append(walk(a, i))
    return lines


def borders(counties):
    """State lines and Texas county lines, found from edges that two county shapes share."""
    sides = defaultdict(set)
    for feature in counties:
        fips = feature["id"]
        if fips[:2] in NOT_CONUS:
            continue
        for ring in rings_of(feature["geometry"]):
            pts = [(round(x, 5), round(y, 5)) for x, y in ring]
            for a, b in zip(pts, pts[1:]):
                if a != b:
                    sides[(a, b) if a < b else (b, a)].add(fips)
    state, texas_edge, texas_inner = [], [], []
    for edge, owners in sides.items():
        states = {f[:2] for f in owners}
        if len(owners) == 1 or len(states) > 1:
            state.append(edge)
            if TEXAS in states:
                texas_edge.append(edge)
        elif states == {TEXAS}:
            texas_inner.append(edge)
    return state, texas_edge, texas_inner


def main():
    metrics = json.loads((REPORTS / "metrics.json").read_text())
    counties = json.loads((RAW / "geojson-counties-fips.json").read_text())["features"]
    out = {"week": metrics["latest_week"], "levels": LEVELS}

    # --- 1. Base map: state lines, Texas outline, Texas county lines, one dot per US county
    state, texas_edge, _ = borders(counties)
    out["states"] = [pack(simplify(l, 0.03), 1000) for l in chain(state)]
    out["texas"] = [pack(simplify(l, 0.004)) for l in chain(texas_edge)]
    dots = []
    for feature in counties:
        if feature["id"][:2] in NOT_CONUS:
            continue
        ring = max(rings_of(feature["geometry"]), key=len)
        dots += [round(sum(p[0] for p in ring) / len(ring) * 100), round(sum(p[1] for p in ring) / len(ring) * 100)]
    out["dots"] = dots
    out["nCounties"] = len(dots) // 2
    out["nTexasCounties"] = sum(1 for f in counties if f["id"][:2] == TEXAS)

    # --- 2. Rivers inside the map window
    west, south, east, north = WINDOW
    rivers = []
    for feature in json.loads((RAW / "ne_10m_rivers_lake_centerlines.geojson").read_text())["features"]:
        geometry, props = feature["geometry"], feature["properties"]
        if not geometry or props["featurecla"] != "River":
            continue
        parts = geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]
        for part in parts:
            inside = [(p[0], p[1]) for p in part if west <= p[0] <= east and south <= p[1] <= north]
            if len(inside) > 1:
                rivers.append({"name": props["name"] or "", "rank": props["scalerank"],
                               "line": pack(simplify(inside, 0.003))})
    out["rivers"] = rivers

    # --- 3. This week's forecast for the Texas counties along the Rio Grande
    latest = pd.read_parquet(PROCESSED / "latest.parquet")
    latest["fips"] = latest["fips"].astype(str).str.zfill(5)
    focus = latest[(latest["river"] == metrics["focus_river"]) & latest["fips"].str.startswith(TEXAS)]
    rows = []
    for row in focus.sort_values("lon").itertuples():
        rows.append({
            "fips": row.fips, "name": row.county, "lon": round(row.lon, 3), "lat": round(row.lat, 3),
            "risk": row.risk_level, "cls": int(row.cls), "p4": round(float(row.p_model), 3),
            "pSeason": round(float(row.p_season), 4), "weeksLow": round(float(row.weeks_low), 1),
            "weeksHigh": round(float(row.weeks_high), 1), "weeksModel": round(float(row.weeks_model), 1),
            "typical": float(row.typical_drought_weeks), "longest": float(row.longest_drought_weeks),
            "feedUsd": round(float(row.damage_usd_per_100_head)), "reservoir": row.res_name,
            "resPct": float(row.res_pct_full),
        })
    out["counties"] = rows

    # --- 3b. Every Texas county: shape, name, and its Drought Monitor class now and 4 weeks ago
    usdm = json.loads((RAW / "usdm-counties.json").read_text())
    series = dict(zip(usdm["counties"], usdm["series"]))
    digit = lambda ch: int(ch) if ch.isdigit() else -1  # "." means no data that week
    everyone = []
    for feature in counties:
        fips = feature["id"]
        if fips[:2] != TEXAS:
            continue
        rings = rings_of(feature["geometry"])
        big = max(rings, key=len)
        weeks = series.get(fips, "..")
        everyone.append({
            "fips": fips, "name": feature["properties"]["NAME"],
            "lon": round(sum(p[0] for p in big) / len(big), 3), "lat": round(sum(p[1] for p in big) / len(big), 3),
            "cls": digit(weeks[-1]), "cls4": digit(weeks[-5]) if len(weeks) > 4 else -1,
            "sqmi": round(feature["properties"]["CENSUSAREA"]),
            "rings": [pack(simplify([(x, y) for x, y in ring], 0.003)) for ring in rings],
        })
    out["txAll"] = everyone
    names = {r["fips"]: r["name"] for r in rows}

    # --- 4. Texas canal and ditch segments with their leak priority
    # Each segment also carries its irrigation district and its place in the sealant plan
    # (written into canals.geojson by src/farmdrought/districts.py).
    soils, canal_names, district_names, segments = [], [""], [""], []
    km = defaultdict(float)
    for feature in json.loads((PROCESSED / "canals.geojson").read_text())["features"]:
        p = feature["properties"]
        if not p["fips"].startswith(TEXAS):
            continue
        if p["soil"] not in soils:
            soils.append(p["soil"])
        name = p["name"] or ""
        if name not in canal_names:
            canal_names.append(name)
        km[p["level"]] += p["length_km"]
        if p["district"] not in district_names:
            district_names.append(p["district"])
        segments.append([LEVELS.index(p["level"]), soils.index(p["soil"]), canal_names.index(name), p["fips"],
                         round(p["length_km"], 2), p["seepage_rate"], p["score"],
                         pack(simplify([(x, y) for x, y in feature["geometry"]["coordinates"]], 0.00015)),
                         # 8: district (0 = none), 9: sealant rank (0 = not in the plan), 10: cost in dollars
                         district_names.index(p["district"]), p["seal_rank"] or 0, p["seal_usd"] or 0])
    out.update(soils=soils, canalNames=canal_names, canals=segments, districtNames=district_names,
               canalKm={level: round(km[level], 1) for level in LEVELS})

    # --- 4b. Irrigation districts: boundary, drought risk and canal totals (districts.py)
    block = metrics["districts"]
    districts = []
    for feature in json.loads((PROCESSED / "districts.geojson").read_text())["features"]:
        d = feature["properties"]
        districts.append({
            "name": d["district"], "kind": d["kind"], "counties": d["counties"], "risk": d["risk"],
            "pSeason": d["p_season"], "canalKm": d["canal_km"], "treatableKm": d["treatable_km"],
            "rings": [pack(simplify([(x, y) for x, y in ring], 0.0004)) for ring in rings_of(feature["geometry"])],
        })
    out["districts"] = districts
    # The plan's fixed figures. The page shares out any budget itself, with the pipeline's own rule:
    # pay for canals in rank order while the running total still fits inside the budget.
    out["sealant"] = {
        "budget": block["budget_usd"], "maxBudget": block["cost_to_treat_everything_usd"],
        "usdPerSqft": block["assumptions"]["sealant_usd_per_sqft"], "widthFt": block["assumptions"]["wetted_width_ft"],
        "cutLow": block["assumptions"]["sealant_cut_low"], "cutHigh": block["assumptions"]["sealant_cut_high"],
        "days": block["assumptions"]["days_one_application_lasts"], "gallonsPerAf": 325851,
        "source": block["source"], "note": block["note"], "rule": block["rule"],
        # the pipeline's own totals at its example budget, so the page can be checked against them
        "check": {k: block[k] for k in ("sealed_km", "spent_usd", "saved_af_low", "saved_af_high")},
    }

    # --- 4c. When the data was last refreshed (written by src/farmdrought/refresh.py)
    refresh_file = REPORTS / "refresh.json"
    refresh = json.loads(refresh_file.read_text()) if refresh_file.exists() else {"refreshed_at": "", "sources": {}}
    out["refresh"] = {"at": refresh["refreshed_at"],
                      "newest": {name: source.get("newest", "") for name, source in refresh["sources"].items()}}

    # --- 5. Reservoir storage, latest reading in each Texas Water Development Board file
    lakes = []
    for name, filename, lon, lat in RESERVOIRS:
        lines = [l for l in (RAW / "reservoirs" / filename).read_text().splitlines() if l and not l.startswith("#")]
        last = dict(zip(lines[0].split(","), lines[-1].split(",")))
        lakes.append({"name": name, "lon": lon, "lat": lat, "date": last["date"], "pct": float(last["percent_full"])})
    out["reservoirs"] = lakes

    # --- 6. Insured drought losses in the Texas counties, by year (same files losses.py reads)
    by_year = defaultdict(float)
    with open(RAW / "rma" / "colsom_rio_grande.csv") as handle:
        for row in csv.DictReader(handle):
            if row["fips"] in names and row["cause"] in metrics["losses"]["causes_included"]:
                by_year[int(row["year"])] += float(row["indemnity"])
    first, last = metrics["losses"]["years"]
    out["losses"] = {
        "byYear": [[year, round(by_year[year])] for year in range(first, last + 1)],
        "byCounty": [[c["county"], c["usd"]] for c in metrics["losses"]["by_county"] if c["fips"] in names],
        "source": metrics["losses"]["source"],
    }

    # --- 7. Test results and limits, copied as they are
    out["skill"] = {
        "alert": next(p for p in metrics["policies"] if p["name"] == "Our system"),
        "alertBestRule": metrics["headline"]["cheapest_baseline_cost"],
        "season": metrics["season"]["focus"], "year": metrics["year"]["focus"],
        "events": metrics["events"], "trigger": metrics["trigger"]["rules"][0],
        "reservoirHelped": metrics["reservoir"]["helped"],
        # version 2 of the 4-week alert (chosen on validation years only, see reports/decision.md)
        "alertV2": {k: metrics["v2"]["alert"][k] for k in ("v2", "v1", "simple_rule")},
    }
    out["leakyRate"] = metrics["canal_priority"]["leaky_soil_rate"]
    out["threshold"] = metrics["season"]["threshold"]
    out["seepage"] = metrics["canal_priority"]["seepage_gal_sqft_day"]
    out["feedCost"] = metrics["map_fields"]["feed_cost_per_head_month"]
    out["limits"] = metrics["limits"]

    text = "window.DEMO = " + json.dumps(out, separators=(",", ":")) + ";\n"
    (ROOT / "demo" / "data.js").write_text(text)
    print(f"wrote demo/data.js  {len(text) / 1e6:.2f} MB")
    print(f"  {out['nCounties']} county dots, {len(out['states'])} state lines, {len(rivers)} river reaches")
    print(f"  {len(rows)} Texas river counties, {len(segments)} canal segments, km by level {out['canalKm']}")
    print(f"  Texas insured drought losses {sum(v for _, v in out['losses']['byYear']):,} "
          f"(metrics by county: {sum(v for _, v in out['losses']['byCounty']):,})")


if __name__ == "__main__":
    main()
