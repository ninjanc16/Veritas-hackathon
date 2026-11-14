"""robustness.py: checks on how solid the results are. None of them changes the system.

  1. Seed check. A random forest uses random numbers, so a different "seed" gives a slightly
     different forest. Our wins over the best simple rule are thin (2 to 4%). If they only
     appear with one lucky seed, they are noise. So we retrain with 5 seeds and count how
     often the system still wins.
  2. Buffer check. Counties were chosen with a 50 km rule. Would the result survive a
     100 km rule, which brings in more counties?
  3. Extra simple rules. An outside review of this code suggested two simple rules that were
     not in our baseline list. We score them here on the same rows, and report the result
     even though it goes against us.

Writes reports/robustness.json. Run it with:  PYTHONPATH=src python -m farmdrought.robustness
(Run farmdrought.export first: the baseline numbers are read from reports/metrics.json.)
"""
import json

import pandas as pd

from farmdrought.alert import fit_alert, make_forest, run_alert, split_masks
from farmdrought.config import (D2_CLASS, FOCUS_RIVER, METRICS, OUTLOOK, REPORTS, SEASON_THRESHOLD, SEASON_WEEKS,
                                YEAR_WEEKS)
from farmdrought.drought import build_panel
from farmdrought.evaluate import tally
from farmdrought.features import FEATURES_H
from farmdrought.outlook import (FEATURES_SEASON, FEATURES_YEAR, chain, issue_rows, make_classifier, make_regressor,
                                 run_outlook)

SEEDS = list(range(10))  # seed 0 is the system itself
ROBUSTNESS = REPORTS / "robustness.json"


def best_baselines(metrics):
    """The best simple rule for each product on the Rio Grande, read from the final metrics."""
    s, y = metrics["season"]["focus"], metrics["year"]["focus"]
    return {
        "alert_cost": metrics["headline"]["cheapest_baseline_cost"],
        "season_cost": min(s[k] for k in ("persistence_cost", "d1_rule_cost", "usual_cost",
                                          "always_warn_cost", "never_warn_cost")),
        "year_mae": min(y[k] for k in ("mae_same_as_now", "mae_last_year", "mae_usual")),
    }


def seed_check(panel, baselines):
    """Retrain all three Rio Grande models with each seed and score them the same way as the system."""
    train, val, test = split_masks(panel)
    focus = panel["river"] == FOCUS_RIVER
    alert_test = panel[test & focus]
    table = issue_rows(panel)
    rg = table[table["river"] == FOCUS_RIVER].reset_index(drop=True)
    everyone = pd.Series(True, index=rg.index)

    runs = []
    for seed in SEEDS:
        # 4-week alert: new forest, and its threshold is picked again on validation years
        model, threshold = fit_alert(panel, train & focus, val & focus, make_forest(seed))
        alarm = model.predict_proba(alert_test[FEATURES_H])[:, 1] >= threshold
        # The two outlooks, with the same forward chaining as the system
        p = chain(rg, "y_season", SEASON_WEEKS, FEATURES_SEASON, lambda: make_classifier(seed), everyone, everyone)
        w = chain(rg, "y_weeks", YEAR_WEEKS, FEATURES_YEAR, lambda: make_regressor(seed), everyone, everyone)
        known = p.notna() & rg["y_season"].notna() & rg["y_weeks"].notna()
        runs.append({
            "seed": seed,
            "alert_cost": tally(alert_test["y"], alarm)["cost"],
            "season_cost": tally(rg.loc[known, "y_season"], p[known] >= SEASON_THRESHOLD)["cost"],
            "year_mae": round(float((w[known] - rg.loc[known, "y_weeks"]).abs().mean()), 2),
        })

    # For each product: the range across seeds, and how many seeds beat the best simple rule
    summary = {}
    for key, baseline in baselines.items():
        values = [run[key] for run in runs]
        summary[key] = {"lowest": min(values), "highest": max(values), "best_baseline": baseline,
                        "seeds_beating_best_baseline": f"{sum(v < baseline for v in values)}/{len(values)}"}
    return {"runs": runs, "summary": summary}


