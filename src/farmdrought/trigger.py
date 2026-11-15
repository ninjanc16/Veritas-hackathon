"""trigger.py: is the 6-month outlook a good PRE-SEASON trigger for sealing canals?

THE DECISION. Before the irrigation season (January to March) a district must decide:
seal and repair the leakiest canals this year, or not? Sealing pays off if a drought season
follows. So we ask: of the outlooks issued in January, February and March, how many
drought seasons did each rule catch, and how often did it fire for nothing?

A "drought season" is the 6-month truth already used elsewhere (y_season): 8 or more
weeks in a row at D2 or worse inside the next 26 weeks.

FIVE RULES ARE COMPARED:
  Our forecast                 : fire when p_season >= 0.25
  Our forecast with reservoirs : fire when p_season_res >= 0.25
  D1 or worse now              : fire when the county is in moderate drought or worse today
  D2 or worse now              : fire when the county is in severe drought today
  Seal every year              : always fire

Nothing here is trained. It only re-scores predictions that outlook.py already made.

Run it with:  PYTHONPATH=src python -m farmdrought.trigger
"""
import numpy as np
import pandas as pd

from farmdrought.config import (COST_RATIOS, COUNTY_RESERVOIR, D2_CLASS, FOCUS_RIVER, SEASON_THRESHOLD,
                                TRIGGER_MONTHS)
from farmdrought.config import SEASON_WEEKS
from farmdrought.prob_calibration import class_frequency_by_past


def score(name, y, fires):
    """Count what one rule did. y = 1 if a drought season followed, fires = True if the rule fired."""
    y, fires = np.asarray(y) == 1, np.asarray(fires, dtype=bool)
    caught = int((fires & y).sum())           # fired, and a drought season came
    missed = int((~fires & y).sum())          # did not fire, and a drought season came
    false_alarms = int((fires & ~y).sum())    # fired, and no drought season came
    return {
        "name": name, "fires": int(fires.sum()), "caught": caught, "missed": missed, "false_alarms": false_alarms,
        "recall": round(caught / max(caught + missed, 1), 3),       # share of drought seasons caught
        "precision": round(caught / max(int(fires.sum()), 1), 3),   # share of firings that were right
    }


def value(y, fires, cost_ratio):
    """Net value per row of acting on a rule.

    Each caught drought season is worth 1. Each firing costs cost_ratio (the cost of
    sealing, as a share of the loss it avoids). So value = (caught - cost_ratio x fires) / rows.
    Higher is better. "Never seal" scores 0.
    """
    y, fires = np.asarray(y) == 1, np.asarray(fires, dtype=bool)
    return round(float(((fires & y).sum() - cost_ratio * fires.sum()) / len(y)), 4)


def rules_table(rows):
    """Score the five rules on one group of rows."""
    y = rows["y_season"]
    return [
        score("Our forecast", y, rows["p_season"] >= SEASON_THRESHOLD),
        score("Our forecast with reservoirs", y, rows["p_season_res"] >= SEASON_THRESHOLD),
        score("D1 or worse now", y, rows["cls"] >= D2_CLASS - 1),
        score("D2 or worse now", y, rows["cls"] >= D2_CLASS),
        score("Seal every year", y, np.ones(len(rows), dtype=bool)),
    ]


def value_sweep(rows):
    """Value of each rule at each cost ratio.

    The two forecasts fire when their probability is at least the cost ratio (the break-even
    point: act when the chance of drought is bigger than the relative cost of acting).
    The three fixed rules fire the same way whatever the ratio.
    """
    y = rows["y_season"]
    return [{
        "cost_ratio": ratio,
        "forecast": value(y, rows["p_season"] >= max(ratio, 0.02), ratio),
        "forecast_reservoir": value(y, rows["p_season_res"] >= max(ratio, 0.02), ratio),
        "d1_rule": value(y, rows["cls"] >= D2_CLASS - 1, ratio),
        "persistence": value(y, rows["cls"] >= D2_CLASS, ratio),
        "seal_every_year": value(y, np.ones(len(rows), dtype=bool), ratio),
    } for ratio in COST_RATIOS]


def run_trigger(scored):
    """Build the "trigger" block of metrics.json from the scored outlook rows."""
    rows = scored[(scored["river"] == FOCUS_RIVER) & scored["date"].dt.month.isin(TRIGGER_MONTHS)]
    sweep = value_sweep(rows)
    at_threshold = next(line for line in sweep if line["cost_ratio"] == SEASON_THRESHOLD)
    # The same table for only the 14 counties that are matched to a reservoir
    with_reservoir = rows[rows["fips"].isin(COUNTY_RESERVOIR)]
    return {
        "issue_months": TRIGGER_MONTHS,
        "threshold": SEASON_THRESHOLD,
        "rows": len(rows),
        "drought_seasons": int(rows["y_season"].sum()),
        "rules": rules_table(rows),
        "value_sweep": sweep,
        # True only if the forecast is worth strictly more than the D1 rule at cost ratio 0.25
        "forecast_beats_d1_rule": bool(at_threshold["forecast"] > at_threshold["d1_rule"]),
        "reservoir_forecast_beats_d1_rule": bool(at_threshold["forecast_reservoir"] > at_threshold["d1_rule"]),
        # ---- extra, beyond the agreed keys ----
        "reservoir_counties_only": {
            "counties": int(with_reservoir["fips"].nunique()), "rows": len(with_reservoir),
            "drought_seasons": int(with_reservoir["y_season"].sum()),
            "rules": rules_table(with_reservoir), "value_sweep": value_sweep(with_reservoir),
        },
    }


