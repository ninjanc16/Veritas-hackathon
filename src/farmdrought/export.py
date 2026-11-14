"""export.py: run everything and write the four handoff files the App track reads.

  data/processed/predictions.parquet : 4-week alert, test years, with the truth
  data/processed/outlook.parquet     : 6- and 12-month outlooks, test years, with the truth
  data/processed/latest.parquet      : this week's alert and outlooks (no truth yet)
  reports/metrics.json               : every reported number

The exact columns and keys are fixed by the contract (architecture doc, section P2).
Each table is checked against the contract BEFORE it is written.

Run it with:  PYTHONPATH=src python -m farmdrought.export
"""
import json
from datetime import datetime

import numpy as np
import pandas as pd

from farmdrought.alert import make_forest, run_alert, split_masks
from farmdrought.config import (ALERT_WEEKS, FOCUS_RIVER, LATEST, METRICS, MISS_COST, OUTLOOK, OUTLOOK_TEST,
                                PREDICTIONS, PROCESSED, REPORTS, SEASON_THRESHOLD, SEASON_WEEKS, TEST_START,
                                TRAIN, VAL, YEAR_WEEKS)
from farmdrought.features import FEATURES_H
from farmdrought.flow import FEATURES_F, add_flow_features
from farmdrought.outlook import (FEATURES_SEASON, FEATURES_YEAR, extra_inputs_test, issue_rows, make_classifier,
                                 make_regressor, run_outlook)
from farmdrought.robustness import ROBUSTNESS
from farmdrought.snow import FEATURES_S, add_snow_features

IS_FINAL = True  # the numbers are locked: reports/decision.md was committed before this run

# Column order of each file, exactly as in the contract
PREDICTION_COLUMNS = ["date", "fips", "county", "state", "river", "lat", "lon", "y", "cls", "d2_streak",
                      "p_model", "tier", "alarm_system", "alarm_persistence", "alarm_d1_now",
                      "alarm_worsening", "alarm_calendar"]
OUTLOOK_COLUMNS = ["date", "fips", "county", "state", "river", "cls", "y_season", "p_season", "alarm_season",
                   "alarm_season_persistence", "alarm_season_d1", "p_season_usual", "y_weeks", "weeks_model",
                   "weeks_last_year", "weeks_same_as_now", "weeks_usual"]
LATEST_COLUMNS = ["date", "fips", "county", "state", "river", "lat", "lon", "cls", "d2_streak", "p_model",
                  "tier", "alarm_system", "p_season", "season_tier", "weeks_model", "weeks_usual"]
WHOLE_NUMBERS = ["y", "cls", "d2_streak", "y_season", "y_weeks"]


def tiers(score, threshold):
    """Turn a score into Low / Watch / Warning. Watch starts at half the alarm threshold."""
    return np.where(score >= threshold, "Warning", np.where(score >= threshold / 2, "Watch", "Low"))


def finish(table, columns, sort_by):
    """Put a table into contract shape, then check it. Raises an error if anything is wrong."""
    table = table.sort_values(sort_by).reset_index(drop=True)[columns].copy()  # contract columns only
    for column in WHOLE_NUMBERS:
        if column in table:
            table[column] = table[column].astype(int)
    table["date"] = table["date"].dt.date  # a plain date, with no time of day
    assert not table.isna().any().any(), "the contract allows no missing values"
    assert table["fips"].str.fullmatch(r"\d{5}").all(), "fips must be 5 digits, leading zeros kept"
    return table


def latest_table(panel, threshold):
    """This week's forecasts for every county. There is no truth yet, so nothing to score.

    The three models are retrained on ALL Rio Grande rows whose answer is known, so the
    live forecast uses the newest data. The alarm threshold stays the one picked on
    validation years.
    """
    focus = panel["river"] == FOCUS_RIVER
    now = panel[panel["date"] == panel["date"].max()].copy()

    known = focus & panel["y"].notna()
    alert = make_forest().fit(panel.loc[known, FEATURES_H], panel.loc[known, "y"])
    now["p_model"] = alert.predict_proba(now[FEATURES_H])[:, 1]
    now["alarm_system"] = now["p_model"] >= threshold
    now["tier"] = tiers(now["p_model"], threshold)

    monthly = issue_rows(panel)  # the outlooks learn from monthly rows, as in testing
    rg = monthly[monthly["river"] == FOCUS_RIVER]
    known = rg[rg["y_season"].notna()]
    now["p_season"] = make_classifier().fit(known[FEATURES_SEASON], known["y_season"]).predict_proba(now[FEATURES_SEASON])[:, 1]
    now["season_tier"] = tiers(now["p_season"], SEASON_THRESHOLD)
    known = rg[rg["y_weeks"].notna()]
    now["weeks_model"] = make_regressor().fit(known[FEATURES_YEAR], known["y_weeks"]).predict(now[FEATURES_YEAR])
    # "Usual" = each county's own average over every month whose answer is known
    now["weeks_usual"] = now["fips"].map(monthly.groupby("fips")["y_weeks"].mean())
    return now


