"""forecast_pre2020.py: a forecast model that is FROZEN at the end of 2019.

WHY: the simulation should be honest about what it knew and when. This script trains the
same 6-month random forest the pipeline uses (same inputs, same settings), but only on
answers that were fully known before January 1, 2020. Then it does two things:

  1. TEST   predicts every month from 2020 on, years the model never saw, and counts how
            often its warnings were right.
  2. LIVE   predicts this week, from the newest Drought Monitor and El Nino data the daily
            refresh downloaded. The model is old; the data it reads is new.

It imports the pipeline's own functions and writes one small file. It changes nothing in
the pipeline.

Run it with:   PYTHONPATH=src python -m app.forecast_pre2020     (takes about a minute;
               needs scikit-learn, so use the pipeline's Python environment)
Output:        app/data/pre2020.json
"""
import json
from pathlib import Path

import pandas as pd

from farmdrought.alert import run_alert
from farmdrought.config import FOCUS_RIVER, SEASON_THRESHOLD, SEASON_WEEKS
from farmdrought.outlook import FEATURES_SEASON, issue_rows, make_classifier

CUTOFF = pd.Timestamp("2020-01-01")     # nothing whose answer came after this date is used for training
OUT = Path(__file__).resolve().parent / "data" / "pre2020.json"
D1 = 2                                  # drought classes: 0 none, 1 D0, 2 D1, 3 D2, 4 D3, 5 D4


def tally(warned, happened):
    """Count hits and misses for a yes/no warning against what really happened."""
    caught = int((warned & happened).sum())
    return {
        "rows": int(len(happened)), "warnings": int(warned.sum()), "droughtSeasons": int(happened.sum()), "caught": caught,
        "missed": int((~warned & happened).sum()), "falseAlarms": int((warned & ~happened).sum()),
        "recall": round(caught / max(1, int(happened.sum())), 3),        # share of drought seasons caught
        "precision": round(caught / max(1, int(warned.sum())), 3),       # share of warnings that were right
    }


def main():
    panel, _ = run_alert()                                   # the pipeline's weekly table, all rivers
    monthly = issue_rows(panel)                              # one row per county per month
    river = monthly[monthly["river"] == FOCUS_RIVER]

    # Train only on rows whose 26-week answer window had closed before the cut-off.
    window_end = river["date"] + pd.Timedelta(weeks=SEASON_WEEKS)
    train = river[river["y_season"].notna() & (window_end < CUTOFF)]
    model = make_classifier().fit(train[FEATURES_SEASON], train["y_season"])

    # 1. TEST on the Texas river counties, 2020 on, wherever the answer is already known.
    texas = river[(river["state"] == "Texas") & (river["date"] >= CUTOFF)].copy()
    texas["p"] = model.predict_proba(texas[FEATURES_SEASON])[:, 1]
    known = texas[texas["y_season"].notna()]
    happened = known["y_season"] == 1
    pre_season = known["date"].dt.month.isin([1, 2, 3])      # the months a sealing decision is made
    test = {
        "allMonths": {"forecast": tally(known["p"] >= SEASON_THRESHOLD, happened),
                      "d1Rule": tally(known["cls"] >= D1, happened)},
        "preSeason": {"forecast": tally(known.loc[pre_season, "p"] >= SEASON_THRESHOLD, happened[pre_season]),
                      "d1Rule": tally(known.loc[pre_season, "cls"] >= D1, happened[pre_season])},
        "from": str(known["date"].min().date()), "to": str(known["date"].max().date()),
    }

    # 2. LIVE: this week's rows, read by the frozen model.
    now = panel[(panel["date"] == panel["date"].max()) & (panel["river"] == FOCUS_RIVER) & (panel["state"] == "Texas")]
    live = {r.fips: round(float(p), 3) for r, p in zip(now.itertuples(), model.predict_proba(now[FEATURES_SEASON])[:, 1])}

    out = {
        "cutoff": str(CUTOFF.date()),
        "trainedOn": {"rows": len(train), "from": str(train["date"].min().date()), "to": str(train["date"].max().date())},
        "threshold": SEASON_THRESHOLD,
        "test": test,
        "liveWeek": str(panel["date"].max().date()),
        "live": live,
        # every monthly forecast from 2020 on: {county: [[date, chance, what happened (1/0/None)], ...]}
        "monthly": {fips: [[str(r.date.date()), round(float(r.p), 2), None if pd.isna(r.y_season) else int(r.y_season)]
                           for r in rows.itertuples()] for fips, rows in texas.groupby("fips")},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"trained on {len(train)} rows up to {out['trainedOn']['to']}")
    print("test, pre-season months:", json.dumps(test["preSeason"]))
    print("live week", out["liveWeek"], live)


if __name__ == "__main__":
    main()
