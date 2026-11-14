"""Checks the four handoff files against the contract (architecture doc, section P2).

These tests read the files exactly as the App track will. Run `python -m farmdrought.export`
first so the files exist.
"""
import json

import pandas as pd
import pytest

from farmdrought.config import LATEST, METRICS, OUTLOOK, PREDICTIONS, RIVERS
from farmdrought.export import LATEST_COLUMNS, OUTLOOK_COLUMNS, PREDICTION_COLUMNS

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
    check_common(predictions, PREDICTION_COLUMNS)
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
    check_common(outlook, OUTLOOK_COLUMNS)
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
    assert list(latest.columns) == LATEST_COLUMNS and not latest.isna().any().any()
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
    assert any("river flow" in limit for limit in metrics["limits"])


def test_headline_numbers_can_be_recomputed_from_the_predictions_file(files):
    """The numbers in metrics.json must match what anyone can count from File 1."""
    predictions, _, _, metrics = files
    rio = predictions[predictions["river"] == "Rio Grande"]
    for policy in metrics["policies"]:
        alarm = rio[policy["column"]]
        missed = int((~alarm & (rio["y"] == 1)).sum())
        false_alarms = int((alarm & (rio["y"] == 0)).sum())
        assert policy["cost"] == metrics["miss_cost"] * missed + false_alarms
