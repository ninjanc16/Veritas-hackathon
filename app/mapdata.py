"""
mapdata.py - reads the small river-lines file the app keeps for the map (app/map_data/rivers.json).
Made by app/make_river_lines.py from the public Natural Earth river map.
"""
import json

from app.contract import REPO_ROOT

RIVERS_FILE = REPO_ROOT / "app" / "map_data" / "rivers.json"


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