def failure_examples(rg, rg_outlook):
    """Real cases where the system was wrong, each picked by a fixed rule (not by hand).

    rg         : Rio Grande test rows of the 4-week alert
    rg_outlook : Rio Grande test rows of the two outlooks
    """
    example = lambda product, row, text: {"product": product, "date": str(row["date"].date()),
                                          "county": row["county"], "state": row["state"], "what_happened": text}

    # 4-week alert: the most confident false alarm, and the least expected miss
    false_alarms = rg[rg["alarm_system"] & (rg["y"] == 0)]
    misses = rg[~rg["alarm_system"] & (rg["y"] == 1)]
    fa = false_alarms.loc[false_alarms["p_model"].idxmax()]
    miss = misses.loc[misses["p_model"].idxmin()]

    # 6-month outlook: the row where the probability was furthest from what happened
    season = rg_outlook.loc[(rg_outlook["p_season"] - rg_outlook["y_season"]).abs().idxmax()]
    if season["y_season"] == 1:
        season_text = (f"Miss: the outlook gave only a {season['p_season']:.0%} chance of 8 or more severe-drought "
                       "weeks in a row within 6 months, but it happened.")
    else:
        season_text = (f"False alarm: the outlook gave a {season['p_season']:.0%} chance of 8 or more severe-drought "
                       "weeks in a row within 6 months, but it did not happen.")

    # 12-month outlook: the row with the largest error in weeks
    error = (rg_outlook["weeks_model"] - rg_outlook["y_weeks"]).abs()
    worst = rg_outlook.loc[error.idxmax()]
    # Do the largest errors fall in the deepest drought year? Compare the two years.
    by_year = rg_outlook.groupby(rg_outlook["date"].dt.year)
    worst_year = int(error.groupby(rg_outlook["date"].dt.year).mean().idxmax())
    deepest_year = int(by_year["y_weeks"].mean().idxmax())
    if worst_year == deepest_year:
        year_note = f"The largest errors fall on forecasts issued in {worst_year}, the deepest drought year of the test period."
    else:
        year_note = (f"The largest errors fall on forecasts issued in {worst_year}. The deepest drought followed "
                     f"forecasts issued in {deepest_year}.")
    year_text = (f"The outlook estimated {worst['weeks_model']:.0f} weeks of severe drought in the next 52, "
                 f"but there were {worst['y_weeks']:.0f}. {year_note}")

    return [
        example("4-week alert", fa, f"False alarm: the system warned with a risk score of {fa['p_model']:.2f}, "
                                    "but the county did not reach severe drought in the next 4 weeks."),
        example("4-week alert", miss, f"Miss: the risk score was only {miss['p_model']:.2f}, so there was no warning, "
                                      "but the county reached severe drought within 4 weeks."),
        example("6-month outlook", season, season_text),
        example("12-month outlook", worst, year_text),
    ]


def extra_input_lines(panel):
    """Ablation lines for river flow and snowpack. They were tested but are NOT part of the system."""
    table = add_snow_features(add_flow_features(issue_rows(panel)))
    lines = []
    for name, extra in [("River flow", FEATURES_F), ("Snowpack (snowmelt supply)", FEATURES_S),
                        ("River flow and snowpack together", FEATURES_F + FEATURES_S)]:
        r = extra_inputs_test(table, extra)
        lines.append({"name": f"{name} added as an input", "product": "6-month outlook",
                      "result": f"Cost {r['season_cost_with']} with it, against {r['season_cost_without']} without it, "
                                f"on the same {r['rows']} Rio Grande rows."})
        lines.append({"name": f"{name} added as an input", "product": "12-month outlook",
                      "result": f"Average error {r['mae_with']} weeks with it, against {r['mae_without']} without it, "
                                f"on the same {r['rows']} Rio Grande rows."})
    return lines


