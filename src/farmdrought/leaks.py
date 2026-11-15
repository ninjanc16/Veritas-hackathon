"""leaks.py: which canals are most likely to be leaking, and which to check first.

THE CHAIN (three links, in order):
  1. THE AI FORECAST says WHEN: the 6-month forest gives each county a chance of a drought
     season (p_season in latest.parquet).
  2. THE CANAL MAP says WHERE: every mapped canal and ditch segment (canals.py).
  3. THE SOIL UNDER THE CANAL says HOW LEAKY: a bare-earth canal dug through sandy soil
     loses far more water than one dug through clay. Texas A&M published a seepage rate
     for each soil type (config.SEEPAGE_GAL_SQFT_DAY).

  priority = worst when BOTH are true: the forecast warns AND the soil is leaky.

SOIL DATA: USDA Natural Resources Conservation Service, Soil Survey (SSURGO), read through
its public "Soil Data Access" service (no key needed):
    https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest
For the middle point of each canal segment we ask which soil map unit it sits in, then take
that unit's main soil and its texture about 1 meter down (roughly where a canal bed is).

BE HONEST ABOUT WHAT THIS IS:
  - It is an ESTIMATE of where leaks are likely. Nobody measured these canals.
  - We do not know which canals are lined with concrete. A lined canal on sandy soil is
    flagged here even though the lining may stop the leak. (Lining is no guarantee either:
    the three concrete canals Texas A&M tested leaked more than the two earth ones.)
  - Real seepage also depends on how the canal was built, silt, and the water table.
  - The source report itself says each canal must be checked on the ground.
So the output is a list of canals to INSPECT FIRST, not a list of proven leaks.

Run it with:  PYTHONPATH=src python -m farmdrought.leaks            (summarize)
              PYTHONPATH=src python -m farmdrought.leaks download   (ask the soil service again)
              PYTHONPATH=src python -m farmdrought.leaks download-ksat   (ADDED: permeability and
                            water-table depth for the same soil layer, into canal_ksat.csv)
"""
import json
import sys

import pandas as pd
import requests

from farmdrought.config import NOT_IRRIGATION_NAMES
from farmdrought.config import (CANAL_KSAT_CSV, CANAL_SOIL_CSV, CANALS_CSV, CANALS_GEOJSON, KSAT_TO_GAL_SQFT_DAY, LATEST,
                                LEAKY_SOIL_RATE, SEASON_THRESHOLD, SEEPAGE_GAL_SQFT_DAY, WATER_TABLE_DEEP_CM,
                                WATER_TABLE_MIN_FACTOR, WATER_TABLE_SHALLOW_CM)

SOIL_SERVICE = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
SOIL_SOURCE = "USDA NRCS Soil Survey (SSURGO), through the Soil Data Access service"
RATE_SOURCE = ("Fipps (Texas A&M), 1998: Table 7 (quoting the Texas Board of Water Engineers, 1946), the low end of "
               "Table 6 for sands, and one measured canal in Table 8 for sandy clay loam")
BED_DEPTH_CM = 100  # we read the soil about 1 meter down
# Segments whose name says they carry water AWAY (drains) are not irrigation canals.
NOT_IRRIGATION = NOT_IRRIGATION_NAMES   # "Drain|Wasteway|Floodway", now kept in config.py and shared
LEVELS = ["Inspect first", "Watch", "Low", "Unknown soil", "Drain"]


def ask(query):
    """Send one question (written in SQL) to the soil service and return the answer as a table."""
    reply = requests.post(SOIL_SERVICE, json={"format": "JSON+COLUMNNAME", "query": query}, timeout=300)
    reply.raise_for_status()
    rows = reply.json().get("Table", [])
    return pd.DataFrame(rows[1:], columns=rows[0]) if rows else pd.DataFrame()


