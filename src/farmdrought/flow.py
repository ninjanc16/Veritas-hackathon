"""flow.py: river flow as an extra input for the outlooks (tested as an ablation only).

Idea: how much water is in the Rio Grande today might tell us about drought months ahead.

For each gauge and each forecast date we compute two numbers:
  flow90  : average flow over the last 90 days, as a percentile
  flow365 : average flow over the last 365 days, as a percentile
"Percentile" = the share of EARLIER years in which the same calendar window had less
flow. 0.10 means the river is lower than in 9 of 10 earlier years.

LEAKAGE RULE: the percentile compares a date only with years BEFORE it, never after.

Download the data with:  PYTHONPATH=src python -m farmdrought.flow
"""
import numpy as np
import pandas as pd

from farmdrought.config import FOCUS_RIVER, GAUGES, RAW
from farmdrought.counties import km

FEATURES_F = ["flow90", "flow365"]
START = "1990-01-01"  # ten years before the drought record, so early percentiles have years to compare with
GAUGE_LIST = RAW / "flow_gauges.csv"


def download_flow():
    """Download daily mean flow for each gauge from the USGS and save one CSV per gauge.

    A gauge that fails twice or has no data is dropped and reported. We never guess another gauge.
    """
    from dataretrieval import waterdata  # imported here so the rest of the pipeline runs without it

    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    kept = []
    for name, gauge_id in GAUGES.items():
        data = None
        for attempt in (1, 2):  # try, then retry once
            try:
                # 00060 = river flow (discharge). 00003 = daily mean.
                data, _ = waterdata.get_daily(monitoring_location_id=gauge_id, parameter_code="00060",
                                              statistic_id="00003", time=f"{START}/{today}")
                break
            except Exception as error:
                print(f"{gauge_id} attempt {attempt} failed: {error}")
        if data is None or len(data) == 0:
            print(f"DROPPED {gauge_id} ({name}): the USGS returned no daily flow data")
            continue
        data = data.sort_values("time")
        data[["time", "value"]].to_csv(RAW / f"flow_{gauge_id}.csv", index=False)
        lon, lat = data["geometry"].iloc[0]  # the gauge's location comes with the data
        kept.append({"gauge_id": gauge_id, "name": name, "lon": lon, "lat": lat,
                     "first_day": data["time"].min().date(), "last_day": data["time"].max().date()})
        print(f"saved {gauge_id} ({name}): {len(data)} days, to {kept[-1]['last_day']}")
    pd.DataFrame(kept).to_csv(GAUGE_LIST, index=False)


def past_percentile(daily, dates, days, how="mean"):
    """For each date: summarize the last `days` days, then rank that against the same
    calendar window in every EARLIER year.

    daily : one value per day, indexed by date
    how   : "mean" (average over the window) or "max" (highest value in the window)
    Returns one number per date between 0 and 1, or NaN if there is too little data.
    """
    daily = daily.asfreq("D")  # one row per calendar day. Missing days become NaN.
    window = daily.rolling(days, min_periods=int(days * 0.8))  # allow a few missing days
    summary = window.mean() if how == "mean" else window.max()
    first_year = daily.index[0].year
    out = []
    for date in dates:
        now = summary.get(date, np.nan)
        # The same window, 1 year earlier, 2 years earlier, ... back to the start of the record
        earlier = [summary.get(date - pd.DateOffset(years=k), np.nan) for k in range(1, date.year - first_year + 1)]
        earlier = np.array([v for v in earlier if not np.isnan(v)])
        if np.isnan(now) or len(earlier) < 5:
            out.append(np.nan)  # not enough history to rank against
        else:
            out.append((earlier <= now).mean())
    return np.array(out)


def add_flow_features(table):
    """Add flow90 and flow365 to the Rio Grande rows. Each county uses its nearest gauge.

    Rows on other rivers, and dates where the gauge has no data, are left as NaN.
    """
    gauges = pd.read_csv(GAUGE_LIST)
    dates = pd.DatetimeIndex(sorted(table["date"].unique()))

    # 1. The two percentiles for every gauge and forecast date
    per_gauge = {}
    for gauge_id in gauges["gauge_id"]:
        daily = pd.read_csv(RAW / f"flow_{gauge_id}.csv", parse_dates=["time"]).set_index("time")["value"]
        per_gauge[gauge_id] = pd.DataFrame({"flow90": past_percentile(daily, dates, 90),
                                            "flow365": past_percentile(daily, dates, 365)}, index=dates)

    # 2. Give each Rio Grande county the values of its nearest gauge
    table[FEATURES_F] = np.nan
    rg = table[table["river"] == FOCUS_RIVER]
    for fips, county in rg.groupby("fips"):
        distance = km(county["lon"].iloc[0], county["lat"].iloc[0], gauges["lon"].values, gauges["lat"].values)
        nearest = gauges["gauge_id"].iloc[int(np.argmin(distance))]
        table.loc[county.index, FEATURES_F] = per_gauge[nearest].loc[county["date"]].values
    return table


if __name__ == "__main__":
    download_flow()
