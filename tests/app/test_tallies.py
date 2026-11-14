"""Tests for tallies.py using a hand-made frame where the right answers are known by hand."""
import pandas as pd
import pytest

from app.tallies import tally, weeks_error

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