def download_soil(batch=200):
    """For every canal segment, find the soil texture under its middle point. Saves a CSV."""
    canals = pd.read_csv(CANALS_CSV, dtype={"fips": str})

    # Step 1: which soil map unit ("mukey") is each point in? 200 points per question.
    units = []
    for start in range(0, len(canals), batch):
        part = canals.iloc[start : start + batch]
        points = ", ".join(f"('{row.id}', 'point({row.lon} {row.lat})')" for row in part.itertuples())
        units.append(ask(f"SELECT p.id, M.mukey FROM (VALUES {points}) AS p(id, wkt) "
                         "CROSS APPLY SDA_Get_Mukey_from_intersection_with_WktWgs84(p.wkt) AS M"))
        print(f"soil map units: {min(start + batch, len(canals))} of {len(canals)} segments")
    units = pd.concat(units).drop_duplicates("id")  # a point on a border can match two units: keep one

    # Step 2: the layer at canal-bed depth in the main soil of each map unit
    texture = bed_layer(soil_layers(sorted(units["mukey"].unique()), batch)).set_index("mukey")["texcl"]

    canals = canals[["id"]].astype(str).merge(units, on="id", how="left")
    canals["soil"] = canals["mukey"].map(texture)
    canals.to_csv(CANAL_SOIL_CSV, index=False)


def soil_layers(keys, batch=200):
    """The soil layers of each map unit. A unit holds several soils ("components"), each with
    layers ("horizons") from the surface down, each layer with a texture.

    ADDED in round 3: the same question also returns each layer's permeability (saturated
    hydraulic conductivity, Ksat, in micrometres per second): low, typical and high.
    """
    layers = []
    for start in range(0, len(keys), batch):
        layers.append(ask(
            "SELECT c.mukey, c.cokey, c.comppct_r, h.hzdept_r, h.hzdepb_r, t.texcl, h.ksat_l, h.ksat_r, h.ksat_h "
            "FROM component c JOIN chorizon h ON h.cokey = c.cokey "
            "JOIN chtexturegrp g ON g.chkey = h.chkey AND g.rvindicator = 'Yes' "
            "JOIN chtexture t ON t.chtgkey = g.chtgkey "
            f"WHERE c.mukey IN ({', '.join(keys[start : start + batch])})"))
        print(f"soil layers: {min(start + batch, len(keys))} of {len(keys)} map units")
    return pd.concat(layers)


def bed_layer(layers):
    """One row per map unit: the layer at canal-bed depth in the unit's main soil.

    This is the rule the texture has always been picked by; the permeability columns (if the
    table has them) simply come along from the same row.
    """
    layers = layers.dropna(subset=["texcl"]).copy()
    for column in ["comppct_r", "hzdept_r", "hzdepb_r"]:
        layers[column] = pd.to_numeric(layers[column])

    # Keep the MAIN soil of each unit (the one covering the largest share of it)...
    main = layers.sort_values("comppct_r", ascending=False).drop_duplicates("mukey")["cokey"]
    layers = layers[layers["cokey"].isin(main)]
    # ...and of its layers, the one that contains the 1 meter depth. If the soil is shallower
    # than that, take its deepest layer.
    layers["reaches_bed"] = (layers["hzdept_r"] <= BED_DEPTH_CM) & (layers["hzdepb_r"] > BED_DEPTH_CM)
    return layers.sort_values(["reaches_bed", "hzdept_r"], ascending=False).drop_duplicates("mukey")


def download_ksat(batch=200):
    """ADDED in round 3. For every canal segment: the permeability of the same soil layer the
    texture was read from, and the depth to the water table. Saves canal_ksat.csv with
    id, mukey, ksat_low, ksat_typ, ksat_high (micrometres per second) and wt_cm (centimetres).

    It starts from the map unit of each segment as saved in canal_soil.csv and NEVER rewrites
    that file, which belongs to the frozen snapshot. Returns (the table, the texture the service
    gives today for each map unit), so a caller can check today's texture against the saved one.
    """
    soil = pd.read_csv(CANAL_SOIL_CSV, dtype={"id": str, "mukey": str})
    keys = sorted(soil["mukey"].dropna().unique())
    layer = bed_layer(soil_layers(keys, batch)).set_index("mukey")

    # Depth to the water table: the shallowest in a normal year, one value per map unit.
    tables = []
    for start in range(0, len(keys), batch):
        tables.append(ask(f"SELECT mukey, wtdepannmin FROM muaggatt WHERE mukey IN ({', '.join(keys[start : start + batch])})"))
    water = pd.concat(tables).drop_duplicates("mukey").set_index("mukey")["wtdepannmin"]

    out = soil[["id", "mukey"]].copy()
    for column, source in (("ksat_low", "ksat_l"), ("ksat_typ", "ksat_r"), ("ksat_high", "ksat_h")):
        out[column] = pd.to_numeric(out["mukey"].map(layer[source]))
    out["wt_cm"] = pd.to_numeric(out["mukey"].map(water))
    out.to_csv(CANAL_KSAT_CSV, index=False)
    return out, layer["texcl"]


