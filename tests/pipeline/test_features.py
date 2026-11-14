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
