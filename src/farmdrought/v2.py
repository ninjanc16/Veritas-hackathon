"""v2.py: version 2 of the three Rio Grande forecasts. Version 1 is not changed by this file.

THE PROBLEM. We have already seen version 1's test results. If we now tried settings until the
test score improved, the improvement would be fake ("tuning on the test years").

THE HONEST WAY. Build a list of candidate recipes, then let the PAST choose:
  - Outlooks: standing at each New Year, score every candidate on the earlier years whose
    answers are already known, and use the cheapest one for the coming year.
  - 4-week alert: pick the candidate that is cheapest on the validation years (2015-2018).
No candidate is ever chosen using a year it is then scored on.

A CANDIDATE is three choices:
  1. forest settings (how many trees, how deep)
  2. inputs: version 1's own, or the same plus weather (rain and temperature, weather.py)
  3. blend: how much weight the forest gets, with the rest given to a simple rule

Honest note: the candidate LIST was written after seeing version 1's test results (see
reports/decision.md). Only the choice among candidates is protected.

Writes reports/v2.json. Run it with:  PYTHONPATH=src python -m farmdrought.v2
"""
import json

import numpy as np
import pandas as pd

from farmdrought.alert import make_forest, split_masks
from farmdrought.config import (D2_CLASS, FOCUS_RIVER, OUTLOOK_TEST, REPORTS, SEASON_THRESHOLD, SEASON_WEEKS,
                                YEAR_WEEKS)
from farmdrought.config import SCORE_THROUGH
from farmdrought.drought import build_panel
from farmdrought.evaluate import pick_threshold, tally
from farmdrought.features import FEATURES_H
from farmdrought.outlook import (FEATURES_SEASON, FEATURES_YEAR, chain, issue_rows, make_classifier,
                                 make_regressor)
from farmdrought.weather import FEATURES_W, add_weather_features

V2_JSON = REPORTS / "v2.json"
V1 = "v1 settings, forest 100%"  # the name of the candidate that is exactly version 1
SELECT_START = 2005              # candidates are forecast from 2005 (the first year the 12-month forest has training rows)
SEEDS = [0, 1, 2, 3, 4]          # seed 0 is the reported run. The others show how much is luck.

# Choice 1: forest settings. The first of each list is version 1's own.
OUTLOOK_SETTINGS = {
    "v1 settings": dict(n_estimators=80, max_depth=10, min_samples_leaf=20),
    "more trees": dict(n_estimators=300, max_depth=10, min_samples_leaf=20),
    "shallow": dict(n_estimators=300, max_depth=6, min_samples_leaf=50),
    "deep": dict(n_estimators=300, max_depth=None, min_samples_leaf=5),
}
ALERT_SETTINGS = {
    "v1 settings": dict(n_estimators=100, max_depth=12, min_samples_leaf=100),
    "more trees": dict(n_estimators=300, max_depth=12, min_samples_leaf=100),
    "shallow": dict(n_estimators=300, max_depth=8, min_samples_leaf=200),
    "deep": dict(n_estimators=300, max_depth=None, min_samples_leaf=30),
}
# Choice 2: inputs. "" means version 1's own inputs.
INPUT_SETS = {"": [], " + weather": FEATURES_W}
# Choice 3: the forest's share of the blend. The simple rule gets the rest.
FOREST_SHARES = [1.0, 0.75, 0.5]


def pick_by_past(table, candidates, label, horizon, loss):
    """For each test year, use the candidate that did best on the years already known.

    candidates : one column of forecasts per candidate
    loss       : function (truth, forecast) -> a number, lower is better
    Returns (the chosen forecast for every row, {year: name of the candidate chosen}).
    """
    window_end = table["date"] + pd.Timedelta(weeks=horizon)
    has_forecast = candidates.notna().all(axis=1)
    out, chosen = pd.Series(np.nan, index=table.index), {}
    for year in range(OUTLOOK_TEST[0], OUTLOOK_TEST[1] + 1):
        # the past = rows that were forecast AND whose answer was fully known before January 1
        past = has_forecast & table[label].notna() & (window_end < pd.Timestamp(f"{year}-01-01"))
        scores = {name: loss(table.loc[past, label], candidates.loc[past, name]) for name in candidates}
        best = min(scores, key=scores.get)  # on a tie, min() keeps the first, which is version 1
        this_year = table["date"].dt.year == year
        out[this_year] = candidates.loc[this_year, best]
        chosen[year] = best
    return out, chosen


