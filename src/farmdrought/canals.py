"""canals.py: where the canals and ditches are in the 31 Rio Grande counties.

DATA: U.S. Geological Survey, National Hydrography Dataset (NHD), high resolution.
It is the federal government's map of every stream, river, canal and ditch. We ask its
public map service for every line of feature type 336, which the USGS calls "Canal/Ditch":
    https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6   (Flowline - Large Scale)

HOW A SEGMENT IS GIVEN A COUNTY: each line is a short segment (often under 1 km). We take
the middle point of the segment and check which county shape it falls inside.

WHAT THIS DATA DOES NOT SAY (be honest about it):
  - It does not separate irrigation canals from drainage ditches. Both are type 336.
  - It does not say whether a canal is lined with concrete or bare earth.
  - It does not say how much water a canal leaks, or which district owns it.
  - Most segments have no name.
So it shows WHERE the canals are and HOW MANY km there are. It cannot rank canals by leakage.

Run it with:  PYTHONPATH=src python -m farmdrought.canals            (summarize)
              PYTHONPATH=src python -m farmdrought.canals download   (rebuild the files)
"""
import json
import sys

import pandas as pd
import requests

from farmdrought.config import CANALS_CSV, CANALS_DIR, CANALS_GEOJSON, COUNTIES_GEOJSON, FOCUS_RIVER

SERVICE = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query"
CANAL_DITCH = 336  # the USGS feature-type code for "Canal/Ditch"
PAGE = 2000        # the service returns at most 2,000 lines per request
SOURCE = "U.S. Geological Survey, National Hydrography Dataset (high resolution), feature type 336 Canal/Ditch"


def county_polygons(fips):
    """Return {county FIPS: list of polygons}. A polygon is a list of rings, the first is the outer edge."""
    with open(COUNTIES_GEOJSON) as f:
        features = json.load(f)["features"]
    shapes = {}
    for feature in features:
        if feature["id"] in fips:
            geometry = feature["geometry"]
            shapes[feature["id"]] = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return shapes


def inside_ring(lon, lat, ring):
    """Is the point inside this ring of corner points? (The standard "ray casting" test.)

    Imagine a ray going east from the point. Count how many edges of the ring it crosses.
    An odd count means the point is inside. An even count means it is outside.
    """
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        crosses_latitude = (y1 > lat) != (y2 > lat)  # the edge spans the point's latitude
        if crosses_latitude and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def inside_county(lon, lat, polygons):
    """Inside a county = inside the outer edge of one of its polygons, and not inside a hole."""
    return any(inside_ring(lon, lat, polygon[0]) and not any(inside_ring(lon, lat, hole) for hole in polygon[1:])
               for polygon in polygons)


