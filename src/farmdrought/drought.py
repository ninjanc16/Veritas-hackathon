"""drought.py: load the drought history and build the county-week panel.

The "panel" is one big table with one row per river county per week. Each row holds the
county's details, the 24 model inputs, and the truth we want to predict.

Classes: 0 none, 1 D0, 2 D1, 3 D2 (severe), 4 D3, 5 D4.
"""
import json

import numpy as np
import pandas as pd

from farmdrought.config import ALERT_WEEKS, BUFFER_KM, D2_CLASS, NEIGHBOR_KM, USDM_JSON
from farmdrought.counties import km, load_county_centers, load_river_points, nearest_river
from farmdrought.features import FEATURES_H, history_features


def load_usdm(path=USDM_JSON):
    """Read the U.S. Drought Monitor file.

    Returns a dict with:
      fips, county, state : one entry per county
      dates               : the map date of each week (weekly, Tuesdays)
      classes             : array (counties, weeks), the worst drought class in the county
                            that week. NaN where the county has no data.
    """
    with open(path) as f:
        raw = json.load(f)
    # Each county's history is one string with one character per week.
    # "0" to "5" is the drought class. "." means missing.
    classes = np.array([[np.nan if ch == "." else int(ch) for ch in series] for series in raw["series"]])
    return {
        "fips": raw["counties"],
        "county": raw["county_names"],
        "state": raw["state_names"],
        "dates": pd.date_range(raw["week0"], periods=raw["weeks"], freq="7D"),
        "classes": classes,
    }


def label_alert(classes, horizon=ALERT_WEEKS):
    """Truth for the 4-week alert: 1 if the county is at D2 or worse in ANY of the next
    `horizon` weeks, otherwise 0.

    The window starts at week t+1, so the current week is never part of its own answer.
    The last `horizon` weeks get NaN: their future has not happened yet.
    """
    n_counties, n_weeks = classes.shape
    y = np.full((n_counties, n_weeks), np.nan)
    for t in range(n_weeks - horizon):
        future = classes[:, t + 1 : t + 1 + horizon]  # weeks t+1 .. t+horizon
        y[:, t] = future.max(axis=1) >= D2_CLASS
    return y


def d2_streak(classes):
    """Weeks in a row at D2 or worse, counting the current week. 0 if not in D2 now."""
    in_d2 = classes >= D2_CLASS
    streak = np.zeros(classes.shape)
    streak[:, 0] = in_d2[:, 0]
    for t in range(1, classes.shape[1]):
        streak[:, t] = np.where(in_d2[:, t], streak[:, t - 1] + 1, 0)
    return streak


def build_panel():
    """Build the county-week table for the 436 river counties.

    Columns: date, fips, county, state, river, lat, lon, d2_streak, the 24 inputs
    (which include cls, the class now), and y (the 4-week truth, NaN if not known yet).
    Rows from each county's first year are dropped, because the inputs look back 52 weeks.
    """
    usdm = load_usdm()
    centers = load_county_centers()

    # 1. Keep counties that have a shape on the map and no missing weeks at all,
    #    so every county has the same full history.
    keep = [i for i, f in enumerate(usdm["fips"])
            if f in centers and not np.isnan(usdm["classes"][i]).any()]
    all_classes = usdm["classes"][keep]
    lon = np.array([centers[usdm["fips"][i]][0] for i in keep])
    lat = np.array([centers[usdm["fips"][i]][1] for i in keep])

    # 2. A river county is one whose center is within 50 km of one of the five rivers.
    river, distance = nearest_river(lon, lat, load_river_points())
    chosen = np.where(distance <= BUFFER_KM)[0]

    # 3. Neighbors of each river county: ALL counties within 150 km, except itself.
    neighbors = []
    for j in chosen:
        near = np.where(km(lon[j], lat[j], lon, lat) <= NEIGHBOR_KM)[0]
        neighbors.append(near[near != j])

    # 4. Inputs and truth, each as an array of shape (river counties, weeks).
    classes = all_classes[chosen]
    columns = history_features(classes, all_classes, neighbors, usdm["dates"])
    columns["d2_streak"] = d2_streak(classes)
    columns["y"] = label_alert(classes)

    # 5. Flatten to one row per county per week. ravel() lists county 1's weeks, then
    #    county 2's, and so on. So county details repeat and the dates tile.
    n_weeks = classes.shape[1]
    panel = pd.DataFrame({name: values.ravel() for name, values in columns.items()})
    for name, values in [("fips", usdm["fips"]), ("county", usdm["county"]), ("state", usdm["state"])]:
        panel[name] = np.repeat([values[keep[j]] for j in chosen], n_weeks)
    panel["river"] = np.repeat(river[chosen], n_weeks)
    panel["lat"] = np.repeat(lat[chosen], n_weeks)
    panel["lon"] = np.repeat(lon[chosen], n_weeks)
    panel["date"] = np.tile(usdm["dates"], len(chosen))

    # 6. Drop rows where an input is missing (the first 52 weeks of the record).
    #    Rows with a missing y are KEPT: they are the newest weeks, used for "latest".
    return panel.dropna(subset=FEATURES_H).reset_index(drop=True)