def outlook_candidates(rg, label, horizon, features, make_model, rule, seed):
    """Forecast every candidate with forward chaining. Returns one column per candidate.

    rule : the simple rule's own forecast for every row (it needs no training)
    """
    everyone = pd.Series(True, index=rg.index)
    columns = {}
    for setting_name, settings in OUTLOOK_SETTINGS.items():
        for input_name, extra in INPUT_SETS.items():
            make = lambda: make_model(seed).set_params(**settings)
            forest = chain(rg, label, horizon, features + extra, make, everyone, everyone, first_year=SELECT_START)
            for share in FOREST_SHARES:
                columns[f"{setting_name}{input_name}, forest {share:.0%}"] = share * forest + (1 - share) * rule
    columns["simple rule alone"] = rule.where(forest.notna())  # only on rows the forests also forecast
    return pd.DataFrame(columns)


def outlook_v2(rg, seed=0):
    """Version 2 of the 6-month and 12-month outlooks. Returns (rows with v2 columns, results)."""
    rg = rg.copy()
    # ---- 6-month: chance of a drought season. Simple rule: "D1 or worse now" (1 = warn, 0 = not) ----
    season_loss = lambda y, p: tally(y, p >= SEASON_THRESHOLD)["cost"]
    d1_rule = (rg["cls"] >= D2_CLASS - 1).astype(float)
    season = outlook_candidates(rg, "y_season", SEASON_WEEKS, FEATURES_SEASON, make_classifier, d1_rule, seed)
    rg["p_season_v2"], season_chosen = pick_by_past(rg, season, "y_season", SEASON_WEEKS, season_loss)

    # ---- 12-month: weeks of severe drought. Simple rule: the average of two baselines ----
    year_loss = lambda y, w: float((w - y).abs().mean())
    same_as_now = pd.Series(np.where(rg["cls"] >= D2_CLASS, 52.0, 0.0), index=rg.index)
    two_baselines = (same_as_now + rg["share52"] * 52) / 2
    year = outlook_candidates(rg, "y_weeks", YEAR_WEEKS, FEATURES_YEAR, make_regressor, two_baselines, seed)
    rg["weeks_v2"], year_chosen = pick_by_past(rg, year, "y_weeks", YEAR_WEEKS, year_loss)

    # ---- Score exactly the rows version 1 is scored on: test years with the full future known ----
    scored = rg["p_season_v2"].notna() & rg["y_season"].notna() & rg["y_weeks"].notna()
    s, y = rg[scored], rg.loc[scored, "y_weeks"]

    def block(candidates, v2_column, label, loss, chosen):
        """Version 2 against version 1 and the simple rule, on the scored rows."""
        each = {name: round(loss(s[label], candidates.loc[scored, name]), 2) for name in candidates}
        v2 = round(loss(s[label], s[v2_column]), 2)
        return {"rows": int(scored.sum()), "v2": v2, "v1": each[V1], "simple_rule": each["simple rule alone"],
                "v2_beats_v1": bool(v2 < each[V1]), "v2_beats_simple_rule": bool(v2 < each["simple rule alone"]),
                "weather_alone": each["v1 settings + weather, forest 100%"],
                "chosen_each_year": chosen,
                # Every candidate's score on the test years. FOR INFORMATION ONLY: these numbers
                # were never used to choose, because that would be tuning on the test years.
                "every_candidate_on_test": each}

    results = {"season": block(season, "p_season_v2", "y_season", season_loss, season_chosen),
               "year": block(year, "weeks_v2", "y_weeks", year_loss, year_chosen)}
    return rg, results


