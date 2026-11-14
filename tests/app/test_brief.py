"""Tests for brief.py: right content, and it never peeks at the future or at the truth."""
import copy

import pandas as pd

from app.brief import build_brief
from app.contract import load_demo


def _inputs():
    pred, _, latest, metrics = load_demo()
    row = latest[latest["river"] == "Rio Grande"].iloc[0]
    history = pred[pred["fips"] == row["fips"]].copy()
    return row, history, copy.deepcopy(metrics)


def test_brief_contains_status_tier_and_rounded_numbers():
    row, history, metrics = _inputs()
    text = build_brief(row, history, metrics, "DEMO")
    assert "Status: DEMO" in text
    assert row["tier"] in text
    assert f"{round(row['p_model'] * 100)}%" in text
    assert f"{round(row['p_season'] * 100)}%" in text
    assert f"{round(row['weeks_model'])} weeks" in text
    assert "Not financial or legal advice" in text
    assert metrics["limits"][0] in text


def test_later_rows_and_truth_columns_do_not_change_the_brief():
    row, history, metrics = _inputs()
    before = build_brief(row, history, metrics, "DEMO")
    later = history["date"] > row["date"] - pd.Timedelta(weeks=4)   # rows too recent to be used
    history.loc[later, "cls"] = 0                                    # change them...
    history["y"] = 1 - history["y"]                                  # ...and flip the truth column
    assert build_brief(row, history, metrics, "DEMO") == before


def test_transfer_river_gets_a_warning_line():
    pred, _, latest, metrics = load_demo()
    row = latest[latest["river"] == "Ohio"].iloc[0]
    text = build_brief(row, pred[pred["fips"] == row["fips"]], metrics, "DEMO")
    assert "not on this river" in text
