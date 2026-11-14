"""counties.py: work out which counties lie along each of the five rivers.

Steps:
  1. Read each river's line from the map file and turn it into a list of points.
  2. Read each county's shape and take its center.
  3. Measure the distance from every county center to every river.
A county is "along a river" if its center is within 50 km of that river (config.BUFFER_KM).
"""
import json

import numpy as np

from farmdrought.config import COUNTIES_GEOJSON, RIVERS, RIVERS_GEOJSON


def load_river_points(path=RIVERS_GEOJSON):
    """Return {river name: array of (lon, lat) points along that river}."""
    with open(path) as f:
        features = json.load(f)["features"]
    points = {name: [] for name in RIVERS}
    for feature in features:
        name = feature["properties"].get("name")
        if name not in points:
            continue  # not one of our five rivers
        geometry = feature["geometry"]
        # A river is stored as one line or as several lines. Treat both as a list of lines.
        lines = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
        for line in lines:
            for i, (lon, lat) in enumerate(line):
                # Keep only points inside the lower 48 states. Other countries have rivers
                # with the same names. Latitude 25 drops Argentina's "Colorado".
                if lat < 25 or lon < -125 or lon > -66:
                    continue
                points[name].append((lon, lat))
                # The file stores long straight stretches as just two far-apart points.
                # Add extra points about every 0.1 degree so no stretch of river is skipped.
                if i + 1 < len(line):
                    lon2, lat2 = line[i + 1]
                    steps = int(max(abs(lon2 - lon), abs(lat2 - lat)) / 0.1)
                    for k in range(1, steps):
                        points[name].append((lon + (lon2 - lon) * k / steps, lat + (lat2 - lat) * k / steps))
    return {name: np.array(pts) for name, pts in points.items()}


def load_county_centers(path=COUNTIES_GEOJSON):
    """Return {county FIPS code: (lon, lat) of the county's center}."""
    with open(path) as f:
        features = json.load(f)["features"]
    centers = {}
    for feature in features:
        geometry = feature["geometry"]
        # A county is one polygon, or several (for example a county with islands)
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        # The center is the average of the corner points on each polygon's outer edge
        corners = np.array([point for polygon in polygons for point in polygon[0]])
        centers[feature["id"]] = (corners[:, 0].mean(), corners[:, 1].mean())
    return centers


def km(lon1, lat1, lon2, lat2):
    """Distance in km between points on the Earth (the haversine formula).

    Works on single numbers or numpy arrays. 12742 is the Earth's diameter in km.
    """
    rad = np.pi / 180  # degrees to radians
    a = (np.sin((lat2 - lat1) * rad / 2) ** 2
         + np.cos(lat1 * rad) * np.cos(lat2 * rad) * np.sin((lon2 - lon1) * rad / 2) ** 2)
    return 12742 * np.arcsin(np.sqrt(a))


def nearest_river(lon, lat, river_points):
    """For each county center, return (name of the nearest river, distance to it in km)."""
    names = list(river_points)
    # distance[r, c] = distance from county c to the closest point on river r
    distance = np.array([[km(lon[c], lat[c], pts[:, 0], pts[:, 1]).min() for c in range(len(lon))]
                         for pts in river_points.values()])
    nearest = distance.argmin(axis=0)
    return np.array(names)[nearest], distance.min(axis=0)