def buffer_check(buffer_km=100):
    """Rebuild everything with a wider county rule and report the Rio Grande headline numbers."""
    panel, alert = run_alert(buffer_km)
    _, season, year = run_outlook(panel)
    s, y = season["focus"], year["focus"]
    return {
        "buffer_km": buffer_km,
        "n_focus_counties": panel.loc[panel["river"] == FOCUS_RIVER, "fips"].nunique(),
        "alert": {"system_cost": alert["headline"]["system_cost"],
                  "best_baseline": alert["headline"]["cheapest_baseline_on_test"],
                  "best_baseline_cost": alert["headline"]["cheapest_baseline_cost"],
                  "beats_every_baseline": alert["headline"]["honesty_check_pass"]},
        "season": {"system_cost": s["system_cost"], "d1_rule_cost": s["d1_rule_cost"],
                   "persistence_cost": s["persistence_cost"], "beats_every_baseline": s["beats_every_baseline"]},
        "year": {"mae_system": y["mae_system"], "mae_same_as_now": y["mae_same_as_now"],
                 "mae_last_year": y["mae_last_year"], "beats_every_baseline": y["beats_every_baseline"]},
    }


def extra_rules_check(panel):
    """Score two simple rules suggested by an outside review. They were added AFTER the
    final run, so they are reported here and are not part of the fixed baseline list.

    4-week rule : warn if in D2 now, or in D1 and worse than 4 OR 8 weeks ago.
                  (Our "Worsening" baseline only looks 4 weeks back.)
    12-month    : the plain average of two of our own baselines, "same as now" and
                  "same as the last 52 weeks". It has no settings to tune.
    """
    train, val, test = split_masks(panel)
    focus = panel["river"] == FOCUS_RIVER
    d1 = D2_CLASS - 1
    rule = (panel["cls"] >= D2_CLASS) | ((panel["cls"] >= d1) & ((panel["chg4"] > 0) | (panel["chg8"] > 0)))
    model, threshold = fit_alert(panel, train & focus, val & focus)  # the system itself (seed 0)
    system = pd.Series(model.predict_proba(panel[FEATURES_H])[:, 1] >= threshold, index=panel.index)
    cost = lambda alarm, rows: tally(panel.loc[rows & focus, "y"], alarm[rows & focus])["cost"]

    # The 12-month check reads the handoff file, so it uses exactly the rows that were scored
    outlook = pd.read_parquet(OUTLOOK)
    rg = outlook[outlook["river"] == FOCUS_RIVER]
    blend = (rg["weeks_same_as_now"] + rg["weeks_last_year"]) / 2
    return {
        "alert_rule": "D2 now, or D1 and worse than 4 or 8 weeks ago",
        "alert_rule_cost_validation": cost(rule, val), "system_cost_validation": cost(system, val),
        "alert_rule_cost_test": cost(rule, test), "system_cost_test": cost(system, test),
        "year_rule": "average of 'same as now' and 'same as the last 52 weeks'",
        "year_rule_mae": round(float((blend - rg["y_weeks"]).abs().mean()), 2),
        "system_mae": round(float((rg["weeks_model"] - rg["y_weeks"]).abs().mean()), 2),
    }


if __name__ == "__main__":
    with open(METRICS) as f:
        baselines = best_baselines(json.load(f))
    panel = build_panel()
    result = {"seed_check": seed_check(panel, baselines), "buffer_check": buffer_check(),
              "extra_rules_check": extra_rules_check(panel)}
    with open(ROBUSTNESS, "w") as f:
        json.dump(result, f, indent=2, default=lambda value: value.item())
    print(pd.DataFrame(result["seed_check"]["runs"]).to_string(index=False), "\n")
    print(pd.DataFrame(result["seed_check"]["summary"]).T.to_string(), "\n")
    print(json.dumps(result["buffer_check"], indent=2, default=lambda value: value.item()))
    print(json.dumps(result["extra_rules_check"], indent=2, default=lambda value: value.item()))
