"""Tests for tallies.py using a hand-made frame where the right answers are known by hand."""
import pandas as pd
import pytest

from app.contract import load_demo
from app.tallies import errors_table, reconcile, river_grid, tally, weeks_error

# 8 rows.  alarm: rows 0,1,2,6 fire.  truth: drought followed rows 0,2,3.
FRAME = pd.DataFrame({
    "alarm": [1, 1, 1, 0, 0, 0, 1, 0],
    "truth": [1, 0, 1, 1, 0, 0, 0, 0],
})


def test_tally_by_hand():
    t = tally(FRAME, "alarm", "truth")
    assert t["alarms"] == 4
    assert t["caught"] == 2          # rows 0 and 2
    assert t["missed"] == 1          # row 3
    assert t["false_alarms"] == 2    # rows 1 and 6
    assert t["cost"] == 3 * 1 + 2    # 3 x missed + false alarms
    assert t["precision"] == pytest.approx(2 / 4)
    assert t["recall"] == pytest.approx(2 / 3)


def test_tally_no_alarms_means_precision_is_none():
    t = tally(FRAME.assign(alarm=0), "alarm", "truth")
    assert t["precision"] is None and t["missed"] == 3


def test_tally_no_droughts_means_recall_is_none():
    t = tally(FRAME.assign(truth=0), "alarm", "truth")
    assert t["recall"] is None and t["false_alarms"] == 4


def test_tally_empty_frame():
    t = tally(FRAME.iloc[0:0], "alarm", "truth")
    assert t["cost"] == 0 and t["precision"] is None and t["recall"] is None


def test_tally_accepts_true_false():
    t = tally(FRAME.astype(bool), "alarm", "truth")
    assert t["caught"] == 2


def test_weeks_error():
    df = pd.DataFrame({"y_weeks": [10, 20, 30], "guess": [12, 18, 33]})
    assert weeks_error(df, "guess") == pytest.approx((2 + 2 + 3) / 3)
    assert weeks_error(df.iloc[0:0], "guess") is None


# --- Phase 4 helpers -------------------------------------------------------
def _mistakes_frame():
    # 4 rows: a hit, a miss, a false alarm, and a correct quiet week.
    return pd.DataFrame({
        "date": pd.to_datetime(["2020-01-07", "2020-01-14", "2020-01-21", "2020-01-28"]),
        "county": ["A", "A", "A", "A"], "state": ["S"] * 4, "river": ["R"] * 4,
        "cls": [3, 3, 0, 0], "p_model": [0.9, 0.1, 0.8, 0.1],
        "y": [1, 1, 0, 0], "alarm": [True, False, True, False],
    })


def test_errors_table_splits_misses_and_false_alarms():
    missed, false_alarms = errors_table(_mistakes_frame(), "alarm")
    assert list(missed["date"].dt.day) == [14]          # the miss
    assert list(false_alarms["date"].dt.day) == [21]    # the false alarm
    assert list(missed.columns) == ["date", "county", "state", "river", "cls", "p_model"]


def test_river_grid_orders_counties_north_to_south_and_filters():
    d = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-07", "2020-01-14"] * 2 + ["2021-01-05", "2020-01-07"]),
        "county": ["South", "South", "North", "North", "North", "Other"],
        "state": ["T", "T", "T", "T", "T", "T"],
        "river": ["R", "R", "R", "R", "R", "X"],           # last row is another river
        "lat": [30.0, 30.0, 40.0, 40.0, 40.0, 35.0],
        "tier": ["Low", "Watch", "Warning", "Low", "Low", "Low"],
        "cls": [0, 1, 4, 2, 0, 0],
    })
    tiers, cls = river_grid(d, "R", 2020)
    assert list(tiers.index) == ["North, T", "South, T"]      # north first
    assert tiers.shape == (2, 2)                              # 2021 and river X left out
    assert tiers.loc["North, T"].tolist() == [2, 0]           # Warning, Low
    assert cls.loc["South, T"].tolist() == [0, 1]


def test_reconcile_matches_demo_and_catches_a_wrong_number():
    pred, _, _, metrics = load_demo()
    assert reconcile(pred, metrics) == []                      # fake data was built to add up
    metrics["policies"][0]["missed"] += 1                      # tamper with one reported number
    problems = reconcile(pred, metrics)
    assert len(problems) == 1 and "missed" in problems[0]
