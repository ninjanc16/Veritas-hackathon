"""outlook.py: the 6-month and 12-month outlooks.

Two questions, asked once a month for each county:
  6-month : "Will the next 26 weeks contain 8 or more D2 weeks in a row?"  (yes/no)
  12-month: "How many of the next 52 weeks will be at D2 or worse?"       (a number, 0 to 52)

HOW THE TESTING WORKS ("forward chaining"). For each test year from 2008 to 2025:
  1. Train a fresh model using only rows whose answer was fully known BEFORE that year began.
  2. Predict that year's rows.
So every prediction comes from a model that never saw its year. It is the same as
pretending to stand at January 1 of each year with only the data that existed then.

Run it with:  PYTHONPATH=src python -m farmdrought.outlook
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from farmdrought.config import (D2_CLASS, FOCUS_RIVER, OUTLOOK_TEST, RIVERS, SEASON_THRESHOLD, SEASON_WEEKS,
                                YEAR_WEEKS)
from farmdrought.drought import build_panel
from farmdrought.evaluate import season_block, season_river, tally, year_block, year_river
from farmdrought.features import FEATURES_E, FEATURES_H, FEATURES_L

# Inputs for each outlook. They come from the plan and were not re-chosen by this code.
FEATURES_SEASON = FEATURES_H + FEATURES_L + FEATURES_E  # 6-month: history + long memory + ENSO
FEATURES_YEAR = FEATURES_H + FEATURES_L                 # 12-month: history + long memory


def make_classifier(seed=0):
    """6-month forest (yes/no). No class weighting, so its output is a rough probability."""
    return RandomForestClassifier(n_estimators=80, max_depth=10, min_samples_leaf=20,
                                  max_features="sqrt", random_state=seed, n_jobs=-1)


def make_regressor(seed=0):
    """12-month forest. It predicts a number of weeks instead of yes/no."""
    return RandomForestRegressor(n_estimators=80, max_depth=10, min_samples_leaf=20,
                                 max_features="sqrt", random_state=seed, n_jobs=-1)


def issue_rows(panel):
    """Keep one row per county per month: the first Drought Monitor week of each month.

    Rows from the first 3 years are dropped, because the long-memory inputs look back 156 weeks.
    """
    monthly = panel[panel["date"].dt.day <= 7]  # a weekly date with day 1-7 is the month's first
    return monthly.dropna(subset=FEATURES_SEASON).reset_index(drop=True)


def folds(table, label, horizon):
    """Yield (year, train mask, test mask) for each test year.

    Training rows are those whose answer window ENDED before January 1 of the test year.
    """
    window_end = table["date"] + pd.Timedelta(weeks=horizon)
    for year in range(OUTLOOK_TEST[0], OUTLOOK_TEST[1] + 1):
        train = table[label].notna() & (window_end < pd.Timestamp(f"{year}-01-01"))
        test = table["date"].dt.year == year
        yield year, train, test


def predict(model, x):
    """A classifier gives the probability of "yes". A regressor gives a number."""
    if not hasattr(model, "predict_proba"):
        return model.predict(x)
    if len(model.classes_) == 1:
        # The training rows were all "yes" or all "no" (it happens on wet rivers in early
        # years). The model can then only ever give that one answer.
        return np.full(len(x), float(model.classes_[0]))
    return model.predict_proba(x)[:, 1]


def chain(table, label, horizon, features, make_model, train_on, predict_on):
    """Forward chaining. Returns one prediction per row (NaN outside the test years).

    train_on   : mask of rows the model may learn from (for example Rio Grande rows only)
    predict_on : mask of rows to predict
    """
    out = pd.Series(np.nan, index=table.index)
    for _, train, test in folds(table, label, horizon):
        fit_rows = train & train_on
        model = make_model().fit(table.loc[fit_rows, features], table.loc[fit_rows, label])
        rows = test & predict_on
        out[rows] = predict(model, table.loc[rows, features])
    return out


def usual(table, label, horizon):
    """Baseline "usual for this county": the county's own average answer in earlier years.

    Computed from each fold's training rows only, so it never sees the test year.
    """
    out = pd.Series(np.nan, index=table.index)
    for _, train, test in folds(table, label, horizon):
        county_average = table[train].groupby("fips")[label].mean()
        out[test] = table.loc[test, "fips"].map(county_average)
    return out


def run_outlook(panel):
    """Run both outlooks. Returns (scored rows, season results, year results)."""
    table = issue_rows(panel)
    focus = table["river"] == FOCUS_RIVER
    everyone = pd.Series(True, index=table.index)
    season = dict(label="y_season", horizon=SEASON_WEEKS)
    year = dict(label="y_weeks", horizon=YEAR_WEEKS)

    # ---- Our system: trained on Rio Grande rows only, applied to all five rivers ----
    table["p_season"] = chain(table, **season, features=FEATURES_SEASON, make_model=make_classifier,
                              train_on=focus, predict_on=everyone)
    table["weeks_model"] = chain(table, **year, features=FEATURES_YEAR, make_model=make_regressor,
                                 train_on=focus, predict_on=everyone)
    table["alarm_season"] = table["p_season"] >= SEASON_THRESHOLD

    # ---- Baselines ----
    table["alarm_season_persistence"] = table["cls"] >= D2_CLASS      # in D2 now
    table["alarm_season_d1"] = table["cls"] >= D2_CLASS - 1           # in D1 or worse now
    table["p_season_usual"] = usual(table, **season)                  # how often it was "yes" before
    table["weeks_last_year"] = table["share52"] * 52                  # D2 weeks in the past 52 weeks
    table["weeks_same_as_now"] = np.where(table["cls"] >= D2_CLASS, 52.0, 0.0)  # future = today
    table["weeks_usual"] = usual(table, **year)                       # the county's average so far

    # ---- Comparison models (not the system, just to compare) ----
    # (a) trained on all five rivers
    table["p_season_all"] = chain(table, **season, features=FEATURES_SEASON, make_model=make_classifier,
                                  train_on=everyone, predict_on=everyone)
    table["weeks_all"] = chain(table, **year, features=FEATURES_YEAR, make_model=make_regressor,
                               train_on=everyone, predict_on=everyone)
    # (b) the 6-month outlook without the El Nino inputs
    table["p_season_no_enso"] = chain(table, **season, features=FEATURES_H + FEATURES_L,
                                      make_model=make_classifier, train_on=focus, predict_on=everyone)
    # (c) retrained on each river's own counties (for the Rio Grande that is the system itself)
    table["p_season_own"] = table["p_season"]
    table["weeks_own"] = table["weeks_model"]
    for river in RIVERS:
        if river != FOCUS_RIVER:
            own = table["river"] == river
            table.loc[own, "p_season_own"] = chain(table, **season, features=FEATURES_SEASON,
                                                   make_model=make_classifier, train_on=own, predict_on=own)[own]
            table.loc[own, "weeks_own"] = chain(table, **year, features=FEATURES_YEAR,
                                                make_model=make_regressor, train_on=own, predict_on=own)[own]

    # ---- Score only rows in the test years whose full 52-week future is known ----
    scored = table[table["p_season"].notna() & table["y_season"].notna() & table["y_weeks"].notna()]
    scored = scored.reset_index(drop=True)
    rg = scored[scored["river"] == FOCUS_RIVER]
    by_river = [(river, scored[scored["river"] == river]) for river in RIVERS]

    season_results = {
        "focus": season_block(rg),
        "per_river": [season_river(river, g) for river, g in by_river],
        # comparison costs on the Rio Grande, used for the "ablations" lines
        "all_rivers_cost": season_block(rg, "p_season_all")["system_cost"],
        "no_enso_cost": season_block(rg, "p_season_no_enso")["system_cost"],
    }
    year_results = {
        "focus": year_block(rg),
        "per_river": [year_river(river, g) for river, g in by_river],
        "all_rivers_mae": year_block(rg, "weeks_all")["mae_system"],
    }
    return scored, season_results, year_results


def extra_inputs_test(table, extra):
    """Ablation: would extra inputs (river flow, snowpack) have helped on the Rio Grande?

    Runs both outlooks twice on the SAME rows, once without and once with the extra inputs,
    using the same forward chaining. Rows where an extra input is missing are left out of both
    runs, so the comparison is fair. The system itself is NOT changed by this test.
    """
    rg = table[(table["river"] == FOCUS_RIVER) & table[extra].notna().all(axis=1)].reset_index(drop=True)
    everyone = pd.Series(True, index=rg.index)
    out = {}
    for name, added in [("without", []), ("with", extra)]:
        p = chain(rg, "y_season", SEASON_WEEKS, FEATURES_SEASON + added, make_classifier, everyone, everyone)
        w = chain(rg, "y_weeks", YEAR_WEEKS, FEATURES_YEAR + added, make_regressor, everyone, everyone)
        known = p.notna() & rg["y_season"].notna() & rg["y_weeks"].notna()  # test years, full future known
        out["rows"] = int(known.sum())
        out[f"season_cost_{name}"] = tally(rg.loc[known, "y_season"], p[known] >= SEASON_THRESHOLD)["cost"]
        out[f"mae_{name}"] = round(float((w[known] - rg.loc[known, "y_weeks"]).abs().mean()), 2)
    return out


if __name__ == "__main__":
    _, s, y = run_outlook(build_panel())
    print("=== 6-month outlook, Rio Grande (cost: lower is better) ===")
    print(pd.Series(s["focus"]).to_string(), "\n")
    print("Trained on all five rivers:", s["all_rivers_cost"], "| Without El Nino inputs:", s["no_enso_cost"], "\n")
    print(pd.DataFrame(s["per_river"]).to_string(index=False), "\n")
    print("=== 12-month outlook, Rio Grande (average error in weeks: lower is better) ===")
    print(pd.Series(y["focus"]).to_string(), "\n")
    print("Trained on all five rivers:", y["all_rivers_mae"], "\n")
    print(pd.DataFrame(y["per_river"]).to_string(index=False))