def build_metrics(alert, season, year, predictions, scored, panel):
    """Collect every reported number into one dictionary, with the contract's keys."""
    # Rivers where the Rio Grande-trained models did not beat the best simple rule
    others = lambda entries: [e for e in entries if e["river"] != FOCUS_RIVER]
    names = lambda entries: ", ".join(e["river"] for e in entries) or "none"
    alert_lost = names([e for e in others(alert["per_river"]) if e["system_cost"] >= e["best_rule_cost"]])
    alert_lost_persistence = names([e for e in others(alert["per_river"]) if e["system_cost"] >= e["persistence_cost"]])
    season_lost = names([e for e in others(season["per_river"]) if e["system_cost"] >= e["best_rule_cost"]])
    year_lost = names([e for e in others(year["per_river"]) if e["mae_system"] >= e["mae_best_baseline"]])
    onset = alert["onset"]
    focus_rows = int((predictions["river"] == FOCUS_RIVER).sum())
    system, cheapest = alert["headline"]["system_cost"], alert["headline"]["cheapest_baseline_cost"]
    s, y = season["focus"], year["focus"]
    return {
        "contract_version": 2,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "is_final": IS_FINAL,
        "focus_river": FOCUS_RIVER,
        "training_scope": "Rio Grande counties only",
        "n_rows": len(predictions),
        "n_focus_rows": focus_rows,
        "n_counties": panel["fips"].nunique(),
        "n_focus_counties": panel.loc[panel["river"] == FOCUS_RIVER, "fips"].nunique(),
        "horizon_weeks": ALERT_WEEKS,
        "train_years": list(TRAIN),
        "val_years": list(VAL),
        "test_years": [TEST_START, predictions["date"].max().year],
        "latest_week": str(panel["date"].max().date()),
        "miss_cost": MISS_COST,
        "policies": alert["policies"],
        "headline": alert["headline"],
        "onset": alert["onset"],
        "events": alert["events"],
        "cost_sensitivity": alert["cost_sensitivity"],
        "year_by_year": alert["year_by_year"],
        "per_river": alert["per_river"],
        "season": {
            "horizon_weeks": SEASON_WEEKS,
            "target": "8 or more consecutive weeks at D2 or worse inside the next 26 weeks",
            "test_years": list(OUTLOOK_TEST), "threshold": SEASON_THRESHOLD,
            "focus": s, "per_river": season["per_river"],
        },
        "year": {
            "horizon_weeks": YEAR_WEEKS,
            "target": "number of weeks at D2 or worse in the next 52 weeks",
            "test_years": list(OUTLOOK_TEST),
            "focus": y, "per_river": year["per_river"],
        },
        "failure_examples": failure_examples(predictions[predictions["river"] == FOCUS_RIVER],
                                             scored[scored["river"] == FOCUS_RIVER]),
        "shuffled_auc_mean": alert["shuffled_auc_mean"],
        "ablations": [
            {"name": "4-week forest trained on all five rivers", "product": "4-week alert",
             "result": f"Cost {alert['per_river'][0]['all_rivers_cost']} on the Rio Grande, against {system} for the Rio Grande-trained system."},
            {"name": "Logistic regression in place of the forest", "product": "4-week alert",
             "result": f"Cost {alert['logistic_cost']} on the Rio Grande, against {system} for the forest."},
            {"name": "6-month forest without the El Nino inputs", "product": "6-month outlook",
             "result": f"Cost {season['no_enso_cost']} on the Rio Grande, against {s['system_cost']} with them."},
            {"name": "6-month forest trained on all five rivers", "product": "6-month outlook",
             "result": f"Cost {season['all_rivers_cost']} on the Rio Grande, against {s['system_cost']} for the Rio Grande-trained system."},
            {"name": "12-month forest trained on all five rivers", "product": "12-month outlook",
             "result": f"Average error {year['all_rivers_mae']} weeks on the Rio Grande, against {y['mae_system']} for the Rio Grande-trained system."},
        ] + extra_input_lines(panel),
        "feature_importance": alert["feature_importance"],
        "limits": [
            "The cost rule (a miss costs 3 false alarms) is our assumption. Results at other costs are in cost_sensitivity.",
            "The 4-week risk score is not a calibrated probability.",
            f"On the Rio Grande the 4-week system (cost {system}) is close to a tie with the best simple rule, "
            f"{alert['headline']['cheapest_baseline_on_test']} (cost {cheapest}).",
            f"Onset is the hard part. For counties not yet in severe drought, the system caught {onset['recall']:.0%} of "
            f"the weeks that led to it, with precision {onset['precision']:.0%}. Its cost was {onset['system_cost']}, "
            f"against {onset['best_rule_cost']} for the best simple rule ({onset['best_rule']}) and "
            f"{onset['never_warn_cost']} for never warning.",
            f"The 6-month outlook costs {s['system_cost']}, against {s['d1_rule_cost']} for the 'D1 or worse now' rule. "
            "That is close to a tie.",
            f"The 12-month outlook is off by {y['mae_system']} weeks on average, against an average of "
            f"{y['mean_weeks']} weeks. It is a planning range, not a precise forecast.",
            f"Transfer of the Rio Grande-trained 4-week system: it did not beat the best simple rule on: {alert_lost}. "
            f"It did not beat persistence on: {alert_lost_persistence}.",
            f"Transfer of the Rio Grande-trained 6-month outlook: it did not beat the best simple rule on: {season_lost}.",
            f"Transfer of the Rio Grande-trained 12-month outlook: it did not beat the best baseline on: {year_lost}.",
            "The 31 Rio Grande counties move together, so the real sample is about 18 years, not thousands of rows.",
            "Design choices were made after exploratory runs on the same test years.",
            "Counties are chosen by a 50 km rule from the river's main line. A different width gives a different set.",
            "The Drought Monitor map is drawn by people each week, so the target includes their judgment.",
            "A warning is not a payment decision. The grazing-period rule of the aid program is not modeled.",
            "Nothing here measures crop yields or dollars saved.",
            "River flow and snowpack were tested as extra inputs and are not part of the system. See ablations. "
            "The El Paso gauge had no daily flow data and was dropped. The Del Norte gauge ends in 2024.",
            "Weather inputs (rain, temperature, soil moisture) were not tested.",
            "A random forest cannot predict a drought longer or deeper than any it saw in training.",
        ],
        # ---- keys added after the contract's list (contract rule 2 allows additions at the end) ----
        "alert_threshold": alert["threshold"],
    }