def annual_rows(scored, month=3, history=None):
    """The rows the annual trigger test scores, and the class frequency for each of them.

    Returns (rows, frequency, in_history): the Rio Grande rows issued in `month` (exactly one
    per county per year, or an AssertionError), the class-conditional frequency of each row
    (NaN where there is none), and whether each row's county and date are in the history.
    See run_trigger_annual for `history`.
    """
    focus = scored[scored["river"] == FOCUS_RIVER]
    rows = focus[focus["date"].dt.month == month]
    county_years = int(pd.MultiIndex.from_arrays([rows["fips"], rows["date"].dt.year]).nunique())
    assert len(rows) == county_years, f"{len(rows)} rows but {county_years} county-years"

    past = focus if history is None else history[history["river"] == FOCUS_RIVER]
    keys = pd.MultiIndex.from_arrays([past["fips"], past["date"]])
    assert keys.is_unique, "the history holds a county and date twice"
    frequency_all = pd.Series(class_frequency_by_past(past, "y_season", SEASON_WEEKS).to_numpy(), index=keys)
    row_keys = pd.MultiIndex.from_arrays([rows["fips"], rows["date"]])
    return rows, frequency_all.reindex(row_keys).to_numpy(), row_keys.isin(keys)


def annual_fires(rows, frequency, ratio):
    """Which rows each rule fires on at one cost ratio, for the rules round 3 compares.

    The forecast and the class frequency fire when their probability is at least the cost ratio
    (never below 0.02, as in value_sweep). The two class rules fire the same whatever the ratio.
    A missing frequency (no past rows) compares as False, so that rule does not fire there.
    """
    return {"forecast": (rows["p_season"] >= max(ratio, 0.02)).to_numpy(),
            "d1_rule": (rows["cls"] >= D2_CLASS - 1).to_numpy(),
            "d0_rule": (rows["cls"] >= D2_CLASS - 2).to_numpy(),
            "class_frequency": frequency >= max(ratio, 0.02)}


def run_trigger_annual(scored, month=3, history=None):
    """ADDED in round 3 (ARCHITECTURE.md section 3.2): the trigger test with ONE decision per
    county per year. run_trigger above is not changed and stays the reported table.

    run_trigger counts the January, February and March outlooks, so each county-year is counted
    three times and those three rows are not independent. Here only the outlooks issued in
    `month` (March by default) are kept: one row per county per year.

    The rule table and the value sweep are the same as run_trigger's, plus two ADDED rules,
    each marked "added": True:
      D0 or worse now             : fire when the county is abnormally dry or worse today
      Class-conditional frequency : fire when, in past years, a county in today's drought class
                                    went on to a drought season at least `threshold` of the time
                                    (prob_calibration.class_frequency_by_past). In the value
                                    sweep it fires at the cost ratio, like the forecasts.

    history : the rows the class frequency may learn from (it keeps the Rio Grande ones and
              uses only those whose answer was known before each New Year). When None, the
              scored rows themselves are used. Those start in the first test year, so its rows
              have no past and the rule cannot fire there. Pass the full table of issue rows to
              give the rule the earlier years.

    Two counts say where the class-frequency rule could not fire for lack of a number:
      class_frequency_rows_without_past        the row is in the history, but no earlier answer
                                               was known yet at its New Year
      class_frequency_rows_absent_from_history the row's county and date are not in `history`
                                               at all (a sign the wrong table was passed)
    """
    rows, frequency, in_history = annual_rows(scored, month, history)
    county_years = len(rows)

    y = rows["y_season"]
    d0 = (rows["cls"] >= D2_CLASS - 2).to_numpy()
    rules = rules_table(rows) + [
        {**score("D0 or worse now", y, d0), "added": True},
        {**score("Class-conditional frequency", y, frequency >= SEASON_THRESHOLD), "added": True},
    ]
    sweep = [{**line,
              "d0_rule": value(y, d0, line["cost_ratio"]),
              "class_frequency": value(y, annual_fires(rows, frequency, line["cost_ratio"])["class_frequency"],
                                       line["cost_ratio"])}
             for line in value_sweep(rows)]
    at_threshold = next(line for line in sweep if line["cost_ratio"] == SEASON_THRESHOLD)
    return {
        "issue_month": month,
        "threshold": SEASON_THRESHOLD,
        "rows": len(rows),
        "county_years": county_years,
        "years": int(rows["date"].dt.year.nunique()),
        "drought_seasons": int(y.sum()),
        "rules": rules,
        "value_sweep": sweep,
        "added_sweep_keys": ["d0_rule", "class_frequency"],
        "class_frequency_rows_without_past": int((np.isnan(frequency) & in_history).sum()),
        "class_frequency_rows_absent_from_history": int((~in_history).sum()),
        "forecast_beats_d1_rule": bool(at_threshold["forecast"] > at_threshold["d1_rule"]),
        "reservoir_forecast_beats_d1_rule": bool(at_threshold["forecast_reservoir"] > at_threshold["d1_rule"]),
    }


if __name__ == "__main__":
    from farmdrought.drought import build_panel
    from farmdrought.outlook import run_outlook

    result = run_trigger(run_outlook(build_panel())[0])
    print(f"{result['rows']} pre-season outlooks, {result['drought_seasons']} followed by a drought season\n")
    print(pd.DataFrame(result["rules"]).to_string(index=False), "\n")
    print(pd.DataFrame(result["value_sweep"]).to_string(index=False), "\n")
    print("Forecast beats the D1 rule:", result["forecast_beats_d1_rule"],
          "| With reservoirs:", result["reservoir_forecast_beats_d1_rule"], "\n")
    only = result["reservoir_counties_only"]
    print(f"Only the {only['counties']} counties with a reservoir ({only['rows']} rows):")
    print(pd.DataFrame(only["rules"]).to_string(index=False), "\n")
    print(pd.DataFrame(only["value_sweep"]).to_string(index=False))
