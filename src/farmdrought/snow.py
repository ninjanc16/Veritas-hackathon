"""snow.py: mountain snowpack as an extra input for the outlooks (tested as an ablation only).

Idea: the Rio Grande is fed by snow melting in the mountains of Colorado and New Mexico.
A thin winter snowpack means less snowmelt and less river water the following summer.

The measure is "snow water equivalent" (SWE): how many inches of water the snowpack would
give if it all melted. It comes from SNOTEL, the USDA's automated mountain snow stations.

Two numbers per forecast date, the same for every Rio Grande county:
  swe_now  : average SWE over the last 30 days, as a percentile
  swe_peak : the highest SWE in the last 365 days (the last winter's peak, which is the
             snowmelt supply), as a percentile
Percentiles compare each date only with EARLIER years (see flow.past_percentile).

Download the data with:  PYTHONPATH=src python -m farmdrought.snow
"""
import pandas as pd
import requests

from farmdrought.config import FOCUS_RIVER, RAW
from farmdrought.flow import START, past_percentile

FEATURES_S = ["swe_now", "swe_peak"]
API = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"  # USDA snow and water data service
SNOW_CSV = RAW / "snow_swe.csv"
STATION_LIST = RAW / "snow_stations.csv"


def download_snow():
    """Download daily SWE for the SNOTEL stations in the upper Rio Grande basin.

    Stations are picked by a fixed rule, not by hand:
      - in hydrologic unit 1301 or 1302 (Rio Grande headwaters and upper Rio Grande), and
      - recording since before 1990, so the same stations cover the whole period.
    """
    stations = requests.get(f"{API}/stations", params={"stationTriplets": "*:CO:SNTL,*:NM:SNTL", "activeOnly": "true"},
                            timeout=120).json()
    chosen = [s for s in stations if s["huc"][:4] in ("1301", "1302") and s["beginDate"] < START]
    pd.DataFrame(chosen)[["stationTriplet", "name", "huc", "latitude", "longitude", "elevation", "beginDate"]] \
        .to_csv(STATION_LIST, index=False)

    # WTEQ is the code for snow water equivalent, in inches
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    reply = requests.get(f"{API}/data", params={
        "stationTriplets": ",".join(s["stationTriplet"] for s in chosen),
        "elements": "WTEQ", "duration": "DAILY", "beginDate": START, "endDate": today}, timeout=300).json()
    # One column per station, one row per day
    columns = {station["stationTriplet"]: pd.Series({v["date"]: v.get("value") for v in station["data"][0]["values"]})
               for station in reply if station["data"]}
    swe = pd.DataFrame(columns).sort_index()
    swe.index.name = "date"
    swe.to_csv(SNOW_CSV)
    print(f"saved {swe.shape[1]} stations, {len(swe)} days, {swe.index[0]} to {swe.index[-1]}")


def add_snow_features(table):
    """Add swe_now and swe_peak to the Rio Grande rows. Rows on other rivers stay NaN."""
    swe = pd.read_csv(SNOW_CSV, index_col="date", parse_dates=True)
    basin = swe.mean(axis=1)  # average over all stations that reported that day
    dates = pd.DatetimeIndex(sorted(table["date"].unique()))
    by_date = pd.DataFrame({"swe_now": past_percentile(basin, dates, 30, "mean"),
                            "swe_peak": past_percentile(basin, dates, 365, "max")}, index=dates)
    rg = table["river"] == FOCUS_RIVER
    for name in FEATURES_S:
        table[name] = table["date"].map(by_date[name]).where(rg)
    return table


if __name__ == "__main__":
    download_snow()
