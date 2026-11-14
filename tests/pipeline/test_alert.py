"""Checks on the real data: county counts, the time split, and that the threshold never sees test rows."""
import numpy as np
import pandas as pd

from farmdrought.alert import fit_alert, split_masks
from farmdrought.config import ALERT_WEEKS, FOCUS_RIVER


def test_county_counts_per_river(panel):
    counts = panel.groupby("river")["fips"].nunique().to_dict()
    assert counts == {"Rio Grande": 31, "Colorado": 13, "Missouri": 103, "Mississippi": 164, "Ohio": 125}


def test_splits_are_by_time_and_do_not_overlap(panel):
    train, val, test = split_masks(panel)
    assert not (train & val).any() and not (val & test).any() and not (train & test).any()
    window_end = panel["date"] + pd.Timedelta(weeks=ALERT_WEEKS)
    # Every training answer is fully known before validation starts, and the same for val/test
    assert window_end[train].max() < panel.loc[val, "date"].min()
    assert window_end[val].max() < panel.loc[test, "date"].min()
    assert panel.loc[test, "date"].min().year == 2019
    # Rows with no answer yet are in none of the three blocks
    assert panel.loc[train | val | test, "y"].notna().all()


def test_threshold_is_computed_without_test_rows(panel):
    train, val, test = split_masks(panel)
    focus = panel["river"] == FOCUS_RIVER
    _, threshold = fit_alert(panel, train & focus, val & focus)

    # Scramble everything in the test years: flip the answers and randomize the class.
    scrambled = panel.copy()
    scrambled.loc[test, "y"] = 1 - scrambled.loc[test, "y"]
    scrambled.loc[test, "cls"] = np.random.default_rng(0).integers(0, 6, size=int(test.sum()))
    _, threshold_scrambled = fit_alert(scrambled, train & focus, val & focus)

    # If the threshold used test rows in any way, it would have moved
    assert threshold == threshold_scrambled
