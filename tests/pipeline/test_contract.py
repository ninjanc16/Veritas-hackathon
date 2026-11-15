"""Checks the four handoff files against the contract (architecture doc, section P2).

These tests read the files exactly as the App track will. Run `python -m farmdrought.export`
first so the files exist.
"""
import json

import pandas as pd
import pytest

from farmdrought.config import LATEST, METRICS, OUTLOOK, PREDICTIONS, RIVERS
from farmdrought.export import (LATEST_COLUMNS, OUTLOOK_COLUMNS, PIVOT_LATEST_COLUMNS, PIVOT_OUTLOOK_COLUMNS, V2_COLUMNS,
                                PREDICTION_COLUMNS)
from farmdrought.mapfields import MAP_COLUMNS

TIERS = {"Low", "Watch", "Warning"}


@pytest.fixture(scope="module")
def files():
    with open(METRICS) as f:
        metrics = json.load(f)
    return (pd.read_parquet(PREDICTIONS), pd.read_parquet(OUTLOOK), pd.read_parquet(LATEST), metrics)


def check_common(table, columns):
    assert list(table.columns) == columns                      # right columns, right order
    assert not table.isna().any().any()                        # no missing values
    assert table["fips"].str.fullmatch(r"\d{5}").all()         # 5 digits, leading zeros kept
    assert set(table["river"]) == set(RIVERS)


def test_predictions_file(files):
    predictions, _, _, metrics = files
    check_common(predictions, PREDICTION_COLUMNS + V2_COLUMNS)  # version 2 alarm at the end
    assert predictions[["date", "fips"]].equals(predictions[["date", "fips"]].sort_values(["date", "fips"]).reset_index(drop=True))
    assert set(predictions["y"]) == {0, 1} and predictions["cls"].between(0, 5).all()
    assert predictions["p_model"].between(0, 1).all() and set(predictions["tier"]) <= TIERS
    assert min(predictions["date"]).year == 2019               # test years only
    # A Warning tier and an alarm are the same thing
    assert ((predictions["tier"] == "Warning") == predictions["alarm_system"]).all()
    assert (predictions["alarm_system"] == (predictions["p_model"] >= metrics["alert_threshold"])).all()
    assert (predictions["alarm_persistence"] == (predictions["cls"] >= 3)).all()
    assert len(predictions) == metrics["n_rows"]
    assert (predictions["river"] == "Rio Grande").sum() == metrics["n_focus_rows"]
    assert predictions["fips"].nunique() == metrics["n_counties"] == 436


def test_outlook_file(files):
    _, outlook, _, metrics = files
    check_common(outlook, OUTLOOK_COLUMNS + PIVOT_OUTLOOK_COLUMNS)  # pivot column at the end
    assert outlook["p_season_res"].between(0, 1).all()
    assert outlook[["date", "fips"]].equals(outlook[["date", "fips"]].sort_values(["date", "fips"]).reset_index(drop=True))
    assert set(outlook["y_season"]) == {0, 1} and outlook["y_weeks"].between(0, 52).all()
    assert outlook["p_season"].between(0, 1).all() and outlook["weeks_model"].between(0, 52).all()
    assert (outlook["alarm_season"] == (outlook["p_season"] >= metrics["season"]["threshold"])).all()
    years = {d.year for d in outlook["date"]}
    assert years == set(range(2008, 2026))                     # the outlook test years
    assert all(d.day <= 7 for d in outlook["date"])            # first week of each month
    rio = outlook[outlook["river"] == "Rio Grande"]
    assert len(rio) == metrics["season"]["focus"]["rows"] == metrics["year"]["focus"]["rows"]


def test_latest_file(files):
    _, _, latest, metrics = files
    # The contract columns come first, then the map columns, then the pivot columns
    assert list(latest.columns) == LATEST_COLUMNS + MAP_COLUMNS + PIVOT_LATEST_COLUMNS + V2_COLUMNS
    assert not latest.isna().any().any()
    assert len(latest) == 436 and latest["fips"].is_unique and latest["fips"].is_monotonic_increasing
    assert {str(d) for d in latest["date"]} == {metrics["latest_week"]}  # one week only
    assert set(latest["tier"]) <= TIERS and set(latest["season_tier"]) <= TIERS


def test_metrics_file(files):
    _, _, _, metrics = files
    required = ["contract_version", "generated_at", "is_final", "focus_river", "training_scope", "n_rows",
                "n_focus_rows", "n_counties", "n_focus_counties", "horizon_weeks", "train_years", "val_years",
                "test_years", "latest_week", "miss_cost", "policies", "headline", "onset", "events",
                "cost_sensitivity", "year_by_year", "per_river", "season", "year", "failure_examples",
                "shuffled_auc_mean", "ablations", "feature_importance", "limits"]
    assert list(metrics)[: len(required)] == required           # every key, in contract order
    assert metrics["contract_version"] == 2 and metrics["focus_river"] == "Rio Grande"
    assert metrics["n_focus_counties"] == 31 and metrics["miss_cost"] == 3

    # One policy for our system and one per baseline. Baselines have no AUC.
    assert [p["column"] for p in metrics["policies"]] == ["alarm_system", "alarm_persistence", "alarm_d1_now",
                                                          "alarm_worsening", "alarm_calendar"]
    assert all(p["auc"] is None for p in metrics["policies"][1:])

    # Every per-river list covers all five rivers
    for per_river in (metrics["per_river"], metrics["season"]["per_river"], metrics["year"]["per_river"]):
        assert {entry["river"] for entry in per_river} == set(RIVERS)

    # Leakage rule 6: a model trained on shuffled answers must be no better than a coin flip
    assert 0.40 <= metrics["shuffled_auc_mean"] <= 0.60
    assert len(metrics["failure_examples"]) >= 2
    assert isinstance(metrics["headline"]["honesty_check_pass"], bool)
    assert any("River flow" in limit for limit in metrics["limits"])
    products = {example["product"] for example in metrics["failure_examples"]}
    assert products == {"4-week alert", "6-month outlook", "12-month outlook"}