def fetch_box(west, south, east, north):
    """Ask the USGS for every canal/ditch line touching a box. Pages through the results."""
    lines, offset = [], 0
    while True:
        reply = requests.get(SERVICE, timeout=300, params={
            "where": f"ftype={CANAL_DITCH}", "geometry": f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "permanent_identifier,gnis_name,lengthkm,fcode",
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": PAGE, "f": "geojson"})
        reply.raise_for_status()
        page = reply.json()
        if "features" not in page:
            raise RuntimeError(f"the USGS service returned an error: {page}")  # never continue with partial data
        lines += page["features"]
        if len(page["features"]) < PAGE:
            return lines
        offset += PAGE


def download_canals(counties):
    """Download the canal lines of every county and save a table and a map file.

    counties : table with fips, county and state
    """
    shapes = county_polygons(set(counties["fips"]))
    rows, map_lines, seen = [], [], set()
    for county in counties.itertuples():
        polygons = shapes[county.fips]
        corners = [point for polygon in polygons for point in polygon[0]]
        # The box around the county. Lines in the box but outside the county are dropped below.
        box = (min(x for x, _ in corners), min(y for _, y in corners), max(x for x, _ in corners), max(y for _, y in corners))
        kept = 0
        for line in fetch_box(*box):
            properties, geometry = line["properties"], line["geometry"]
            # A line is one string of points, or (rarely) several. Flatten to one list of points.
            points = geometry["coordinates"] if geometry["type"] == "LineString" else [p for part in geometry["coordinates"] for p in part]
            middle = points[len(points) // 2]
            identifier = properties["permanent_identifier"]
            if identifier in seen or not inside_county(middle[0], middle[1], polygons):
                continue  # already counted in a neighboring county's box, or outside this county
            seen.add(identifier)
            kept += 1
            row = {"id": identifier, "fips": county.fips, "name": properties["gnis_name"] or "",
                   "length_km": properties["lengthkm"], "fcode": properties["fcode"],
                   "lon": round(middle[0], 5), "lat": round(middle[1], 5)}
            rows.append(row)
            # 5 decimal places is about 1 meter, which keeps the map file small
            map_lines.append({"type": "Feature", "properties": {k: row[k] for k in ("fips", "name", "length_km")},
                              "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y, *_ in points]}})
        print(f"{county.county}, {county.state}: {kept} segments")
    CANALS_DIR.mkdir(parents=True, exist_ok=True)
    CANALS_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(CANALS_CSV, index=False)
    with open(CANALS_GEOJSON, "w") as f:
        json.dump({"type": "FeatureCollection", "features": map_lines}, f, separators=(",", ":"))


def run_canals(counties):
    """Build the "canals" block of metrics.json: km of mapped canal and ditch per county."""
    if not CANALS_CSV.exists():
        return {"source": SOURCE, "total_km": 0, "by_county": [], "named": [],
                "note": "The canal file was not downloaded, so there is nothing to report."}
    table = pd.read_csv(CANALS_CSV, dtype={"fips": str, "name": str}).fillna({"name": ""})
    names = counties.drop_duplicates("fips").set_index("fips")
    km = table.groupby("fips")["length_km"].sum()
    named = table[table["name"] != ""]
    named_km = named.groupby("fips")["length_km"].sum()
    longest = named.groupby("name")["length_km"].sum().sort_values(ascending=False).head(15)
    return {
        "source": SOURCE,
        "total_km": round(float(table["length_km"].sum()), 1),
        "segments": len(table),
        # every Rio Grande county, most canal km first
        "by_county": sorted([{"fips": fips, "county": names.loc[fips, "county"], "state": names.loc[fips, "state"],
                              "canal_km": round(float(km.get(fips, 0)), 1),
                              "named_km": round(float(named_km.get(fips, 0)), 1)} for fips in names.index],
                            key=lambda entry: -entry["canal_km"]),
        "named": [{"name": name, "km": round(float(value), 1)} for name, value in longest.items()],
        "map_file": "data/processed/canals.geojson",
        "checked_against": "OpenStreetMap canal, ditch and drain lines, for two counties: Cameron 2,640 km against "
                           "2,750 km here, Alamosa 767 km against 724 km here. OpenStreetMap partly copies the same "
                           "USGS data, so this is a sanity check, not independent proof.",
        "note": "Mapped canal and ditch lines whose middle point lies inside the county. The map does not separate "
                "irrigation canals from drainage ditches, and does not say whether a canal is lined, how much it "
                "leaks or which district owns it. Most segments have no name. This shows where canals are, not "
                "which ones to seal.",
    }


if __name__ == "__main__":
    from farmdrought.drought import build_panel

    panel = build_panel()
    counties = panel.loc[panel["river"] == FOCUS_RIVER, ["fips", "county", "state"]].drop_duplicates()
    if sys.argv[1:] == ["download"]:
        download_canals(counties)
    result = run_canals(counties)
    print(result["note"], "\n\nTotal:", result["total_km"], "km in", result["segments"], "segments\n")
    print(pd.DataFrame(result["by_county"]).to_string(index=False), "\n")
    print(pd.DataFrame(result["named"]).to_string(index=False))
