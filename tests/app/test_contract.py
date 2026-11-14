"""
Tests for app/contract.py: do the fake files pass, do broken files fail, are extras ignored?
Run: pytest tests/app -q
"""
import copy

import pytest

from app.contract import (REAL_DIR, REAL_METRICS, load, load_demo, validate_all,
                          validate_latest, validate_metrics, validate_outlook,
                          validate_predictions)


@pytest.fixture
def demo():
    """Fresh copies of the four fake files for each test (so one test can't break another)."""
    pred, outlook, latest, metrics = load_demo()
    return pred.copy(), outlook.copy(), latest.copy(), copy.deepcopy(metrics)


def test_demo_files_are_valid(demo):
    # The fake files must follow the contract exactly.
    assert validate_all(*demo) == []


def test_missing_column_fails(demo):
    pred, outlook, latest, _ = demo
    assert validate_predictions(pred.drop(columns=["tier"])) != []
    assert validate_outlook(outlook.drop(columns=["y_weeks"])) != []
    assert validate_latest(latest.drop(columns=["season_tier"])) != []


def test_missing_metrics_key_fails(demo):
    metrics = demo[3]
    del metrics["headline"]
    assert validate_metrics(metrics) != []


def test_missing_nested_metrics_key_fails(demo):
    metrics = demo[3]
    del metrics["season"]["focus"]["system_cost"]
    assert validate_metrics(metrics) != []


def test_extra_columns_and_keys_are_ignored(demo):
    # The pipeline may ADD things at the end later. The app must not break.
    pred, outlook, latest, metrics = demo
    pred["new_column"] = 1
    outlook["new_column"] = 1
    latest["new_column"] = 1
    metrics["new_key"] = "hello"
    assert validate_all(pred, outlook, latest, metrics) == []


def test_wrong_values_fail(demo):
    pred, _, _, metrics = demo
    pred.loc[0, "cls"] = 9                    # drought class must be 0..5
    assert validate_predictions(pred) != []
    metrics["contract_version"] = 3           # the app only understands version 2
    assert validate_metrics(metrics) != []


def test_unsorted_rows_fail(demo):
    pred = demo[0].iloc[::-1].reset_index(drop=True)   # reverse the row order
    assert validate_predictions(pred) != []


def test_fips_keeps_leading_zero(demo):
    pred = demo[0]
    assert (pred["fips"].str.len() == 5).all()
    assert pred["fips"].str.startswith("0").any()      # e.g. Colorado counties start with 08


def test_n_rows_must_match(demo):
    pred, _, _, metrics = demo
    metrics["n_rows"] = len(pred) + 1
    assert validate_metrics(metrics, n_rows=len(pred)) != []


def test_load_falls_back_to_demo_when_no_real_files():
    # No real handoff files in this branch yet, so load() must return demo data.
    if REAL_DIR.exists() or REAL_METRICS.exists():
        pytest.skip("real files are present")
    *_, source, problems = load()
    assert source == "demo" and problems == []


@pytest.mark.skipif(not (REAL_DIR / "predictions.parquet").exists(), reason="no real files yet")
def test_real_files_pass_when_present():
    *_, source, problems = load()
    assert problems == [] and source == "real"


def test_python_dates_pass_but_text_dates_fail(demo):
    # Real parquet DATE columns arrive as Python dates: that is a valid "date".
    pred = demo[0].copy()
    pred["date"] = pred["date"].dt.date
    assert validate_predictions(pred) == []
    # Dates stored as text are NOT dates, so they must still fail.
    pred["date"] = pred["date"].astype(str)
    assert validate_predictions(pred) != []


def test_map_columns_are_checked_when_present(demo):
    _, _, latest, _ = demo
    assert "risk_level" in latest.columns                      # the demo files carry them too
    # some but not all of the map columns -> a problem
    assert validate_latest(latest.drop(columns=["damage_months"])) != []
    # a range that is upside down -> a problem
    broken = latest.copy()
    broken.loc[0, "weeks_low"], broken.loc[0, "weeks_high"] = 40.0, 10.0
    assert validate_latest(broken) != []
    # an unknown level name -> a problem
    broken = latest.copy()
    broken["risk_level"] = broken["risk_level"].astype(object)
    broken.loc[0, "risk_level"] = "Panic"
    assert validate_latest(broken) != []


def test_map_columns_need_the_metrics_explanation(demo):
    pred, outlook, latest, metrics = demo
    del metrics["map_fields"]
    assert any("map_fields" in p for p in validate_all(pred, outlook, latest, metrics))


def test_files_without_map_columns_still_pass(demo):
    # Older handoffs have no map columns: that must stay valid (the map falls back to the tiers).
    from app.contract import MAP_COLUMNS
    pred, outlook, latest, metrics = demo
    assert validate_all(pred, outlook, latest.drop(columns=MAP_COLUMNS), metrics) == []