def main():
    # 1. Run the three experiments
    panel, alert = run_alert()
    scored, season, year = run_outlook(panel)

    # 2. Build the three tables in contract shape
    _, _, test = split_masks(panel)
    predictions = panel[test].copy()
    predictions["tier"] = tiers(predictions["p_model"], alert["threshold"])
    metrics = build_metrics(alert, season, year, predictions, scored, panel)
    predictions = finish(predictions, PREDICTION_COLUMNS, ["date", "fips"])
    outlook = finish(scored, OUTLOOK_COLUMNS, ["date", "fips"])
    latest = finish(latest_table(panel, alert["threshold"]), LATEST_COLUMNS, ["fips"])

    # 3. Write the four files
    PROCESSED.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(PREDICTIONS, index=False)
    outlook.to_parquet(OUTLOOK, index=False)
    latest.to_parquet(LATEST, index=False)
    # Add the robustness checks (seeds and county buffer) if they have been run.
    # They are extra keys at the end, which contract rule 2 allows.
    if ROBUSTNESS.exists():
        with open(ROBUSTNESS) as f:
            checks = json.load(f)
        metrics.update(checks)
        seeds, wide, extra = checks["seed_check"]["summary"], checks["buffer_check"], checks["extra_rules_check"]
        metrics["limits"] += [
            f"Seed check: retrained with {len(checks['seed_check']['runs'])} random seeds, the system beat the best simple rule in "
            f"{seeds['alert_cost']['seeds_beating_best_baseline']} runs for the 4-week alert, "
            f"{seeds['season_cost']['seeds_beating_best_baseline']} for the 6-month outlook and "
            f"{seeds['year_mae']['seeds_beating_best_baseline']} for the 12-month outlook.",
            f"Buffer check: with a {wide['buffer_km']} km county rule ({wide['n_focus_counties']} counties), the 4-week "
            f"system cost {wide['alert']['system_cost']} against {wide['alert']['best_baseline_cost']} for the best "
            f"simple rule ({wide['alert']['best_baseline']}).",
            "An outside review suggested two simple rules that were not in our baseline list. They were scored "
            "after the final run. "
            f"4-week rule '{extra['alert_rule']}': cost {extra['alert_rule_cost_test']} on the test years, against "
            f"{extra['system_cost_test']} for the system. "
            f"12-month rule '{extra['year_rule']}': average error {extra['year_rule_mae']} weeks, against "
            f"{extra['system_mae']} for the system.",
            "The 6-month outlook uses an El Nino value that NOAA publishes a few days into the month, around the "
            "same days the outlook is issued. A real-time forecast might have to use the value from a month earlier.",
        ]
    with open(METRICS, "w") as f:
        # default=... turns numpy numbers into plain numbers that JSON accepts
        json.dump(metrics, f, indent=2, default=lambda value: value.item())
    print(f"Wrote {len(predictions)} alert rows, {len(outlook)} outlook rows, {len(latest)} latest rows, and metrics.json")


if __name__ == "__main__":
    main()