def test_headline_numbers_can_be_recomputed_from_the_predictions_file(files):
    """The numbers in metrics.json must match what anyone can count from File 1."""
    predictions, _, _, metrics = files
    rio = predictions[predictions["river"] == "Rio Grande"]
    for policy in metrics["policies"]:
        alarm = rio[policy["column"]]
        missed = int((~alarm & (rio["y"] == 1)).sum())
        false_alarms = int((alarm & (rio["y"] == 0)).sum())
        assert policy["cost"] == metrics["miss_cost"] * missed + false_alarms


def test_pivot_columns_and_keys(files):
    """The canal-action additions: new columns in the latest file, three new keys in metrics.json."""
    _, outlook, latest, metrics = files
    assert latest["p_season_res"].between(0, 1).all() and latest["d2_share_history"].between(0, 1).all()
    assert set(latest["res_name"]) == {"Amistad-Falcon", "Elephant Butte", "none"}
    # 10 + 4 counties have a reservoir. Every other county has "none" and -1.
    assert (latest["res_name"] != "none").sum() == 14
    assert (latest.loc[latest["res_name"] == "none", "res_pct_full"] == -1).all()
    assert latest.loc[latest["res_name"] != "none", "res_pct_full"].between(0, 100).all()

    assert list(metrics)[-7:] == ["trigger", "reservoir", "losses", "canals", "canal_priority", "v2", "districts"]   # new keys at the end
    trigger = metrics["trigger"]
    assert [r["name"] for r in trigger["rules"]] == ["Our forecast", "Our forecast with reservoirs",
                                                     "D1 or worse now", "D2 or worse now", "Seal every year"]
    for rule in trigger["rules"]:
        assert rule["caught"] + rule["missed"] == trigger["drought_seasons"]
        assert rule["caught"] + rule["false_alarms"] == rule["fires"]
    assert trigger["rules"][-1]["fires"] == trigger["rows"]            # "seal every year" always fires
    assert isinstance(trigger["forecast_beats_d1_rule"], bool)
    assert isinstance(trigger["reservoir_forecast_beats_d1_rule"], bool)
    # The trigger counts can be recomputed from the outlook file by anyone
    rio = outlook[(outlook["river"] == "Rio Grande") & outlook["date"].map(lambda d: d.month <= 3)]
    assert len(rio) == trigger["rows"] and rio["y_season"].sum() == trigger["drought_seasons"]
    assert ((rio["p_season"] >= 0.25) & (rio["y_season"] == 1)).sum() == trigger["rules"][0]["caught"]

    assert metrics["reservoir"]["counties_without_reservoir"] == 17
    losses = metrics["losses"]
    assert losses["total_usd"] == sum(entry["usd"] for entry in losses["by_year"])
    assert len(losses["by_county"]) == 31 and losses["causes_included"] == ["Drought"]

    canals = metrics["canals"]
    assert len(canals["by_county"]) == 31
    assert abs(canals["total_km"] - sum(entry["canal_km"] for entry in canals["by_county"])) < 2   # rounding only
    assert all(entry["named_km"] <= entry["canal_km"] for entry in canals["by_county"])

    # Canal priority: every km of canal has exactly one level, and "inspect first" needs BOTH links
    priority = metrics["canal_priority"]
    assert abs(sum(entry["km"] for entry in priority["by_level"]) - canals["total_km"]) < 2
    for entry in priority["by_county"]:
        assert entry["inspect_first_km"] <= entry["leaky_soil_km"] <= entry["canal_km"]
        if entry["p_season"] < priority["forecast_threshold"]:
            assert entry["inspect_first_km"] == 0      # no forecast warning, so nothing is "inspect first"


def test_version_2_alarm_and_key(files):
    predictions, _, latest, metrics = files
    # the version 2 alarm is the last column of both files, and is True/False everywhere
    assert predictions.columns[-1] == latest.columns[-1] == "alarm_v2"
    assert predictions["alarm_v2"].dtype == bool and latest["alarm_v2"].dtype == bool
    # version 2 exists for the Rio Grande only: elsewhere it repeats version 1's alarm
    other = predictions[predictions["river"] != "Rio Grande"]
    assert (other["alarm_v2"] == other["alarm_system"]).all()
    # the reported version 2 cost can be recomputed from the file: 3 x missed + false alarms
    rio = predictions[predictions["river"] == "Rio Grande"]
    missed = ((rio["y"] == 1) & ~rio["alarm_v2"]).sum()
    false_alarms = ((rio["y"] == 0) & rio["alarm_v2"]).sum()
    v2 = metrics["v2"]
    assert 3 * missed + false_alarms == v2["alert"]["v2"]
    # version 1's numbers inside the v2 report match the main report
    assert v2["alert"]["v1"] == metrics["headline"]["system_cost"]
    assert v2["season"]["v1"] == metrics["season"]["focus"]["system_cost"]
    assert v2["year"]["v1"] == metrics["year"]["focus"]["mae_system"]
