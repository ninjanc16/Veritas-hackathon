"""Tests for the lining-cost arithmetic (src/farmdrought/costs.py), moved from app/canal.py."""
import json

import pytest

from farmdrought import costs as lining
from farmdrought.config import ROOT

costs = json.loads((ROOT / "app" / "reference" / "costs.json").read_text(encoding="utf-8"))


def one_mile_seepage_af():
    # 1 mile x 5,280 ft x 20 ft = 105,600 sq ft. Sandy loam leaks 11.22 gal/sq ft/day, 300 days.
    gallons = 11.22 * 105_600 * 300          # worked out by hand: 355,449,600 gallons
    return gallons / costs["gallons_per_af"]  # about 1,090.8 acre-feet


def test_wetted_area_one_mile_hand_computed():
    assert lining.wetted_area_sqft(1, 20) == 105_600


def test_lining_life_is_fifty_years():
    assert lining.LINING_LIFE_YEARS == 50


def test_lining_cost_per_af_low_not_above_high():
    lin_low, lin_high = lining.lining_cost_per_af_range(1, 20, one_mile_seepage_af(), costs)
    assert lin_low <= lin_high


def test_lining_cost_per_af_hand_computed():
    seep = one_mile_seepage_af()
    lin_low, lin_high = lining.lining_cost_per_af_range(1, 20, seep, costs)
    # area x dollars per sq ft, divided by the water saved over the 50-year life
    assert lin_low == pytest.approx(105_600 * costs["lining_usd_per_sqft_low"] / (seep * 50))
    assert lin_high == pytest.approx(105_600 * costs["lining_usd_per_sqft_high"] / (seep * 50))


def test_no_seepage_means_no_cost_per_af():
    assert lining.lining_cost_per_af_range(1, 20, 0, costs) == (None, None)
