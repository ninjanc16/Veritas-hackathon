"""Leakage checks on the model inputs: an input for week t must not use anything after week t."""
import numpy as np
import pandas as pd

from farmdrought.features import FEATURES_H, history_features


def make_inputs(seed=0):
    """A small random drought history: 6 counties x 120 weeks. The first 3 are 'river counties'."""
    rng = np.random.default_rng(seed)
    all_classes = rng.integers(0, 6, size=(6, 120)).astype(float)
    neighbors = [np.array([1, 3]), np.array([0, 4, 5]), np.array([5])]
    dates = pd.date_range("2000-01-04", periods=120, freq="7D")
    return all_classes, neighbors, dates


def test_set_h_has_24_inputs_and_no_location():
    all_classes, neighbors, dates = make_inputs()
    feats = history_features(all_classes[:3], all_classes, neighbors, dates)
    assert list(feats) == FEATURES_H and len(FEATURES_H) == 24
    # No latitude or longitude, so a Rio Grande model can be applied to another river
    assert "lat" not in FEATURES_H and "lon" not in FEATURES_H


def test_changing_the_future_does_not_change_past_inputs():
    all_classes, neighbors, dates = make_inputs()
    before = history_features(all_classes[:3], all_classes, neighbors, dates)

    # Rewrite every week after week 80 with completely different data
    t = 80
    changed = all_classes.copy()
    changed[:, t + 1 :] = np.random.default_rng(1).integers(0, 6, size=changed[:, t + 1 :].shape)
    after = history_features(changed[:3], changed, neighbors, dates)

    # Every input for weeks 0..80 must be exactly the same as before
    for name in FEATURES_H:
        np.testing.assert_array_equal(before[name][:, : t + 1], after[name][:, : t + 1], err_msg=name)


# ---------------- Sets L and E, used by the outlooks ----------------
from farmdrought.config import ONI_TXT
from farmdrought.features import FEATURES_E, FEATURES_L, enso_features, load_oni, long_memory_features


def test_long_memory_inputs_do_not_see_the_future():
    all_classes, _, _ = make_inputs()
    all_classes = np.tile(all_classes, 2)  # 240 weeks, so the 156-week input has values
    river = np.array(["A", "A", "B", "B", "B", "A"])
    before = long_memory_features(all_classes, river)
    assert list(before) == FEATURES_L

    t = 200
    changed = all_classes.copy()
    changed[:, t + 1 :] = 5  # rewrite everything after week 200
    after = long_memory_features(changed, river)
    for name in FEATURES_L:
        np.testing.assert_array_equal(before[name][:, : t + 1], after[name][:, : t + 1], err_msg=name)


def test_enso_uses_only_seasons_that_ended_before_the_issue_month():
    oni = load_oni(ONI_TXT)
    # For a forecast issued on March 2, 2010, the newest usable season is Dec-Jan-Feb 2010,
    # which ended in February. The file gives it as 1.47.
    feats = enso_features(pd.to_datetime(["2010-03-02"]), oni)
    assert list(feats) == FEATURES_E
    assert feats["oni"][0] == 1.47

    # Rewrite every season that ended in March 2010 or later. The inputs must not change.
    changed = oni.copy()
    changed[changed.index >= pd.Period("2010-03", "M")] = 99.0
    feats_changed = enso_features(pd.to_datetime(["2010-03-02"]), changed)
    for name in FEATURES_E:
        assert feats[name][0] == feats_changed[name][0], name


# ---------------- River flow and snowpack percentiles ----------------
from farmdrought.flow import past_percentile


def test_percentile_compares_only_with_earlier_years():
    days = pd.date_range("1990-01-01", "2012-12-31", freq="D")
    daily = pd.Series(np.random.default_rng(0).random(len(days)), index=days)
    dates = pd.to_datetime(["2005-06-07", "2010-03-02"])
    before = past_percentile(daily, dates, 90)
    assert ((before >= 0) & (before <= 1)).all()

    # Rewrite every day after the last forecast date. Nothing may change.
    changed = daily.copy()
    changed[changed.index > dates[-1]] = 1e9
    np.testing.assert_array_equal(before, past_percentile(changed, dates, 90))

    # A record high must rank above every earlier year, and a record low below them
    high, low = daily.copy(), daily.copy()
    high["2010-01-01":"2010-03-02"] = 1e9
    low["2010-01-01":"2010-03-02"] = -1e9
    assert past_percentile(high, dates, 90)[1] == 1.0
    assert past_percentile(low, dates, 90)[1] == 0.0