def alert_v2(panel, seed=0):
    """Version 2 of the 4-week alert. The candidate is chosen on validation years only.

    Returns (results, the chosen candidate's alarm for every Rio Grande row).
    """
    rg = add_weather_features(panel[panel["river"] == FOCUS_RIVER]).reset_index(drop=True)
    train, val, test = split_masks(rg)
    y = rg["y"]
    cost = lambda alarm, rows: tally(y[rows], alarm[rows])["cost"]

    # Two simple rules. "Worsening" is in version 1's baseline list. The wider one (4 OR 8
    # weeks) came from the outside review, after the test results were known.
    d1 = rg["cls"] >= D2_CLASS - 1
    rules = {"worsening": (rg["cls"] >= D2_CLASS) | (d1 & (rg["chg4"] > 0)),
             "worsening 4 or 8 weeks": (rg["cls"] >= D2_CLASS) | (d1 & ((rg["chg4"] > 0) | (rg["chg8"] > 0)))}

    alarms = {}  # candidate name -> True/False alarm for every row
    for setting_name, settings in ALERT_SETTINGS.items():
        for input_name, extra in INPUT_SETS.items():
            model = make_forest(seed).set_params(**settings).fit(rg.loc[train, FEATURES_H + extra], y[train])
            forest = pd.Series(model.predict_proba(rg[FEATURES_H + extra])[:, 1], index=rg.index)
            blends = {f"{setting_name}{input_name}, forest 100%": forest}
            for rule_name, rule in rules.items():
                for share in FOREST_SHARES[1:]:
                    blends[f"{setting_name}{input_name}, forest {share:.0%} + {rule_name}"] = \
                        share * forest + (1 - share) * rule
            for name, score in blends.items():
                # each candidate gets its own alarm threshold, picked on VALIDATION rows
                alarms[name] = score >= pick_threshold(score[val], y[val])
    for rule_name, rule in rules.items():
        alarms[f"{rule_name} alone"] = rule

    validation = {name: cost(alarm, val) for name, alarm in alarms.items()}
    best = min(validation, key=validation.get)  # chosen on validation. Ties go to version 1 (it is first).
    each = {name: cost(alarm, test) for name, alarm in alarms.items()}
    rule_cost = min(each["worsening alone"], each["worsening 4 or 8 weeks alone"])
    results = {"rows": int(test.sum()), "chosen": best, "chosen_validation_cost": validation[best],
            "v1_validation_cost": validation[V1],
            "v2": each[best], "v1": each[V1], "simple_rule": rule_cost,
            "v2_beats_v1": bool(each[best] < each[V1]), "v2_beats_simple_rule": bool(each[best] < rule_cost),
            "weather_alone": each["v1 settings + weather, forest 100%"],
            "every_candidate_on_validation": validation,
            "every_candidate_on_test": each}  # FOR INFORMATION ONLY, never used to choose
    return results, rg[["fips", "date"]].assign(alarm_v2=alarms[best])


def run_v2(panel):
    """Run version 2 for all three products, then repeat with other seeds."""
    rg = panel[panel["river"] == FOCUS_RIVER]
    table = add_weather_features(issue_rows(rg)).reset_index(drop=True)
    _, results = outlook_v2(table)
    results["alert"], _ = alert_v2(panel)

    # Seed check: a forest uses random numbers. Does version 2 still beat version 1 with other seeds?
    runs = []
    for seed in SEEDS:
        if seed == 0:
            r = results
        else:
            _, r = outlook_v2(table, seed)
            r["alert"], _ = alert_v2(panel, seed)
        runs.append({"seed": seed, **{f"{k}_{version}": r[k][version] for k in ("alert", "season", "year")
                                      for version in ("v1", "v2")}})
    results["seed_check"] = {
        "runs": runs,
        "seeds_where_v2_beats_v1": {k: f"{sum(run[f'{k}_v2'] < run[f'{k}_v1'] for run in runs)}/{len(runs)}"
                                    for k in ("alert", "season", "year")}}
    return results


if __name__ == "__main__":
    # Weeks after the scoring cut-off are left out, so a rerun after new data arrives scores the
    # same weeks as the frozen results (ARCHITECTURE.md section 3.0).
    results = run_v2(build_panel(score_through=SCORE_THROUGH))
    with open(V2_JSON, "w") as f:
        json.dump(results, f, indent=2)
    for product in ("alert", "season", "year"):
        r = results[product]
        print(f"=== {product}: v2 {r['v2']} | v1 {r['v1']} | simple rule {r['simple_rule']} | "
              f"weather alone {r['weather_alone']} ===")
        print("chosen:", r.get("chosen") or pd.Series(r["chosen_each_year"]).value_counts().to_dict(), "\n")
    print(pd.DataFrame(results["seed_check"]["runs"]).to_string(index=False))
    print(results["seed_check"]["seeds_where_v2_beats_v1"])
