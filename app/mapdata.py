"""
mapdata.py - reads the small river-lines file the app keeps for the map (app/map_data/rivers.json).
Made by app/make_river_lines.py from the public Natural Earth river map.
"""
import json

from app.contract import REPO_ROOT

RIVERS_FILE = REPO_ROOT / "app" / "map_data" / "rivers.json"
CANALS_FILE = REPO_ROOT / "data" / "processed" / "canals.geojson"   # the pipeline's canal lines (read only)


def load_river_line(river):
    """
    The river as one list of (lat, lon) pieces, e.g. [[(lat, lon), ...], [...]].
    Returns [] if the file or the river is missing: the map simply draws without the line.
    """
    try:
        data = json.loads(RIVERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data.get(river, [])


def load_canals(path=CANALS_FILE):
    """
    Read the pipeline's canal lines (a GeoJSON file, one LineString per canal segment) and group
    them by county: {fips: [segment, ...]}. Each segment is a dict with name, soil, seepage_rate,
    level, score, length_km and line = [(lat, lon), ...]. GeoJSON stores (lon, lat), so we flip.
    Returns {} if the file is missing or not what we expect: the map then says "not available yet".
    This function only reads; it never writes the file.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        by_county = {}
        for f in data["features"]:
            if f["geometry"]["type"] != "LineString":
                continue
            prop = f["properties"]
            seg = dict(name=prop.get("name") or "", soil=prop.get("soil") or "", level=prop["level"],
                       seepage_rate=prop.get("seepage_rate"), score=prop.get("score"),
                       length_km=prop.get("length_km"),
                       line=[(lat, lon) for lon, lat in f["geometry"]["coordinates"]])
            by_county.setdefault(prop["fips"], []).append(seg)
        return by_county
    except (OSError, ValueError, KeyError, TypeError):
        return {}
