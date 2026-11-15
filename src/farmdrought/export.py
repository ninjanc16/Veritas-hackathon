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

from farmdrought.canals import run_canals
from farmdrought.districts import run_districts
from farmdrought.alert import make_forest, run_alert, split_masks
from farmdrought.config import (ALERT_WEEKS, COUNTY_RESERVOIR, D2_CLASS, FEED_COST_PER_HEAD_MONTH, FOCUS_RIVER, LATEST, METRICS, MISS_COST, OUTLOOK, OUTLOOK_TEST,
                                PREDICTIONS, PROCESSED, REPORTS, SEASON_THRESHOLD, SEASON_WEEKS, TEST_START,
                                TRAIN, VAL, YEAR_WEEKS)
from farmdrought.features import FEATURES_H
from farmdrought.leaks import run_leaks
from farmdrought.flow import FEATURES_F, add_flow_features
from farmdrought.losses import run_losses
from farmdrought.mapfields import MAP_COLUMNS, add_map_fields, range_coverage
from farmdrought.outlook import (FEATURES_SEASON, FEATURES_SEASON_RES, FEATURES_YEAR, extra_inputs_test, issue_rows, make_classifier,
                                 make_regressor, run_outlook)
from farmdrought.reservoirs import add_reservoir_features, reservoir_summary
from farmdrought.robustness import ROBUSTNESS
from farmdrought.snow import FEATURES_S, add_snow_features
from farmdrought.trigger import run_trigger
from farmdrought.v2 import V2_JSON, alert_v2

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
# Pivot columns (canal action). Added at the END of the files, which contract rule 2 allows.
PIVOT_OUTLOOK_COLUMNS = ["p_season_res"]
PIVOT_LATEST_COLUMNS = ["p_season_res", "d2_share_history", "res_name", "res_pct_full"]
# Version 2 column (v2.py), also at the END of the files. See add_v2_alarm below.
V2_COLUMNS = ["alarm_v2"]
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

    # The outlooks learn from monthly rows, as in testing. The reservoir inputs are added to
    # the training rows and to this week's rows. Only p_season_res uses them.
    monthly = add_reservoir_features(issue_rows(panel))
    now = add_reservoir_features(now)
    rg = monthly[monthly["river"] == FOCUS_RIVER]
    known = rg[rg["y_season"].notna()]
    now["p_season"] = make_classifier().fit(known[FEATURES_SEASON], known["y_season"]).predict_proba(now[FEATURES_SEASON])[:, 1]
    now["season_tier"] = tiers(now["p_season"], SEASON_THRESHOLD)
    # Pivot: the second 6-month forecast, which also sees reservoir storage
    now["p_season_res"] = make_classifier().fit(known[FEATURES_SEASON_RES], known["y_season"]).predict_proba(now[FEATURES_SEASON_RES])[:, 1]
    # Pivot: plain facts for the canal screen (no model involved)
    now["res_name"] = now["fips"].map(COUNTY_RESERVOIR).fillna("none")
    now["res_pct_full"] = now["res_pct"].round(1)  # already -1 for counties with no reservoir
    now["d2_share_history"] = now["fips"].map((panel["cls"] >= D2_CLASS).groupby(panel["fips"]).mean())
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
            "The 6-month target (8 weeks in a row at D2) matches the aid rule for years up to 2025. For 2026 USDA "
            "lowered the trigger to 4 weeks in a row (FSA Notice LFP-8).",
            "The damage figure on the map is an estimate, not a tested forecast. It assumes every week of severe "
            "drought is a week of bought feed, priced at USDA's 2026 monthly feed cost for an adult beef cow. "
            "It was not checked against real losses, and it inherits the 12-month outlook's error.",
            "Nothing here measures crop yields.",
            "River flow and snowpack were tested as extra inputs and are not part of the system. See ablations. "
            "The El Paso gauge had no daily flow data and was dropped. The Del Norte gauge ends in 2024.",
            "Weather inputs (rain, temperature, soil moisture) were not tested.",
            "A random forest cannot predict a drought longer or deeper than any it saw in training.",
        ],
        # ---- keys added after the contract's list (contract rule 2 allows additions at the end) ----
        "alert_threshold": alert["threshold"],
    }


def add_v2_alarm(table, v2_alarm):
    """Add the version 2 alarm of the 4-week alert as a last column.

    Version 2 exists for the Rio Grande only. On the other rivers the column repeats version 1's
    alarm, because the contract allows no empty cells.
    shortcut: this week's version 2 alarm comes from the forest trained on 2000-2014 (the tested
    one), not one retrained on all years like version 1's live alarm. Retrain if v2 goes live.
    """
    table = table.merge(v2_alarm, on=["fips", "date"], how="left")
    table["alarm_v2"] = table["alarm_v2"].fillna(table["alarm_system"]).astype(bool)
    return table


