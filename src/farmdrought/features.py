"""features.py: the model's inputs.

Set H ("history") has 24 inputs. All of them come from the drought map itself:
the county's own past, its neighbors, and the time of year.

LEAKAGE RULE: an input for week t may only use data from week t or earlier.
Every helper below only looks backwards, and tests/pipeline/test_features.py checks it.

All arrays here have shape (counties, weeks). Classes are 0 (no drought) to 5 (D4).
"""
import numpy as np
import pandas as pd

from farmdrought.config import D2_CLASS

# The 24 inputs of set H, in a fixed order.
# There is NO latitude or longitude, so a model trained on one river can be used on another.
FEATURES_H = [
    "cls", "l1", "l2", "l4", "l8", "l12", "l26", "l52",   # class now and 1 to 52 weeks ago
    "chg4", "chg8",                                       # change over the last 4 and 8 weeks
    "max12", "max26", "max52",                            # worst class in the last 12/26/52 weeks
    "mean12", "mean26",                                   # average class in the last 12/26 weeks
    "run", "since_d2",                                    # weeks at this class; weeks since last D2
    "nb_mean", "nb_max", "nb_d2", "nb_chg4", "nb_minus_self",  # neighbors within 150 km
    "sin", "cos",                                         # time of year
]


def lag(m, k):
    """The value k weeks earlier. The first k weeks have no earlier value, so they are NaN."""
    out = np.full(m.shape, np.nan)
    out[:, k:] = m[:, :-k]
    return out


def rolling(m, k, how):
    """Max or mean over the last k weeks, counting the current week. NaN until k weeks exist."""
    window = pd.DataFrame(m.T).rolling(k, min_periods=k)  # pandas rolls down rows, so flip
    return (window.max() if how == "max" else window.mean()).values.T


def history_features(classes, all_classes, neighbors, dates):
    """Build set H. Returns {input name: array of shape (counties, weeks)}.

    classes     : drought class for the river counties
    all_classes : drought class for EVERY county (drought can spread in from anywhere)
    neighbors   : for each river county, the row numbers in all_classes of counties within 150 km
    dates       : the map date of each week
    """
    c = classes.astype(float)
    n_weeks = c.shape[1]

    # --- weeks in a row at the current class, and weeks since the county was last in D2 ---
    run = np.ones_like(c)
    since_d2 = np.where(c[:, :1] >= D2_CLASS, 0.0, 104.0) * np.ones_like(c)
    for t in range(1, n_weeks):
        run[:, t] = np.where(c[:, t] == c[:, t - 1], run[:, t - 1] + 1, 1)
        # Capped at 104 weeks: "2 years or more" is all treated the same
        since_d2[:, t] = np.where(c[:, t] >= D2_CLASS, 0, np.minimum(since_d2[:, t - 1] + 1, 104))

    # --- neighbors: average class, worst class, and share of neighbors in D2 ---
    nb_mean = np.stack([all_classes[rows].mean(axis=0) for rows in neighbors])
    nb_max = np.stack([all_classes[rows].max(axis=0) for rows in neighbors])
    nb_d2 = np.stack([(all_classes[rows] >= D2_CLASS).mean(axis=0) for rows in neighbors])

    # --- time of year as a point on a circle, so week 52 sits next to week 1 ---
    week_of_year = pd.DatetimeIndex(dates).isocalendar().week.to_numpy().astype(float)
    season = np.ones_like(c) * (2 * np.pi * week_of_year / 52)  # same value for every county

    return {
        "cls": c,
        "l1": lag(c, 1), "l2": lag(c, 2), "l4": lag(c, 4), "l8": lag(c, 8),
        "l12": lag(c, 12), "l26": lag(c, 26), "l52": lag(c, 52),
        "chg4": c - lag(c, 4), "chg8": c - lag(c, 8),
        "max12": rolling(c, 12, "max"), "max26": rolling(c, 26, "max"), "max52": rolling(c, 52, "max"),
        "mean12": rolling(c, 12, "mean"), "mean26": rolling(c, 26, "mean"),
        "run": run, "since_d2": since_d2,
        "nb_mean": nb_mean, "nb_max": nb_max, "nb_d2": nb_d2,
        "nb_chg4": nb_mean - lag(nb_mean, 4),   # are the neighbors getting worse?
        "nb_minus_self": nb_mean - c,           # are the neighbors drier than this county?
        "sin": np.sin(season), "cos": np.cos(season),
    }


# ======================= Extra inputs for the 6- and 12-month outlooks =======================

# Set L ("long memory"): how drought-prone has this county been over the last few years?
FEATURES_L = ["share52", "share104", "share156", "share_all", "river_mean"]
# Set E (ENSO): the state of El Nino / La Nina in the Pacific, which shifts rain patterns
FEATURES_E = ["oni", "oni_chg3", "oni_mean12", "oni_min12", "oni_max12"]


def long_memory_features(classes, river):
    """Build set L. Returns {input name: array of shape (counties, weeks)}.

    classes : drought class for the river counties
    river   : the river each of those counties belongs to
    """
    in_d2 = (classes >= D2_CLASS).astype(float)
    n_weeks = classes.shape[1]
    # Share of the last 1, 2 and 3 years spent at D2 or worse
    feats = {f"share{k}": rolling(in_d2, k, "mean") for k in (52, 104, 156)}
    # Share of ALL weeks so far at D2 or worse (D2 weeks so far / weeks so far)
    feats["share_all"] = in_d2.cumsum(axis=1) / np.arange(1, n_weeks + 1)
    # Average class right now across all counties on the same river
    river_mean = np.zeros(classes.shape)
    for name in np.unique(river):
        river_mean[river == name] = classes[river == name].mean(axis=0)
    feats["river_mean"] = river_mean
    return feats


def load_oni(path):
    """Read NOAA's El Nino index. Returns a Series: month a season ENDED -> index value.

    Each line of the file is a year followed by up to 12 values, one per 3-month season:
    DJF (Dec-Jan-Feb, ends in February), JFM (ends in March), ... NDJ (ends next January).
    """
    values = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#"):
                continue  # the first line is a comment
            parts = line.split()
            year = int(parts[0])
            for i, value in enumerate(parts[1:]):
                # Season number i ends in month i+2. The last one (NDJ) ends in January next year.
                end = pd.Period(year=year, month=i + 2, freq="M") if i < 11 else pd.Period(year=year + 1, month=1, freq="M")
                values[end] = float(value)
    return pd.Series(values).sort_index()


def enso_features(dates, oni):
    """Build set E. Returns {input name: one value per week}. It is the same for every county.

    LEAKAGE RULE: a forecast issued in some month may only use seasons that ENDED
    before that month began.
    """
    rows = []
    for date in dates:
        known = oni[oni.index < pd.Period(date, "M")]  # seasons that ended before this month
        last12 = known.iloc[-12:]
        rows.append((known.iloc[-1],                    # latest value
                     known.iloc[-1] - known.iloc[-4],   # change over 3 seasons
                     last12.mean(), last12.min(), last12.max()))
    return dict(zip(FEATURES_E, np.array(rows).T))
