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
from farmdrought.outlook import (FEATURES_SEASON, FEATURES_YEAR, issue_rows, make_classifier, make_regressor,
                                 run_outlook)

IS_FINAL = False  # stays False until the numbers are locked (Phase P4)

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


def failure_examples(rg):
    """Two real cases where the 4-week alert was wrong, picked by a fixed rule (not by hand):
    the most confident false alarm, and the least expected miss."""
    false_alarms = rg[rg["alarm_system"] & (rg["y"] == 0)]
    misses = rg[~rg["alarm_system"] & (rg["y"] == 1)]
    worst_false_alarm = false_alarms.loc[false_alarms["p_model"].idxmax()]
    worst_miss = misses.loc[misses["p_model"].idxmin()]
    describe = lambda row, text: {"product": "4-week alert", "date": str(row["date"].date()),
                                  "county": row["county"], "state": row["state"],
                                  "what_happened": text.format(p=row["p_model"])}
    return [
        describe(worst_false_alarm, "False alarm: the system warned with a risk score of {p:.2f}, "
                                    "but the county did not reach severe drought in the next 4 weeks."),
        describe(worst_miss, "Miss: the risk score was only {p:.2f}, so there was no warning, "
                             "but the county reached severe drought within 4 weeks."),
    ]


def build_metrics(alert, season, year, predictions, panel):
    """Collect every reported number into one dictionary, with the contract's keys."""
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
        "failure_examples": failure_examples(predictions[predictions["river"] == FOCUS_RIVER]),
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
        ],
        "feature_importance": alert["feature_importance"],
        "limits": [
            "Provisional: river flow not tested yet.",
            "The cost rule (a miss costs 3 false alarms) is our assumption.",
            "The 4-week risk score is not a calibrated probability.",
            f"On the Rio Grande the 4-week system (cost {system}) is close to a tie with the best simple rule, "
            f"{alert['headline']['cheapest_baseline_on_test']} (cost {cheapest}).",
            "On the other four rivers the Rio Grande-trained 4-week system beats persistence on the Mississippi, "
            "Missouri and Colorado, but it does not beat the best simple rule on any of them.",
            f"The 6-month outlook (cost {s['system_cost']}) is close to a tie with the 'D1 or worse now' rule "
            f"(cost {s['d1_rule_cost']}). It fails on the Mississippi, Missouri and Ohio.",
            f"The 12-month outlook is off by {y['mae_system']} weeks on average, against an average of "
            f"{y['mean_weeks']} weeks. It is a planning range, not a precise forecast.",
            "The 31 Rio Grande counties move together, so the real sample is about 18 years, not thousands of rows.",
            "Design choices were made after exploratory runs on the same test years.",
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
    metrics = build_metrics(alert, season, year, predictions, panel)
    predictions = finish(predictions, PREDICTION_COLUMNS, ["date", "fips"])
    outlook = finish(scored, OUTLOOK_COLUMNS, ["date", "fips"])
    latest = finish(latest_table(panel, alert["threshold"]), LATEST_COLUMNS, ["fips"])

    # 3. Write the four files
    PROCESSED.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(PREDICTIONS, index=False)
    outlook.to_parquet(OUTLOOK, index=False)
    latest.to_parquet(LATEST, index=False)
    with open(METRICS, "w") as f:
        # default=... turns numpy numbers into plain numbers that JSON accepts
        json.dump(metrics, f, indent=2, default=lambda value: value.item())
    print(f"Wrote {len(predictions)} alert rows, {len(outlook)} outlook rows, {len(latest)} latest rows, and metrics.json")


if __name__ == "__main__":
    main()