def water_table_factor(wt_cm):
    """g: how much a shallow water table holds seepage back. ASSUMPTION (see config.py).

    1 when the depth is unknown or more than 300 cm; a straight line from 1 at 300 cm down to
    0.1 at 100 cm; 0.1 for anything shallower.
    """
    if wt_cm is None or pd.isna(wt_cm) or wt_cm >= WATER_TABLE_DEEP_CM:
        return 1.0
    if wt_cm <= WATER_TABLE_SHALLOW_CM:
        return WATER_TABLE_MIN_FACTOR
    share = (wt_cm - WATER_TABLE_SHALLOW_CM) / (WATER_TABLE_DEEP_CM - WATER_TABLE_SHALLOW_CM)
    return WATER_TABLE_MIN_FACTOR + (1 - WATER_TABLE_MIN_FACTOR) * share


def seepage_rate(ksat, wt_cm, c=1.0):
    """ADDED in round 3. Seepage rate in gallons per square foot of wetted canal per day, from
    the soil's permeability:  q = ksat x 2.1205 x g x c.

    ksat  : saturated hydraulic conductivity of the soil at canal-bed depth, micrometres per second
    wt_cm : depth to the water table in centimetres (None or NaN if unknown)
    c     : the calibration factor (1.0 = not calibrated)
    A missing ksat gives NaN: no permeability, no rate.

    ASSUMPTION: this treats the hydraulic gradient as 1 and ignores any silt layer on the canal
    bed. It is a modelled rate, not a measured one. Nothing uses it for ranking or pricing yet;
    the texture-table rate stays beside it for comparison.
    """
    if ksat is None or pd.isna(ksat):
        return float("nan")
    return float(ksat) * KSAT_TO_GAL_SQFT_DAY * water_table_factor(wt_cm) * c


def rate_canals(latest):
    """Join the three links. Returns one row per canal segment with its level.

    latest : this week's forecasts (needs fips and p_season)
    """
    canals = pd.read_csv(CANALS_CSV, dtype={"fips": str, "id": str, "name": str}).fillna({"name": ""})
    soil = pd.read_csv(CANAL_SOIL_CSV, dtype={"id": str})
    canals = canals.merge(soil[["id", "soil"]], on="id", how="left")
    # Link 3: seepage rate from the published table. Soil types not in the table stay empty.
    canals["seepage_rate"] = canals["soil"].map(SEEPAGE_GAL_SQFT_DAY)
    # Link 1: the AI forecast for the segment's county
    canals["p_season"] = canals["fips"].map(latest.set_index("fips")["p_season"])

    forecast_warns = canals["p_season"] >= SEASON_THRESHOLD      # the same 0.25 rule as everywhere else
    leaky_soil = canals["seepage_rate"] >= LEAKY_SOIL_RATE
    canals["level"] = "Low"                                      # neither
    canals.loc[forecast_warns | leaky_soil, "level"] = "Watch"   # one of the two
    canals.loc[forecast_warns & leaky_soil, "level"] = "Inspect first"  # both
    canals.loc[canals["seepage_rate"].isna(), "level"] = "Unknown soil"
    canals.loc[canals["name"].str.contains(NOT_IRRIGATION, case=False), "level"] = "Drain"
    # A score for sorting: seepage rate x chance of a drought season (0 when unknown or a drain)
    canals["score"] = (canals["seepage_rate"] * canals["p_season"]).where(~canals["level"].isin(LEVELS[3:]), 0).round(2)
    return canals


