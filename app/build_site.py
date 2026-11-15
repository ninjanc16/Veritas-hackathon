"""build_site.py: pack everything the website draws into two small JavaScript files.

The website (app/site/) is plain HTML and JavaScript. It cannot read parquet files, so this
script reads the pipeline's saved outputs and writes them out as JavaScript data:

    app/site/data/core.js   maps, this week's forecasts, canals, districts, test results
    app/site/data/sim.js    the weekly history (2008 on) that the simulation replays

Nothing is calculated here that the pipeline did not already calculate. This script only
selects, rounds and renames. The one exception is the list of Texas counties, which gets
this week's U.S. Drought Monitor class straight from the raw Drought Monitor file.

Run it with:   python -m app.build_site        (from the repo root)
Run it again whenever the pipeline outputs change (the daily refresh changes them).
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SITE = ROOT / "app" / "site"
OUT = SITE / "data"

TEXAS = "48"                       # every Texas county code starts with 48
DM_LABELS = ["None", "D0", "D1", "D2", "D3", "D4"]   # U.S. Drought Monitor classes
SIM_START = "2008-01-01"           # the first week the model has an out-of-sample forecast for
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
    """Weekly records from 2008 on, for the simulation: drought class, forecast, reservoirs, losses."""
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
            lake = pd.read_csv(RAW / "reservoirs" / name, comment="#", parse_dates=["date"]).set_index("date")
            lake = lake[~lake.index.duplicated()].reindex(pd.date_range("2007-12-01", weeks[-1])).ffill()
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
    }


def write_js(path, variable, data):
    """Save data as a JavaScript file that sets one global variable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    path.write_text(f"// Generated by app/build_site.py. Do not edit by hand.\nwindow.{variable} = {text};\n",
                    encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}  ({path.stat().st_size / 1e6:.2f} MB)")


def build():
    metrics = load_json(ROOT / "reports" / "metrics.json")
    usdm = load_json(RAW / "usdm-counties.json")
    latest = pd.read_parquet(PROCESSED / "latest.parquet")
    profiles_file = SITE / "photos" / "profiles.json"
    profiles = load_json(profiles_file) if profiles_file.exists() else {}
    photo_files = {p.name for p in (SITE / "photos").glob("*.jpg")}

    river = river_counties(latest)
    name_to_fips = {c["name"]: c["fips"] for c in river}
    district_list = districts(name_to_fips)
    district_names = [d["name"] for d in district_list]
    canal_names, soils, canals = texas_canals(district_names)

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
    write_js(OUT / "core.js", "HG", core)
    write_js(OUT / "sim.js", "HG_SIM", weekly_history(usdm, [c["fips"] for c in river]))


if __name__ == "__main__":
    build()