def v2_metrics(metrics_limits):
    """The "v2" key: reports/v2.json as written by v2.py, plus its limit sentences."""
    with open(V2_JSON) as f:
        v2 = json.load(f)
    a, s, y, seeds = v2["alert"], v2["season"], v2["year"], v2["seed_check"]["seeds_where_v2_beats_v1"]
    limits = [
        "Version 2 was built after version 1's test results were known, so its list of candidates is not blind. "
        "Only the choice among candidates is protected: it never uses a year it is then scored on.",
        f"Version 2, 4-week alert: cost {a['v2']} against {a['v1']} for version 1 and {a['simple_rule']} for the "
        f"best simple rule. It won with {seeds['alert']} random seeds. The recipe ({a['chosen']}) was chosen on "
        "only 4 validation years, and it leans on a simple rule that an outside review found after the test.",
        f"Version 2, 6-month outlook: cost {s['v2']} against {s['v1']} for version 1. It did not improve "
        f"(it won with {seeds['season']} seeds). Version 1 stays.",
        f"Version 2, 12-month outlook: {y['v2']} weeks off against {y['v1']} for version 1, but the simple rule "
        f"alone is {y['simple_rule']}. In most years version 2 simply chose that rule over the forest.",
        f"Weather inputs alone (rain and temperature) did not help: 4-week {a['weather_alone']}, 6-month "
        f"{s['weather_alone']}, 12-month {y['weather_alone']}, each worse than version 1.",
    ]
    return {"limits": metrics_limits + limits, "v2": v2}


def pivot_metrics(scored, season, panel, metrics_limits, latest):
    """The five pivot keys (trigger, reservoir, losses, canals, canal_priority), plus their limit sentences added to the
    existing list of limits (metrics_limits)."""
    trigger = run_trigger(scored)
    rg = panel[panel["river"] == FOCUS_RIVER]
    counties = rg[["fips", "county", "state"]].drop_duplicates()
    losses = run_losses(counties)
    rule = {r["name"]: r for r in trigger["rules"]}
    ours, with_res, d1 = rule["Our forecast"], rule["Our forecast with reservoirs"], rule["D1 or worse now"]
    at_threshold = next(v for v in trigger["value_sweep"] if v["cost_ratio"] == SEASON_THRESHOLD)
    cost, cost_res = season["focus"]["system_cost"], season["reservoir_cost"]
    reservoir = {
        "systems": reservoir_summary(),
        "counties_without_reservoir": int(counties["fips"].nunique() - len(COUNTY_RESERVOIR)),
        "note": "Counties were matched to reservoirs by us, not from a published list. The ten Texas counties "
                "from Val Verde to Cameron use Amistad-Falcon (the two lakes added together). Sierra, Dona Ana, "
                "El Paso and Hudspeth use Elephant Butte. Counties upstream of a reservoir cannot draw from it, "
                "so they get no reservoir input. Storage data: Texas Water Development Board, waterdatafortexas.org.",
        # ---- extra, beyond the agreed keys: did reservoir storage help the 6-month outlook? ----
        "season_cost_without": cost,
        "season_cost_with": cost_res,
        "helped": bool(cost_res < cost),
    }
    limits = [
        f"Pre-season trigger (outlooks issued January to March): our forecast caught {ours['caught']} of "
        f"{trigger['drought_seasons']} drought seasons with {ours['false_alarms']} false alarms. The simple rule "
        f"'D1 or worse now' caught {d1['caught']} with {d1['false_alarms']}. At a cost ratio of 0.25 the forecast is "
        f"worth {at_threshold['forecast']} per decision against {at_threshold['d1_rule']} for the rule. "
        "That is a tie, not a win.",
        f"Reservoir storage did {'' if reservoir['helped'] else 'not '}help. The 6-month outlook costs {cost_res} "
        f"with reservoir inputs, against {cost} without them. As a pre-season trigger the reservoir forecast caught "
        f"{with_res['caught']} drought seasons with {with_res['false_alarms']} false alarms.",
        "Only 14 of the 31 Rio Grande counties are matched to a reservoir, and that matching is our assumption.",
        "County drought is not the same as water supply. Water in the canals also depends on reservoir releases "
        "and on Mexico's deliveries under the 1944 water treaty, which are not modeled.",
        "The loss figures are insured crop losses only, not all drought losses, and are not adjusted for inflation.",
        "The canal map shows where canals and ditches are. It does not say which are irrigation canals, which are "
        "lined, how much any canal leaks or which district owns it.",
        "The canal priority levels are an estimate of where leaks are likely, not measured leaks. They combine "
        "the 6-month forecast with a published seepage rate for the soil under each canal. They assume bare-earth "
        "canals, because we do not know which canals are lined. No canal was inspected or measured by us.",
    ]
    return {"limits": metrics_limits + limits, "trigger": trigger, "reservoir": reservoir, "losses": losses,
            "canals": run_canals(counties),
            # the chain: AI forecast (when) + canal map (where) + soil under the canal (how leaky)
            "canal_priority": run_leaks(latest, counties)}


