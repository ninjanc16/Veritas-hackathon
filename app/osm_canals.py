"""osm_canals.py: a second canal source, OpenStreetMap, to add detail the USGS map lacks.

The pipeline's canals come from the USGS National Hydrography Dataset. It is the official
map, but it calls everything "Canal/Ditch" and names very few. OpenStreetMap (a public,
volunteer-made map) knows three things the USGS file does not:

  - the KIND of each line: irrigation canal, drainage ditch, or drain
  - whether a stretch runs in a PIPE or culvert (a pipe does not seep, so sealing it is wasted money)
  - many more canal NAMES, and some canals the USGS file misses

This script downloads the OpenStreetMap lines for the three canal areas on the Texas reach
of the Rio Grande and saves a small file. app/build_site.py then uses it to (1) label the
USGS canals and (2) add the canals only OpenStreetMap has.

What it cannot do: say whether a canal is lined, or how much it leaks. Nobody publishes that.

Run it with:   python -m app.osm_canals        (needs the internet; takes a minute or two)
Output:        app/data/osm_canals.json
"""
import json
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "data" / "osm_canals.json"
# Overpass is OpenStreetMap's public query service. Several hosts run it; we try each in turn.
HOSTS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass-api.de/api/interpreter",
         "https://overpass.private.coffee/api/interpreter"]
# The three canal areas as (south, west, north, east): Lower Valley, El Paso Valley, Eagle Pass.
BOXES = [(25.8, -99.3, 26.8, -97.1), (31.0, -106.7, 32.1, -105.2), (28.3, -100.9, 29.0, -100.1)]
KINDS = "canal|ditch|drain"


def download():
    """Ask for every canal, ditch and drain line in the three boxes."""
    parts = "".join(f'way["waterway"~"^({KINDS})$"]({s},{w},{n},{e});' for s, w, n, e in BOXES)
    query = f"[out:json][timeout:150];({parts});out tags geom;"
    for host in HOSTS:
        try:
            reply = requests.post(host, data={"data": query}, timeout=200,
                                  headers={"User-Agent": "canal-map-student-project/1.0", "Accept": "*/*"})
            if reply.ok and reply.text.lstrip().startswith("{"):
                return reply.json()["elements"]
        except requests.RequestException:
            pass                                  # try the next host
    raise RuntimeError("no OpenStreetMap host answered; try again later")


def main():
    ways = []
    for element in download():
        tags = element["tags"]
        ways.append({
            "id": element["id"], "kind": tags["waterway"], "name": tags.get("name", ""),
            "piped": "tunnel" in tags,            # tunnel = the water runs underground (pipe or culvert)
            "line": [[round(p["lon"], 5), round(p["lat"], 5)] for p in element["geometry"]],
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "OpenStreetMap contributors, via the Overpass API (ODbL licence)",
                               "ways": ways}, separators=(",", ":")), encoding="utf-8")
    print(f"saved {len(ways)} lines to {OUT}  ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
