"""
Tests for app/contract.py: do the fake files pass, do broken files fail, are extras ignored?
Run: pytest tests/app -q
"""
import copy
import json

import pandas as pd
import pytest

from app import contract, make_demo_data
from app.contract import (OPTIONAL_LATEST_COLUMNS, OPTIONAL_METRICS_KEYS, REAL_DIR,
                          load, load_reference, validate_all,
                          validate_latest, validate_metrics, validate_outlook,
                          validate_predictions)


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory):
    """The four fake files, built once into pytest's temporary folder by app/make_demo_data.py."""
    folder = tmp_path_factory.mktemp("demo_data")
    make_demo_data.main(folder)
    return folder


@pytest.fixture
def demo(demo_dir):
    """Fresh copies of the four fake files for each test (so one test can't break another)."""
    pred, outlook, latest = (pd.read_parquet(demo_dir / f"{name}.parquet")
                             for name in ("predictions", "outlook", "latest"))
    metrics = json.loads((demo_dir / "metrics.json").read_text(encoding="utf-8"))
    tables = (df.assign(date=pd.to_datetime(df["date"])) for df in (pred, outlook, latest))
    return (*tables, copy.deepcopy(metrics))


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


def test_load_returns_no_data_and_a_problem_when_no_real_files(tmp_path, monkeypatch):
    # There is no demo fallback any more: missing real files give no tables and say what is missing.
    monkeypatch.setattr(contract, "REAL_DIR", tmp_path)
    monkeypatch.setattr(contract, "REAL_METRICS", tmp_path / "metrics.json")
    pred, outlook, latest, metrics, source, problems = load()
    assert (pred, outlook, latest, metrics) == (None, None, None, None)
    assert source == "none" and any("predictions.parquet" in p for p in problems)


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


# --- optional canal-pivot columns and keys -------------------------------------------------
def test_pivot_pieces_are_optional(demo):
    """Files without the new columns/keys still validate (the app just says 'not available yet')."""
    pred, outlook, latest, metrics = demo
    latest = latest.drop(columns=[c for c, _ in OPTIONAL_LATEST_COLUMNS])
    outlook = outlook.drop(columns=["p_season_res"])
    metrics = {k: v for k, v in metrics.items() if k not in OPTIONAL_METRICS_KEYS}
    assert validate_all(pred, outlook, latest, metrics) == []


def test_pivot_pieces_are_checked_when_present(demo):
    pred, outlook, latest, metrics = demo
    assert any("p_season_res" in p for p in validate_latest(latest.assign(p_season_res=5.0)))
    assert any("res_name" in p for p in validate_latest(latest.assign(res_name="Nowhere")))
    assert any("res_pct_full" in p for p in validate_latest(latest.assign(res_name="none", res_pct_full=40.0)))
    broken = {**metrics, "losses": {"source": "x"}}
    assert any("losses.total_usd" in p for p in validate_metrics(broken))


def test_load_reference():
    districts, costs = load_reference()
    assert len(districts) == 19 and costs["gallons_per_af"] == 325851