def main():
    # 1. Run the three experiments
    panel, alert = run_alert()
    scored, season, year = run_outlook(panel)

    # 2. Build the three tables in contract shape
    _, _, test = split_masks(panel)
    predictions = panel[test].copy()
    predictions["tier"] = tiers(predictions["p_model"], alert["threshold"])
    metrics = build_metrics(alert, season, year, predictions, scored, panel)
    # Version 2 of the 4-week alert (Rio Grande only): its alarm goes in as a last column
    _, v2_alarm = alert_v2(panel)
    predictions = finish(add_v2_alarm(predictions, v2_alarm), PREDICTION_COLUMNS + V2_COLUMNS, ["date", "fips"])
    outlook = finish(scored, OUTLOOK_COLUMNS + PIVOT_OUTLOOK_COLUMNS, ["date", "fips"])
    # This week's rows, plus the extra columns for the risk map (added at the end, which
    # contract rule 2 allows). The length range uses each river's measured 12-month error.
    error_by_river = {entry["river"]: entry["mae_system"] for entry in year["per_river"]}
    latest = add_map_fields(latest_table(panel, alert["threshold"]), panel, error_by_river)
    latest = finish(add_v2_alarm(latest, v2_alarm), LATEST_COLUMNS + MAP_COLUMNS + PIVOT_LATEST_COLUMNS + V2_COLUMNS,
                    ["fips"])
    rg_scored = scored[scored["river"] == FOCUS_RIVER]
    metrics["map_fields"] = {
        "columns": {
            "risk_level": "Overall level for the map: the worse of the 4-week tier and the 6-month tier",
            "weeks_low": "Low end of the 12-month estimate: weeks_model minus the average error measured on that river",
            "weeks_high": "High end of the 12-month estimate: weeks_model plus that average error, at most 52",
            "typical_drought_weeks": "Median length of the county's past severe-drought spells, in weeks (0 if none)",
            "longest_drought_weeks": "The county's longest severe-drought spell on record, in weeks",
            "damage_months": "Months of bought feed if every expected severe-drought week needs bought feed",
            "damage_usd_per_100_head": "damage_months x monthly feed cost per head x 100 cattle, in dollars",
        },
        "feed_cost_per_head_month": FEED_COST_PER_HEAD_MONTH,
        "feed_cost_source": "USDA Farm Service Agency, Notice LFP-7, 2026 LFP Payment Rates, adult beef cattle",
        # In testing, how often the truth fell inside weeks_low..weeks_high on the Rio Grande
        "length_range_coverage_focus": range_coverage(rg_scored, error_by_river[FOCUS_RIVER]),
        "tested": "risk_level and the length range come from tested forecasts. The damage columns are untested estimates.",
    }

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
    # ---- Pivot keys (canal action), at the very end ----
    metrics.update(pivot_metrics(scored, season, panel, metrics["limits"], latest))
    # ---- Version 2 key, after everything else (run farmdrought.v2 first: it writes v2.json) ----
    if V2_JSON.exists():
        metrics.update(v2_metrics(metrics["limits"]))
    # ---- Districts and the sealant plan: the last link of the chain (must run after the canal levels) ----
    metrics["districts"] = run_districts(latest)
    metrics["limits"] += [
        "The district map and sealant plan cover Texas districts only. We found no public boundary file for "
        "districts in New Mexico or Colorado.",
        "The sealant plan is a ranking, not a measurement. It assumes every canal is bare earth, has 20 feet of "
        "wetted width and carries water for 90 days. We do not know which canals are already lined. The budget "
        "is an example figure, and the sealant price is materials only.",
    ]
    with open(METRICS, "w") as f:
        # default=... turns numpy numbers into plain numbers that JSON accepts
        json.dump(metrics, f, indent=2, default=lambda value: value.item())
    print(f"Wrote {len(predictions)} alert rows, {len(outlook)} outlook rows, {len(latest)} latest rows, and metrics.json")


if __name__ == "__main__":
    main()
