"""Tests for the canal arithmetic (app/canal.py) and the reference files."""
import pytest

from app import canal
from app.contract import load_reference

districts, costs = load_reference()


def test_seepage_one_mile_hand_computed():
    # 1 mile x 5,280 ft x 20 ft = 105,600 sq ft. Sandy loam leaks 11.22 gal/sq ft/day, 300 days.
    gallons = 11.22 * 105_600 * 300          # worked out by hand: 355,449,600 gallons
    expected = gallons / 325_851             # about 1,090.8 acre-feet
    got = canal.seepage_af_per_year(1, 20, costs["seepage_gal_sqft_day"]["Sandy loam"], 300,
                                    costs["gallons_per_af"])
    assert got == pytest.approx(expected)
    assert 1090 < got < 1092


def test_sealant_cost_and_applications():
    assert canal.applications_per_season(300, 3) == 4          # about 9.9 months of flow -> 4 coats
    assert canal.sealant_cost_per_season(1, 20, 300, costs) == pytest.approx(105_600 * 0.004 * 4)


def test_cost_per_af_low_not_above_high():
    seep = canal.seepage_af_per_year(1, 20, 11.22, 300, costs["gallons_per_af"])
    low, high = canal.water_saved_range(seep, costs)
    assert low < high
    cpa_low, cpa_high = canal.cost_per_af_range(canal.sealant_cost_per_season(1, 20, 300, costs), low, high)
    assert cpa_low <= cpa_high
    lin_low, lin_high = canal.lining_cost_per_af_range(1, 20, seep, costs)
    assert lin_low <= lin_high
    assert canal.cost_per_af_range(100, 0, 0) == (None, None)   # no water saved -> no cost per af


def test_district_with_no_recoverable_water_ranks_last():
    ranked = canal.district_priority(districts, 0.3)
    assert list(ranked.columns) == ["district", "efficiency_pct", "save80_low", "save80_high",
                                    "priority_low", "priority_high"]
    assert ranked.iloc[0]["district"] == "CCID#2 (San Benito)"
    assert ranked.iloc[-1]["priority_high"] == 0
    assert ranked["priority_high"].is_monotonic_decreasing


def test_action_tiers():
    assert canal.action_tier(0.25)[0].startswith("Seal")
    assert canal.action_tier(0.2)[0].startswith("Inspect")
    assert canal.action_tier(0.05)[0].startswith("No extra")


def test_trigger_verdict_calls_a_tiny_gap_a_tie():
    # The shape of the real handoff: forecast 0.3135 vs D1 0.3132 at the 25% threshold.
    trig = {"threshold": 0.25, "value_sweep": [
        {"cost_ratio": 0.1, "forecast": 0.4216, "forecast_reservoir": 0.4179, "d1_rule": 0.4048},
        {"cost_ratio": 0.25, "forecast": 0.3135, "forecast_reservoir": 0.3065, "d1_rule": 0.3132}]}
    vs_d1, res = canal.trigger_verdict(trig)
    assert "about as well as" in vs_d1 and "ties" in vs_d1
    assert "did not help" in res
    trig["value_sweep"][1]["d1_rule"] = 0.25
    assert "did better" in canal.trigger_verdict(trig)[0]
