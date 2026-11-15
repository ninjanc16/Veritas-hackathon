"""
prob_calibration.py - is a forecast of "30%" right about 30% of the time?

ADDED in round 3 (ARCHITECTURE.md section 3.3). It changes no version 1 number.

A forest's output is only a rough probability. The trigger compares it with a threshold
(act when the chance is above the relative cost of acting), which assumes the number means
what it says. This file (1) adjusts a forecast using ONLY earlier years whose answers were
already known, (2) gives the fair simple rival, "how often did this drought class lead to a
yes before?", and (3) measures how well a probability matches what happened.

"The past" is always the same as in outlook.folds: rows whose answer window (issue date plus
`horizon` weeks) ended before 1 January of the year being handled. The year itself and every
later year are never used.

Note: this "calibration" is about forecast probabilities. seepage_calibration.py (canal
leakage) is a different thing with a similar name.
"""
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression


def _past_of(table, horizon, year):
    """Mask of rows whose answer window ended before 1 January of `year`."""
    window_end = table["date"] + pd.Timedelta(weeks=horizon)
    return window_end < pd.Timestamp(f"{year}-01-01")


def calibrate_by_past(table, p_column, label, horizon, min_years=3):
    """
    Adjust the probabilities in `p_column`, one calendar year at a time, using only the past.

    For each year Y in the table: take the past rows (window ended before 1 January Y) that
    have both a forecast and an answer, fit an isotonic regression of answer on forecast
    (a step curve that can only go up, kept between 0 and 1), and pass year Y's forecasts
    through it. Because the curve only goes up, the ORDER of the forecasts inside a year is
    kept (some may become equal), so a ranking is not changed by this.

    If those past rows cover fewer than `min_years` different calendar years (of issue date),
    year Y's forecasts are returned unchanged. A missing forecast stays missing.
    Returns a Series with the same index as `table`.
    """
    out = table[p_column].astype(float).copy()
    usable = table[p_column].notna() & table[label].notna()
    years = table["date"].dt.year
    for year in sorted(years.unique()):
        past = usable & _past_of(table, horizon, year)
        if years[past].nunique() < min_years:
            continue
        curve = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        curve.fit(table.loc[past, p_column].to_numpy(dtype=float), table.loc[past, label].to_numpy(dtype=float))
        rows = (years == year) & table[p_column].notna()
        out[rows] = curve.predict(table.loc[rows, p_column].to_numpy(dtype=float))
    return out


def class_frequency_by_past(table, label, horizon, class_column="cls"):
    """
    The simple probabilistic rule: P(yes | the county's drought class today), from the past.

    For each year Y in the table, every row of Y gets the share of past rows (window ended
    before 1 January Y, answer known) in the SAME class that had answer 1. A class never seen
    in the past gets the overall past rate. If there are no past rows at all the value is
    missing (NaN). Returns a Series with the same index as `table`.
    """
    out = pd.Series(np.nan, index=table.index)
    years = table["date"].dt.year
    for year in sorted(years.unique()):
        past = table[table[label].notna() & _past_of(table, horizon, year)]
        if past.empty:
            continue
        by_class = past.groupby(class_column)[label].mean()
        rows = years == year
        out[rows] = table.loc[rows, class_column].map(by_class).fillna(float(past[label].mean()))
    return out


def _known_pairs(y, p):
    """The answers and forecasts as float arrays, keeping only rows where both are present."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    known = ~np.isnan(y) & ~np.isnan(p)
    return y[known], p[known]


def reliability(y, p, bins=10):
    """
    Reliability table: cut 0..1 into `bins` equal slices and, for the forecasts in each slice,
    compare their average (mean_p) with how often the answer was yes (observed).

    A slice holds forecasts from bin_low up to but not including bin_high; the last slice also
    holds 1.0. An empty slice is listed with n 0 and None for the two averages. Rows with a
    missing answer or forecast are left out. Well calibrated means observed is close to mean_p.
    """
    y, p = _known_pairs(y, p)
    if ((p < 0) | (p > 1)).any():
        raise ValueError("a probability must be between 0 and 1")
    which = np.minimum(np.floor(p * bins).astype(int), bins - 1)   # p = 1.0 goes in the last slice
    table = []
    for i in range(bins):
        inside = which == i
        n = int(inside.sum())
        table.append({"bin_low": i / bins, "bin_high": (i + 1) / bins, "n": n,
                      "mean_p": float(p[inside].mean()) if n else None,
                      "observed": float(y[inside].mean()) if n else None})
    return table


def brier(y, p):
    """
    Brier score: the average squared gap between the probability and what happened (1 or 0).
    Lower is better. 0 is perfect; always saying 0.5 scores 0.25. Rows with a missing answer or
    forecast are left out.
    """
    y, p = _known_pairs(y, p)
    return float(((p - y) ** 2).mean())
