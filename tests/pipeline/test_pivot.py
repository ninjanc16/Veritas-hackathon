"""Checks for the canal-action pivot: the reservoir inputs and the trigger scoring."""
import numpy as np
import pandas as pd

from farmdrought.reservoirs import FEATURES_R, add_reservoir_features, load_reservoirs, reservoir_features
from farmdrought.trigger import score, value


def test_trigger_counts_on_a_hand_made_table():
    # 10 decisions. A drought season followed the first 4.
    y = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    fires = [True, True, True, False, True, True, False, False, False, False]
    result = score("rule", y, fires)
    assert result["fires"] == 5 and result["caught"] == 3 and result["missed"] == 1 and result["false_alarms"] == 2
    assert result["recall"] == 0.75 and result["precision"] == 0.6
    # value = (caught - cost ratio x fires) / rows = (3 - 0.25 x 5) / 10
    assert value(y, fires, 0.25) == 0.175
    assert value(y, [False] * 10, 0.25) == 0   # never sealing is worth exactly 0


def test_reservoir_inputs_do_not_use_the_future():
    """LEAKAGE CHECK: rewriting every day AFTER the issue date must not change any input."""
    pct = load_reservoirs()["Elephant Butte"]
    dates = pd.DatetimeIndex(["2012-03-06", "2018-01-02"])
    before = reservoir_features(pct, dates)
    changed = pct.copy()
    changed[changed.index > dates.max()] = 99.0   # a made-up future: the lake is suddenly full
    after = reservoir_features(changed, dates)
    pd.testing.assert_frame_equal(before, after)


def test_reservoir_inputs_on_real_rows(panel):
    rows = panel[panel["date"] == panel["date"].max()]
    table = add_reservoir_features(rows)
    assert not table[FEATURES_R].isna().any().any()
    with_res = table[table["has_res"] == 1]
    assert len(with_res) == 14 and set(with_res["river"]) == {"Rio Grande"}
    assert with_res["res_pct"].between(0, 100).all() and with_res["res_pctile"].between(0, 1).all()
    # Counties with no reservoir get -1 in all four inputs
    assert (table.loc[table["has_res"] == 0, FEATURES_R[:4]] == -1).all().all()