def run_leaks(latest, counties):
    """Build the "canal_priority" block of metrics.json and add the levels to the map file."""
    if not (CANALS_CSV.exists() and CANAL_SOIL_CSV.exists()):
        return {"levels": LEVELS, "by_level": [], "by_county": [], "named": [],
                "note": "The canal or soil file was not downloaded, so there is nothing to report."}
    canals = rate_canals(latest)

    # Write soil, rate, forecast and level into the map file, so the App can color each line
    with open(CANALS_GEOJSON) as f:
        map_file = json.load(f)
    assert len(map_file["features"]) == len(canals), "the map file and the canal table must hold the same segments"
    for feature, row in zip(map_file["features"], canals.itertuples()):
        feature["properties"].update({
            "soil": row.soil if isinstance(row.soil, str) else "", "level": row.level, "score": row.score,
            "seepage_rate": None if pd.isna(row.seepage_rate) else row.seepage_rate,
            "p_season": round(row.p_season, 3)})
    with open(CANALS_GEOJSON, "w") as f:
        json.dump(map_file, f, separators=(",", ":"))

    km = lambda rows: round(float(rows["length_km"].sum()), 1)
    names = counties.drop_duplicates("fips").set_index("fips")
    first = canals[canals["level"] == "Inspect first"]
    named = first[first["name"] != ""].groupby(["name", "fips"]).agg(
        km=("length_km", "sum"), seepage_rate=("seepage_rate", "mean"), p_season=("p_season", "first")).reset_index()
    named = named.sort_values("km", ascending=False).head(20)
    return {
        "soil_source": SOIL_SOURCE,
        "seepage_rate_source": RATE_SOURCE,
        "seepage_gal_sqft_day": SEEPAGE_GAL_SQFT_DAY,
        "leaky_soil_rate": LEAKY_SOIL_RATE,
        "forecast_threshold": SEASON_THRESHOLD,
        "levels": LEVELS,
        "rule": "Inspect first = the 6-month forecast warns for the county AND the soil under the canal is leaky "
                "(loam or sandier). Watch = one of the two. Low = neither. Unknown soil = the soil type has no "
                "published seepage rate. Drain = the name says it is a drain, wasteway or floodway.",
        "by_level": [{"level": level, "km": km(canals[canals["level"] == level]),
                      "segments": int((canals["level"] == level).sum())} for level in LEVELS],
        "by_soil": [{"soil": soil, "km": km(rows), "seepage_rate": SEEPAGE_GAL_SQFT_DAY.get(soil)}
                    for soil, rows in sorted(canals.fillna({"soil": "(no soil data)"}).groupby("soil"),
                                             key=lambda pair: -pair[1]["length_km"].sum())],
        # every county, most "inspect first" km at the top
        "by_county": sorted([{"fips": fips, "county": names.loc[fips, "county"], "state": names.loc[fips, "state"],
                              "p_season": round(float(latest.set_index("fips").loc[fips, "p_season"]), 3),
                              "inspect_first_km": km(first[first["fips"] == fips]),
                              "leaky_soil_km": km(canals[(canals["fips"] == fips) & (canals["seepage_rate"] >= LEAKY_SOIL_RATE)]),
                              "canal_km": km(canals[canals["fips"] == fips])} for fips in names.index],
                            key=lambda entry: -entry["inspect_first_km"]),
        # the named canals with the most "inspect first" km
        "named": [{"name": row.name, "county": names.loc[row.fips, "county"], "state": names.loc[row.fips, "state"],
                   "inspect_first_km": round(row.km, 1), "seepage_rate": round(row.seepage_rate, 2),
                   "p_season": round(row.p_season, 3)} for row in named.itertuples()],
        "note": "An estimate of where leaks are LIKELY, not measured leaks. It assumes bare-earth canals: we do not "
                "know which canals are lined. Real seepage also depends on construction, silt and the water table. "
                "The levels change every week with the forecast. Use it to choose canals to inspect, not to claim "
                "water savings.",
    }


if __name__ == "__main__":
    from farmdrought.config import FOCUS_RIVER

    if sys.argv[1:] == ["download"]:
        download_soil()
    if sys.argv[1:] == ["download-ksat"]:
        table, _ = download_ksat()
        print(f"saved {len(table)} segments, {int(table['ksat_typ'].notna().sum())} with a permeability")
        sys.exit(0)
    latest = pd.read_parquet(LATEST)
    counties = latest.loc[latest["river"] == FOCUS_RIVER, ["fips", "county", "state"]]
    result = run_leaks(latest, counties)
    print(result["note"], "\n")
    for key in ["by_level", "by_soil", "by_county", "named"]:
        print(pd.DataFrame(result[key]).to_string(index=False), "\n")
