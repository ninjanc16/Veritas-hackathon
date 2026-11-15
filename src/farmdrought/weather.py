"""weather.py: county rainfall and temperature as extra inputs (set W). Used by version 2 only.

Idea: the drought map is drawn AFTER the weather happens. So a dry, hot spell may show up in
the rainfall and temperature record before the map changes class.

Source: NOAA's county climate record (nClimDiv), one value per county per month since 1895.
https://www.ncei.noaa.gov/pub/data/cirs/climdiv/  (public, no key)

Five numbers per county per forecast date:
  rain3, rain6, rain12 : rain over the last 3, 6 and 12 months, divided by what is normal for
                         those same calendar months. 1.0 = normal, 0.5 = half the normal rain.
  heat3, heat12        : average temperature over the last 3 and 12 months, minus normal (deg F).
"Normal" is the county's own 1901 to 1999 average. That period ends before our drought record
starts (2000), so "normal" never contains a training or test year.

LEAKAGE RULE: NOAA publishes a month's value about a week into the NEXT month. A forecast made
in month M therefore only uses months up to M-2. Example: a forecast on March 3 uses data
through January, because February's value may not be out yet.

Download the data with:  PYTHONPATH=src python -m farmdrought.weather
"""
import re

import pandas as pd
import requests

from farmdrought.config import FOCUS_RIVER, RAW

FEATURES_W = ["rain3", "rain6", "rain12", "heat3", "heat12"]
NOAA_DIR = "https://www.ncei.noaa.gov/pub/data/cirs/climdiv/"
WEATHER_CSV = RAW / "weather" / "climate_rio_grande.csv"  # the 31 Rio Grande counties only
NORMAL_YEARS = (1901, 1999)   # the years that define "normal"
PUBLISH_LAG_MONTHS = 2        # a forecast in month M uses months up to M-2 (see the rule above)

# NOAA numbers the states its own way (alphabetical), not with the usual FIPS state codes.
# Only the three Rio Grande states are needed.  FIPS state code -> NOAA state code
NOAA_STATE = {"08": "05",   # Colorado
              "35": "29",   # New Mexico
              "48": "41"}   # Texas


def download_weather(fips_list):
    """Download NOAA's two county files (rain and temperature) and keep our counties.

    Each line of a NOAA file is one county and one year:
        characters 1-2 state, 3-5 county, 6-7 what is measured, 8-11 year, then 12 monthly values.
    A value of -9.99 (rain) or -99.9 (temperature) means "not published yet".
    """
    listing = requests.get(NOAA_DIR, headers={"User-Agent": "Mozilla/5.0"}, timeout=120).text
    # our county codes written NOAA's way, mapped back to the usual FIPS code
    wanted = {NOAA_STATE[f[:2]] + f[2:]: f for f in fips_list}
    tables = {}
    for column, code in [("rain_in", "pcpncy"), ("temp_f", "tmpccy")]:
        # the file name ends with the date it was published, so look the name up in the listing
        name = sorted(set(re.findall(rf"climdiv-{code}-v[0-9.]+-[0-9]+", listing)))[-1]
        text = requests.get(NOAA_DIR + name, headers={"User-Agent": "Mozilla/5.0"}, timeout=600).text
        rows = []
        for line in text.splitlines():
            if line[:5] in wanted:
                year = int(line[7:11])
                for month, value in enumerate(line[11:].split(), start=1):
                    if float(value) > -9:  # skip "not published yet"
                        rows.append((wanted[line[:5]], year, month, float(value)))
        tables[column] = pd.DataFrame(rows, columns=["fips", "year", "month", column])
        print(f"{name}: {len(rows)} county-months")
    both = tables["rain_in"].merge(tables["temp_f"], on=["fips", "year", "month"])
    WEATHER_CSV.parent.mkdir(parents=True, exist_ok=True)
    both.sort_values(["fips", "year", "month"]).to_csv(WEATHER_CSV, index=False)
    print(f"saved {both['fips'].nunique()} counties, {both['year'].min()} to {both['year'].max()}")


def monthly_features():
    """Build the five numbers for every county and month. The row for month m describes the
    months UP TO AND INCLUDING m. The publication lag is applied later, in add_weather_features.
    """
    data = pd.read_csv(WEATHER_CSV, dtype={"fips": str})
    data["period"] = pd.PeriodIndex.from_fields(year=data["year"], month=data["month"], freq="M")
    out = []
    for fips, county in data.groupby("fips"):
        county = county.sort_values("period").set_index("period")
        # "normal" for each calendar month (January, February, ...), from 1901-1999 only
        old = county[county["year"].between(*NORMAL_YEARS)].groupby("month")[["rain_in", "temp_f"]].mean()
        normal_rain = county["month"].map(old["rain_in"])
        normal_temp = county["month"].map(old["temp_f"])
        feats = pd.DataFrame({"fips": fips}, index=county.index)
        for k in (3, 6, 12):
            # rain in the last k months / normal rain for those same k calendar months
            feats[f"rain{k}"] = county["rain_in"].rolling(k).sum() / normal_rain.rolling(k).sum()
        for k in (3, 12):
            # average of (temperature - normal) over the last k months
            feats[f"heat{k}"] = (county["temp_f"] - normal_temp).rolling(k).mean()
        out.append(feats.reset_index())
    return pd.concat(out, ignore_index=True)


def add_weather_features(table):
    """Add set W to any table that has "fips" and "date" columns.

    A row dated in month M gets the numbers for month M-2 (the publication lag).
    Counties that are not in the weather file (the other four rivers) get NaN.
    """
    feats = monthly_features()
    table = table.copy()
    table["period"] = table["date"].dt.to_period("M") - PUBLISH_LAG_MONTHS
    table = table.merge(feats, on=["fips", "period"], how="left")
    return table.drop(columns="period")


if __name__ == "__main__":
    from farmdrought.drought import build_panel
    panel = build_panel()
    download_weather(sorted(panel.loc[panel["river"] == FOCUS_RIVER, "fips"].unique()))
    # show the newest row of one county, so the numbers can be eyeballed
    print(add_weather_features(panel[panel["river"] == FOCUS_RIVER]).iloc[-1][["fips", "date"] + FEATURES_W])
