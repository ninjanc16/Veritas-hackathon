"""reservoirs.py: how full the Rio Grande's big reservoirs are, as extra model inputs (set R).

WHY: farmers in an irrigation district get their water from a reservoir, and the Drought
Monitor map does not show how full it is. So reservoir storage might tell the 6-month
outlook something the drought map cannot.

DATA: one CSV per lake from the Texas Water Development Board (waterdatafortexas.org),
downloaded on Nov 14, 2026 from
    https://www.waterdatafortexas.org/reservoirs/individual/<lake>.csv
Each file has one row per day. We use two columns:
    conservation_storage  = usable water in the lake (acre-feet)
    conservation_capacity = usable water when the lake is full (acre-feet)

Only 14 of the 31 Rio Grande counties are matched to a reservoir (see COUNTY_RESERVOIR in
config.py). That matching is our assumption.

Run it with:  PYTHONPATH=src python -m farmdrought.reservoirs
"""
import pandas as pd

from farmdrought.config import COUNTY_RESERVOIR, RESERVOIR_DIR, RESERVOIR_FILES, raw_path

# Set R: four reservoir inputs plus a flag saying whether the county has a reservoir at all
FEATURES_R = ["res_pct", "res_chg12", "res_chg52", "res_pctile", "has_res"]
START = "1990-01-01"  # same starting year as the flow and snow inputs
NO_RESERVOIR = -1.0   # value of the four inputs for a county with no reservoir


def load_reservoirs():
    """Return a daily table: one column per reservoir system, holding its percent full.

    For Amistad-Falcon the two lakes are added first: (storage A + storage F) divided by
    (capacity A + capacity F). A day missing in either lake is missing in the sum.
    Gaps of up to 14 days are filled with the last known value. Longer gaps stay empty.
    """
    systems = {}
    for name, files in RESERVOIR_FILES.items():
        # comment="#" skips the long disclaimer at the top of each file
        lakes = [pd.read_csv(raw_path(RESERVOIR_DIR / f), comment="#", index_col="date", parse_dates=True) for f in files]
        storage = sum(lake["conservation_storage"] for lake in lakes)
        capacity = sum(lake["conservation_capacity"] for lake in lakes)
        systems[name] = 100 * storage / capacity
    daily = pd.DataFrame(systems).loc[START:]
    return daily.asfreq("D").ffill(limit=14)  # asfreq("D") puts every calendar day in the index


def reservoir_features(pct, dates):
    """Build the four inputs of set R for one reservoir system.

    pct   : daily percent full (a Series indexed by day)
    dates : the forecast issue dates

    LEAKAGE RULE: every input uses only days ON OR BEFORE the issue date.
    """
    now = pct.reindex(dates)  # percent full on the issue date itself
    out = pd.DataFrame({
        "res_pct": now.values,
        # change over the past 12 weeks (84 days) and the past 52 weeks (364 days)
        "res_chg12": now.values - pct.reindex(dates - pd.Timedelta(weeks=12)).values,
        "res_chg52": now.values - pct.reindex(dates - pd.Timedelta(weeks=52)).values,
    }, index=dates)
    # res_pctile: how does today's level rank against the SAME calendar month in EARLIER
    # years? 0 = lower than every earlier year, 1 = higher than every earlier year.
    # Only earlier years are used, so nothing from the future (or the test year) leaks in.
    ranks = []
    for date, value in now.items():
        earlier = pct[(pct.index.month == date.month) & (pct.index.year < date.year)].dropna()
        ranks.append((earlier < value).mean())
    out["res_pctile"] = ranks
    return out


def add_reservoir_features(table):
    """Add set R to a table that has "fips" and "date" columns.

    Counties with no reservoir get has_res = 0 and -1 in the four inputs. A forest can split
    on that, so one model can serve counties with and without a reservoir.
    """
    table = table.copy()
    daily = load_reservoirs()
    dates = pd.DatetimeIndex(sorted(table["date"].unique()))
    system = table["fips"].map(COUNTY_RESERVOIR)  # empty for counties with no reservoir
    table["has_res"] = system.notna().astype(int)
    for name in FEATURES_R[:4]:
        table[name] = NO_RESERVOIR
    for name in daily.columns:
        feats = reservoir_features(daily[name], dates)
        rows = system == name
        for column in feats.columns:
            table.loc[rows, column] = table.loc[rows, "date"].map(feats[column])
    return table


def reservoir_summary():
    """Facts about the reservoir data for metrics.json."""
    daily = load_reservoirs()
    counties = pd.Series(COUNTY_RESERVOIR).value_counts()
    return [{"name": name, "counties": int(counties[name]),
             "first_date": str(daily[name].first_valid_index().date()),
             "last_date": str(daily[name].last_valid_index().date())} for name in daily.columns]


if __name__ == "__main__":
    daily = load_reservoirs()
    print(pd.DataFrame(reservoir_summary()).to_string(index=False))
    print("\nPercent full on the latest day:\n", daily.ffill().iloc[-1].round(1).to_string())
    print("\nEmpty days since 2000 (gaps longer than 14 days):\n", daily.loc["2000":].isna().sum().to_string())
